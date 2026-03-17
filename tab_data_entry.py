import streamlit as st
import json
from models import (
    EquipmentSlot, EquipmentQuality, ConditionType, RequirementType, 
    StatName, SkillName, ActivityLootTableType, ChestTableCategory
)
from utils.constants import RESTRICTED_TOOL_KEYWORDS
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import requests
import time
# --- DYNAMIC FORM HELPERS ---

def render_dynamic_list(prefix, label, render_func, context=None):
    """Generic helper to manage dynamic lists of form inputs."""
    count_key = f"{prefix}_cnt"
    if count_key not in st.session_state: 
        st.session_state[count_key] = 0
        
    c1, c2, _ = st.columns([1, 1, 3])
    with c1:
        if st.button(f"➕ Add {label}", key=f"{prefix}_add"):
            st.session_state[count_key] += 1
    with c2:
        if st.button(f"➖ Remove {label}", key=f"{prefix}_rem") and st.session_state[count_key] > 0:
            st.session_state[count_key] -= 1

    results = []
    for i in range(st.session_state[count_key]):
        with st.container(border=True):
            res = render_func(prefix, i, context)
            if res: results.append(res)
    return results

def render_req(prefix, i, context):
    c1, c2, c3 = st.columns([1.5, 2, 1])
    req_type = c1.selectbox("Requirement Type", [e.value for e in RequirementType], key=f"{prefix}_t_{i}")
    
    target, val = None, 1
    
    # Contextual Target Box
    if req_type == RequirementType.SKILL_LEVEL.value:
        target = c2.selectbox("Skill", [e.value for e in SkillName], key=f"{prefix}_tgt_{i}")
        val = c3.number_input("Level Required", min_value=1, value=1, key=f"{prefix}_v_{i}")
    
    elif req_type in [RequirementType.ACTIVITY_COMPLETION.value, RequirementType.SPECIFIC_ACTIVITY.value]:
        target = c2.selectbox("Activity", context["act_ids"], index=None, placeholder="Search activities...", key=f"{prefix}_tgt_{i}")
        val = c3.number_input("Amount", min_value=1, value=1, key=f"{prefix}_v_{i}")
        
    elif req_type in [RequirementType.TOOL_EQUIPPED.value, RequirementType.UNIQUE_TOOLS.value]:
        target = c2.selectbox("Tool Type", list(RESTRICTED_TOOL_KEYWORDS), index=None, placeholder="Select tool type...", key=f"{prefix}_tgt_{i}")
        val = c3.number_input("Amount", min_value=1, value=1, key=f"{prefix}_v_{i}")
        
    elif req_type in [RequirementType.ACHIEVEMENT_POINTS.value, RequirementType.CHARACTER_LEVEL.value]:
        c2.caption("No target string needed.")
        val = c3.number_input("Amount Required", min_value=1, value=1, key=f"{prefix}_v_{i}")
        
    else:
        target = c2.text_input("Target (Text)", key=f"{prefix}_tgt_{i}")
        val = c3.number_input("Value", min_value=1, value=1, key=f"{prefix}_v_{i}")

    return {"type": req_type, "target": target if target else None, "value": val}

