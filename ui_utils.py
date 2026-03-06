import streamlit as st
import json
import math
import os
import uuid
from collections import Counter
from typing import List, Dict, Tuple, Any

from utils.data_loader import load_game_data
from utils.constants import StatName, PERCENTAGE_STATS, EquipmentQuality, INSTANT_ACTION_PET_ABILITIES
from calculations import calculate_steps, calculate_quality_probabilities
from models import (
    Equipment, GearSet, Collectible, Modifier, Condition, Service, Recipe, Activity, 
    Requirement, RequirementType, ConditionType, GATHERING_SKILLS, ARTISAN_SKILLS,
    Pet, Consumable, Container, CraftingNode, Loadout
)
from drop_calculator import DropCalculator

# --- GLOBAL TARGET CONFIG ---
TARGET_CATEGORIES = {
    "Main": ["Reward Rolls", "Xp", "Chests", "Materials From Input", "Fine",],
    "Quality": [ "Eternal Per Input","Good Per Step", "Great Per Step", "Excellent Per Step", "Perfect Per Step", "Eternal Per Step"],
    "Drops & Materials": [ "Gems", "Collectibles", "Tokens Per Step", "Ectoplasm Per Step", ],
    "🤑": ["Coins", "Coins No Chests", "Coins No Fines", "Coins No Chests No Fines"],
    "Pets & Abilities":["Reward Rolls No Steps", "Exp No Steps","Chests No Steps", "Fine No Steps"]
}

def find_category(target_name):
    for cat, targets in TARGET_CATEGORIES.items():
        if target_name in targets: return cat
    return "Base" 

# --- Helpers ---
def get_xp_for_level(level: int) -> int:
    total = 0
    for i in range(1, level):
        total += math.floor(i + 300 * (2 ** (i / 7.0)))
    return math.floor(total / 4)

def calculate_level_from_xp(current_xp: int) -> int:
    for lvl in range(1, 150):
        if get_xp_for_level(lvl + 1) > current_xp:
            return lvl
    return 150

def calculate_char_level_from_steps(current_steps: int) -> int:
    for lvl in range(1, 120):
        xp_req_standard = get_xp_for_level(lvl + 1)
        steps_req = math.floor(xp_req_standard) * 4.6
        if steps_req > current_steps:
            return lvl
    return 120

def calculate_total_level(skills_data: Dict[str, int]) -> int:
    total = 0
    for xp in skills_data.values():
        total += calculate_level_from_xp(xp)
    return total

def extract_user_reputation(user_data: Dict) -> Dict[str, float]:
    if "reputation" in user_data and isinstance(user_data["reputation"], dict):
        return {k.lower(): float(v) for k, v in user_data["reputation"].items()}
    return {}

def check_condition_details(cond: Condition, context: Dict, set_keyword_counts: Counter) -> Tuple[bool, str]:
    c_type = cond.type
    c_target = cond.target.lower() if cond.target else None
    c_val = cond.value
    
    active_skill = context.get("skill", "").lower()
    loc_id = context.get("location_id")
    loc_tags = context.get("location_tags", set())
    act_id = context.get("activity_id")
    user_ap = context.get("achievement_points", 0)
    total_lvl = context.get("total_skill_level", 0)

    if c_type == ConditionType.GLOBAL:
        return True, "Global"
    elif c_type == ConditionType.SKILL_ACTIVITY:
        if not active_skill: return False, "No active skill"
        if c_target == active_skill: return True, f"Skill is {active_skill}"
        if c_target == "gathering" and active_skill in GATHERING_SKILLS: return True, "Skill is Gathering"
        if c_target == "artisan" and active_skill in ARTISAN_SKILLS: return True, "Skill is Artisan"
        return False, f"Requires {c_target}, current is {active_skill}"
    elif c_type == ConditionType.LOCATION:
        if not loc_id: return False, "No location set"
        if c_target == loc_id.lower(): return True, "Location Match"
        if c_target in loc_tags: return True, f"Location Tag Match ({c_target})"
        return False, f"Requires Location/Tag '{c_target}'"
    elif c_type == ConditionType.REGION:
        if c_target in loc_tags: return True, f"Region Match ({c_target})"
        return False, f"Requires Region '{c_target}'"
    elif c_type == ConditionType.SPECIFIC_ACTIVITY:
        if act_id and c_target == act_id.lower(): return True, "Activity Match"
        return False, "Wrong Activity"
    elif c_type == ConditionType.ACHIEVEMENT_POINTS:
        req = c_val or 0
        if user_ap >= req: return True, f"AP {user_ap} >= {req}"
        return False, f"Requires {req} AP (Have: {user_ap})"
    elif c_type == ConditionType.TOTAL_SKILL_LEVEL:
        req = c_val or 0
        if total_lvl >= req: return True, f"Total Lvl {total_lvl} >= {req}"
        return False, f"Requires {req} Total Lvl (Have: {total_lvl})"
    elif c_type == ConditionType.SET_EQUIPPED:
        norm_target = cond.target.replace("_", " ").strip()
        req = c_val or 1
        count = set_keyword_counts.get(norm_target, 0)
        if count >= req: return True, f"Set '{norm_target}' active ({count}/{req})"
        return False, f"Requires {req}x '{norm_target}' items (Have: {count})"
    return False, f"Unknown condition: {c_type}"

