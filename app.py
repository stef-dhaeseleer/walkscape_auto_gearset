import streamlit as st
import streamlit.components.v1 as components
import json
import math
import os
import time
import pandas as pd
from typing import List, Dict, Optional, Tuple, Set
from collections import Counter, defaultdict

# Updated imports
from utils.data_loader import load_game_data
from utils.export import export_gearset
from calculations import calculate_passive_stats, calculate_score, analyze_score, calculate_steps
from gear_optimizer import GearOptimizer, OPTIMAZATION_TARGET, PERCENTAGE_STATS, StatName
from models import (
    Equipment, GearSet, Collectible, Modifier, Condition, Service, Recipe, Activity, 
    Requirement, RequirementType, ConditionType, GATHERING_SKILLS, ARTISAN_SKILLS,
    Pet, PetLevel, Consumable, EquipmentSlot
)

# --- NEW IMPORT ---
from streamlit_js_eval import streamlit_js_eval

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
        /* Style for the target rows to align vertically */
        .stSelectbox, .stSlider {
            margin-bottom: 0px !important;
        }
        
        .score-badge {
            display: inline-flex;
            align-items: center;
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 4px 10px;
            font-size: 0.85rem;
            color: #e2e8f0;
            margin-right: 8px;
            margin-bottom: 8px;
        }
        .score-badge-label {
            color: #94a3b8;
            margin-right: 6px;
            font-weight: 500;
        }
        .score-badge-val {
            font-weight: 700;
            color: #60a5fa;
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
            
    return items, activities, recipes, locations, services, collectibles, pets, consumables


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
    if 'locked_items_state' not in st.session_state:
        st.session_state['locked_items_state'] = {}
    if 'blacklist_state' not in st.session_state:
        st.session_state['blacklist_state'] = []
    if 'user_json_text' not in st.session_state:
        st.session_state['user_json_text'] = ""
    if 'ls_loaded' not in st.session_state:
        st.session_state['ls_loaded'] = False

    # Initialize dynamic target list if not present
    if 'opt_targets_list' not in st.session_state:
        st.session_state['opt_targets_list'] = [{"id": 0, "target": "Reward Rolls", "weight": 100}]
        st.session_state['next_target_id'] = 1

    # --- LOCAL STORAGE: LOAD ---
    stored_json = streamlit_js_eval(js_expressions="localStorage.getItem('WALKSCAPE_USER_DATA')", key="ls_loader")
    
    if stored_json and not st.session_state['ls_loaded']:
        st.session_state['user_json_text'] = stored_json
        st.session_state['ls_loaded'] = True
        st.rerun()

    all_items_raw, activities, recipes, locations, services, all_collectibles_raw, all_pets, all_consumables = load_data()   
    
    loc_map = {loc.id: loc for loc in locations}
    WIKI_URL = "https://gear.walkscape.app"

    st.title("🛡️ WalkScape Gear Optimizer")

    with st.container():
        with st.expander("📂 User Save Data & Settings", expanded=True):
            col_json, col_opts = st.columns([3, 1])
            with col_json:
                user_json_input = st.text_area(
                    "Paste User JSON", 
                    height=70, 
                    placeholder='{"name": "...", "skills": {...}, "collectibles": [...], "reputation": {...}}',
                    key="user_json_text"
                )

                if user_json_input:
                    safe_js_string = json.dumps(user_json_input)
                    streamlit_js_eval(
                        js_expressions=f"localStorage.setItem('WALKSCAPE_USER_DATA', {safe_js_string})",
                        key="ls_saver"
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

        # --- ADVANCED CONFIG (Locks & Blacklist) ---
        with st.expander("⚙️ Advanced Configuration (Locks & Blacklist)", expanded=False):
            st.caption("Manually lock items to slots (bypasses ownership checks) or blacklist items from results.")
            
            tab_locks, tab_blacklist = st.tabs(["🔒 Locked Slots", "🚫 Blacklist"])
            
            with tab_locks:
                st.markdown("**Standard Slots**")
                cols_std = st.columns(5)
                std_slots = [
                    "Head", "Chest", "Legs", "Feet", 
                    "Back", "Cape", "Neck", "Hands", 
                    "Primary", "Secondary"
                ]
                
                all_sorted = sorted(all_items_raw, key=lambda x: x.name)
                items_by_slot = defaultdict(list)
                for item in all_sorted:
                    items_by_slot[item.slot].append(item)
                
                slot_enum_map = {
                    "Head": EquipmentSlot.HEAD, "Chest": EquipmentSlot.CHEST, "Legs": EquipmentSlot.LEGS,
                    "Feet": EquipmentSlot.FEET, "Back": EquipmentSlot.BACK, "Cape": EquipmentSlot.CAPE,
                    "Neck": EquipmentSlot.NECK, "Hands": EquipmentSlot.HANDS, 
                    "Primary": EquipmentSlot.PRIMARY, "Secondary": EquipmentSlot.SECONDARY
                }

                for i, slot_name in enumerate(std_slots):
                    with cols_std[i % 5]:
                        enum_type = slot_enum_map[slot_name]
                        opts = ["None"] + [it.name for it in items_by_slot[enum_type]]
                        ss_key = f"lock_{slot_name.lower()}"
                        
                        def update_lock(s_key=ss_key, s_name=slot_name.lower(), s_enum=enum_type):
                            val = st.session_state[s_key]
                            if val == "None":
                                st.session_state['locked_items_state'].pop(s_name, None)
                            else:
                                found = next((x for x in items_by_slot[s_enum] if x.name == val), None)
                                if found: st.session_state['locked_items_state'][s_name] = found
                        
                        idx = 0
                        current_locked = st.session_state['locked_items_state'].get(slot_name.lower())
                        if current_locked:
                            try: idx = opts.index(current_locked.name)
                            except: idx = 0

                        st.selectbox(slot_name, opts, index=idx, key=ss_key, on_change=update_lock)

                st.markdown("**Rings & Tools**")
                c_ring, c_tool = st.columns([1, 2])
                
                with c_ring:
                    ring_opts = ["None"] + [it.name for it in items_by_slot[EquipmentSlot.RING]]
                    for i in range(2):
                        r_key = f"ring_{i}"
                        ss_key = f"lock_{r_key}"
                        
                        def update_ring(s_key=ss_key, r_k=r_key):
                            val = st.session_state[s_key]
                            if val == "None":
                                st.session_state['locked_items_state'].pop(r_k, None)
                            else:
                                found = next((x for x in items_by_slot[EquipmentSlot.RING] if x.name == val), None)
                                if found: st.session_state['locked_items_state'][r_k] = found

                        curr = st.session_state['locked_items_state'].get(r_key)
                        idx = 0
                        if curr:
                             try: idx = ring_opts.index(curr.name)
                             except: idx = 0
                        st.selectbox(f"Ring {i+1}", ring_opts, index=idx, key=ss_key, on_change=update_ring)
                
                with c_tool:
                    tool_opts = ["None"] + [it.name for it in items_by_slot[EquipmentSlot.TOOLS]]
                    
                    t_cols = st.columns(3)
                    for i in range(6):
                        t_key = f"tool_{i}"
                        ss_key = f"lock_{t_key}"
                        
                        def update_tool(s_key=ss_key, t_k=t_key):
                            val = st.session_state[s_key]
                            if val == "None":
                                st.session_state['locked_items_state'].pop(t_k, None)
                            else:
                                found = next((x for x in items_by_slot[EquipmentSlot.TOOLS] if x.name == val), None)
                                if found: st.session_state['locked_items_state'][t_k] = found

                        curr = st.session_state['locked_items_state'].get(t_key)
                        idx = 0
                        if curr:
                             try: idx = tool_opts.index(curr.name)
                             except: idx = 0
                        
                        with t_cols[i % 3]:
                            st.selectbox(f"Tool {i+1}", tool_opts, index=idx, key=ss_key, on_change=update_tool)

            with tab_blacklist:
                b_col1, b_col2 = st.columns([5, 1])
                with b_col1:
                    filter_opts = ["All", "Head", "Chest", "Legs", "Feet", "Back", "Cape", "Neck", "Rings", "Primary & Secondary", "Tools"]
                    active_filter = st.segmented_control(
                        "Filter by Slot",
                        options=filter_opts,
                        selection_mode="single",
                        default="All",
                        label_visibility="collapsed"
                    )
                with b_col2:
                    if st.button("🗑️ Clear All", help="Remove all items from blacklist"):
                        st.session_state['blacklist_state'] = []
                        st.rerun()

                current_blacklist_ids = set(st.session_state.get('blacklist_state', []))
                all_sorted = sorted(all_items_raw, key=lambda x: x.name)
                
                available_rows = []
                blacklisted_rows = []
                
                def get_filter_cat(item):
                    s = item.slot.lower()
                    if s in ["head", "chest", "legs", "feet", "back"]: return s.title()
                    if s in ["neck"]: return "Neck"
                    if s in ["ring"]: return "Rings"
                    if s in ["cape"]: return "Cape"
                    if s in ["primary", "secondary"]: return "Primary & Secondary"
                    if s in ["tools"]: return "Tools"
                    return "Other"

                for item in all_sorted:
                    row = {
                        "Item Name": item.name,
                        "Select": False,
                        "id": item.id
                    }
                    if item.id in current_blacklist_ids:
                        blacklisted_rows.append(row)
                    else:
                        cat = get_filter_cat(item)
                        if active_filter == "All" or cat == active_filter:
                            available_rows.append(row)

                c_avail, c_mid, c_black = st.columns([5, 0.5, 5])
                
                with c_avail:
                    st.markdown(f"**Available** ({len(available_rows)})")
                    if available_rows:
                        df_avail = pd.DataFrame(available_rows).set_index("id")
                        edited_avail = st.data_editor(
                            df_avail,
                            column_config={
                                "Select": st.column_config.CheckboxColumn("Mark", width="small", default=False),
                                "Item Name": st.column_config.TextColumn("Item", width="large", disabled=True),
                            },
                            width="stretch",
                            height=450,
                            key="editor_avail_new"
                        )
                    else:
                        st.info("No items match filter.")
                        edited_avail = pd.DataFrame()

                with c_mid:
                    st.write(""); st.write(""); st.write(""); st.write(""); st.write("")
                    if st.button("➡", width="stretch", help="Block Checked Items"):
                        if not edited_avail.empty:
                            to_block = edited_avail[edited_avail["Select"] == True].index.tolist()
                            if to_block:
                                new_set = current_blacklist_ids.union(set(to_block))
                                st.session_state['blacklist_state'] = list(new_set)
                                st.rerun()

                    st.write("")
                    do_restore = st.button("⬅", width="stretch", help="Restore Checked Items")

                with c_black:
                    st.markdown(f"**Blacklisted** ({len(blacklisted_rows)})")
                    if blacklisted_rows:
                        df_black = pd.DataFrame(blacklisted_rows).set_index("id")
                        edited_black = st.data_editor(
                            df_black,
                            column_config={
                                "Select": st.column_config.CheckboxColumn("Mark", width="small", default=False),
                                "Item Name": st.column_config.TextColumn("Item", width="large", disabled=True),
                            },
                            width="stretch",
                            height=450,
                            key="editor_black_new"
                        )
                        if do_restore:
                            to_restore = edited_black[edited_black["Select"] == True].index.tolist()
                            if to_restore:
                                new_set = current_blacklist_ids.difference(set(to_restore))
                                st.session_state['blacklist_state'] = list(new_set)
                                st.rerun()
                    else:
                        st.info("Blacklist empty.")
        
        with st.expander("🧪 Active Buffs (Pet & Consumables)", expanded=False):
            st.caption("Select active buffs. These are treated as permanent stats during optimization.")
            col_pet, col_lvl, col_cons = st.columns([2, 1, 2])
            
            with col_pet:
                pet_names = ["None"] + [p.name for p in all_pets]
                selected_pet_name = st.selectbox("Select Pet", pet_names)
            
            selected_pet = None
            if selected_pet_name != "None":
                selected_pet = next((p for p in all_pets if p.name == selected_pet_name), None)
                
            with col_lvl:
                if selected_pet:
                    max_lvl = max([l.level for l in selected_pet.levels]) if selected_pet.levels else 1
                    lvls = list(range(1, max_lvl + 1))
                    sel_level = st.selectbox("Pet Level", lvls, index=len(lvls)-1)
                    selected_pet = selected_pet.copy(update={"active_level": sel_level})
                    
                    st.caption(f"**Level {sel_level} Effects:**")
                    mods = selected_pet.modifiers
                    if not mods: st.caption("No modifiers.")
                    else:
                        html = ""
                        for mod in mods:
                            val = mod.value
                            if mod.stat in PERCENTAGE_STATS: val = f"{val}%"
                            html += f"<span class='service-mod'>{mod.stat.replace('_',' ').title()}: {val}</span>"
                        st.markdown(html, unsafe_allow_html=True)
                else:
                    st.selectbox("Pet Level", ["-"], disabled=True)
            
            with col_cons:
                cons_names = ["None"] + sorted([c.name for c in all_consumables])
                selected_cons_name = st.selectbox("Select Consumable", cons_names)
            
            selected_cons = None
            if selected_cons_name != "None":
                selected_cons = next((c for c in all_consumables if c.name == selected_cons_name), None)
                if selected_cons and selected_cons.modifiers:
                    st.caption(f"**{selected_cons.name} Effects:**")
                    html = ""
                    for mod in selected_cons.modifiers:
                        val = mod.value
                        if mod.stat in PERCENTAGE_STATS: val = f"{val}%"
                        html += f"<span class='service-mod'>{mod.stat.replace('_',' ').title()}: {val}</span>"
                    st.markdown(html, unsafe_allow_html=True)


        c1, c2, c3 = st.columns([2, 2, 1])
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
                    compatible_services = get_compatible_services(selected_obj, services)
                    if compatible_services:
                        s_names = [f"{s.name} ({s.location})" for s in compatible_services]
                        selected_s_name = st.selectbox("Select Service", s_names)
                        selected_service = next((s for s in compatible_services if f"{s.name} ({s.location})" == selected_s_name), None)
                        
                        if selected_service and (selected_service.modifiers or selected_service.requirements):
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
            st.write("🎯 **Optimization Targets**")
            
            # --- DYNAMIC TARGETS UI ---
            targets_to_remove = []
            
            # Header Row
            h_col1, h_col2, h_col3 = st.columns([3, 4, 1])
            with h_col1: st.caption("Target")
            with h_col2: st.caption("Weight (%)")

            # Iterate through session state targets
            for index, item in enumerate(st.session_state['opt_targets_list']):
                row_cols = st.columns([3, 4, 1])
                
                with row_cols[0]:
                    # Target Selector
                    options = [t.name.replace('_', ' ').title() for t in OPTIMAZATION_TARGET]
                    current_val = item['target']
                    try: sel_idx = options.index(current_val)
                    except ValueError: sel_idx = 0
                        
                    new_target = st.selectbox(
                        "Target", options, index=sel_idx, 
                        key=f"target_sel_{item['id']}", label_visibility="collapsed"
                    )
                    item['target'] = new_target

                with row_cols[1]:
                    # Weight Slider
                    new_weight = st.slider(
                        "Weight", min_value=1, max_value=100, 
                        value=int(item['weight']), format="%d%%",
                        key=f"target_slider_{item['id']}", label_visibility="collapsed"
                    )
                    item['weight'] = new_weight

                with row_cols[2]:
                    # Remove Button
                    if st.button("❌", key=f"target_rem_{item['id']}", help="Remove target"):
                        targets_to_remove.append(index)

            # Process Removal
            if targets_to_remove:
                for i in sorted(targets_to_remove, reverse=True):
                    del st.session_state['opt_targets_list'][i]
                st.rerun()

            # Add Button
            if st.button("➕ Add Target", key="add_target_btn", help="Add a new optimization target row"):
                new_id = st.session_state.get('next_target_id', 1)
                st.session_state['opt_targets_list'].append({"id": new_id, "target": "Reward Rolls", "weight": 100})
                st.session_state['next_target_id'] = new_id + 1
                st.rerun()

           
            # Prepare list for optimizer
            weighted_targets = []
            for item in st.session_state['opt_targets_list']:
                t_enum = next((t for t in OPTIMAZATION_TARGET if t.name.replace('_', ' ').title() == item["target"]), None)
                if t_enum and item['weight'] > 0:
                    weighted_targets.append((t_enum, float(item["weight"])))
        
        with c3:
            st.write("")
            st.write("")
            st.write("")
            can_run = (selected_obj is not None) and (len(weighted_targets) > 0)
            if is_recipe and not selected_service: can_run = False
            run_opt = st.button("🚀 Optimize", type="primary", width="stretch", disabled=not can_run)

    st.divider()

    left_col, right_col = st.columns([1, 2.5])

    with right_col:
        st.subheader("Gear Tool Reference (fala's tool)")
        components.iframe(WIKI_URL, height=1200, scrolling=True)

    with left_col:
        st.subheader("Results")

        if use_owned and user_data:
            available_items = filter_user_items(all_items_raw, user_data)
        else:
            available_items = all_items_raw
            item_counts = None

        if run_opt and selected_obj:
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
            
            optimizer = GearOptimizer(available_items, all_locations=locations)
            
            with st.spinner(f"Optimizing {final_activity.name}..."):
                req_kw = {} 
                for req in final_activity.requirements:
                    if req.type == RequirementType.KEYWORD_COUNT and req.target:
                         req_kw[req.target.lower().replace("_", " ").strip()] = req.value
                
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

                locked_items_map = st.session_state.get('locked_items_state', {})
                blacklist_set = set(st.session_state.get('blacklist_state', []))

                start_time = time.time()
                
                best_gear, error_msg = optimizer.optimize(
                    final_activity, 
                    player_level=player_lvl, 
                    player_skill_level=final_skill_lvl,
                    optimazation_target=weighted_targets, # Pass list
                    owned_item_counts=item_counts if use_owned else None,
                    achievement_points=user_ap,
                    user_reputation=user_reputation,
                    owned_collectibles=owned_collectibles,
                    extra_passive_stats=service_modifiers_stats,
                    context_override=context,
                    pet=selected_pet,
                    consumable=selected_cons,
                    locked_items=locked_items_map,
                    blacklisted_ids=blacklist_set
                )
                
                # --- TIMING END ---
                end_time = time.time()
                elapsed_time = end_time - start_time
                st.session_state['opt_duration'] = elapsed_time

                if error_msg:
                    st.error(error_msg)
                else:
                    st.session_state['best_gear'] = best_gear
                    st.session_state['final_skill_lvl'] = final_skill_lvl
                    st.session_state['selected_activity_obj'] = final_activity 
                    st.session_state['service_stats'] = service_modifiers_stats
                    st.session_state['debug_candidates'] = optimizer.debug_candidates
                    st.session_state['debug_rejected'] = optimizer.debug_rejected
                    st.session_state['owned_collectibles'] = owned_collectibles
                    st.session_state['context'] = context
                    st.session_state['selected_pet'] = selected_pet
                    st.session_state['selected_cons'] = selected_cons
                    st.session_state['selected_target_list'] = weighted_targets
                    # Store normalization context for math display
                    st.session_state['normalization_context'] = optimizer.last_normalization_context

        if 'best_gear' in st.session_state:
            best_gear = st.session_state['best_gear']
            context = st.session_state['context']
            saved_skill_lvl = st.session_state.get('final_skill_lvl', 99)
            saved_activity = st.session_state.get('selected_activity_obj')
            saved_collectibles = st.session_state.get('owned_collectibles', [])
            saved_service_stats = st.session_state.get('service_stats', {})
            saved_pet = st.session_state.get('selected_pet')
            saved_cons = st.session_state.get('selected_cons')
            weighted_targets_saved = st.session_state.get('selected_target_list', [])
            norm_context_saved = st.session_state.get('normalization_context', {})
            
            opt_duration = st.session_state.get('opt_duration', 0.0)

            optimizer = GearOptimizer(available_items, all_locations=locations) 

            if saved_activity:
                st.caption(f"Optimization completed in **{opt_duration:.4f} seconds**")
                
                passive_stats = calculate_passive_stats(saved_collectibles, context)
                for k,v in saved_service_stats.items():
                    passive_stats[k] = passive_stats.get(k, 0.0) + v

                # Use first target for debug/display if list, or list itself
                display_target = weighted_targets_saved if weighted_targets_saved else OPTIMAZATION_TARGET.reward_rolls
                
                # Get full analysis (now includes breakdown)
                analysis_result = analyze_score(best_gear, saved_activity, saved_skill_lvl, display_target, context, passive_stats=passive_stats, normalization_context=norm_context_saved)
                
                score = analysis_result["score"]
                stats = analysis_result["stats"]
                final_steps = analysis_result["steps"]

                # --- NEW COMPACT SUMMARY ---
                badges_html = ""
                # Generate badges for active stats
                # Common stats to highlight
                badge_stats = [
                    ('double_action', 'DA', True), 
                    ('double_rewards', 'DR', True), 
                    ('work_efficiency', 'Eff', True), 
                    ('xp_percent', 'XP', True),
                    ('fine_material_finding', 'Fine', True),
                    ('chest_finding', 'Chest', True),
                    ('find_collectibles', 'Collectible', True)
                ]
                
                for key, label, is_percent in badge_stats:
                    val = stats.get(key, 0)
                    if val > 0.001:
                        fmt_val = f"{val*100:.1f}%" if is_percent else f"{val:.2f}"
                        badges_html += f"""
                        <div class="score-badge">
                            <span class="score-badge-label">{label}</span>
                            <span class="score-badge-val">+{fmt_val}</span>
                        </div>
                        """

                st.html(f"""
                <div style="background-color: #0e1117; padding: 15px; border-radius: 10px; border: 1px solid #30363d;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <span style="font-size: 2.2em; font-weight: 700; color: #4ade80;">{score:.4f}</span>
                            <span style="font-size: 1em; color: #94a3b8; margin-left: 10px;">Total Score</span>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-size: 1.1em; font-weight: 600;">{final_steps} Steps</div>
                            <div style="font-size: 0.9em; color: #64748b;">Base: {saved_activity.base_steps}</div>
                        </div>
                    </div>
                    <hr style="margin: 10px 0; border-color: #30363d;">
                    <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                         {badges_html}
                    </div>
                </div>
                """)
                
                st.write("") # Spacer

                loadout_data = []
                if saved_pet:
                     loadout_data.append({"Slot": "🐾 Pet", "Item": f"{saved_pet.name} (Lvl {saved_pet.active_level})"})
                if saved_cons:
                     loadout_data.append({"Slot": "🧪 Consumable", "Item": saved_cons.name})

                for slot in ["Head", "Chest", "Legs", "Feet", "Back", "Cape", "Neck", "Hands", "Primary", "Secondary"]:
                    item = getattr(best_gear, slot.lower())
                    loadout_data.append({"Slot": slot, "Item": item.name if item else "-"})
                
                for i, ring in enumerate(best_gear.rings):
                    loadout_data.append({"Slot": f"Ring {i+1}", "Item": ring.name})
                for i, tool in enumerate(best_gear.tools):
                    loadout_data.append({"Slot": f"Tool {i+1}", "Item": tool.name})

                st.dataframe(pd.DataFrame(loadout_data), hide_index=True, width="stretch")

                with st.expander("🔍 Detailed Item Breakdown", expanded=False):
                    st.caption("Inspect active modifiers and conditions for each item.")
                    
                    equipped_items = []
                    for slot in ["Head", "Chest", "Legs", "Feet", "Back", "Cape", "Neck", "Hands", "Primary", "Secondary"]:
                        item = getattr(best_gear, slot.lower())
                        if item: equipped_items.append((slot, item))
                    for i, r in enumerate(best_gear.rings):
                        equipped_items.append((f"Ring {i+1}", r))
                    for i, t in enumerate(best_gear.tools):
                        equipped_items.append((f"Tool {i+1}", t))

                    set_counts = best_gear.get_keyword_counts()
                    
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
                        st.markdown("---")

                    st.markdown("### ♾️ Permanent Modifiers")
                    
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
                                if is_active: html_mods += f"<div class='mod-active'>✅ <b>{stat_name}</b>: +{val_str}</div>"
                                else:
                                    html_mods += f"<div class='mod-inactive'>❌ <b>{stat_name}</b>: +{val_str}</div>"
                                    for r in fail_reasons: html_mods += f"<div class='mod-condition'>↳ {r}</div>"
                            st.markdown(html_mods, unsafe_allow_html=True)
                        else: st.caption("No modifiers for this level.")
                        st.markdown("---")
                    
                    if saved_cons:
                        st.markdown(f"<div class='item-header'>🧪 Consumable: {saved_cons.name}</div>", unsafe_allow_html=True)
                        if saved_cons.modifiers:
                            html_mods = ""
                            for mod in saved_cons.modifiers:
                                is_active = True
                                fail_reasons = []
                                for cond in mod.conditions:
                                    met, reason = check_condition_details(cond, context, set_counts)
                                    if not met: is_active = False; fail_reasons.append(reason)
                                val_str = f"{mod.value}"
                                if mod.stat in PERCENTAGE_STATS: val_str += "%"
                                stat_name = mod.stat.replace('_', ' ').title()
                                if is_active: html_mods += f"<div class='mod-active'>✅ <b>{stat_name}</b>: +{val_str}</div>"
                                else:
                                    html_mods += f"<div class='mod-inactive'>❌ <b>{stat_name}</b>: +{val_str}</div>"
                                    for r in fail_reasons: html_mods += f"<div class='mod-condition'>↳ {r}</div>"
                            st.markdown(html_mods, unsafe_allow_html=True)
                        else: st.caption("No modifiers.")
                        st.markdown("---")

                    if saved_collectibles:
                        st.markdown(f"<div class='item-header'>🏆 Collectibles ({len(saved_collectibles)})</div>", unsafe_allow_html=True)
                        active_coll_mods = []
                        for coll in saved_collectibles:
                            for mod in coll.modifiers:
                                is_active = True
                                for cond in mod.conditions:
                                    met, _ = check_condition_details(cond, context, set_counts)
                                    if not met: is_active = False; break
                                if is_active: active_coll_mods.append((coll.name, mod))
                        
                        if active_coll_mods:
                            html_coll = ""
                            for name, mod in active_coll_mods:
                                 val_str = f"{mod.value}"
                                 if mod.stat in PERCENTAGE_STATS: val_str += "%"
                                 html_coll += f"<div class='mod-active'>✅ <b>{mod.stat.replace('_',' ').title()}</b>: +{val_str} <span style='color:gray; font-size:0.8em'>({name})</span></div>"
                            st.markdown(html_coll, unsafe_allow_html=True)
                        else: st.caption("No collectibles currently active.")

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

                st.markdown("---")
                with st.expander("🧪 Laboratory / Debugger", expanded=False):
                    tab_exp, tab_cand, tab_math = st.tabs(["Item Swapper", "🕵️ Candidate Inspector", "🧮 Score Math"])
                    
                    # --- MATH TAB ---
                    with tab_math:
                        breakdown = analysis_result.get("target_breakdown", [])
                        if breakdown:
                            st.markdown("### Normalization & Scoring Breakdown")
                            st.caption("Each target is normalized between 0.0 (Baseline) and 1.0 (Approx Max) before weighting.")
                            st.caption("Formula: `Contribution = ((Raw - Baseline) / Range) * Weight`")
                            
                            df_math = pd.DataFrame(breakdown)
                            # Formatting
                            df_math['weight'] = df_math['weight'].apply(lambda x: f"{int(x)}%")
                            df_math['raw_value'] = df_math['raw_value'].apply(lambda x: f"{x:.4f}")
                            df_math['baseline'] = df_math['baseline'].apply(lambda x: f"{x:.4f}")
                            df_math['max_val'] = df_math['max_val'].apply(lambda x: f"{x:.4f}")
                            df_math['normalized'] = df_math['normalized'].apply(lambda x: f"{x:.4f}")
                            df_math['contribution'] = df_math['contribution'].apply(lambda x: f"{x:.4f}")
                            
                            st.dataframe(
                                df_math, 
                                column_config={
                                    "target": "Target",
                                    "weight": "Weight",
                                    "raw_value": "Raw Value",
                                    "baseline": "Baseline (0%)",
                                    "max_val": "Max (100%)",
                                    "normalized": "Norm. Score",
                                    "contribution": "Points Added"
                                },
                                hide_index=True,
                                width="stretch"
                            )
                        else:
                            st.info("No composite score breakdown available (Single target or no normalization context).")

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
                                test_gear = GearSet(**best_gear.model_dump())
                                test_gear.rings = list(best_gear.rings)
                                test_gear.tools = list(best_gear.tools)
                                test_gear.pet = best_gear.pet 
                                test_gear.consumable = best_gear.consumable # Preserve Consumable
                                
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

                                analysis = analyze_score(test_gear, saved_activity, saved_skill_lvl, display_target, context, passive_stats=passive_stats, normalization_context=norm_context_saved)
                                test_score = analysis.get("score", 0)
                                test_steps = analysis.get("denominator", 0)
                                
                                orig_analysis = analyze_score(best_gear, saved_activity, saved_skill_lvl, display_target, context, passive_stats=passive_stats, normalization_context=norm_context_saved)
                                orig_score = orig_analysis.get("score", 0)
                                orig_steps = orig_analysis.get("denominator", 0)
                                
                                st.markdown("##### Comparison")
                                def show_diff(label, orig, new, is_good_up=True):
                                    diff = new - orig
                                    color = "off"
                                    if diff > 0: color = "green" if is_good_up else "red"
                                    elif diff < 0: color = "red" if is_good_up else "green"
                                    st.markdown(f"**{label}**: {orig:.4f} → **{new:.4f}** :{color}[({diff:+.4f})]")

                                show_diff("Score", orig_score, test_score, True)
                                show_diff("Steps", orig_steps, test_steps, False)
                                
                                st.markdown("---")
                                st.caption("Detailed Stat Changes:")
                                test_stats = analysis.get("stats", {})
                                orig_stats = orig_analysis.get("stats", {})
                                for k in ["fine_material_finding", "double_rewards", "double_action", "work_efficiency", "xp_percent", "percent_step_reduction"]:
                                    v1 = orig_stats.get(k, 0)
                                    v2 = test_stats.get(k, 0)
                                    if abs(v1-v2) > 0.001:
                                        st.text(f"{k}: {v1:.2f} -> {v2:.2f}")

                    with tab_cand:
                        st.write("Inspect which items passed the filter and their scores.")
                        insp_slot = st.selectbox("Inspect Slot", options=["tools", "ring", "head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary"])
                        
                        debug_candidates = st.session_state.get('debug_candidates', {})
                        debug_rejected = st.session_state.get('debug_rejected', [])
                        
                        items = debug_candidates.get(insp_slot, [])
                        if items:
                            st.markdown(f"**✅ Accepted Candidates ({len(items)})**")
                            cand_data = []
                            for item in items:
                                d_set = GearSet()
                                d_set.pet = best_gear.pet
                                d_set.consumable = best_gear.consumable # Preserve Consumable
                                if insp_slot == "tools": d_set.tools = [item]
                                elif insp_slot == "ring": d_set.rings = [item]
                                else: setattr(d_set, insp_slot, item)
                                
                                # Use simplified non-normalized score for raw power check
                                s = calculate_score(d_set, saved_activity, saved_skill_lvl, display_target, context, ignore_requirements=True)
                                cand_data.append({"Name": item.name, "Score": s, "ID": item.id})
                            
                            df_cand = pd.DataFrame(cand_data).sort_values(by="Score", ascending=False)
                            st.dataframe(df_cand, width="stretch")
                        else:
                            st.warning("No candidates found for this slot.")

                        st.markdown("---")
                        st.markdown("**❌ Rejected Items (Sample)**")
                        rejected_in_slot = [r for r in debug_rejected if r['slot'] == insp_slot]
                        if rejected_in_slot:
                             df_rej = pd.DataFrame(rejected_in_slot)
                             st.dataframe(df_rej, width="stretch")
                        else: st.write("No items specifically rejected.")

        elif not selected_obj:
            st.info("👈 Select an activity or recipe to start.")
            
        else:
            st.write("Ready.")

if __name__ == "__main__":
    main()