def render_mod(prefix, i, context):
    c1, c2 = st.columns([2, 1])
    stat = c1.selectbox("Stat", [e.value for e in StatName], key=f"{prefix}_stat_{i}", index=None, placeholder="Search stats...")
    
    # Use text_input to avoid clunky numeric spinners. Much better for mobile and varied scale typing.
    val_str = c2.text_input("Stat Value", value="0.0", key=f"{prefix}_val_{i}", placeholder="e.g. 0.05 or 10")
    
    # Safely convert to float, handling commas for European keyboard layouts
    val = 0.0
    if val_str:
        try:
            val = float(val_str.replace(',', '.'))
        except ValueError:
            pass # Invalid text will safely default to 0.0

    st.caption("Condition (Leave as Global if none)")
    cc1, cc2, cc3 = st.columns([1.5, 2, 1])
    cond_type = cc1.selectbox("Condition Type", [e.value for e in ConditionType], index=0, key=f"{prefix}_ct_{i}") # Global is index 0
    
    cond_tgt, cond_val = None, None
    
    # Contextual Condition Inputs
    if cond_type == ConditionType.GLOBAL.value:
        cc2.caption("Applies everywhere.")
        
    elif cond_type == ConditionType.SKILL_ACTIVITY.value:
        opts = [e.value for e in SkillName] + ["gathering", "artisan"]
        cond_tgt = cc2.selectbox("Target Skill/Category", opts, key=f"{prefix}_ctgt_{i}")
        
    elif cond_type == ConditionType.LOCATION.value:
        cond_tgt = cc2.selectbox("Location", context["loc_ids"], index=None, placeholder="Search locations...", key=f"{prefix}_ctgt_{i}")
        
    elif cond_type == ConditionType.SPECIFIC_ACTIVITY.value:
        cond_tgt = cc2.selectbox("Activity", context["act_ids"], index=None, placeholder="Search activities...", key=f"{prefix}_ctgt_{i}")
        
    elif cond_type == ConditionType.ITEM_OWNERSHIP.value:
        cond_tgt = cc2.selectbox("Item ID", context["all_item_ids"], index=None, placeholder="Search items...", key=f"{prefix}_ctgt_{i}")
        
    elif cond_type in [ConditionType.ACHIEVEMENT_POINTS.value, ConditionType.TOTAL_SKILL_LEVEL.value]:
        cc2.caption("No target string needed.")
        cond_val = cc3.number_input("Amount Required", min_value=1, value=100, key=f"{prefix}_cv_{i}")
        
    else: # SET_EQUIPPED, REGION, REPUTATION, etc.
        cond_tgt = cc2.text_input("Target String", key=f"{prefix}_ctgt_{i}")
        cond_val = cc3.number_input("Value (if applicable)", min_value=0, value=0, key=f"{prefix}_cv_{i}")
    
    conditions = [{"type": cond_type, "target": cond_tgt, "value": cond_val if cond_val else None}]
    
    if stat:
        return {"stat": stat, "value": val, "conditions": conditions}
    return None

def item_selector_ui(label, prefix, i, context):
    """Helper for picking an item from the database, with a manual override."""
    c_toggle, c_input = st.columns([1, 3])
    manual = c_toggle.checkbox("Manual ID entry", key=f"{prefix}_man_{i}")
    if manual:
        return c_input.text_input(label, key=f"{prefix}_id_txt_{i}")
    else:
        return c_input.selectbox(label, context["all_item_ids"], index=None, placeholder="Search database...", key=f"{prefix}_id_sel_{i}")

def render_drop(prefix, i, context):
    st.markdown(f"**Drop {i+1}**")
    item_id = item_selector_ui("Item ID to Drop", prefix, i, context)
    
    c1, c2, c3, c4 = st.columns(4)
    min_q = c1.number_input("Min", min_value=1, value=1, key=f"{prefix}_min_{i}")
    max_q = c2.number_input("Max", min_value=1, value=1, key=f"{prefix}_max_{i}")
    chance = c3.number_input("Chance %", min_value=0.0, max_value=100.0, value=100.0, step=1.0, format="%.4f", key=f"{prefix}_ch_{i}")
    cat = c4.selectbox("Category", ["None"] + [e.value for e in ChestTableCategory], key=f"{prefix}_cat_{i}")
    
    if item_id:
        return {
            "item_id": item_id, "min_quantity": min_q, "max_quantity": max_q, 
            "chance": chance, "category": cat if cat != "None" else None
        }
    return None

def render_recipe_mat(prefix, i, context):
    item_id = item_selector_ui(f"Material {i+1}", prefix, i, context)
    amt = st.number_input("Amount", min_value=1, value=1, key=f"{prefix}_amt_{i}")
    if item_id:
        return {"item_id": item_id, "amount": amt}
    return None

def render_sec_xp(prefix, i, context):
    c1, c2 = st.columns(2)
    skill = c1.selectbox("Skill", [e.value for e in SkillName], key=f"{prefix}_sk_{i}")
    xp = c2.number_input("XP Amount", min_value=0.0, value=1.0, step=1.0, format="%.2f", key=f"{prefix}_xp_{i}")
    if skill:
        return (skill, xp)
    return None

def render_faction(prefix, i, context):
    c1, c2 = st.columns(2)
    fac_id = c1.text_input("Faction ID", key=f"{prefix}_fid_{i}")
    amt = c2.number_input("Amount", value=1.0, step=1.0, format="%.2f", key=f"{prefix}_famt_{i}")
    if fac_id:
        return {"faction_id": fac_id, "amount": amt}
    return None

