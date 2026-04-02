import streamlit as st
import streamlit.components.v1 as components
import json
import time
import pandas as pd
from collections import defaultdict

from utils.constants import StatName, PERCENTAGE_STATS
from utils.export import export_gearset
from calculations import calculate_passive_stats, calculate_score, analyze_score
from gear_optimizer import GearOptimizer, OPTIMAZATION_TARGET
from models import EquipmentSlot, GearSet, Recipe, Activity, RequirementType, CraftingNode

from ui_utils import (
    TARGET_CATEGORIES, find_category, filter_user_items, 
    get_compatible_services, synthesize_activity_from_recipe, 
    extract_modifier_stats, check_condition_details, calculate_level_from_xp,
    get_best_auto_pet
)

@st.dialog("Configure Target")
def edit_target_dialog(item_id=None):
    if item_id is None:
        current_target_name = "Reward Rolls"
        weight = 100
    else:
        item = next((x for x in st.session_state['opt_targets_list'] if x['id'] == item_id), None)
        if not item: return
        current_target_name = item['target']
        weight = item['weight']
        
    current_cat = find_category(current_target_name)
    new_cat = st.selectbox("Category", options=list(TARGET_CATEGORIES.keys()), index=list(TARGET_CATEGORIES.keys()).index(current_cat), key="dialog_cat")
    
    available_targets = TARGET_CATEGORIES[new_cat]
    target_idx = available_targets.index(current_target_name) if current_target_name in available_targets else 0
    new_target = st.selectbox("Target", options=available_targets, index=target_idx, key="dialog_tgt")
    
    new_weight = st.slider("Weight", min_value=1, max_value=100, value=int(weight), format="%d%%", key="dialog_weight")
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save", type="primary", use_container_width=True):
            if item_id is None:
                new_id = st.session_state.get('next_target_id', 1)
                st.session_state['opt_targets_list'].append({"id": new_id, "target": new_target, "weight": new_weight})
                st.session_state['next_target_id'] = new_id + 1
            else:
                for x in st.session_state['opt_targets_list']:
                    if x['id'] == item_id:
                        x['target'] = new_target
                        x['weight'] = new_weight
                        break
            st.rerun()
    with c2:
        if item_id is not None:
            if st.button("Delete", use_container_width=True):
                st.session_state['opt_targets_list'] = [x for x in st.session_state['opt_targets_list'] if x['id'] != item_id]
                st.rerun()

