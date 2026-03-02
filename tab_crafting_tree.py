import streamlit as st
import streamlit.components.v1 as components
import json
import pandas as pd
from models import CraftingNode
from utils.constants import EquipmentQuality, OPTIMAZATION_TARGET
from ui_utils import build_default_tree, can_tree_use_fine, calculate_level_from_xp, TARGET_CATEGORIES
from calculations import calculate_node_metrics
from gear_optimizer import GearOptimizer
from utils.export import export_gearset

@st.dialog("⚙️ Choose Optimization Targets")
def node_target_dialog(node: CraftingNode):
    targets = node.auto_optimize_target
    
    all_targets = []
    for cat_targets in TARGET_CATEGORIES.values():
        all_targets.extend(cat_targets)
        
    for i, t in enumerate(targets):
        c1, c2, c3 = st.columns([3, 2, 1])
        with c1:
            t_idx = all_targets.index(t["target"]) if t["target"] in all_targets else 0
            new_t = st.selectbox("Target", options=all_targets, index=t_idx, key=f"dlg_t_{node.node_id}_{i}")
            targets[i]["target"] = new_t
        with c2:
            new_w = st.number_input("Weight %", min_value=1, max_value=100, value=int(t["weight"]), key=f"dlg_w_{node.node_id}_{i}")
            targets[i]["weight"] = new_w
        with c3:
            st.write("")
            st.write("")
            if st.button("🗑️", key=f"dlg_del_{node.node_id}_{i}"):
                if len(targets) > 1:
                    targets.pop(i)
                    st.rerun()
                
    if st.button("➕ Add Target"):
        targets.append({"id": len(targets), "target": all_targets[0], "weight": 50})
        st.rerun()
        
    if st.button("Save & Close", type="primary"):
        node.auto_optimize_target = targets
        st.rerun()

