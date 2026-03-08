import streamlit as st
import pandas as pd
import json
from models import EquipmentSlot, EquipmentQuality, ConditionType, RequirementType, StatName, SkillName, ActivityLootTableType

def render_data_entry_tab():
    st.subheader("📝 Game Data Entry Portal")
    st.caption("Fill out the forms below to generate perfectly mapped JSON for the game database.")

    entity_type = st.selectbox("Select Entity Type to Create", [
        "Location", "Material", "Consumable", "Equipment", "Pet", "Activity", "Recipe"
    ])

    st.divider()

    # Shared Base Fields
    c1, c2, c3 = st.columns(3)
    with c1: name = st.text_input("Name", placeholder="e.g. Copper Ore")
    with c2: item_id = st.text_input("ID", value=name.lower().replace(" ", "_") if name else "")
    with c3: slug = st.text_input("Wiki Slug", placeholder="Special:MyLanguage/...")

    # Shared Item Fields (Values & Keywords)
    value = 0
    keywords = []
    if entity_type in ["Material", "Consumable", "Equipment"]:
        c4, c5 = st.columns([1, 3])
        with c4: value = st.number_input("Coin Value", min_value=0, value=0)
        with c5: 
            kw_str = st.text_input("Keywords (comma separated)", placeholder="Ore, exact_item_copper_ore")
            keywords = [k.strip() for k in kw_str.split(",") if k.strip()]

    st.markdown("---")

    # ==========================================
    # 1. LOCATION
    # ==========================================
    if entity_type == "Location":
        tags_str = st.text_input("Tags (comma separated)", placeholder="syrenthia, underwater")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        
        final_json = {
            "id": item_id, "wiki_slug": slug, "name": name, "tags": tags
        }

    # ==========================================
    # 2. MATERIAL
    # ==========================================
    elif entity_type == "Material":
        modifiers = ui_modifier_builder()
        
        c_sell, _ = st.columns(2)
        with c_sell:
            has_special = st.checkbox("Has Special Sell?")
            if has_special:
                sell_id = st.text_input("Special Sell Target ID")
                sell_amt = st.number_input("Special Sell Amount", min_value=1)
            else:
                sell_id, sell_amt = None, None

        final_json = {
            "id": item_id, "wiki_slug": slug, "name": name, "value": value, "keywords": keywords,
            "special_sell": {"item_id": sell_id, "amount": sell_amt} if has_special else None,
            "modifiers": modifiers
        }

    # ==========================================
    # 3. CONSUMABLE
    # ==========================================
    elif entity_type == "Consumable":
        duration = st.number_input("Duration (steps)", min_value=1, value=1000)
        modifiers = ui_modifier_builder()
        
        final_json = {
            "id": item_id, "wiki_slug": slug, "name": name, "value": value, "keywords": keywords,
            "duration": duration, "modifiers": modifiers
        }

    # ==========================================
    # 4. EQUIPMENT
    # ==========================================
    elif entity_type == "Equipment":
        c_slot, c_qual = st.columns(2)
        with c_slot: slot = st.selectbox("Slot", [e.value for e in EquipmentSlot])
        with c_qual: qual = st.selectbox("Quality", [e.value for e in EquipmentQuality])
        
        uuid_val = f"item-{item_id}-placeholder-uuid"

        t_req, t_mod = st.tabs(["Requirements", "Modifiers"])
        with t_req: requirements = ui_requirement_builder()
        with t_mod: modifiers = ui_modifier_builder()

        final_json = {
            "id": item_id, "wiki_slug": slug, "name": name, "value": value, "keywords": keywords,
            "uuid": uuid_val, "slot": slot, "quality": qual,
            "requirements": requirements, "modifiers": modifiers
        }

    # ==========================================
    # 5. PET
    # ==========================================
    elif entity_type == "Pet":
        c_egg, c_xp = st.columns(2)
        with c_egg: egg_id = st.text_input("Egg Item ID", value=f"{item_id}_egg" if item_id else "")
        with c_xp: xp_desc = st.text_input("XP Requirement Desc", placeholder="None")

        st.markdown("#### Pet Levels")
        num_levels = st.number_input("Number of Levels", min_value=1, max_value=6, value=3)
        
        levels_array = []
        tabs = st.tabs([f"Level {i+1}" for i in range(int(num_levels))])
        
        for i, tab in enumerate(tabs):
            with tab:
                lvl_xp = st.number_input(f"Total XP for Level {i+1}", min_value=0, value=50000 * (i+1), key=f"pet_xp_{i}")
                
                st.markdown("**Modifiers**")
                lvl_mods = ui_modifier_builder(key_prefix=f"pet_mod_{i}")
                
                st.markdown("**Abilities**")
                df_ab = pd.DataFrame([{"name": "", "effect": "", "cooldown": "", "charges": 1}])
                edited_ab = st.data_editor(df_ab, num_rows="dynamic", key=f"pet_ab_{i}", width="stretch")
                
                abilities = []
                for _, row in edited_ab.iterrows():
                    if row["name"]:
                        abilities.append({
                            "name": row["name"], "effect": row["effect"],
                            "requirements": None, "cooldown": row["cooldown"] if row["cooldown"] else None,
                            "charges": int(row["charges"])
                        })
                
                levels_array.append({
                    "level": i + 1, "total_xp": lvl_xp, "modifiers": lvl_mods, "abilities": abilities
                })

        final_json = {
            "id": item_id, "wiki_slug": slug, "name": name, "egg_item_id": egg_id,
            "xp_requirement_desc": xp_desc if xp_desc else None, "levels": levels_array
        }

    # ==========================================
    # 6. ACTIVITY
    # ==========================================
    elif entity_type == "Activity":
        c_sk, c_loc = st.columns(2)
        with c_sk: skill = st.selectbox("Primary Skill", [e.value for e in SkillName])
        with c_loc: 
            loc_str = st.text_input("Locations (comma separated)")
            act_locations = [l.strip() for l in loc_str.split(",") if l.strip()]

        c_step, c_xp, c_eff = st.columns(3)
        with c_step: base_steps = st.number_input("Base Steps", min_value=1, value=50)
        with c_xp: base_xp = st.number_input("Base XP", min_value=0.0, value=10.0)
        with c_eff: max_eff = st.number_input("Max Efficiency", min_value=0.0, max_value=1.0, value=0.5)

        st.markdown("#### Economy Worth")
        cw1, cw2, cw3 = st.columns(3)
        with cw1: n_worth = st.number_input("Normal Roll Worth", value=1.0)
        with cw2: c_worth = st.number_input("Chest Roll Worth", value=0.5)
        with cw3: f_worth = st.number_input("Fine Roll Worth", value=5.0)

        t_req, t_mod, t_loot = st.tabs(["Requirements", "Modifiers", "Loot Tables"])
        with t_req: requirements = ui_requirement_builder()
        with t_mod: modifiers = ui_modifier_builder()
        
        with t_loot:
            loot_tables = []
            lt_types = st.multiselect("Loot Table Types", [e.value for e in ActivityLootTableType], default=["main"])
            
            for lt_type in lt_types:
                st.markdown(f"**{lt_type.title()} Drops**")
                df_drops = pd.DataFrame([{"item_id": "nothing", "min": 0, "max": 0, "chance": 50.0}])
                edited_drops = st.data_editor(df_drops, num_rows="dynamic", key=f"drops_{lt_type}", width="stretch")
                
                drops_array = []
                for _, row in edited_drops.iterrows():
                    if row["item_id"]:
                        drops_array.append({
                            "item_id": row["item_id"], "min_quantity": int(row["min"]), "max_quantity": int(row["max"]),
                            "chance": float(row["chance"]), "category": None
                        })
                loot_tables.append({"type": lt_type, "drops": drops_array})

        final_json = {
            "id": item_id, "wiki_slug": slug, "name": name, "primary_skill": skill, "locations": act_locations,
            "base_steps": base_steps, "base_xp": base_xp, "secondary_xp": {}, "max_efficiency": max_eff,
            "requirements": requirements, "faction_rewards": [], "loot_tables": loot_tables,
            "modifiers": modifiers, "normal_roll_worth": n_worth, "chest_roll_worth": c_worth, "fine_roll_worth": f_worth
        }

    # ==========================================
    # 7. RECIPE
    # ==========================================
    elif entity_type == "Recipe":
        c_sk, c_lvl, c_srv = st.columns(3)
        with c_sk: skill = st.selectbox("Skill", [e.value for e in SkillName])
        with c_lvl: level = st.number_input("Level", min_value=1, value=1)
        with c_srv: service = st.text_input("Service", placeholder="basic_forge")

        c_out, c_qty = st.columns(2)
        with c_out: output_id = st.text_input("Output Item ID", value=item_id)
        with c_qty: output_qty = st.number_input("Output Quantity", min_value=1, value=1)

        c_step, c_xp, c_eff = st.columns(3)
        with c_step: base_steps = st.number_input("Base Steps", min_value=1, value=50)
        with c_xp: base_xp = st.number_input("Base XP", min_value=0.0, value=10.0)
        with c_eff: max_eff = st.number_input("Max Efficiency", min_value=0.0, max_value=1.0, value=0.5)

        st.markdown("#### Required Materials")
        st.caption("Each row is an OR requirement (e.g., Use 1 Copper OR 1 Tin). To require multiple different items, add them in separate groups.")
        
        materials_array = []
        num_groups = st.number_input("Number of Material Groups (AND)", min_value=1, max_value=5, value=1)
        
        for i in range(int(num_groups)):
            st.markdown(f"**Material Group {i+1}**")
            df_mat = pd.DataFrame([{"item_id": "", "amount": 1}])
            edited_mat = st.data_editor(df_mat, num_rows="dynamic", key=f"mat_grp_{i}", width="stretch")
            
            group_opts = []
            for _, row in edited_mat.iterrows():
                if row["item_id"]:
                    group_opts.append({"item_id": row["item_id"], "amount": int(row["amount"])})
            if group_opts:
                materials_array.append(group_opts)

        final_json = {
            "id": item_id, "wiki_slug": slug, "name": name, "skill": skill, "level": level, "service": service,
            "output_item_id": output_id, "output_quantity": output_qty, "materials": materials_array,
            "base_xp": base_xp, "base_steps": base_steps, "max_efficiency": max_eff
        }

    # ==========================================
    # EXPORT & OUTPUT
    # ==========================================
    st.markdown("---")
    st.markdown("### Generated JSON")
    
    # Remove empty string lists/dicts to keep JSON clean
    json_output = json.dumps(final_json, indent=2)
    st.code(json_output, language="json")

    st.download_button("💾 Download JSON Entry", data=json_output, file_name=f"{item_id if item_id else 'new_entry'}.json", mime="application/json")