def render_optimizer_tab(is_mobile, user_state, all_items_raw, activities, recipes, locations, services, all_pets, all_consumables,all_materials, drop_calc, WIKI_URL):
    # Unpack user state
    use_owned = user_state["use_owned"]
    user_data = user_state["user_data"]
    calculated_char_lvl = user_state["calculated_char_lvl"]
    valid_json = user_state["valid_json"]
    user_skills_map = user_state["user_skills_map"]
    item_counts = user_state["item_counts"]
    user_ap = user_state["user_ap"]
    user_total_level = user_state["user_total_level"]
    owned_collectibles = user_state["owned_collectibles"]
    user_reputation = user_state["user_reputation"]

    loc_map = {loc.id: loc for loc in locations}

    with st.expander("⚙️ Advanced Configuration (Locks & Blacklist)", expanded=False):
        st.caption("Manually lock items to slots (bypasses ownership checks) or blacklist items from results.")
        tab_locks, tab_blacklist = st.tabs(["🔒 Locked Slots", "🚫 Blacklist"])
        
        with tab_locks:
            if 'best_gear' in st.session_state:
                if st.button("📍 Lock Current Optimized Set", help="Overwrite all locks with the current best gear results"):
                    bg = st.session_state['best_gear']
                    new_locks = {}
                    
                    std_slots_to_sync = [
                        "head", "chest", "legs", "feet", "back", 
                        "cape", "neck", "hands", "primary", "secondary"
                    ]
                    for slot in std_slots_to_sync:
                        item = getattr(bg, slot)
                        if item:
                            new_locks[slot] = item
                            st.session_state[f"lock_{slot}"] = item.name
                        else:
                            st.session_state[f"lock_{slot}"] = "None"
                    for i in range(2):
                        item = bg.rings[i] if i < len(bg.rings) else None
                        if item:
                            new_locks[f"ring_{i}"] = item
                            st.session_state[f"lock_ring_{i}"] = item.name
                        else:
                            st.session_state[f"lock_ring_{i}"] = "None"
                            
                    for i in range(6):
                        item = bg.tools[i] if i < len(bg.tools) else None
                        if item:
                            new_locks[f"tool_{i}"] = item
                            st.session_state[f"lock_tool_{i}"] = item.name
                        else:
                            st.session_state[f"lock_tool_{i}"] = "None"
                    
                    st.session_state['locked_items_state'] = new_locks
                    st.rerun()
            elif not use_owned:
                st.info("💡 Run an optimization first to lock the results here.")
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
        
        owned_pets = user_state.get("owned_pets", {})
        
        with col_pet:
            pet_opts = ["Auto", "None"] + [p.id for p in all_pets]
            
            def format_pet(pid):
                if pid == "Auto": return "✨ Auto Select Best Pet"
                if pid == "None": return "None"
                p_obj = next((x for x in all_pets if x.id == pid), None)
                if not p_obj: return pid
                if pid in owned_pets: return f"{owned_pets[pid]['name']} ({p_obj.name})"
                return p_obj.name
                
            selected_pet_id = st.selectbox("Select Pet", pet_opts, format_func=format_pet)
        
        selected_pet = None
        if selected_pet_id not in ["None", "Auto"]:
            selected_pet = next((p for p in all_pets if p.id == selected_pet_id), None)
            
        with col_lvl:
            if selected_pet_id == "Auto":
                st.selectbox("Pet Level", ["Auto"], disabled=True)
            elif selected_pet:
                max_lvl = max([l.level for l in selected_pet.levels]) if selected_pet.levels else 1
                lvls = list(range(1, max_lvl + 1))
                
                default_lvl = max_lvl
                if selected_pet_id in owned_pets:
                    default_lvl = min(owned_pets[selected_pet_id]["level"], max_lvl)
                    
                try: default_idx = lvls.index(default_lvl)
                except ValueError: default_idx = len(lvls)-1
                
                sel_level = st.selectbox("Pet Level", lvls, index=default_idx)
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

    c1, c2, c3 = st.columns([1.5, 2.5, 1])
    act_map = {f"[Activity] {a.name}": a for a in activities}
    rec_map = {f"[Recipe] {r.name}": r for r in recipes}
    combined_map = {**act_map, **rec_map}
    combined_names = sorted(list(combined_map.keys()))

    with c1:
        selected_key = st.selectbox("**Select Activity or Recipe**", options=combined_names, index=None, placeholder="Search...")
        selected_obj = None
        is_recipe = False
        selected_service = None
        selected_location_id = None
        selected_input_materials = [] 
        
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
            
            elif isinstance(selected_obj, Activity):
                if selected_obj.locations:
                    loc_names = []
                    loc_name_to_id = {}
                    for loc_id in selected_obj.locations:
                        loc_name = loc_map[loc_id].name if loc_id in loc_map else loc_id
                        loc_names.append(loc_name)
                        loc_name_to_id[loc_name] = loc_id
                    sel_loc_name = st.selectbox("Select Location", loc_names)
                    if sel_loc_name:
                        selected_location_id = loc_name_to_id[sel_loc_name]

            # --- NEW: Dynamic Input Material Selection ---
            if is_recipe and getattr(selected_obj, 'materials', None):
                st.markdown("**Input Materials**")
                for i, mat_group in enumerate(selected_obj.materials):
                    options_ids = set()
                    for mat in mat_group:
                        options_ids.add(mat.item_id)
                        options_ids.add(f"{mat.item_id}_fine") # Auto-include fine variants
                    
                    valid_mats = [m for m in all_materials if m.id in options_ids]
                    if valid_mats:
                        mat_names = [m.name for m in valid_mats]
                        sel_mat_name = st.selectbox(f"Select Input {i+1}", mat_names, key=f"mat_sel_{selected_obj.id}_{i}")
                        sel_mat_obj = next((m for m in valid_mats if m.name == sel_mat_name), None)
                        
                        if sel_mat_obj:
                            selected_input_materials.append(sel_mat_obj)
                            if sel_mat_obj.modifiers:
                                st.caption(f"*{sel_mat_obj.name} Buffs:*")
                                html = ""
                                for mod in sel_mat_obj.modifiers:
                                    val = mod.value
                                    if mod.stat in PERCENTAGE_STATS: val = f"{val}%"
                                    html += f"<span class='service-mod'>{mod.stat.replace('_',' ').title()}: {val}</span>"
                                st.markdown(html, unsafe_allow_html=True)
                                
            elif not is_recipe and getattr(selected_obj, 'requirements', None):
                # For Activities: Find consumable input requirements
                input_reqs = [r for r in selected_obj.requirements if getattr(r.type, 'value', r.type) in ('keyword_count', 'input_keyword', 'item')]
                
                if input_reqs:
                    materials_added = False
                    for i, req in enumerate(input_reqs):
                        req_type_val = getattr(req.type, 'value', req.type)
                        valid_mats = []
                        
                        if req_type_val in ('keyword_count', 'input_keyword') and req.target:
                            kw_target = req.target.lower().replace("_", " ").strip()
                            for mat in all_materials + all_consumables:
                                if hasattr(mat, 'keywords') and mat.keywords:
                                    mat_kws = [k.lower().replace("_", " ").strip() for k in mat.keywords]
                                    if kw_target in mat_kws:
                                        valid_mats.append(mat)
                        elif req_type_val == 'item' and req.target:
                            item_target = req.target.lower()
                            for mat in all_materials + all_consumables:
                                if mat.id == item_target or mat.id == f"{item_target}_fine":
                                    valid_mats.append(mat)
                                    
                        if valid_mats:
                            if not materials_added:
                                st.markdown("**Required Inputs / Consumables**")
                                materials_added = True
                                
                            seen = set()
                            unique_valid_mats = []
                            for m in valid_mats:
                                if m.id not in seen:
                                    seen.add(m.id)
                                    unique_valid_mats.append(m)
                                    
                            mat_names = [m.name for m in unique_valid_mats]
                            sel_mat_name = st.selectbox(f"Select {req.target.replace('_', ' ').title()} ({req.value}x)", mat_names, key=f"act_mat_sel_{selected_obj.id}_{i}")
                            
                            if sel_mat_name != "(Provided by Gear)":
                                sel_mat_obj = next((m for m in unique_valid_mats if m.name == sel_mat_name), None)
                                if sel_mat_obj:
                                    selected_input_materials.append(sel_mat_obj)
                                    if getattr(sel_mat_obj, 'modifiers', None):
                                        st.caption(f"*{sel_mat_obj.name} Buffs:*")
                                        html = ""
                                        for mod in sel_mat_obj.modifiers:
                                            val = mod.value
                                            if mod.stat in PERCENTAGE_STATS: val = f"{val}%"
                                            html += f"<span class='service-mod'>{mod.stat.replace('_',' ').title()}: {val}</span>"
                                        st.markdown(html, unsafe_allow_html=True)
    
    with c2:
        st.write("🎯 **Optimization Targets**")
        if is_mobile:
            for item in st.session_state['opt_targets_list']:
                col_txt, col_btn = st.columns([4, 1])
                with col_txt:
                    st.markdown(f"<div style='background-color:#1e293b; padding:8px 12px; border: 1px solid #334155; border-radius:6px; margin-bottom:4px;'><b style='color:#e2e8f0'>{item['target']}</b> <span style='color:#94a3b8; font-size:0.85em;'>({item['weight']}%)</span></div>", unsafe_allow_html=True)
                with col_btn:
                    if st.button("✏️", key=f"edit_m_{item['id']}", use_container_width=True):
                        edit_target_dialog(item['id'])
            
            if st.button("➕ Add Target", key="add_tgt_btn_mobile", use_container_width=True):
                edit_target_dialog(None)

        else:
            targets_to_remove = []
            for index, item in enumerate(st.session_state['opt_targets_list']):
                c_cat, c_target, c_slider, c_btn = st.columns([3, 3, 3, 1])
                current_target_name = item['target']
                current_cat = find_category(current_target_name)
                with c_cat:
                    new_cat = st.selectbox(
                        "Category", 
                        options=list(TARGET_CATEGORIES.keys()), 
                        index=list(TARGET_CATEGORIES.keys()).index(current_cat),
                        key=f"cat_sel_{item['id']}", 
                        label_visibility="collapsed"
                    )
                    if new_cat != current_cat:
                        item['target'] = TARGET_CATEGORIES[new_cat][0]
                        st.rerun()
                with c_target:
                    available_targets = TARGET_CATEGORIES[new_cat]
                    try:
                        target_idx = available_targets.index(item['target'])
                    except ValueError:
                        target_idx = 0
                    
                    new_target = st.selectbox(
                        "Target", 
                        options=available_targets,
                        index=target_idx,
                        key=f"target_sel_{item['id']}", 
                        label_visibility="collapsed"
                    )
                    item['target'] = new_target
                with c_slider:
                    item['weight'] = st.slider(
                        "Weight", min_value=1, max_value=100, 
                        value=int(item['weight']), format="%d%%",
                        key=f"target_slider_{item['id']}", label_visibility="collapsed"
                    )

                with c_btn:
                    if st.button("❌", key=f"target_rem_{item['id']}", help="Remove target"):
                        targets_to_remove.append(index)

            if targets_to_remove:
                for i in sorted(targets_to_remove, reverse=True):
                    del st.session_state['opt_targets_list'][i]
                st.rerun()
            if st.button("➕ Add Target", key="add_tgt_btn_desktop", use_container_width=True):
                new_id = st.session_state.get('next_target_id', 1)
                st.session_state['opt_targets_list'].append({"id": new_id, "target": "Reward Rolls", "weight": 100})
                st.session_state['next_target_id'] = new_id + 1
                st.rerun()

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

    if is_mobile:
        tab_res, tab_wiki = st.tabs(["📊 Results", "📖 Gear Tool (Wiki)"])
        container_results = tab_res
        container_wiki = tab_wiki
    else:
        left_col, right_col = st.columns([1, 2.5])
        container_results = left_col
        container_wiki = right_col

    with container_wiki:
        if not is_mobile:
            st.subheader("Gear Tool Reference (fala's tool)")
        components.iframe(WIKI_URL, height=1200 if not is_mobile else 800, scrolling=True)

    with container_results:
        st.subheader("Results")

        if use_owned and user_data:
            available_items = filter_user_items(all_items_raw, user_data)
        else:
            available_items = all_items_raw
            item_counts_filtered = None

        if run_opt and selected_obj:
            final_activity = selected_obj
            extra_passive_stats = {}
            
            if is_recipe and selected_service:
                final_activity = synthesize_activity_from_recipe(selected_obj, selected_service)
                extra_passive_stats = extract_modifier_stats(selected_service.modifiers)
            for mat in selected_input_materials:
                if mat.modifiers:
                    mat_stats = extract_modifier_stats(mat.modifiers)
                    for k, v in mat_stats.items():
                        extra_passive_stats[k] = extra_passive_stats.get(k, 0.0) + v

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
                    req_type_val = getattr(req.type, 'value', req.type)
                    if req_type_val in ('keyword_count', 'input_keyword') and req.target:
                        kw = req.target.lower().replace("_", " ").strip()
                        req_kw[kw] = req_kw.get(kw, 0) + req.value
                
                # Subtract keywords fulfilled by selected input materials/consumables
                for mat in selected_input_materials:
                    if hasattr(mat, 'keywords') and mat.keywords:
                        for kw in mat.keywords:
                            norm_kw = kw.lower().replace("_", " ").strip()
                            req_kw.pop(norm_kw, None)
                
                if not is_recipe and selected_location_id:
                    current_loc_id = selected_location_id
                else:
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
                    "total_skill_level": user_total_level,
                    "special_ev_map": drop_calc.get_special_ev_map()
                }

                locked_items_map = st.session_state.get('locked_items_state', {})
                blacklist_set = set(st.session_state.get('blacklist_state', []))

                start_time = time.time()

                actual_pet = selected_pet
                if selected_pet_id == "Auto":
                    game_data_dict = {
                        'recipes': {r.id: r for r in recipes},
                        'activities': {a.id: a for a in activities},
                        'pets': {p.id: p for p in all_pets}
                    }
                    dummy_node = CraftingNode(
                        node_id="dummy", 
                        item_id="dummy", 
                        source_type="recipe" if is_recipe else "activity",
                        source_id=selected_obj.id,
                        selected_location_id=selected_location_id
                    )
                    
                    auto_pet_id, auto_pet_lvl = get_best_auto_pet(
                        dummy_node, game_data_dict, loc_map, drop_calc, 
                        user_ap, user_total_level, use_owned, user_state.get("owned_pets", {})
                    )
                    
                    if auto_pet_id:
                        actual_pet = next((p for p in all_pets if p.id == auto_pet_id), None)
                        if actual_pet:
                            actual_pet = actual_pet.copy(update={"active_level": auto_pet_lvl})
                best_gear, error_msg, filler_slots = optimizer.optimize(
                    final_activity, 
                    player_level=player_lvl, 
                    player_skill_level=final_skill_lvl,
                    optimazation_target=weighted_targets,
                    owned_item_counts=item_counts if use_owned else None,
                    achievement_points=user_ap,
                    user_reputation=user_reputation,
                    owned_collectibles=owned_collectibles,
                    extra_passive_stats=extra_passive_stats,
                    context_override=context,
                    pet=actual_pet,
                    consumable=selected_cons,
                    locked_items=locked_items_map,
                    blacklisted_ids=blacklist_set
                )
                
                end_time = time.time()
                elapsed_time = end_time - start_time
                st.session_state['opt_duration'] = elapsed_time

                if error_msg:
                    st.error(error_msg)
                else:
                    st.session_state['best_gear'] = best_gear
                    st.session_state['filler_slots'] = filler_slots
                    st.session_state['final_skill_lvl'] = final_skill_lvl
                    st.session_state['selected_activity_obj'] = final_activity 
                    st.session_state['service_stats'] = extra_passive_stats
                    st.session_state['selected_input_materials'] = selected_input_materials 
                    st.session_state['debug_candidates'] = optimizer.debug_candidates
                    st.session_state['debug_rejected'] = optimizer.debug_rejected
                    st.session_state['owned_collectibles'] = owned_collectibles
                    st.session_state['context'] = context
                    st.session_state['selected_pet'] = actual_pet
                    st.session_state['selected_cons'] = selected_cons
                    st.session_state['selected_target_list'] = weighted_targets
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
            saved_materials = st.session_state.get('selected_input_materials', []) 
            weighted_targets_saved = st.session_state.get('selected_target_list', [])
            norm_context_saved = st.session_state.get('normalization_context', {})
            
            opt_duration = st.session_state.get('opt_duration', 0.0)

            if saved_activity:
                st.caption(f"Optimization completed in **{opt_duration:.4f} seconds**")
                
                passive_stats = calculate_passive_stats(saved_collectibles, context)
                for k,v in saved_service_stats.items():
                    passive_stats[k] = passive_stats.get(k, 0.0) + v

                display_target = weighted_targets_saved if weighted_targets_saved else OPTIMAZATION_TARGET.reward_rolls
                
                analysis_result = analyze_score(best_gear, saved_activity, saved_skill_lvl, display_target, context, passive_stats=passive_stats, normalization_context=norm_context_saved)
                
                score = analysis_result["score"]
                stats = analysis_result["stats"]
                final_steps = analysis_result["steps"]
                breakdown = analysis_result.get("target_breakdown", [])

                badges_html = ""
                badge_stats = [
                    (StatName.WORK_EFFICIENCY, 'WE'),
                    (StatName.DOUBLE_ACTION, 'DA'),
                    (StatName.DOUBLE_REWARDS, 'DR'),
                    (StatName.NO_MATERIALS_CONSUMED, 'NMC'),
                    (StatName.QUALITY_OUTCOME, 'QO'),
                    (StatName.CHEST_FINDING, 'CF'),
                    (StatName.FIND_COLLECTIBLES, 'Collectibles'),
                    (StatName.FINE_MATERIAL_FINDING, 'FMF'),
                    (StatName.FIND_GOLD, 'Gold Drops'),
                ]
                
                for key, label in badge_stats:
                    is_percent = key in PERCENTAGE_STATS
                    val = stats.get(key, 0)
                    if val > 0.001:
                        fmt_val = f"{val*100:.1f}%" if is_percent else f"{val:.2f}"
                        badges_html += f"""
                        <div class="score-badge">
                            <span class="score-badge-label">{label}</span>
                            <span class="score-badge-val">+{fmt_val}</span>
                        </div>
                        """
                
                raw_scores_html = ""
                if breakdown:
                    raw_scores_html = "<div style='margin-top: 12px; padding-top: 12px; border-top: 1px dashed #30363d; display: flex; gap: 18px; flex-wrap: wrap;'>"
                    for item in breakdown:
                        t_name = item["target"]
                        raw_val = item["raw_value"]
                        t_name_lower = t_name.lower()
                        
                        if "no steps" in t_name_lower:
                            display_text = f"{raw_val:.2f} Output per Action"
                        elif "reward rolls" in t_name_lower:
                            human_val = 1.0 / raw_val if raw_val > 0 else 0
                            display_text = f"{human_val:.2f} Steps/Roll" if raw_val > 0 else "∞ Steps/Roll"
                        elif "xp" in t_name_lower:
                            display_text = f"{raw_val:.2f} XP/Step"
                        elif "chests" in t_name_lower:
                            human_val = 250.0 / raw_val if raw_val > 0 else 0
                            display_text = f"{human_val:.1f} Steps/Chest" if raw_val > 0 else "∞ Steps/Chest"
                        elif "materials from input" in t_name_lower:
                            display_text = f"{raw_val:.3f} Output Ratio"
                        elif "fine" in t_name_lower:
                            human_val = 100.0 / raw_val if raw_val > 0 else 0
                            display_text = f"{human_val:.1f} Steps/Fine Roll" if raw_val > 0 else "∞ Steps/Fine Roll"
                        elif "collectibles" in t_name_lower:
                            relative_mult = raw_val * saved_activity.base_steps
                            display_text = f"{relative_mult:.2f}x Collectibles Base Rate"
                        elif "gems" in t_name_lower:
                            relative_mult = raw_val * saved_activity.base_steps
                            display_text = f"{relative_mult:.2f}x Gems Base Rate"
                        elif "coins" in t_name_lower:
                            human_val = raw_val * 1000.0
                            display_text = f"{human_val:.2f} Coins/1k Steps"
                        elif "eternal per input" in t_name_lower:
                            human_val = 1.0 / raw_val if raw_val > 0 else float('inf')
                            display_text = f"{human_val:.2f} Inputs/Eternal" if raw_val > 0 else "∞ Inputs/Eternal"
                        elif any(q in t_name_lower for q in ["good per step", "great per step", "excellent per step", "perfect per step", "eternal per step"]):
                            human_val = 1.0 / raw_val if raw_val > 0 else float('inf')
                            display_tier_name = t_name.split()[0].title()
                            display_text = f"{human_val:.2f} Steps/{display_tier_name}" if raw_val > 0 else f"∞ Steps/{display_tier_name}"
                        elif "tokens" in t_name_lower:
                            human_val = 1.0 / raw_val if raw_val > 0 else float('inf')
                            display_text = f"{human_val:.2f} Steps/Token" if raw_val > 0 else "∞ Steps/Token"
                        elif "ectoplasm" in t_name_lower:
                            human_val = 1.0 / raw_val if raw_val > 0 else float('inf')
                            display_text = f"{human_val:.2f} Steps/Ecto" if raw_val > 0 else "∞ Steps/Ecto"
                        else:
                            display_text = f"{raw_val:.4f}"
                        raw_scores_html += f"<div style='font-size: 0.95rem; color: #e2e8f0;'><span style='color: #94a3b8;'>{t_name}:</span> <span style='font-weight: 600; color: #93c5fd;'>{display_text}</span></div>"
                    raw_scores_html += "</div>"

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
                        {raw_scores_html}
                    <hr style="margin: 10px 0; border-color: #30363d;">
                    <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                        {badges_html}
                    </div>
                </div>
                """)
                
                st.write("") 

                loadout_data = []
                
                pet_str = "-"
                if saved_pet:
                    pet_str = f"{saved_pet.name} (Lvl {saved_pet.active_level})"
                loadout_data.append({"Slot": "🐾 Pet", "Item": pet_str})

                cons_str = "-"
                if saved_cons:
                    cons_str = saved_cons.name
                loadout_data.append({"Slot": "🧪 Consumable", "Item": cons_str})
                
                for i, mat in enumerate(saved_materials):
                    loadout_data.append({"Slot": f"📦 Input {i+1}", "Item": mat.name})
                filler_slots = st.session_state.get('filler_slots', set())

                for slot in ["Head", "Chest", "Legs", "Feet", "Back", "Cape", "Neck", "Hands", "Primary", "Secondary"]:
                    item = getattr(best_gear, slot.lower())
                    name = item.name if item else "-"
                    if slot.lower() in filler_slots:
                        name += " (❌🎯)"
                    loadout_data.append({"Slot": slot, "Item": name})
                
                for i in range(2):
                    r_name = "-"
                    if i < len(best_gear.rings) and best_gear.rings[i]:
                        r_name = best_gear.rings[i].name
                    
                    if f"ring_{i}" in filler_slots:
                        r_name += " (❌🎯)"
                    loadout_data.append({"Slot": f"Ring {i+1}", "Item": r_name})

                for i in range(6):
                    t_name = "-"
                    if i < len(best_gear.tools) and best_gear.tools[i]:
                        t_name = best_gear.tools[i].name
                    if f"tool_{i}" in filler_slots:
                        t_name += " (❌🎯)"
                    loadout_data.append({"Slot": f"Tool {i+1}", "Item": t_name})

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

                    active_keywords = set()
                    for item in best_gear.get_all_items():
                        if hasattr(item, 'keywords'):
                            for kw in item.keywords:
                                active_keywords.add(kw.lower().replace("_", " ").strip())

                    set_counts = best_gear.get_requirement_counts(list(active_keywords))
                    
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
                    if saved_materials:
                        for i, mat in enumerate(saved_materials):
                            st.markdown(f"<div class='item-header'>📦 Input {i+1}: {mat.name}</div>", unsafe_allow_html=True)
                            if mat.modifiers:
                                html_mods = ""
                                for mod in mat.modifiers:
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
                st.markdown("### 🎲 Drop Calculator")
                st.caption(f"Based on **{final_steps} steps per action** (Optimized).")
                st.caption("Includes effects of Double Action (Frequency) and Double Rewards (Quantity).")
                
                drop_rows = drop_calc.get_drop_table(saved_activity, stats, saved_skill_lvl)
                
                if drop_rows:
                    df_drops = pd.DataFrame(drop_rows)
                    st.dataframe(
                        df_drops,
                        column_config={
                            "Item": st.column_config.TextColumn("Item", width="medium"),
                            "Steps": st.column_config.NumberColumn(
                                "Expected Steps", 
                                help="Average steps required to obtain 1 unit of this item.",
                                format="%.2f"
                            ),
                        },
                        hide_index=True,
                        width="stretch",
                    )
                else:
                    st.info("No drop data available for this activity.")
                
                st.markdown("---")
                with st.expander("🧪 Laboratory / Debugger", expanded=True):
                    tab_exp, tab_cand, tab_math = st.tabs(["Item Swapper", "🕵️ Candidate Inspector", "🧮 Score Math"])
                    
                    with tab_math:
                        breakdown = analysis_result.get("target_breakdown", [])
                        if breakdown:
                            st.markdown("### Normalization & Scoring Breakdown")
                            st.caption("Each target is normalized between 0.0 (Baseline) and 1.0 (Approx Max) before weighting.")
                            st.caption("Formula: `Contribution = ((Raw - Baseline) / Range) * Weight`")
                            
                            df_math = pd.DataFrame(breakdown)
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
                            edit_slot = st.selectbox("Select Slot to Swap", options=slot_options, key="lab_slot_select")
                            
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
                            
                            show_unowned = st.checkbox("Show only unowned items", key="lab_show_unowned")

                            if show_unowned:
                                all_slot_items = [i for i in all_items_raw if i.slot == target_enum]
                                
                                if user_data:
                                    owned_objs = filter_user_items(all_items_raw, user_data)
                                    owned_ids = set(i.id for i in owned_objs)
                                    valid_swap_items = [i for i in all_slot_items if i.id not in owned_ids]
                                else:
                                    valid_swap_items = all_slot_items
                            else:
                                valid_swap_items = [i for i in available_items if i.slot == target_enum]
                            
                            valid_swap_items.sort(key=lambda x: x.name)
                            
                            swap_item_name = st.selectbox("Swap with:", options=[i.name for i in valid_swap_items], index=None, key="lab_swap_select")
                            swap_item_obj = next((i for i in valid_swap_items if i.name == swap_item_name), None)

                        with d_col2:
                            if swap_item_obj:
                                test_gear = GearSet(**best_gear.model_dump())
                                test_gear.rings = list(best_gear.rings)
                                test_gear.tools = list(best_gear.tools)
                                test_gear.pet = best_gear.pet 
                                test_gear.consumable = best_gear.consumable
                                
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
                                d_set.consumable = best_gear.consumable
                                if insp_slot == "tools": d_set.tools = [item]
                                elif insp_slot == "ring": d_set.rings = [item]
                                else: setattr(d_set, insp_slot, item)
                                
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