def render_tree_node(node: CraftingNode, game_data_dict: dict, drop_calc, level: int = 0):
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
                # Force new nodes to default to Auto-Optimize out of the box
                if getattr(node, 'loadout_id', None) is None:
                    node.loadout_id = "AUTO"

                loadout_opts = ["✨ Choose Optimization Target", "Default Gear"] + [l.name for l in st.session_state['saved_loadouts'].values()]
                current_idx = 0
                
                if getattr(node, 'loadout_id', None) == "AUTO":
                    current_l_name = "✨ Choose Optimization Target"
                elif node.loadout_id in st.session_state['saved_loadouts']:
                    current_l_name = st.session_state['saved_loadouts'][node.loadout_id].name
                else:
                    current_l_name = "Default Gear"
                    
                if current_l_name in loadout_opts: 
                    current_idx = loadout_opts.index(current_l_name)

                selected_l_name = st.selectbox("Loadout", options=loadout_opts, index=current_idx, key=f"ld_{node.node_id}", label_visibility="collapsed")
                
                if selected_l_name == "Default Gear": 
                    node.loadout_id = "DEFAULT" 
                    node.auto_optimize_target = None
                elif selected_l_name == "✨ Choose Optimization Target":
                    node.loadout_id = "AUTO"
                    
                    if not getattr(node, 'auto_optimize_target', None):
                        default_t = "Reward Rolls No Steps" if node.source_type == "recipe" else "Reward Rolls"
                        node.auto_optimize_target = [{"id": 0, "target": default_t, "weight": 100}]
                        
                    if st.button("⚙️ Configure Targets", key=f"cfg_btn_{node.node_id}"):
                        node_target_dialog(node)
                        
                    summary = " | ".join([f"{t['weight']}% {t['target']}" for t in node.auto_optimize_target])
                    st.caption(f"🎯 **Target:** {summary}")
                else:
                    node.loadout_id = next(l_id for l_id, l in st.session_state['saved_loadouts'].items() if l.name == selected_l_name)
                    node.auto_optimize_target = None

        with c3:
            if node.metrics:
                steps = node.metrics.get("steps", 0)
                if steps != float('inf') and steps > 0:
                    st.markdown(f"<div style='text-align:right; color:#4ade80; font-weight:bold;'>{steps:,.1f} Steps/ea</div>", unsafe_allow_html=True)
                elif steps == 0:
                    st.markdown(f"<div style='text-align:right; color:#94a3b8; font-weight:bold;'>From Bank</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style='text-align:right; color:#f87171;'>Impossible</div>", unsafe_allow_html=True)
                
                if node.metrics.get("gear_set_base64"):
                    export_str = node.metrics["gear_set_base64"]
                    safe_id = node.node_id.replace('-', '_')
                    btn_id = f"copyBtn_{safe_id}"
                    
                    js_code = f"""
                    <script>
                    function copyToClipboard_{safe_id}() {{
                        var content = {json.dumps(export_str)};
                        navigator.clipboard.writeText(content).then(function() {{
                            document.getElementById("{btn_id}").innerHTML = "✅ Copied!";
                            setTimeout(function() {{
                                document.getElementById("{btn_id}").innerHTML = "📋 Copy Gearset";
                            }}, 2000);
                        }}, function(err) {{
                            console.error('Async: Could not copy text: ', err);
                        }});
                    }}
                    </script>
                    <div style="text-align: right; margin-top: 5px;">
                        <button id="{btn_id}" onclick="copyToClipboard_{safe_id}()" style="
                            background-color: #ff4b4b; 
                            color: white; 
                            border: none; 
                            padding: 8px 15px; 
                            border-radius: 4px; 
                            cursor: pointer; 
                            font-family: 'Source Sans Pro', sans-serif;
                            font-weight: 600;
                            font-size: 14px;
                            width: 100%;
                        ">📋 Copy Gearset</button>
                    </div>
                    """
                    components.html(js_code, height=50)

        # Show Local Node Math Breakdown
        if node.metrics and node.metrics.get("stats_used") and node.source_type != "bank":
            stats = node.metrics["stats_used"]
            st.caption("🔍 **Local Node Math Breakdown**")
            cols = st.columns(4)
            cols[0].markdown(f"<span style='font-size:0.85em'>Double Action: **{stats.get('DA', 0)*100:.1f}%**</span>", unsafe_allow_html=True)
            cols[1].markdown(f"<span style='font-size:0.85em'>Double Rewards: **{stats.get('DR', 0)*100:.1f}%**</span>", unsafe_allow_html=True)
            cols[2].markdown(f"<span style='font-size:0.85em'>No Mats Consumed: **{stats.get('NMC', 0)*100:.1f}%**</span>", unsafe_allow_html=True)
            cols[3].markdown(f"<span style='font-size:0.85em'>Target Quality Prob: **{stats.get('p_valid_quality', 1)*100:.2f}%**</span>", unsafe_allow_html=True)

        if node.source_type == "recipe" and node.inputs:
            recipe = game_data_dict['recipes'].get(node.source_id)
            if recipe and recipe.materials:
                has_options = any(len(g) > 1 for g in recipe.materials)
                if has_options:
                    st.caption("🔀 **Alternative Materials Available:**")
                    for i, material_group in enumerate(recipe.materials):
                        if len(material_group) > 1:
                            current_mat_id = None
                            for m in material_group:
                                if f"{m.item_id}_{i}" in node.inputs:
                                    current_mat_id = m.item_id
                                    break
                            
                            if not current_mat_id:
                                current_mat_id = material_group[0].item_id
                                
                            opts = [m.item_id for m in material_group]
                            
                            def make_format_func(mg):
                                def format_func(x):
                                    for m in mg:
                                        if m.item_id == x:
                                            return f"{m.amount}x {m.item_id.replace('_', ' ').title()}"
                                    return x
                                return format_func
                            
                            idx = opts.index(current_mat_id) if current_mat_id in opts else 0
                            
                            new_mat_id = st.selectbox(
                                f"Variant for Input {i+1}", 
                                options=opts, 
                                index=idx, 
                                format_func=make_format_func(material_group),
                                key=f"mat_opt_{node.node_id}_{i}"
                            )
                            
                            if new_mat_id != current_mat_id:
                                old_key = f"{current_mat_id}_{i}"
                                new_mat = next(m for m in material_group if m.item_id == new_mat_id)
                                
                                new_inputs = {}
                                for k, v in node.inputs.items():
                                    if k == old_key:
                                        new_inputs[f"{new_mat_id}_{i}"] = build_default_tree(new_mat.item_id, game_data_dict, new_mat.amount, level + 1)
                                    else:
                                        new_inputs[k] = v
                                        
                                if f"{new_mat_id}_{i}" not in new_inputs:
                                    new_inputs[f"{new_mat_id}_{i}"] = build_default_tree(new_mat.item_id, game_data_dict, new_mat.amount, level + 1)
                                    
                                node.inputs = new_inputs
                                st.rerun()

            st.markdown("###### ⬇️ Requires:")
            with st.container(border=False):
                for child_id, child_node in node.inputs.items():
                    render_tree_node(child_node, game_data_dict, drop_calc, level + 1)