def render_pet_ability(prefix, i, context):
    c1, c2, c3, c4 = st.columns([2, 3, 1, 1])
    name = c1.text_input("Ability Name", key=f"{prefix}_name_{i}")
    effect = c2.text_input("Effect", key=f"{prefix}_eff_{i}")
    cd = c3.text_input("Cooldown", key=f"{prefix}_cd_{i}")
    charges = c4.number_input("Charges", min_value=1, value=1, key=f"{prefix}_chg_{i}")
    if name:
        return {"name": name, "effect": effect, "requirements": None, "cooldown": cd if cd else None, "charges": charges}
    return None


# --- MAIN UI ---

def render_data_entry_tab(
    all_items_raw=None, activities=None, locations=None, services=None, 
    all_pets=None, all_consumables=None, all_materials=None
):
    # --- Build Context Dictionaries for Dropdowns ---
    ctx_items = []
    if all_items_raw: ctx_items.extend([i.id for i in all_items_raw])
    if all_materials: ctx_items.extend([m.id for m in all_materials])
    if all_consumables: ctx_items.extend([c.id for c in all_consumables])
    if all_pets: ctx_items.extend([p.egg_item_id for p in all_pets if p.egg_item_id])
    
    context = {
        "all_item_ids": sorted(list(set(ctx_items))),
        "loc_ids": sorted([l.id for l in locations]) if locations else [],
        "act_ids": sorted([a.id for a in activities]) if activities else [],
        "srv_ids": sorted([s.id for s in services]) if services else [],
        "recipe_services": [
            "basic_forge", "advanced_forge",
            "basic_kitchen", "advanced_kitchen",
            "basic_sawmill", "advanced_sawmill",
            "basic_trinketry_bench", "advanced_trinketry_bench",
            "basic_workshop", "advanced_workshop",
            "basic_tailoring_station", "advanced_tailoring_station"
        ]
    }
    
    st.subheader("📝 Game Data Entry Portal")
    st.caption("Fill out the forms below to generate perfectly mapped JSON for the game database.")

    entity_type = st.selectbox("Select Entity Type to Create", [
        "Location", "Material", "Consumable", "Equipment", "Pet", "Activity", "Recipe"
    ])

    st.divider()

    # Shared Base Fields
    c1, c2, c3 = st.columns(3)
    name = c1.text_input("Name", placeholder="e.g. Copper Ore")
    
    # Auto-generate ID and Wiki Slug
    auto_id = name.lower().replace(" ", "_") if name else ""
    item_id = c2.text_input("ID", value=auto_id)
    auto_slug = f"Special:MyLanguage/{name}" if name else ""
    slug = c3.text_input("Wiki Slug", value=auto_slug)
    
    # Inject the current ID being created into the context so it can be self-referenced!
    if item_id and item_id not in context["all_item_ids"]:
        context["all_item_ids"].insert(0, item_id)

    # Shared Item Fields (Values & Keywords)
    value = 0
    keywords = []
    if entity_type in ["Material", "Consumable", "Equipment"]:
        c4, c5 = st.columns([1, 3])
        value = c4.number_input("Coin Value", min_value=0, value=0)
        kw_str = c5.text_input("Keywords (comma separated)", placeholder="Ore, exact_item_copper_ore")
        keywords = [k.strip() for k in kw_str.split(",") if k.strip()]

    st.markdown("---")
    final_json = {}

    # ==========================================
    # 1. LOCATION
    # ==========================================
    if entity_type == "Location":
        tags_str = st.text_input("Tags (comma separated)", placeholder="syrenthia, underwater")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        final_json = {"id": item_id, "wiki_slug": slug, "name": name, "tags": tags}

    # ==========================================
    # 2. MATERIAL
    # ==========================================
    elif entity_type == "Material":
        st.markdown("#### Modifiers")
        modifiers = render_dynamic_list("mat_mod", "Modifier", render_mod, context)
        
        st.markdown("#### Special Sell")
        has_special = st.checkbox("Has Special Sell?")
        sell_id, sell_amt = None, None
        if has_special:
            sell_id = item_selector_ui("Special Sell Target Item", "sp_sell", 0, context)
            sell_amt = st.number_input("Special Sell Amount", min_value=1)

        final_json = {
            "id": item_id, "wiki_slug": slug, "name": name, "value": value, "keywords": keywords,
            "special_sell": {"item_id": sell_id, "amount": sell_amt} if has_special and sell_id else None,
            "modifiers": modifiers
        }

    # ==========================================
    # 3. CONSUMABLE
    # ==========================================
    elif entity_type == "Consumable":
        duration = st.number_input("Duration (steps)", min_value=1, value=1000)
        st.markdown("#### Modifiers")
        modifiers = render_dynamic_list("cons_mod", "Modifier", render_mod, context)
        
        final_json = {
            "id": item_id, "wiki_slug": slug, "name": name, "value": value, "keywords": keywords,
            "duration": duration, "modifiers": modifiers
        }

    # ==========================================
    # 4. EQUIPMENT
    # ==========================================
    elif entity_type == "Equipment":
        c_slot, c_qual = st.columns(2)
        slot = c_slot.selectbox("Slot", [e.value for e in EquipmentSlot])
        qual = c_qual.selectbox("Quality", [e.value for e in EquipmentQuality])
        
        uuid_val = f"item-{item_id}-placeholder-uuid"

        t_req, t_mod = st.tabs(["Requirements", "Modifiers"])
        with t_req: requirements = render_dynamic_list("eq_req", "Requirement", render_req, context)
        with t_mod: modifiers = render_dynamic_list("eq_mod", "Modifier", render_mod, context)

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
        egg_id = c_egg.selectbox("Egg Item ID (Optional)", ["None"] + context["all_item_ids"], index=0)
        if egg_id == "None": egg_id = None
        xp_desc = c_xp.text_input("XP Requirement Desc", placeholder="None")

        st.markdown("#### Pet Levels")
        num_levels = st.number_input("Number of Levels", min_value=1, max_value=6, value=3)
        
        levels_array = []
        tabs = st.tabs([f"Level {i+1}" for i in range(int(num_levels))])
        
        for i, tab in enumerate(tabs):
            with tab:
                lvl_xp = st.number_input(f"Total XP for Level {i+1}", min_value=0, value=50000 * (i+1), key=f"pet_xp_{i}")
                
                st.markdown("**Modifiers**")
                lvl_mods = render_dynamic_list(f"pet_mod_{i}", "Modifier", render_mod, context)
                
                st.markdown("**Abilities**")
                abilities = render_dynamic_list(f"pet_ab_{i}", "Ability", render_pet_ability, context)
                
                levels_array.append({
                    "level": i + 1, "total_xp": lvl_xp, "modifiers": lvl_mods, "abilities": abilities
                })

        final_json = {
            "id": item_id, "wiki_slug": slug, "name": name, "egg_item_id": egg_id,
            "xp_requirement_desc": xp_desc if xp_desc else None, "levels": levels_array, "active_level": 1
        }

    # ==========================================
    # 6. ACTIVITY
    # ==========================================
    elif entity_type == "Activity":
        c_sk, c_loc = st.columns(2)
        skill = c_sk.selectbox("Primary Skill", [e.value for e in SkillName])
        
        # Multiselect for locations!
        act_locations = c_loc.multiselect("Locations", context["loc_ids"], placeholder="Search locations...")

        c_step, c_xp, c_eff = st.columns(3)
        base_steps = c_step.number_input("Base Steps", min_value=1, value=50)
        base_xp = c_xp.number_input("Base XP", min_value=0.0, value=10.0, step=1.0)
        max_eff = c_eff.number_input("Max Efficiency", min_value=0.0, max_value=1.0, value=0.5, step=0.1)

        st.markdown("#### Economy Worth")
        cw1, cw2, cw3 = st.columns(3)
        n_worth = cw1.number_input("Normal Roll Worth", value=1.0, step=0.5)
        c_worth = cw2.number_input("Chest Roll Worth", value=0.5, step=0.5)
        f_worth = cw3.number_input("Fine Roll Worth", value=5.0, step=0.5)

        t_req, t_mod, t_loot, t_sec, t_fac, t_mat = st.tabs([
            "Requirements", "Modifiers", "Loot Tables", "Secondary XP", "Faction Rewards", "Activity Inputs"
        ])
        
        with t_req: requirements = render_dynamic_list("act_req", "Requirement", render_req, context)
        with t_mod: modifiers = render_dynamic_list("act_mod", "Modifier", render_mod, context)
        
        with t_sec: 
            sec_xp_list = render_dynamic_list("act_sec", "Secondary XP", render_sec_xp, context)
            secondary_xp = {k: v for k, v in sec_xp_list} if sec_xp_list else {}
            
        with t_fac:
            faction_rewards = render_dynamic_list("act_fac", "Faction Reward", render_faction, context)

        with t_mat:
            st.caption("Materials required to perform this activity (e.g., Bait for Fishing). Each group represents an 'OR' requirement.")
            act_materials_array = []
            num_act_groups = st.number_input("Number of Material Groups", min_value=0, max_value=5, value=0, key="act_mat_grps")
            for i in range(int(num_act_groups)):
                st.markdown(f"**Group {i+1}**")
                grp = render_dynamic_list(f"act_mat_{i}", "Material", render_recipe_mat, context)
                if grp: act_materials_array.append(grp)
        
        with t_loot:
            loot_tables = []
            lt_types = st.multiselect("Loot Table Types", [e.value for e in ActivityLootTableType], default=["main"])
            for lt_type in lt_types:
                st.markdown(f"**{lt_type.title()} Drops**")
                drops_array = render_dynamic_list(f"act_drops_{lt_type}", "Drop", render_drop, context)
                loot_tables.append({"type": lt_type, "drops": drops_array})

        final_json = {
            "id": item_id, "wiki_slug": slug, "name": name, "primary_skill": skill, "locations": act_locations,
            "base_steps": base_steps, "base_xp": base_xp, "secondary_xp": secondary_xp, "max_efficiency": max_eff,
            "requirements": requirements, "faction_rewards": faction_rewards, "materials": act_materials_array, 
            "loot_tables": loot_tables, "modifiers": modifiers, 
            "normal_roll_worth": n_worth, "chest_roll_worth": c_worth, "fine_roll_worth": f_worth
        }

    # ==========================================
    # 7. RECIPE
    # ==========================================
    elif entity_type == "Recipe":
        c_sk, c_lvl, c_srv = st.columns(3)
        skill = c_sk.selectbox("Skill", [e.value for e in SkillName])
        level = c_lvl.number_input("Level", min_value=1, value=1)
        
        # Service Dropdown