# --- HELPER FUNCTIONS FOR NESTED LISTS ---

def ui_requirement_builder(key_prefix="req"):
    """Creates a data editor for Requirements."""
    df_req = pd.DataFrame([{
        "type": RequirementType.SKILL_LEVEL.value, "target": "agility", "value": 1
    }])
    
    edited_req = st.data_editor(
        df_req, num_rows="dynamic", key=f"{key_prefix}_editor", width="stretch",
        column_config={
            "type": st.column_config.SelectboxColumn("Type", options=[e.value for e in RequirementType]),
            "target": st.column_config.TextColumn("Target (Skill/Keyword)"),
            "value": st.column_config.NumberColumn("Value", default=1)
        }
    )
    
    reqs = []
    for _, row in edited_req.iterrows():
        if pd.notna(row["type"]):
            reqs.append({
                "type": row["type"], "target": row["target"] if row["target"] else None, "value": int(row["value"])
            })
    return reqs

def ui_modifier_builder(key_prefix="mod"):
    """Creates a data editor for Modifiers and flattens up to 2 conditions for easy UI."""
    df_mod = pd.DataFrame([{
        "stat": StatName.WORK_EFFICIENCY.value, "value": 0.0,
        "cond1_type": ConditionType.GLOBAL.value, "cond1_target": "",
        "cond2_type": None, "cond2_target": ""
    }])
    
    edited_mod = st.data_editor(
        df_mod, num_rows="dynamic", key=f"{key_prefix}_editor", width="stretch",
        column_config={
            "stat": st.column_config.SelectboxColumn("Stat", options=[e.value for e in StatName]),
            "value": st.column_config.NumberColumn("Value", format="%.1f"),
            "cond1_type": st.column_config.SelectboxColumn("Condition 1", options=[e.value for e in ConditionType]),
            "cond1_target": st.column_config.TextColumn("Target 1"),
            "cond2_type": st.column_config.SelectboxColumn("Condition 2", options=[None] + [e.value for e in ConditionType]),
            "cond2_target": st.column_config.TextColumn("Target 2"),
        }
    )
    
    mods = []
    for _, row in edited_mod.iterrows():
        if pd.notna(row["stat"]):
            conditions = []
            if pd.notna(row["cond1_type"]) and row["cond1_type"]:
                conditions.append({"type": row["cond1_type"], "target": row["cond1_target"] if row["cond1_target"] else None, "value": None})
            if pd.notna(row["cond2_type"]) and row["cond2_type"]:
                conditions.append({"type": row["cond2_type"], "target": row["cond2_target"] if row["cond2_target"] else None, "value": None})
            
            # Fallback to global if empty
            if not conditions: conditions.append({"type": "global", "target": None, "value": None})
                
            mods.append({
                "stat": row["stat"], "value": float(row["value"]), "conditions": conditions
            })
    return mods