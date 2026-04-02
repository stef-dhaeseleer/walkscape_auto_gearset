import streamlit as st
import json
import uuid
from streamlit_js_eval import streamlit_js_eval
from models import Loadout
from ui_utils import (
    calculate_char_level_from_steps, calculate_total_level, extract_user_counts, 
    extract_user_reputation, get_user_collectibles
)

def render_sidebar():
    with st.sidebar:
        st.header("💾 Saved Loadouts")
        st.caption("Save optimized sets to use in the Crafting Tree.")
        if 'best_gear' in st.session_state and st.session_state['best_gear']:
            with st.form("save_loadout_form", clear_on_submit=True):
                current_act = st.session_state.get('selected_activity_obj')
                default_name = f"Optimized {current_act.name}" if current_act else "New Loadout"
                loadout_name = st.text_input("Loadout Name", value=default_name)
                if st.form_submit_button("Save Current Gear", type="primary", use_container_width=True):
                    new_id = str(uuid.uuid4())[:8]
                    bg_snapshot = st.session_state['best_gear'].clone()
                    st.session_state['saved_loadouts'][new_id] = Loadout(id=new_id, name=loadout_name, gear_set=bg_snapshot)
                    st.success(f"Saved '{loadout_name}'!")
        else:
            st.info("Run an optimization first to save a loadout.")

        st.divider()
        if st.session_state['saved_loadouts']:
            for l_id, loadout in list(st.session_state['saved_loadouts'].items()):
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"**{loadout.name}**")
                if c2.button("❌", key=f"del_{l_id}", help="Delete"):
                    del st.session_state['saved_loadouts'][l_id]
                    st.rerun()
        else:
            st.caption("No loadouts saved yet.")

def render_user_data_section(is_mobile, all_collectibles_raw):
    user_state = {
        "user_data": None,
        "calculated_char_lvl": 99,
        "user_skills_map": {},
        "valid_json": False,
        "item_counts": {},
        "user_ap": 0,
        "user_total_level": 0,
        "owned_collectibles": [],
        "user_reputation": {},
        "owned_pets": {},
        "use_owned": False
    }

    with st.expander("📂 User Save Data & Settings", expanded=not is_mobile):
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
        
        if user_json_input.strip():
            try:
                user_data = json.loads(user_json_input)
                user_state["valid_json"] = True
                user_state["user_data"] = user_data
                
                steps = user_data.get("steps", 0)
                user_state["calculated_char_lvl"] = calculate_char_level_from_steps(steps)
                user_state["user_skills_map"] = user_data.get("skills", {})
                user_state["user_ap"] = user_data.get("achievement_points", 0)
                user_state["item_counts"] = extract_user_counts(user_data)
                user_state["user_reputation"] = extract_user_reputation(user_data)
                user_state["owned_pets"] = extract_user_pets(user_data)
                
                if user_state["user_skills_map"]:
                    user_state["user_total_level"] = calculate_total_level(user_state["user_skills_map"])

                if all_collectibles_raw:
                    user_state["owned_collectibles"] = get_user_collectibles(all_collectibles_raw, user_data)
                
                st.success(f"Loaded: {user_data.get('name', 'Player')} | Items: {len(user_state['item_counts'])} | AP: {user_state['user_ap']} | Total Lvl: {user_state['user_total_level']} | Rep Factions: {len(user_state['user_reputation'])}")
            except json.JSONDecodeError:
                st.error("Invalid JSON")
        
        with col_opts:
            st.write("")
            user_state["use_owned"] = st.checkbox("Only use owned items", value=user_state["valid_json"])

    return user_state



def extract_user_pets(user_data: dict) -> dict:
    owned_pets = {}
    pets_list = []
    
    # Check for currently equipped pet
    if "pets" in user_data and isinstance(user_data["pets"], dict):
        equipped = user_data["pets"].get("pet")
        if equipped:
            pets_list.append(equipped)
            
    # Add all available (unequipped) pets
    available = user_data.get("available_pets", [])
    if isinstance(available, list):
        pets_list.extend(available)
        
    for p in pets_list:
        species = p.get("species", "").lower()
        lvl = p.get("level", 1)
        name = p.get("name", species.title())
        
        # Keep the highest level if the user has multiple of the same species
        if species not in owned_pets or lvl > owned_pets[species]["level"]:
            owned_pets[species] = {"name": name, "level": lvl}
            
    return owned_pets