# Generic Service Dropdown (with manual override)
        st.markdown("#### Service Requirement")
        c_srv_man, c_srv_sel = st.columns([1, 3])
        if c_srv_man.checkbox("Manual Service Entry"):
            service = c_srv_sel.text_input("Service", placeholder="e.g. expert_forge")
        else:
            service = c_srv_sel.selectbox("Service", context["recipe_services"], index=None, placeholder="Select service tier/type...")

        c_out, c_qty = st.columns(2)
        output_id = item_selector_ui("Output Item ID", "rec_out", 0, context)
        output_qty = c_qty.number_input("Output Quantity", min_value=1, value=1)

        c_step, c_xp, c_eff = st.columns(3)
        base_steps = c_step.number_input("Base Steps", min_value=1, value=50)
        base_xp = c_xp.number_input("Base XP", min_value=0.0, value=10.0, step=1.0)
        max_eff = c_eff.number_input("Max Efficiency", min_value=0.0, max_value=1.0, value=0.5, step=0.1)

        st.markdown("#### Required Materials")
        st.caption("Each group is an 'AND' requirement. Items inside a group are 'OR' options (e.g., 1 Copper OR 1 Tin).")
        
        materials_array = []
        num_groups = st.number_input("Number of Material Groups", min_value=1, max_value=5, value=1)
        for i in range(int(num_groups)):
            st.markdown(f"**Material Group {i+1}**")
            grp = render_dynamic_list(f"rec_mat_{i}", "Material Option", render_recipe_mat, context)
            if grp: materials_array.append(grp)

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
    
    json_output = json.dumps(final_json, indent=2)
    st.code(json_output, language="json")

    c_dl, c_save = st.columns(2)
    with c_dl:
        st.download_button("💾 Download JSON Entry", data=json_output, file_name=f"{item_id if item_id else 'new_entry'}.json", mime="application/json")
    
    with c_save:
        if st.button("🚀 Save Locally & Send for Review", type="primary", key="save_and_sync_btn"):
            
            with st.spinner("Saving locally and syncing to databases..."):
                # --- 1. Save to Local Storage ---
                custom_entry = {"entity_type": entity_type, "data": final_json}
                if 'custom_entities' not in st.session_state:
                    st.session_state['custom_entities'] = []
                    
                existing_idx = next((i for i, x in enumerate(st.session_state['custom_entities']) if x['data'].get('id') == item_id), None)
                if existing_idx is not None:
                    st.session_state['custom_entities'][existing_idx] = custom_entry
                else:
                    st.session_state['custom_entities'].append(custom_entry)
                    
                import streamlit.components.v1 as components
                js_code = f"""
                <script>
                localStorage.setItem('WALKSCAPE_CUSTOM_DATA', JSON.stringify({json.dumps(st.session_state['custom_entities'])}));
                </script>
                """
                components.html(js_code, height=0)
                
                # --- 2. Save to Private Google Sheet ---
                private_success = False
                private_err_msg = ""
                try:
                    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
                    client = gspread.authorize(creds)
                    
                    sheet = client.open("WalkScape Custom Items").sheet1 
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    sheet.append_row([timestamp, entity_type, item_id, name, json.dumps(final_json)])
                    private_success = True
                except Exception as e:
                    private_err_msg = str(e) # Capture the exact error

                # --- 3. Save to Kozz's Community Sheet ---
                community_success = False
                community_err_msg = ""
                try:
                    kozz_tab_map = {
                        "Equipment": "Gear", "Material": "Inputs", "Consumable": "Consumables",
                        "Pet": "Pets", "Activity": "Activities", "Recipe": "Recipes"
                    }
                    kozz_tab = kozz_tab_map.get(entity_type, entity_type)
                    
                    # Create a deep copy so we don't accidentally modify the JSON going to your private sheet
                    import copy
                    kozz_item = copy.deepcopy(final_json)
                    
                    # Force Kozz-specific fields
                    kozz_item["contributed_by"] = "AutoGearsetApp"
                    kozz_item["is_crafted"] = "0"
                    
                    # Map 'quality' to 'rarity'
                    if "quality" in kozz_item:
                        kozz_item["rarity"] = kozz_item.pop("quality")
                    
                    # Inject _quality into modifiers
                    if entity_type in ["Equipment", "Consumable"] and "modifiers" in kozz_item:
                        qual = kozz_item.get("rarity", "Normal")
                        for mod in kozz_item["modifiers"]:
                            mod["_quality"] = qual

                    kozz_payload = {
                        "action": "kozz_upsert",
                        "tab": kozz_tab,
                        "items": [kozz_item]
                    }
                    
                    kozz_url = "https://script.google.com/macros/s/AKfycbwk8pz9mR0x63PasQQ8jUUSSir3GJ95n1ZwW8IjLALp6idCahVwqg_ttN3bp2YOzMstaQ/exec"
                    res = requests.post(kozz_url, json=kozz_payload, allow_redirects=True)
                    
                    # Check if the HTTP request worked AND if Kozz's script returned success: true
                    if res.status_code == 200:
                        try:
                            resp_json = res.json()
                            if resp_json.get("success"):
                                community_success = True
                            else:
                                community_err_msg = f"Script rejected payload: {resp_json}"
                        except json.JSONDecodeError:
                            community_err_msg = "Google returned 200, but response was not JSON."
                    else:
                        community_err_msg = f"HTTP Error {res.status_code}"
                        
                except Exception as e:
                    community_err_msg = str(e)

            # --- 4. Final UI Feedback (Now with explicit error tracing!) ---
            if private_success and community_success:
                st.success(f"Saved '{name}' locally, backed up to private sheet, and synced to Community DB!")
                time.sleep(1)
            elif private_success:
                st.warning(f"Saved locally & private sheet. Community sync failed:\n{community_err_msg}")
                time.sleep(3) # Give user time to read the error
            elif community_success:
                st.warning(f"Saved locally & Community DB. Private sheet failed:\n{private_err_msg}")
                time.sleep(3)
            else:
                st.error(f"Saved locally ONLY.\nPrivate Error: {private_err_msg}\nCommunity Error: {community_err_msg}")
                time.sleep(4)

            st.rerun()

    st.markdown("---")
    with st.expander("🛠️ Manage Local Custom Entities"):
        if 'custom_entities' in st.session_state and st.session_state['custom_entities']:
            st.write(f"You have **{len(st.session_state['custom_entities'])}** custom entities stored locally.")
            for ce in st.session_state['custom_entities']:
                st.text(f"- {ce['data'].get('name', 'Unknown')} ({ce['entity_type']})")
            
            if st.button("🗑️ Clear All Custom Data"):
                st.session_state['custom_entities'] = []
                import streamlit.components.v1 as components
                components.html("<script>localStorage.removeItem('WALKSCAPE_CUSTOM_DATA');</script>", height=0)
                st.rerun()
        else:
            st.write("No custom entities stored currently.")
  