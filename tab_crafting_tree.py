import streamlit as st
from models import CraftingNode
from utils.constants import EquipmentQuality
from ui_utils import build_default_tree, can_tree_use_fine, calculate_level_from_xp
from calculations import calculate_node_metrics

def render_tree_node(node: CraftingNode, level: int = 0):
    icon = {"recipe": "🔨", "activity": "🪓", "chest": "🧰", "bank": "🏦"}.get(node.source_type, "📦")
    item_name = node.item_id.replace('_', ' ').title()
    title = f"{icon} {item_name} (x{node.base_requirement_amount})"
    
    with st.expander(title, expanded=(level < 2)):
        c1, c2, c3 = st.columns([3, 2, 2])
        
        with c1:
            opts = [s["label"] for s in node.available_sources]
            current_label = opts[0]
            if node.source_type != "bank":
                for s in node.available_sources:
                    if s["type"] == node.source_type:
                        if node.source_type == "chest" and s["id"] == f"{node.source_id}::{node.parent_activity_id}":
                            current_label = s["label"]
                            break
                        elif s["id"] == node.source_id:
                            current_label = s["label"]
                            break
            
            idx = opts.index(current_label) if current_label in opts else 0
            new_label = st.selectbox("Source", options=opts, index=idx, key=f"src_{node.node_id}", label_visibility="collapsed")
            
            if new_label != current_label:
                selected_src = next(s for s in node.available_sources if s["label"] == new_label)
                node.source_type = selected_src["type"]
                if selected_src["type"] == "chest":
                    node.source_id, node.parent_activity_id = selected_src["id"].split("::")
                else:
                    node.source_id = selected_src["id"]
                    
                if node.source_type == "bank": node.inputs.clear()
                st.rerun()

        with c2:
            if node.source_type != "bank":
                loadout_opts = ["Default Gear"] + [l.name for l in st.session_state['saved_loadouts'].values()]
                current_idx = 0
                if node.loadout_id in st.session_state['saved_loadouts']:
                    l_name = st.session_state['saved_loadouts'][node.loadout_id].name
                    if l_name in loadout_opts: current_idx = loadout_opts.index(l_name)

                selected_l_name = st.selectbox("Loadout", options=loadout_opts, index=current_idx, key=f"ld_{node.node_id}", label_visibility="collapsed")
                if selected_l_name == "Default Gear": node.loadout_id = None
                else:
                    node.loadout_id = next(l_id for l_id, l in st.session_state['saved_loadouts'].items() if l.name == selected_l_name)

        with c3:
            if node.metrics:
                steps = node.metrics.get("steps", 0)
                xp = node.metrics.get("xp", 0)
                if steps != float('inf') and steps > 0:
                    st.markdown(f"<div style='text-align:right; color:#4ade80; font-weight:bold;'>{steps:,.1f} Steps/ea<br><span style='font-size:0.8em; color:#94a3b8;'>{xp/steps:,.2f} XP/Step</span></div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style='text-align:right; color:#f87171;'>Impossible</div>", unsafe_allow_html=True)

        if node.source_type == "recipe" and node.inputs:
            st.markdown("###### ⬇️ Requires:")
            with st.container(border=False):
                for child_id, child_node in node.inputs.items():
                    render_tree_node(child_node, level + 1)

def render_crafting_tree_tab(recipes, all_items_raw, activities, all_containers, user_skills_map, valid_json, drop_calc):
    st.subheader("Crafting Tree Calculator")
    st.caption("Calculate the true step cost of complex items based on your saved loadouts.")
    
    all_item_names = sorted(list({r.output_item_id for r in recipes} | {item.id for item in all_items_raw}))
    target_item = st.selectbox("Select Target Item", options=all_item_names, format_func=lambda x: x.replace('_', ' ').title())
    
    if st.button("Generate Tree", type="primary"):
        game_data_dict = {
            'recipes': {r.id: r for r in recipes},
            'activities': {a.id: a for a in activities},
            'chests': {c.id: c for c in all_containers} 
        }
        st.session_state['crafting_tree_root'] = build_default_tree(target_item, game_data_dict)
        st.rerun()

    st.divider()

    if st.session_state['crafting_tree_root']:
        root = st.session_state['crafting_tree_root']
        
        st.markdown("### ⚙️ Global Settings")
        c_g1, c_g2 = st.columns(2)
        
        with c_g1:
            qualities = [q for q in EquipmentQuality]
            st.session_state['global_quality'] = st.selectbox("Target Quality (Final Item)", options=qualities, index=0)
        
        with c_g2:
            game_data_dict = {
                'recipes': {r.id: r for r in recipes},
                'activities': {a.id: a for a in activities},
                'chests': {c.id: c for c in all_containers} 
            }
            can_fine = can_tree_use_fine(root, game_data_dict)
            if can_fine:
                st.session_state['global_fine'] = st.checkbox("💎 Use Fine Materials Chain", value=False)
            else:
                st.session_state['global_fine'] = False
                st.caption("*(Fine materials unavailable for some inputs in this chain)*")

        st.divider()
        
        render_tree_node(root)
        
        st.divider()
        if st.button("🧮 Calculate True Cost", type="primary"):
            player_skill_levels = {k: calculate_level_from_xp(v) for k, v in user_skills_map.items()} if valid_json else {}

            with st.spinner("Calculating cascading steps and populating tree..."):
                def run_and_save_metrics(node):
                    for child in node.inputs.values():
                        run_and_save_metrics(child)
                    
                    node.metrics = calculate_node_metrics(
                        node, st.session_state['saved_loadouts'], 
                        game_data_dict, drop_calc, player_skill_levels,
                        global_target_quality=st.session_state.get('global_quality', "Normal"),
                        global_use_fine=st.session_state.get('global_fine', False)
                    )
                    return node.metrics
                
                run_and_save_metrics(root)
                
            st.rerun()