def extract_user_counts(user_data: Dict) -> Dict[str, int]:
    counts = Counter()
    for container in ["bank", "inventory"]:
        data = user_data.get(container, {})
        if isinstance(data, dict):
            for k, v in data.items():
                counts[str(k).lower()] += int(v)
    gear = user_data.get("gear", {})
    if isinstance(gear, dict):
        for v in gear.values():
            if v: counts[str(v).lower()] += 1
    return counts

def get_user_collectibles(all_collectibles: List[Collectible], user_data: Dict) -> List[Collectible]:
    user_owned_ids = set()
    if "collectibles" in user_data and isinstance(user_data["collectibles"], list):
        for c_id in user_data["collectibles"]:
            user_owned_ids.add(str(c_id).lower())
    owned_objs = []
    for c in all_collectibles:
        if c.id.lower() in user_owned_ids or c.wiki_slug.lower() in user_owned_ids:
            owned_objs.append(c)
    return owned_objs

def build_activity_context(activity, user_ap: int, user_total_level: int, loc_map: Dict, drop_calc, selected_location_id: str = None) -> Dict:
    """Shared helper to build exact math context for both Optimizer and Crafting Tree."""
    req_kw = {}
    if hasattr(activity, 'requirements'):
        for req in activity.requirements:
            if req.type == RequirementType.KEYWORD_COUNT and req.target:
                req_kw[req.target.lower().replace("_", " ").strip()] = req.value
                
    current_loc_id = selected_location_id
    if not current_loc_id and getattr(activity, 'locations', None):
        current_loc_id = activity.locations[0]

    current_tags = set()
    if current_loc_id and current_loc_id in loc_map:
        current_tags = {t.lower() for t in loc_map[current_loc_id].tags}
    skill = getattr(activity, 'primary_skill', getattr(activity, 'skill', ""))
    return {
        "skill": skill,
        "location_id": current_loc_id,
        "location_tags": current_tags,
        "activity_id": getattr(activity, 'id', ""),
        "required_keywords": req_kw,
        "achievement_points": user_ap,
        "total_skill_level": user_total_level,
        "special_ev_map": drop_calc.get_special_ev_map()
    }


def filter_user_items(all_items: List[Equipment], user_data: Dict) -> List[Equipment]:
    try:
        owned_ids = set()
        counts = extract_user_counts(user_data)
        for k, v in counts.items():
            if v > 0: owned_ids.add(k)
        
        filtered_items = []
        for item in all_items:
            candidates = set()
            candidates.add(item.id.lower())
            if item.wiki_slug: candidates.add(item.wiki_slug.lower())
            if item.name: candidates.add(item.name.lower())
            base_id = item.id.lower()
            suffixes = ["_common", "_uncommon", "_rare", "_epic", "_legendary", "_ethereal", "_normal"]
            for s in suffixes:
                if base_id.endswith(s): candidates.add(base_id.replace(s, ""))
            
            if not owned_ids.isdisjoint(candidates):
                filtered_items.append(item)
        return filtered_items
    except Exception:
        return all_items

