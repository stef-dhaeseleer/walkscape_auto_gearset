import streamlit as st
import streamlit.components.v1 as components
import json
import math
import os
import pandas as pd
from typing import List, Dict, Optional, Tuple
from collections import Counter, defaultdict

# Updated imports
from utils.data_loader import load_game_data
from utils.utils import calculate_steps
from utils.export import export_gearset
from gear_optimizer import GearOptimizer, OPTIMAZATION_TARGET, PERCENTAGE_STATS, StatName
from models import (
    Equipment, GearSet, Collectible, Modifier, Condition, Service, Recipe, Activity, 
    Requirement, RequirementType, ConditionType, GATHERING_SKILLS, ARTISAN_SKILLS,
    Pet, PetLevel
)

# --- Page Config ---
st.set_page_config(
    page_title="WalkScape Gear Optimizer",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Custom CSS ---
st.markdown("""
    <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }
        iframe { width: 100%; }
        .service-mod {
            font-size: 0.85rem;
            color: #d1d5db;
            background-color: #374151;
            padding: 2px 6px;
            border-radius: 4px;
            margin-right: 4px;
            display: inline-block;
            margin-bottom: 4px;
        }
        .mod-active {
            color: #4ade80; /* Green */
            font-size: 0.9rem;
        }
        .mod-inactive {
            color: #f87171; /* Red */
            font-size: 0.9rem;
            text-decoration: line-through;
            opacity: 0.7;
        }
        .mod-condition {
            font-size: 0.8rem;
            color: #9ca3af; /* Gray */
            font-style: italic;
            margin-left: 1rem;
        }
        .item-header {
            font-weight: bold;
            font-size: 1rem;
            margin-top: 0.5rem;
            margin-bottom: 0.2rem;
        }
    </style>
""", unsafe_allow_html=True)

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
    """Extracts reputation dictionary from user save data."""
    if "reputation" in user_data and isinstance(user_data["reputation"], dict):
        return {k.lower(): float(v) for k, v in user_data["reputation"].items()}
    return {}

def check_condition_details(cond: Condition, context: Dict, set_keyword_counts: Counter) -> Tuple[bool, str]:
    """
    Checks if a condition is met and returns (IsMet, ReasonString).
    """
    c_type = cond.type
    c_target = cond.target.lower() if cond.target else None
    c_val = cond.value
    
    # Extract context
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

@st.cache_data
def load_data():
    base_path = "game_data/wiki_export/autogenerated"
    equipment_path = f"{base_path}/equipment.json"
    act_path = f"{base_path}/activities.json"
    rec_path = f"{base_path}/recipes.json"
    loc_path = f"{base_path}/locations.json"
    services_path = f"{base_path}/services.json"
    collectibles_path = f"{base_path}/collectibles.json"
    
    # Load Main Game Data
    items, activities, recipes, locations, services, collectibles = load_game_data(
        equipment_path, act_path, rec_path, loc_path, services_path, collectibles_path
    )
    
    # Load Pets specific logic here or inside data_loader if moved later
    pets_path = f"{base_path}/pets.json"
    pets = []
    if os.path.exists(pets_path):
        try:
            with open(pets_path, "r", encoding="utf-8") as f:
                pets_data = json.load(f)
                for p_data in pets_data:
                    pets.append(Pet(**p_data))
        except Exception as e:
            st.error(f"Error loading pets.json: {e}")
            
    return items, activities, recipes, locations, services, collectibles, pets


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

# --- Main App ---
def main():
    all_items_raw, activities, recipes, locations, services, all_collectibles_raw, all_pets = load_data()   
    
    # Create a lookup map for locations to fix context generation
    loc_map = {loc.id: loc for loc in locations}

    WIKI_URL = "https://gear.walkscape.app"

    st.title("🛡️ WalkScape Gear Optimizer")

    # --- Inputs ---
    with st.container():
        with st.expander("📂 User Save Data & Settings", expanded=True):
            col_json, col_opts = st.columns([3, 1])
            with col_json:
                user_json_input = st.text_area(
                    "Paste User JSON", 
                    height=70, 
                    placeholder='{"name": "...", "skills": {...}, "collectibles": [...], "reputation": {...}}'
                )
            
            user_data = None
            calculated_char_lvl = 99
            user_skills_map = {}
            valid_json = False
            item_counts = {}
            user_ap = 0
            user_total_level = 0
            owned_collectibles = []
            user_reputation = {} 

            if user_json_input.strip():
                try:
                    user_data = json.loads(user_json_input)
                    valid_json = True
                    steps = user_data.get("steps", 0)
                    calculated_char_lvl = calculate_char_level_from_steps(steps)
                    user_skills_map = user_data.get("skills", {})
                    user_ap = user_data.get("achievement_points", 0)
                    item_counts = extract_user_counts(user_data)
                    user_reputation = extract_user_reputation(user_data)
                    
                    if user_skills_map:
                        user_total_level = calculate_total_level(user_skills_map)

                    if all_collectibles_raw:
                        owned_collectibles = get_user_collectibles(all_collectibles_raw, user_data)
                    
                    st.success(f"Loaded: {user_data.get('name', 'Player')} | Items: {len(item_counts)} | AP: {user_ap} | Total Lvl: {user_total_level} | Rep Factions: {len(user_reputation)}")
                except json.JSONDecodeError:
                    st.error("Invalid JSON")
            
            with col_opts:
                st.write("")
                use_owned = st.checkbox("Only use owned items", value=valid_json)

        # --- PET SELECTION UI ---
        with st.expander("🐾 Active Pet Selection", expanded=False):
            st.caption("Select your active pet and its level. Stats will be treated as permanent modifiers.")
            col_pet, col_lvl = st.columns([2, 1])
            
            with col_pet:
                pet_names = ["None"] + [p.name for p in all_pets]
                selected_pet_name = st.selectbox("Select Pet", pet_names)
            
            selected_pet = None
            if selected_pet_name != "None":
                selected_pet = next((p for p in all_pets if p.name == selected_pet_name), None)
                
            with col_lvl:
                if selected_pet:
                    # Get max level for this pet
                    max_lvl = max([l.level for l in selected_pet.levels]) if selected_pet.levels else 1
                    # Ensure we have at least level 1
                    lvls = list(range(1, max_lvl + 1))
                    sel_level = st.selectbox("Pet Level", lvls, index=len(lvls)-1)
                    
                    # Update the Pet Object state
                    # We create a COPY to avoid mutating the cached object 
                    selected_pet = selected_pet.copy(update={"active_level": sel_level})
                    
                    # Display Modifiers Preview
                    st.caption(f"**Level {sel_level} Effects:**")
                    mods = selected_pet.modifiers
                    if not mods:
                        st.caption("No modifiers.")
                    else:
                        html = ""
                        for mod in mods:
                            val = mod.value
                            if mod.stat in PERCENTAGE_STATS: val = f"{val}%"
                            html += f"<span class='service-mod'>{mod.stat.replace('_',' ').title()}: {val}</span>"
                        st.markdown(html, unsafe_allow_html=True)
                else:
                    st.selectbox("Pet Level", ["-"], disabled=True)

        c1, c2, c3 = st.columns([2, 1, 1])
        
        # Prepare Unified List
        act_map = {f"[Activity] {a.name}": a for a in activities}
        rec_map = {f"[Recipe] {r.name}": r for r in recipes}
        combined_map = {**act_map, **rec_map}
        combined_names = sorted(list(combined_map.keys()))

        with c1:
            selected_key = st.selectbox("Select Activity or Recipe", options=combined_names, index=None, placeholder="Search...")
            
            selected_obj = None
            is_recipe = False
            selected_service = None
            
            if selected_key:
                selected_obj = combined_map[selected_key]
                if isinstance(selected_obj, Recipe):
                    is_recipe = True
                    # Service Selector
                    compatible_services = get_compatible_services(selected_obj, services)
                    if compatible_services:
                        s_names = [f"{s.name} ({s.location})" for s in compatible_services]
                        s_idx = st.selectbox("Select Service", range(len(s_names)), format_func=lambda x: s_names[x])
                        selected_service = compatible_services[s_idx]
                        
                        # Display Service Context
                        if selected_service.modifiers or selected_service.requirements:
                            st.caption("Service Effects:")
                            html = ""
                            for mod in selected_service.modifiers:
                                val = mod.value
                                if mod.stat in PERCENTAGE_STATS: val = f"{val}%"
                                html += f"<span class='service-mod'>{mod.stat.replace('_',' ').title()}: {val}</span>"
                            for req in selected_service.requirements:
                                if req.type == RequirementType.KEYWORD_COUNT:
                                    html += f"<span class='service-mod'>Req: {req.value}x {req.target.replace('_',' ').title()}</span>"
                            st.markdown(html, unsafe_allow_html=True)
                    else:
                        st.error("No compatible services found for this recipe!")
        
        with c2:
            target_options = {t.name.replace('_', ' ').title(): t for t in OPTIMAZATION_TARGET}
            selected_target_key = st.selectbox("Target Stat", options=list(target_options.keys()))
            selected_target = target_options[selected_target_key]
        
        with c3:
            st.write("")
            st.write("")
            # Disable if recipe selected but no service
            can_run = (selected_obj is not None)
            if is_recipe and not selected_service: can_run = False
            
            run_opt = st.button("🚀 Optimize", type="primary", width="stretch", disabled=not can_run)

    st.divider()

    left_col, right_col = st.columns([1, 2.5])

    # --- WIKI ---
    with right_col:
        st.subheader("Gear Tool Reference (fala's tool)")
        components.iframe(WIKI_URL, height=1200, scrolling=True)

    # --- RESULTS & DEBUGGER ---
    with left_col:
        st.subheader("Results")

        if use_owned and user_data:
            available_items = filter_user_items(all_items_raw, user_data)
        else:
            available_items = all_items_raw
            item_counts = None

        if run_opt and selected_obj:
            
            # Prepare Activity Object
            final_activity = selected_obj
            service_modifiers_stats = {}
            
            if is_recipe and selected_service:
                final_activity = synthesize_activity_from_recipe(selected_obj, selected_service)
                service_modifiers_stats = extract_modifier_stats(selected_service.modifiers)

            player_lvl = calculated_char_lvl if valid_json else 99
            final_skill_lvl = 99
            if valid_json and final_activity.primary_skill:
                skill_key = final_activity.primary_skill.lower()
                skill_xp = user_skills_map.get(skill_key, 0)
                final_skill_lvl = calculate_level_from_xp(skill_xp)
            
            # Recreate optimizer fresh each run
            optimizer = GearOptimizer(available_items, all_locations=locations)
            
            # --- Optimize ---
            with st.spinner(f"Optimizing {final_activity.name}..."):
                
                # Rebuild context for session
                req_kw = {} 
                for req in final_activity.requirements:
                    if req.type == RequirementType.KEYWORD_COUNT and req.target:
                         req_kw[req.target.lower().replace("_", " ").strip()] = req.value
                
                # Determine correct location tags
                current_loc_id = final_activity.locations[0] if final_activity.locations else None
                current_tags = set()
                if current_loc_id and current_loc_id in loc_map:
                    current_tags = {t.lower() for t in loc_map[current_loc_id].tags}

                context = {
                    "skill": final_activity.primary_skill,
                    "location_id": current_loc_id,
                    "location_tags": current_tags,
                    "activity_id": final_activity.id,
                    "required_keywords": req_kw,
                    "achievement_points": user_ap,
                    "total_skill_level": user_total_level
                }

                best_gear = optimizer.optimize(
                    final_activity, 
                    player_level=player_lvl, 
                    player_skill_level=final_skill_lvl,
                    optimazation_target=selected_target,
                    owned_item_counts=item_counts if use_owned else None,
                    achievement_points=user_ap,
                    user_reputation=user_reputation,
                    owned_collectibles=owned_collectibles,
                    extra_passive_stats=service_modifiers_stats,
                    context_override=context,
                    pet=selected_pet # Pass the selected pet
                )

                # Save session state
                st.session_state['best_gear'] = best_gear
                st.session_state['final_skill_lvl'] = final_skill_lvl
                st.session_state['selected_activity_obj'] = final_activity 
                st.session_state['service_stats'] = service_modifiers_stats
                st.session_state['debug_candidates'] = optimizer.debug_candidates
                st.session_state['debug_rejected'] = optimizer.debug_rejected
                st.session_state['owned_collectibles'] = owned_collectibles
                st.session_state['context'] = context
                st.session_state['selected_pet'] = selected_pet

        # --- Display Results ---
        if 'best_gear' in st.session_state:
            best_gear = st.session_state['best_gear']
            context = st.session_state['context']
            saved_skill_lvl = st.session_state.get('final_skill_lvl', 99)
            saved_activity = st.session_state.get('selected_activity_obj')
            saved_collectibles = st.session_state.get('owned_collectibles', [])
            saved_service_stats = st.session_state.get('service_stats', {})
            saved_pet = st.session_state.get('selected_pet')

            optimizer = GearOptimizer(available_items, all_locations=locations) 

            if saved_activity:
                # Calculate full passive stats (Collectibles + Service)
                passive_stats = optimizer._calculate_passive_stats(saved_collectibles, context)
                for k,v in saved_service_stats.items():
                    passive_stats[k] = passive_stats.get(k, 0.0) + v

                score = optimizer.calculate_score(best_gear, saved_activity, saved_skill_lvl, selected_target, context, passive_stats=passive_stats)
                
                stats = best_gear.get_stats(context)
                for k, v in passive_stats.items():
                    stats[k] = stats.get(k, 0.0) + v

                final_steps = calculate_steps(
                    saved_activity, saved_skill_lvl, 
                    stats.get("work_efficiency", 0), 
                    stats.get("flat_step_reduction", 0), 
                    stats.get("percent_step_reduction", 0)
                )

                # --- Metrics ---
                c1, c2 = st.columns(2)
                c1.metric("Steps", final_steps, delta=f"{saved_activity.base_steps}", delta_color="inverse")
                c1.caption(f"Score: {score:.5f}")
                
                val_fmt = ""
                if selected_target.name == "fine":
                    val = stats.get('fine_material_finding', 0) * 100
                    val_fmt = f"{val:.1f}% Fine"
                elif selected_target.name == "xp":
                    val = stats.get('xp_percent', 0) * 100
                    val_fmt = f"{val:.1f}% XP"
                elif selected_target.name == "quality":
                    val = stats.get('quality_outcome', 0)
                    val_fmt = f"{val} Quality"
                c2.metric("Target Stat", val_fmt)

                st.divider()

                # --- Loadout ---
                loadout_data = []
                # Include Pet in loadout if active
                if saved_pet:
                     loadout_data.append({"Slot": "🐾 Pet", "Item": f"{saved_pet.name} (Lvl {saved_pet.active_level})"})
                     
                for slot in ["Head", "Chest", "Legs", "Feet", "Back", "Cape", "Neck", "Hands", "Primary", "Secondary"]:
                    item = getattr(best_gear, slot.lower())
                    loadout_data.append({"Slot": slot, "Item": item.name if item else "-"})
                
                for i, ring in enumerate(best_gear.rings):
                    loadout_data.append({"Slot": f"Ring {i+1}", "Item": ring.name})
                for i, tool in enumerate(best_gear.tools):
                    loadout_data.append({"Slot": f"Tool {i+1}", "Item": tool.name})

                st.dataframe(pd.DataFrame(loadout_data), hide_index=True, width="stretch")

                # --- Detailed Breakdown (New Feature) ---
                with st.expander("🔍 Detailed Item Breakdown", expanded=False):
                    st.caption("Inspect active modifiers and conditions for each item.")
                    
                    # 1. Gather all equipped items with slot names
                    equipped_items = []
                    for slot in ["Head", "Chest", "Legs", "Feet", "Back", "Cape", "Neck", "Hands", "Primary", "Secondary"]:
                        item = getattr(best_gear, slot.lower())
                        if item: equipped_items.append((slot, item))
                    for i, r in enumerate(best_gear.rings):
                        equipped_items.append((f"Ring {i+1}", r))
                    for i, t in enumerate(best_gear.tools):
                        equipped_items.append((f"Tool {i+1}", t))

                    set_counts = best_gear.get_keyword_counts()
                    
                    # --- Regular Items ---
                    for slot_name, item in equipped_items:
                        st.markdown(f"<div class='item-header'>{slot_name}: {item.name}</div>", unsafe_allow_html=True)
                        if not item.modifiers:
                            st.caption("No modifiers.")
                            continue
                            
                        html_mods = ""
                        for mod in item.modifiers:
                            is_active = True
                            fail_reasons = []
                            
                            for cond in mod.conditions:
                                met, reason = check_condition_details(cond, context, set_counts)
                                if not met:
                                    is_active = False
                                    fail_reasons.append(reason)
                            
                            val_str = f"{mod.value}"
                            if mod.stat in PERCENTAGE_STATS: val_str += "%"
                            stat_name = mod.stat.replace('_', ' ').title()
                            
                            if is_active:
                                html_mods += f"<div class='mod-active'>✅ <b>{stat_name}</b>: +{val_str}</div>"
                            else:
                                html_mods += f"<div class='mod-inactive'>❌ <b>{stat_name}</b>: +{val_str}</div>"
                                for r in fail_reasons:
                                    html_mods += f"<div class='mod-condition'>↳ {r}</div>"
                        
                        st.markdown(html_mods, unsafe_allow_html=True)
                        st.markdown("---")

                    # --- Permanent Modifiers (Pet / Collectibles) ---
                    st.markdown("### ♾️ Permanent Modifiers")
                    
                    # 1. Pet
                    if saved_pet:
                        st.markdown(f"<div class='item-header'>🐾 Pet: {saved_pet.name} (Lvl {saved_pet.active_level})</div>", unsafe_allow_html=True)
                        mods = saved_pet.modifiers
                        if mods:
                            html_mods = ""
                            for mod in mods:
                                is_active = True
                                fail_reasons = []
                                for cond in mod.conditions:
                                    met, reason = check_condition_details(cond, context, set_counts)
                                    if not met: is_active = False; fail_reasons.append(reason)
                                
                                val_str = f"{mod.value}"
                                if mod.stat in PERCENTAGE_STATS: val_str += "%"
                                stat_name = mod.stat.replace('_', ' ').title()
                                
                                if is_active:
                                    html_mods += f"<div class='mod-active'>✅ <b>{stat_name}</b>: +{val_str}</div>"
                                else:
                                    html_mods += f"<div class='mod-inactive'>❌ <b>{stat_name}</b>: +{val_str}</div>"
                                    for r in fail_reasons: html_mods += f"<div class='mod-condition'>↳ {r}</div>"
                            st.markdown(html_mods, unsafe_allow_html=True)
                        else:
                            st.caption("No modifiers for this level.")
                        st.markdown("---")
                    
                    # 2. Collectibles
                    if saved_collectibles:
                        st.markdown(f"<div class='item-header'>🏆 Collectibles ({len(saved_collectibles)})</div>", unsafe_allow_html=True)
                        active_coll_mods = []
                        for coll in saved_collectibles:
                            for mod in coll.modifiers:
                                is_active = True
                                for cond in mod.conditions:
                                    met, _ = check_condition_details(cond, context, set_counts)
                                    if not met: is_active = False; break
                                if is_active:
                                    active_coll_mods.append((coll.name, mod))
                        
                        if active_coll_mods:
                            html_coll = ""
                            for name, mod in active_coll_mods:
                                 val_str = f"{mod.value}"
                                 if mod.stat in PERCENTAGE_STATS: val_str += "%"
                                 html_coll += f"<div class='mod-active'>✅ <b>{mod.stat.replace('_',' ').title()}</b>: +{val_str} <span style='color:gray; font-size:0.8em'>({name})</span></div>"
                            st.markdown(html_coll, unsafe_allow_html=True)
                        else:
                            st.caption("No collectibles currently active.")


                # --- Export Section ---
                st.success("✅ **Export Ready**")
                
                export_json = export_gearset(best_gear)
                
                st.caption("Hover over the top-right of the code block to copy!")
                st.code(export_json, language="json")
                
                js_code = f"""
                <script>
                function copyToClipboard() {{
                    var content = {json.dumps(export_json)};
                    navigator.clipboard.writeText(content).then(function() {{
                        document.getElementById("copyBtn").innerHTML = "✅ Copied!";
                        setTimeout(function() {{
                            document.getElementById("copyBtn").innerHTML = "Copy Export";
                        }}, 2000);
                    }}, function(err) {{
                        console.error('Async: Could not copy text: ', err);
                    }});
                }}
                </script>
                <div style="text-align: right; margin-top: 5px;">
                    <button id="copyBtn" onclick="copyToClipboard()" style="
                        background-color: #ff4b4b; 
                        color: white; 
                        border: none; 
                        padding: 8px 15px; 
                        border-radius: 4px; 
                        cursor: pointer; 
                        font-family: 'Source Sans Pro', sans-serif;
                        font-weight: 600;
                        font-size: 14px;
                    ">Copy Export</button>
                </div>
                """
                components.html(js_code, height=50)

                # --- DEBUGGER TABS ---
                st.markdown("---")
                with st.expander("🧪 Laboratory / Debugger", expanded=False):
                    
                    tab_exp, tab_cand = st.tabs(["Item Swapper", "🕵️ Candidate Inspector"])
                    
                    # TAB 1: Item Swapper
                    with tab_exp:
                        st.info("Manually swap an item to verify the calculation logic.")
                        d_col1, d_col2 = st.columns([1, 1])
                        
                        with d_col1:
                            slot_options = ["Head", "Chest", "Legs", "Feet", "Back", "Cape", "Neck", "Hands", "Primary", "Secondary", "Ring 1", "Ring 2", "Tool 1", "Tool 2", "Tool 3", "Tool 4", "Tool 5", "Tool 6"]
                            edit_slot = st.selectbox("Select Slot to Swap", options=slot_options)
                            
                            current_item_name = "-"
                            if "Tool" in edit_slot:
                                idx = int(edit_slot.split(" ")[1]) - 1
                                if idx < len(best_gear.tools): current_item_name = best_gear.tools[idx].name
                            elif "Ring" in edit_slot:
                                idx = int(edit_slot.split(" ")[1]) - 1
                                if idx < len(best_gear.rings): current_item_name = best_gear.rings[idx].name
                            else:
                                current_item_obj = getattr(best_gear, edit_slot.lower(), None)
                                if current_item_obj: current_item_name = current_item_obj.name
                            
                            st.caption(f"Currently Equipped: **{current_item_name}**")

                            slot_enum_map = {
                                "Head": "head", "Chest": "chest", "Legs": "legs", "Feet": "feet",
                                "Back": "back", "Cape": "cape", "Neck": "neck", "Hands": "hands",
                                "Primary": "primary", "Secondary": "secondary",
                                "Ring": "ring", "Tool": "tools"
                            }
                            target_enum = slot_enum_map.get(edit_slot.split(" ")[0])
                            
                            valid_swap_items = [i for i in available_items if i.slot == target_enum]
                            valid_swap_items.sort(key=lambda x: x.name)
                            
                            swap_item_name = st.selectbox("Swap with:", options=[i.name for i in valid_swap_items], index=None)
                            swap_item_obj = next((i for i in valid_swap_items if i.name == swap_item_name), None)

                        with d_col2:
                            if swap_item_obj:
                                test_gear = GearSet(**best_gear.dict())
                                test_gear.rings = list(best_gear.rings)
                                test_gear.tools = list(best_gear.tools)
                                test_gear.pet = best_gear.pet # Ensure Pet is preserved in swap test
                                
                                if "Tool" in edit_slot:
                                    idx = int(edit_slot.split(" ")[1]) - 1
                                    while len(test_gear.tools) <= idx: test_gear.tools.append(None)
                                    if idx < len(test_gear.tools): test_gear.tools[idx] = swap_item_obj
                                    else: test_gear.tools.append(swap_item_obj)
                                elif "Ring" in edit_slot:
                                    idx = int(edit_slot.split(" ")[1]) - 1
                                    while len(test_gear.rings) <= idx: test_gear.rings.append(None)
                                    if idx < len(test_gear.rings): test_gear.rings[idx] = swap_item_obj
                                    else: test_gear.rings.append(swap_item_obj)
                                else:
                                    setattr(test_gear, edit_slot.lower(), swap_item_obj)

                                analysis = optimizer.analyze_score(test_gear, saved_activity, saved_skill_lvl, selected_target, context, passive_stats=passive_stats)
                                test_score = analysis.get("score", 0)
                                test_steps = analysis.get("denominator", 0)
                                test_formula = analysis.get("formula", "")

                                orig_analysis = optimizer.analyze_score(best_gear, saved_activity, saved_skill_lvl, selected_target, context, passive_stats=passive_stats)
                                orig_score = orig_analysis.get("score", 0)
                                orig_steps = orig_analysis.get("denominator", 0)
                                orig_formula = orig_analysis.get("formula", "")

                                st.markdown("##### Comparison")
                                def show_diff(label, orig, new, is_good_up=True):
                                    diff = new - orig
                                    color = "off"
                                    if diff > 0: color = "green" if is_good_up else "red"
                                    elif diff < 0: color = "red" if is_good_up else "green"
                                    st.markdown(f"**{label}**: {orig:.4f} → **{new:.4f}** :{color}[({diff:+.4f})]")

                                show_diff("Score", orig_score, test_score, True)
                                show_diff("Steps", orig_steps, test_steps, False)
                                
                                st.markdown("**Formula Breakdown**")
                                st.text(f"Original: {orig_formula}")
                                st.text(f"New:      {test_formula}")
                                
                                st.markdown("---")
                                st.caption("Detailed Stat Changes (Including Collectibles & Service):")
                                test_stats = analysis.get("stats", {})
                                orig_stats = orig_analysis.get("stats", {})
                                for k in ["fine_material_finding", "double_rewards", "double_action", "work_efficiency", "xp_percent", "percent_step_reduction"]:
                                    v1 = orig_stats.get(k, 0)
                                    v2 = test_stats.get(k, 0)
                                    if abs(v1-v2) > 0.001:
                                        st.text(f"{k}: {v1:.2f} -> {v2:.2f}")

                    # TAB 2: Candidate Inspector
                    with tab_cand:
                        st.write("Inspect which items passed the filter and their scores.")
                        insp_slot = st.selectbox("Inspect Slot", options=["tools", "ring", "head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary"])
                        
                        debug_candidates = st.session_state.get('debug_candidates', {})
                        debug_rejected = st.session_state.get('debug_rejected', [])
                        
                        # Passed Items
                        items = debug_candidates.get(insp_slot, [])
                        if items:
                            st.markdown(f"**✅ Accepted Candidates ({len(items)})**")
                            # Calculate scores for display
                            cand_data = []
                            for item in items:
                                # Create dummy set
                                d_set = GearSet()
                                d_set.pet = best_gear.pet # Use same pet context
                                if insp_slot == "tools": d_set.tools = [item]
                                elif insp_slot == "ring": d_set.rings = [item]
                                else: 
                                    setattr(d_set, insp_slot, item)
                                
                                s = optimizer.calculate_score(d_set, saved_activity, saved_skill_lvl, selected_target, context, ignore_requirements=True)
                                cand_data.append({"Name": item.name, "Score": s, "ID": item.id})
                            
                            df_cand = pd.DataFrame(cand_data).sort_values(by="Score", ascending=False)
                            st.dataframe(df_cand, width="stretch")
                        else:
                            st.warning("No candidates found for this slot.")

                        # Rejected Items
                        st.markdown("---")
                        st.markdown("**❌ Rejected Items (Sample)**")
                        rejected_in_slot = [r for r in debug_rejected if r['slot'] == insp_slot]
                        if rejected_in_slot:
                             df_rej = pd.DataFrame(rejected_in_slot)
                             st.dataframe(df_rej, width="stretch")
                        else:
                            st.write("No items specifically rejected (all processed items passed or none checked).")

        elif not selected_obj:
            st.info("👈 Select an activity or recipe to start.")
            
        else:
            st.write("Ready.")

if __name__ == "__main__":
    main()