def render_crafting_tree_tab(recipes, all_items_raw, activities, all_containers, user_state, drop_calc, locations):
    st.subheader("Crafting Tree Calculator")
    st.caption("Calculate the true step cost, raw material requirements, and profitability of complex items.")
    
    with st.expander("📖 **How this math works & Flow of Calculations**", expanded=False):
        st.markdown("""
        **The Logic of the Chain:**
        When calculating the true cost of a crafted item, this tool traverses the tree from bottom to top. It applies your selected gear stats at each node to calculate the true fractional cost of exactly 1 item.

       """)
        
 

        st.markdown("""
            ### 🧮 Formula Breakdown
            
            **1. Action Steps (The base cost of an action):**
            $$ \\text{Action Steps} = \\max\\left(10, \\left[ \\frac{\\text{Base Steps}}{1 + \\text{Work Efficiency}} \\times (1 - \\text{Step Reduction \\%}) \\right] - \\text{Flat Step Reduction} \\right) $$

            **2. Quality Probability (The Target Rule):**
            *Note: When calculating a tree, Quality Probability is strictly calculated for the **Final Crafted Output** (Root Node). All sub-components and materials are calculated at Normal quality (Probability = 1.0) because recipes accept normal inputs.*

            **3. Steps per Item (Recipes):**
            $$ \\text{Steps/Item} = \\frac{\\text{Action Steps}}{\\text{Base Output Qty} \\times (1 + \\text{Double Action}) \\times (1 + \\text{Double Rewards}) \\times \\text{Quality Prob}} $$

            **4. Input Material Ratio (Recipes):**
            *How much of a raw material is consumed to make ONE final output item:*
            $$ \\text{Input Ratio} = \\frac{\\text{Required Amount} \\times (1 - \\text{No Materials Consumed})}{\\text{Base Output Qty} \\times (1 + \\text{Double Rewards}) \\times \\text{Quality Prob}} $$

            **5. Steps per Item (Gathering Activities):**
            $$ \\text{Steps/Item} = \\frac{\\text{Action Steps}}{(\\text{Drop Chance} \\times \\text{Avg Qty}) \\times (1 + \\text{Double Action}) \\times (1 + \\text{Double Rewards})} $$
        
            **6. Steps per Item (Chests 🧰):**
            *First, calculates how many steps it takes to find the chest, then divides by the expected loot:*
            $$ \\text{Steps/Chest} = \\frac{\\text{Action Steps}}{\\text{Chest Drop Chance} \\times (1 + \\text{DA}) \\times (1 + \\text{DR})} $$
            $$ \\text{Steps/Item} = \\frac{\\text{Steps/Chest}}{\\text{Expected Items from Chest Loot Table}} $$

            **7. XP per Item:**
            $$ \\text{XP/Item} = \\frac{(\\text{Base XP} \\times (1 + \\text{Bonus XP \\%})) + \\text{Flat XP}}{\\text{Base Output Qty} \\times (1 + \\text{Double Rewards}) \\times \\text{Quality Prob}} $$
            *(Note: Double Action speeds up your action frequency but does not grant "free" XP per item, meaning it mathematically cancels out of the per-item XP ratio! Double Rewards, however, dilutes the XP by giving you items without extra effort).*
            """)

    all_item_names = sorted(list({r.output_item_id for r in recipes}))
    target_item = st.selectbox("Select Target Item", options=all_item_names, format_func=lambda x: x.replace('_', ' ').title())
    
    game_data_dict = {
        'recipes': {r.id: r for r in recipes},
        'activities': {a.id: a for a in activities},
        'chests': {c.id: c for c in all_containers} 
    }
        
    if st.button("Generate Tree", type="primary"):
        st.session_state['crafting_tree_root'] = build_default_tree(target_item, game_data_dict)
        st.session_state['tree_target_item'] = target_item 
        st.rerun()

    st.divider()

    if st.session_state.get('crafting_tree_root'):
        root = st.session_state['crafting_tree_root']
        target_item_id = st.session_state.get('tree_target_item', root.item_id)
        
        st.markdown("### ⚙️ Global Settings")
        c_g1, c_g2, c_g3, c_g4 = st.columns(4)
        
        with c_g1:
            target_amount = st.number_input("Target Quantity", min_value=1, value=1, step=1)
            
        with c_g2:
            daily_steps = st.number_input("Est. Daily Steps", min_value=1000, value=10000, step=1000, help="Used to estimate real-world time.")
        
        with c_g3:
            is_equipment = any(
                item.id == target_item_id or item.id.startswith(f"{target_item_id}_") 
                for item in all_items_raw
            )
            
            if is_equipment:
                qualities = [q for q in EquipmentQuality]
                st.session_state['global_quality'] = st.selectbox("Target Quality", options=qualities, index=0)
            else:
                st.session_state['global_quality'] = "Normal"
                st.caption("*(Target Quality N/A)*")
        
        with c_g4:
            st.write("")
            st.write("")
            can_fine = can_tree_use_fine(root, drop_calc)
            if can_fine:
                st.session_state['global_fine'] = st.checkbox("💎 Fine Materials", value=False)
            else:
                st.session_state['global_fine'] = False

        st.divider()
        
        render_tree_node(root, game_data_dict, drop_calc)
        
        st.divider()
        if st.button("🧮 Calculate True Cost & Run Optimizers", type="primary"):
            
            valid_json = user_state.get("valid_json", False)
            user_skills_map = user_state.get("user_skills_map", {})
            player_skill_levels = {k: calculate_level_from_xp(v) for k, v in user_skills_map.items()} if valid_json else {}
            
            optimizer = GearOptimizer(all_items_raw, locations)
            owned_item_counts = user_state.get("item_counts", {}) if valid_json else {}
            ap = user_state.get("user_ap", 0) if valid_json else 0
            reputation = user_state.get("user_reputation", {}) if valid_json else {}
            collectibles = user_state.get("owned_collectibles", []) if valid_json else []
            char_lvl = user_state.get("calculated_char_lvl", 99) if valid_json else 99

            with st.spinner("Optimizing gear and calculating cascading steps..."):
                def run_and_save_metrics(node, is_root=False):
                    for child in node.inputs.values():
                        run_and_save_metrics(child, is_root=False)
                    
                    # --- AUTO OPTIMIZE LOGIC ---
                    if getattr(node, 'loadout_id', None) == "AUTO" and getattr(node, 'auto_optimize_target', None):
                        activity_obj = None
                        skill_name = ""
                        if node.source_type == "recipe":
                            recipe_obj = game_data_dict['recipes'].get(node.source_id)
                            if recipe_obj:
                                skill_name = recipe_obj.skill
                                class WrappedRecipe:
                                    def __init__(self, r):
                                        self.id = r.id
                                        self.name = r.name
                                        self.primary_skill = r.skill
                                        self.level = r.level
                                        self.base_xp = r.base_xp
                                        self.base_steps = r.base_steps
                                        self.max_efficiency = r.max_efficiency
                                        self.locations = []
                                        self.requirements = []
                                activity_obj = WrappedRecipe(recipe_obj)
                        elif node.source_type in ["activity", "chest"]:
                            act_id = node.source_id if node.source_type == "activity" else node.parent_activity_id
                            activity_obj = game_data_dict['activities'].get(act_id)
                            skill_name = activity_obj.primary_skill if activity_obj else ""
                        
                        if activity_obj:
                            formatted_targets = []
                            for t_dict in node.auto_optimize_target:
                                target_enum_name = t_dict["target"].replace(" ", "_").lower()
                                try:
                                    enum_target = OPTIMAZATION_TARGET[target_enum_name]
                                    formatted_targets.append((enum_target, float(t_dict["weight"])))
                                except KeyError:
                                    continue
                                    
                            if not formatted_targets:
                                formatted_targets = [(OPTIMAZATION_TARGET.reward_rolls, 100.0)]
                            
                            player_lvl_opt = player_skill_levels.get(skill_name.lower(), 99) if skill_name else 99
                            
                            opt_result = optimizer.optimize(
                                activity=activity_obj,
                                player_level=char_lvl,
                                player_skill_level=player_lvl_opt,
                                optimazation_target=formatted_targets,
                                owned_item_counts=owned_item_counts,
                                achievement_points=ap,
                                user_reputation=reputation,
                                owned_collectibles=collectibles
                            )
                            node.auto_gear_set = opt_result[0] 
                    
                    # --- CALCULATE COST ---
                    target_qual = st.session_state.get('global_quality', "Normal") if is_root else "Normal"
                    
                    node.metrics = calculate_node_metrics(
                        node, st.session_state['saved_loadouts'], 
                        game_data_dict, drop_calc, player_skill_levels,
                        global_target_quality=target_qual,
                        global_use_fine=st.session_state.get('global_fine', False)
                    )
                    
                    # --- EXPORT BASE64 ---
                    if getattr(node, 'loadout_id', None) == "AUTO" and getattr(node, 'auto_gear_set', None):
                        node.metrics["gear_set_base64"] = export_gearset(node.auto_gear_set)
                    elif getattr(node, 'loadout_id', None) and node.loadout_id in st.session_state['saved_loadouts']:
                        node.metrics["gear_set_base64"] = export_gearset(st.session_state['saved_loadouts'][node.loadout_id].gear_set)
                        
                    return node.metrics
                
                run_and_save_metrics(root, is_root=True)
                
            st.rerun()

        # ==========================================
        # SUMMARY SECTION
        # ==========================================
        if root.metrics and root.metrics.get("steps", float('inf')) != float('inf'):
            st.markdown("### 📊 Grand Totals Summary")
            st.caption(f"Calculated for **{target_amount}x {target_item.replace('_', ' ').title()}**")
            
            total_steps = root.metrics["steps"] * target_amount
            days_est = total_steps / daily_steps
            
            # --- Key Metrics Cards ---
            c_sum1, c_sum2, c_sum3 = st.columns(3)
            with c_sum1:
                st.markdown(f"<div style='background-color:#0f172a; padding:15px; border-radius:8px; border: 1px solid #1e293b;'>"
                            f"<h4 style='margin:0; color:#e2e8f0;'>Total Steps</h4>"
                            f"<h2 style='margin:0; color:#4ade80;'>{total_steps:,.0f}</h2>"
                            f"<span style='color:#94a3b8;'>Estimated Time: <b>{days_est:,.1f} days</b></span>"
                            f"</div>", unsafe_allow_html=True)
                
            with c_sum2:
                cost = 0.0
                for item_id, amt in root.metrics["raw_materials"].items():
                    cost += (amt * target_amount) * drop_calc.item_values.get(item_id, 0.0)
                
                st.markdown(f"<div style='background-color:#0f172a; padding:15px; border-radius:8px; border: 1px solid #1e293b;'>"
                            f"<h4 style='margin:0; color:#e2e8f0;'>Total Material Cost</h4>"
                            f"<h2 style='margin:0; color:#f87171;'>{cost:,.0f} 🪙</h2>"
                            f"<span style='color:#94a3b8;'>Value of all gathered & banked inputs</span>"
                            f"</div>", unsafe_allow_html=True)
                
            with c_sum3:
                total_xp = sum(root.metrics["xp"].values()) * target_amount
                avg_xp = total_xp / total_steps if (total_steps > 0 and total_steps != float('inf')) else 0
                
                st.markdown(f"<div style='background-color:#0f172a; padding:15px; border-radius:8px; border: 1px solid #1e293b;'>"
                            f"<h4 style='margin:0; color:#e2e8f0;'>Total XP Yield</h4>"
                            f"<h2 style='margin:0; color:#60a5fa;'>{total_xp:,.0f}</h2>"
                            f"<span style='color:#94a3b8;'>Avg: <b>{avg_xp:,.2f}</b> XP/Step</span>"
                            f"</div>", unsafe_allow_html=True)

            st.write("")
            
            # --- Details Tables ---
            c_det1, c_det2 = st.columns([1.5, 1])
            
            with c_det1:
                st.markdown("##### 🛒 Raw Materials Shopping List")
                st.caption("Materials required from Bank (factors in NMC and Double Rewards).")
                shopping_data = []
                for item_id, amt in root.metrics["shopping_list"].items():
                    final_amt = amt * target_amount
                    shopping_data.append({
                        "Item": item_id.replace('_', ' ').title(),
                        "Amount Needed": f"{final_amt:,.2f}"
                    })
                if shopping_data:
                    st.dataframe(pd.DataFrame(shopping_data), hide_index=True, width="stretch")
                else:
                    st.info("No raw materials required from the bank! (Everything gathered via activities).")
                    
            with c_det2:
                st.markdown("##### 📈 XP Breakdown")
                st.caption("Experience gained by skill.")
                xp_data = []
                for skill, amt in root.metrics["xp"].items():
                    if amt > 0:
                        xp_data.append({
                            "Skill": skill.title(),
                            "XP": f"{amt * target_amount:,.1f}"
                        })
                if xp_data:
                    st.dataframe(pd.DataFrame(xp_data).sort_values(by="Skill"), hide_index=True, width="stretch")
                else:
                    st.info("No XP generated by this chain.")