def get_compatible_services(recipe: Recipe, all_services: List[Service]) -> List[Service]:
    compatible = []
    recipe_tier_req = "basic"
    is_cursed_req = "cursed" in recipe.service.lower()
    
    if "advanced" in recipe.service.lower():
        recipe_tier_req = "advanced"
        
    for s in all_services:
        if s.skill != recipe.skill: continue
        if recipe_tier_req == "advanced" and s.tier.lower() != "advanced": continue
        s_is_cursed = "cursed" in s.id.lower() or "cursed" in s.name.lower()
        if is_cursed_req and not s_is_cursed: continue
        compatible.append(s)
    
    return sorted(compatible, key=lambda x: x.name)

def synthesize_activity_from_recipe(recipe: Recipe, service: Service) -> Activity:
    combined_reqs = list(recipe.requirements) if hasattr(recipe, 'requirements') else [] 
    has_level_req = False
    for r in combined_reqs:
        if r.type == RequirementType.SKILL_LEVEL: has_level_req = True
    
    if not has_level_req and recipe.level > 1:
        combined_reqs.append(Requirement(type=RequirementType.SKILL_LEVEL, target=recipe.skill, value=recipe.level))
        
    combined_reqs.extend(service.requirements)

    return Activity(
        id=f"{recipe.id}__@{service.id}",
        wiki_slug=recipe.wiki_slug,
        name=f"{recipe.name} (@ {service.name})",
        primary_skill=recipe.skill,
        locations=(service.location,),
        base_steps=recipe.base_steps,
        base_xp=recipe.base_xp,
        max_efficiency=recipe.max_efficiency,
        requirements=tuple(combined_reqs),
        modifiers=service.modifiers 
    )

def extract_modifier_stats(modifiers: List[Modifier]) -> Dict[str, float]:
    stats = {}
    for mod in modifiers:
        val = mod.value
        if mod.stat in PERCENTAGE_STATS:
            val = val / 100.0
            
        k = mod.stat.value
        if k == StatName.BONUS_XP_ADD.value: k = "flat_xp"
        elif k == StatName.BONUS_XP_PERCENT.value: k = "xp_percent"
        elif k == StatName.XP_PERCENT.value: k = "xp_percent"
        elif k == StatName.STEPS_ADD.value: 
            k = "flat_step_reduction"
            val = -val 
        elif k == StatName.STEPS_PERCENT.value: 
            k = "percent_step_reduction"
            val = -val
            
        stats[k] = stats.get(k, 0.0) + val
    return stats

def can_tree_use_fine(node: CraftingNode, drop_calc: 'DropCalculator') -> bool:
    if node.source_type == "recipe":
        # A recipe can use fine materials if ALL of its inputs can.
        if not node.inputs:
            return False
            
        for child in node.inputs.values():
            if not can_tree_use_fine(child, drop_calc):
                return False
        return True
        
    else:
        # For leaf nodes (activity, chest, bank), check if the base item 
        # has a known fine variant in the game data.
        if node.item_id.endswith("_fine"):
            return True
            
        return node.item_id in drop_calc.fine_material_map
 
def can_use_pet_ability(ability_name: str, node: CraftingNode, game_data_dict: dict) -> bool:
    """Checks if the equipped pet's ability can actually be used on this specific node."""
    if ability_name not in INSTANT_ACTION_PET_ABILITIES:
        return False
        
    reqs = INSTANT_ACTION_PET_ABILITIES[ability_name]
    
    if node.source_type not in reqs.get("allowed_source_types", []):
        return False
        
    if node.source_type == "recipe":
        recipe = game_data_dict['recipes'].get(node.source_id)
        if not recipe: return False
        
        if reqs.get("skill") and recipe.skill.lower() != reqs["skill"].lower():
            return False
        if reqs.get("recipe_name_contains") and reqs["recipe_name_contains"].lower() not in recipe.name.lower():
            return False
            
    elif node.source_type == "activity":
        activity = game_data_dict['activities'].get(node.source_id)
        if not activity: return False
        
        if reqs.get("skill") and activity.primary_skill.lower() != reqs["skill"].lower():
            return False
            
    return True
def get_applicable_abilities(node: CraftingNode, game_data_dict: dict) -> List[Tuple[Any, Any]]:
    """Scans all pets to find any abilities that can be used on this specific node."""
    applicable = []
    for pet in game_data_dict.get('pets', {}).values():
        for lvl in pet.levels:
            for ab in lvl.abilities:
                if can_use_pet_ability(ab.name, node, game_data_dict):
                    # Only add the ability once per pet (in case it appears on multiple levels)
                    if not any(a.name == ab.name for p, a in applicable):
                        applicable.append((pet, ab))
    return applicable
def build_default_tree(item_id: str, game_data: Dict, amount_needed=1, current_depth=0) -> CraftingNode:
    node = CraftingNode(
        node_id=str(uuid.uuid4())[:8],
        item_id=item_id,
        source_type="bank",
        base_requirement_amount=amount_needed
    )
    
    if current_depth > 12: return node
    
    sources = [{"type": "bank", "id": "bank", "label": "🏦 Bank / Already Owned"}]

    for r in game_data['recipes'].values():
        if r.output_item_id == item_id:
            sources.append({"type": "recipe", "id": r.id, "label": f"🔨 [Recipe] {r.name}"})
            
    for act in game_data['activities'].values():
        for table in act.loot_tables:
            for drop in table.drops:
                if drop.item_id == item_id:
                    sources.append({"type": "activity", "id": act.id, "label": f"🪓 [Activity] {act.name}"})
                    break

    for chest in game_data['chests'].values():
        for drop in chest.drops:
            if drop.item_id == item_id:
                for act in game_data['activities'].values():
                    for table in act.loot_tables:
                        for c_drop in table.drops:
                            if c_drop.item_id == chest.id:
                                sources.append({
                                    "type": "chest", 
                                    "id": f"{chest.id}::{act.id}", 
                                    "label": f"🧰 [Chest] {chest.name} (via {act.name})"
                                })
                                break

    node.available_sources = sources

    if len(sources) > 1:
        best = sources[1]
        node.source_type = best["type"]
        if best["type"] == "chest":
            node.source_id, node.parent_activity_id = best["id"].split("::")
        else:
            node.source_id = best["id"]
            
        if best["type"] == "recipe":
            recipe = game_data['recipes'][node.source_id]
            if recipe.materials:
                for i, material_group in enumerate(recipe.materials):
                    if not material_group: continue
                    mat = material_group[0] 
                    child_node = build_default_tree(mat.item_id, game_data, mat.amount, current_depth + 1)
                    node.inputs[f"{mat.item_id}_{i}"] = child_node

    return node

def calculate_node_cost(
    node: CraftingNode, 
    loadouts: Dict[str, Loadout], 
    game_data: Dict[str, Any], 
    drop_calc: DropCalculator, 
    player_skill_levels: Dict[str, int]
) -> float:
    if node.source_type == "bank":
        return 0.0

    loadout = loadouts.get(node.loadout_id)
    gear_set = loadout.gear_set if loadout else GearSet()
    
    target_item_id = node.item_id
    if node.use_fine_materials and not target_item_id.endswith("_fine"):
        target_item_id = f"{target_item_id}_fine"

    recipe_obj, activity_obj = None, None
    skill_name, min_level = "", 1
    node_context = {"achievement_points": 0, "total_skill_level": 0} 
    
    if node.source_type == "recipe":
        recipe_obj = game_data['recipes'].get(node.source_id)
        if not recipe_obj: return float('inf')
        skill_name, min_level = recipe_obj.skill, recipe_obj.level
        node_context["skill"] = skill_name
    elif node.source_type in ["activity", "chest"]:
        act_id = node.source_id if node.source_type == "activity" else node.parent_activity_id
        activity_obj = game_data['activities'].get(act_id)
        if not activity_obj: return float('inf')
        skill_name, min_level = activity_obj.primary_skill, activity_obj.level
        node_context["skill"] = skill_name
        if activity_obj.locations: node_context["location_id"] = activity_obj.locations[0]

    player_lvl = player_skill_levels.get(skill_name.lower(), 99) if skill_name else 99
    stats = gear_set.get_stats(node_context)
    
    DA = stats.get("double_action", 0.0)
    DR = stats.get("double_rewards", 0.0)
    NMC = stats.get("no_materials_consumed", 0.0)
    
    p_valid_quality = 1.0
    if node.target_quality not in [EquipmentQuality.NORMAL, EquipmentQuality.NONE]:
        from utils.constants import QUALITY_RANK
        target_rank = QUALITY_RANK.get(node.target_quality, 0)
        if node.use_fine_materials: target_rank = max(1, target_rank - 1)
        
        probs = calculate_quality_probabilities(min_level, player_lvl, stats.get("quality_outcome", 0))
        valid_tiers = [q.value for q, r in QUALITY_RANK.items() if r >= target_rank and q != EquipmentQuality.NONE]
        p_valid_quality = sum(probs.get(q, 0.0) for q in valid_tiers)
        if p_valid_quality <= 0.00001: return float('inf')

    if node.source_type == "recipe":
        steps_per_action = calculate_steps(recipe_obj, player_lvl, stats.get("work_efficiency", 0.0), int(stats.get("flat_step_reduction", 0)), stats.get("percent_step_reduction", 0.0))
        q_out = recipe_obj.output_quantity
        isolated_steps = steps_per_action / ((1.0 + DA) * (1.0 + DR) * q_out * p_valid_quality)
        
        children_cost = 0.0
        for input_id, child_node in node.inputs.items():
            req_amount = child_node.base_requirement_amount
            input_ratio = ((1.0 - NMC) * req_amount) / ((1.0 + DR) * q_out * p_valid_quality)
            child_cost = calculate_node_cost(child_node, loadouts, game_data, drop_calc, player_skill_levels)
            children_cost += (input_ratio * child_cost)
            
        return isolated_steps + children_cost

    elif node.source_type == "activity":
        drop_table = drop_calc.get_drop_table(activity_obj, stats, player_lvl)
        for drop in drop_table:
            if drop["Item"] == target_item_id: return drop["Steps"] / p_valid_quality
        return float('inf')

    elif node.source_type == "chest":
        chest_obj = game_data['chests'].get(node.source_id)
        if not chest_obj: return float('inf')
        drop_table = drop_calc.get_drop_table(activity_obj, stats, player_lvl)
        steps_per_chest = float('inf')
        for drop in drop_table:
            if drop["Item"] == node.source_id:
                steps_per_chest = drop["Steps"]
                break
        if steps_per_chest == float('inf'): return float('inf')
        
        expected_items_per_chest = 0.0
        for drop in chest_obj.drops:
            if drop.item_id == target_item_id:
                chance = (drop.chance or 0.0) / 100.0
                avg_q = (drop.min_quantity + drop.max_quantity) / 2.0
                expected_items_per_chest += (chance * avg_q)
        if expected_items_per_chest == 0: return float('inf')
        return (steps_per_chest / expected_items_per_chest) / p_valid_quality

    return 0.0

@st.cache_data
def load_data():
    base_path = "game_data/wiki_export/autogenerated"
    equipment_path = f"{base_path}/equipment.json"
    act_path = f"{base_path}/activities.json"
    rec_path = f"{base_path}/recipes.json"
    loc_path = f"{base_path}/locations.json"
    services_path = f"{base_path}/services.json"
    collectibles_path = f"{base_path}/collectibles.json"
    
    items, activities, recipes, locations, services, collectibles = load_game_data(
        equipment_path, act_path, rec_path, loc_path, services_path, collectibles_path
    )
    
    pets = []
    pets_path = f"{base_path}/pets.json"
    if os.path.exists(pets_path):
        try:
            with open(pets_path, "r", encoding="utf-8") as f:
                pets_data = json.load(f)
                for p_data in pets_data:
                    pets.append(Pet(**p_data))
        except Exception as e:
            st.error(f"Error loading pets.json: {e}")

    consumables = []
    cons_path = f"{base_path}/consumables.json"
    if os.path.exists(cons_path):
        try:
            with open(cons_path, "r", encoding="utf-8") as f:
                cons_data = json.load(f)
                for c_data in cons_data:
                    consumables.append(Consumable(**c_data))
        except Exception as e:
            st.error(f"Error loading consumables.json: {e}")

    containers = []
    cont_path = f"{base_path}/containers.json"
    if os.path.exists(cont_path):
        try:
            with open(cont_path, "r", encoding="utf-8") as f:
                cont_data = json.load(f)
                for c_data in cont_data: containers.append(Container(**c_data))
        except Exception as e: st.error(f"Error loading containers.json: {e}")
            
    return items, activities, recipes, locations, services, collectibles, pets, consumables, containers