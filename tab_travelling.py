import streamlit as st
import time
from collections import defaultdict

from utils.constants import StatName, PERCENTAGE_STATS, OPTIMAZATION_TARGET, SkillName
from calculations import (
    calculate_passive_stats, calculate_score, analyze_score,
    calculate_travelling_xp, calculate_travelling_steps
)
from gear_optimizer import GearOptimizer
from models import Activity, Requirement, RequirementType, GearSet

from ui_utils import (
    TARGET_CATEGORIES, find_category, filter_user_items,
    extract_modifier_stats, calculate_level_from_xp, format_target_metric
)

# Regions in display order
REGION_LABELS = {
    "": "All Regions",
    "jarvonia": "Jarvonia",
    "gdte": "GDTE",
    "syrenthia": "Syrenthia",
    "wallisia": "Wallisia",
    "wrentmark": "Wrentmark",
}

# Travelling-relevant optimization targets
TRAVELLING_TARGETS = {
    "Efficiency": ["Reward Rolls", "Xp"],
    "Drops": ["Chests", "Collectibles", "Tokens Per Step", "Ectoplasm Per Step", "Gems"],
}


def _build_synthetic_activity(route, agility_level):
    """Create a synthetic Activity from a Route for the optimizer."""
    xp = calculate_travelling_xp(route.distance, agility_level)

    # Convert route keyword_counts to Requirement tuples
    requirements = []
    for kw, count in route.keyword_counts.items():
        requirements.append(Requirement(
            type=RequirementType.KEYWORD_COUNT,
            target=kw,
            value=count
        ))

    return Activity(
        id=route.id,
        wiki_slug="",
        name=route.name,
        primary_skill=SkillName.TRAVELING,
        base_steps=route.distance,
        base_xp=xp,
        max_efficiency=999.0,  # No efficiency cap on travelling
        requirements=tuple(requirements),
        locations=(),
        loot_tables=(),
    )


def render_travelling_tab(
    user_state, all_items_raw, routes, locations, all_pets, all_consumables, all_materials
):
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

    if not routes:
        st.warning("No route data available. Run the routes scraper to generate routes.json.")
        return

    loc_map = {loc.id: loc for loc in locations}

    # ── Route Selection ──────────────────────────────────────────────────
    c_region, c_route = st.columns([1, 3])

    with c_region:
        region_options = list(REGION_LABELS.keys())
        selected_region = st.selectbox(
            "Region", region_options,
            format_func=lambda r: REGION_LABELS.get(r, r),
        )

    filtered_routes = routes if not selected_region else [r for r in routes if r.region == selected_region]
    route_map = {r.name: r for r in filtered_routes}

    with c_route:
        selected_route_name = st.selectbox(
            "Route", sorted(route_map.keys()), index=None, placeholder="Select a route..."
        )

    selected_route = route_map.get(selected_route_name) if selected_route_name else None

    # Show route info
    if selected_route:
        info_parts = [f"**Distance:** {selected_route.distance} steps"]
        if selected_route.keyword_counts:
            reqs = ", ".join(f"{v}x {k}" for k, v in selected_route.keyword_counts.items())
            info_parts.append(f"**Gear required:** {reqs}")
        if selected_route.collectible_requirement:
            info_parts.append(f"**Item required:** {selected_route.collectible_requirement}")
        if selected_route.ability_requirement:
            info_parts.append(f"**Ability required:** {selected_route.ability_requirement}")
        st.caption(" | ".join(info_parts))

    # ── Player Config ────────────────────────────────────────────────────
    c_agi, c_pet, c_pet_lvl, c_cons = st.columns([1, 1.5, 0.5, 1.5])

    with c_agi:
        default_agi = 1
        if valid_json:
            agi_xp = user_skills_map.get("agility", 0)
            default_agi = calculate_level_from_xp(agi_xp)
        agility_level = st.number_input("Agility Level", min_value=1, max_value=150, value=default_agi)

    owned_pets = user_state.get("owned_pets", {})

    with c_pet:
        pet_opts = ["None"] + [p.id for p in all_pets]

        def format_pet(pid):
            if pid == "None":
                return "None"
            p_obj = next((x for x in all_pets if x.id == pid), None)
            if not p_obj:
                return pid
            if pid in owned_pets:
                return f"{owned_pets[pid]['name']} ({p_obj.name})"
            return p_obj.name

        selected_pet_id = st.selectbox("Select Pet", pet_opts, format_func=format_pet, key="travel_pet")

    selected_pet = None
    if selected_pet_id != "None":
        selected_pet = next((p for p in all_pets if p.id == selected_pet_id), None)

    with c_pet_lvl:
        if selected_pet:
            max_lvl = max(l.level for l in selected_pet.levels) if selected_pet.levels else 1
            lvls = list(range(1, max_lvl + 1))

            default_lvl = max_lvl
            if selected_pet_id in owned_pets:
                default_lvl = min(owned_pets[selected_pet_id]["level"], max_lvl)

            try:
                default_idx = lvls.index(default_lvl)
            except ValueError:
                default_idx = len(lvls) - 1

            sel_level = st.selectbox("Pet Lvl", lvls, index=default_idx, key="travel_pet_lvl")
            selected_pet = selected_pet.copy(update={"active_level": sel_level})
        else:
            st.selectbox("Pet Lvl", ["-"], disabled=True, key="travel_pet_lvl_disabled")

    with c_cons:
        cons_names = ["None"] + sorted([c.name for c in all_consumables])
        selected_cons_name = st.selectbox("Select Consumable", cons_names, key="travel_cons")

    selected_cons = None
    if selected_cons_name != "None":
        selected_cons = next((c for c in all_consumables if c.name == selected_cons_name), None)

    # ── Optimization Targets ─────────────────────────────────────────────
    if 'travel_targets_list' not in st.session_state:
        st.session_state['travel_targets_list'] = [{"id": 0, "target": "Xp", "weight": 100}]
        st.session_state['travel_next_target_id'] = 1

    st.write("**Optimization Targets**")
    targets_to_remove = []
    for index, item in enumerate(st.session_state['travel_targets_list']):
        current_target_name = item['target']
        current_cat = find_category(current_target_name)
        c_cat, c_target, c_slider, c_btn = st.columns([3, 3, 3, 1])

        with c_cat:
            new_cat = st.selectbox(
                "Category", options=list(TARGET_CATEGORIES.keys()),
                index=list(TARGET_CATEGORIES.keys()).index(current_cat),
                key=f"travel_cat_{item['id']}", label_visibility="collapsed"
            )
            if new_cat != current_cat:
                item['target'] = TARGET_CATEGORIES[new_cat][0]
                st.rerun()
        with c_target:
            available = TARGET_CATEGORIES[new_cat]
            try:
                tidx = available.index(item['target'])
            except ValueError:
                tidx = 0
            new_target = st.selectbox(
                "Target", options=available, index=tidx,
                key=f"travel_tgt_{item['id']}", label_visibility="collapsed"
            )
            item['target'] = new_target
        with c_slider:
            item['weight'] = st.slider(
                "Weight", 1, 100, int(item['weight']), format="%d%%",
                key=f"travel_wt_{item['id']}", label_visibility="collapsed"
            )
        with c_btn:
            if st.button("X", key=f"travel_rem_{item['id']}"):
                targets_to_remove.append(index)

    if targets_to_remove:
        for i in sorted(targets_to_remove, reverse=True):
            del st.session_state['travel_targets_list'][i]
        st.rerun()

    if st.button("+ Add Target", key="travel_add_tgt"):
        new_id = st.session_state.get('travel_next_target_id', 1)
        st.session_state['travel_targets_list'].append({"id": new_id, "target": "Reward Rolls", "weight": 100})
        st.session_state['travel_next_target_id'] = new_id + 1
        st.rerun()

    weighted_targets = []
    for item in st.session_state['travel_targets_list']:
        t_enum = next((t for t in OPTIMAZATION_TARGET if t.name.replace('_', ' ').title() == item["target"]), None)
        if t_enum and item['weight'] > 0:
            weighted_targets.append((t_enum, float(item["weight"])))

    # ── Run Optimization ─────────────────────────────────────────────────
    can_run = selected_route is not None and len(weighted_targets) > 0
    run_opt = st.button("Optimize", type="primary", disabled=not can_run)

    st.divider()

    if use_owned and user_data:
        available_items = filter_user_items(all_items_raw, user_data)
    else:
        available_items = all_items_raw

    if run_opt and selected_route:
        synth_activity = _build_synthetic_activity(selected_route, agility_level)

        # Determine skill level for the optimizer (agility level)
        final_skill_lvl = agility_level
        player_lvl = calculated_char_lvl if valid_json else 99

        req_kw = dict(selected_route.keyword_counts)

        context = {
            "skill": SkillName.TRAVELING.value,
            "location_id": None,
            "location_tags": set(),
            "activity_id": selected_route.id,
            "required_keywords": req_kw,
            "achievement_points": user_ap,
            "total_skill_level": user_total_level,
        }

        # The optimizer's calculate_steps uses a different level-efficiency formula
        # than the wiki's travelling formula. Inject the difference as passive work_efficiency.
        # Wiki travelling: agility_level * 0.005
        # calculate_steps: min(0.25, (skill_level - activity.level) * 0.0125)
        # Since activity.level=1: min(0.25, (agility_level - 1) * 0.0125)
        wiki_agi_eff = agility_level * 0.005
        calc_level_eff = min(0.25, max(0, agility_level - 1) * 0.0125)
        eff_correction = wiki_agi_eff - calc_level_eff
        extra_passive_stats = {}
        if abs(eff_correction) > 0.0001:
            extra_passive_stats["work_efficiency"] = eff_correction

        locked_items_map = st.session_state.get('locked_items_state', {})
        blacklist_set = set(st.session_state.get('blacklist_state', []))

        optimizer = GearOptimizer(available_items, all_locations=locations)

        with st.spinner(f"Optimizing {selected_route.name}..."):
            start_time = time.time()
            best_gear, error_msg, filler_slots = optimizer.optimize(
                synth_activity,
                player_level=player_lvl,
                player_skill_level=final_skill_lvl,
                optimazation_target=weighted_targets,
                owned_item_counts=item_counts if use_owned else None,
                achievement_points=user_ap,
                user_reputation=user_reputation,
                owned_collectibles=owned_collectibles,
                extra_passive_stats=extra_passive_stats,
                context_override=context,
                pet=selected_pet,
                consumable=selected_cons,
                locked_items=locked_items_map,
                blacklisted_ids=blacklist_set,
            )
            elapsed = time.time() - start_time

        if error_msg:
            st.error(error_msg)
        else:
            st.session_state['travel_result'] = {
                'best_gear': best_gear,
                'filler_slots': filler_slots,
                'route': selected_route,
                'agility_level': agility_level,
                'skill_lvl': final_skill_lvl,
                'synth_activity': synth_activity,
                'context': context,
                'elapsed': elapsed,
                'weighted_targets': weighted_targets,
                'norm_context': optimizer.last_normalization_context,
                'owned_collectibles': owned_collectibles,
                'pet': selected_pet,
                'consumable': selected_cons,
            }

    # ── Display Results ──────────────────────────────────────────────────
    if 'travel_result' in st.session_state:
        r = st.session_state['travel_result']
        best_gear = r['best_gear']
        route = r['route']
        agi_lvl = r['agility_level']
        context = r['context']
        synth = r['synth_activity']
        skill_lvl = r['skill_lvl']
        wt = r['weighted_targets']
        nc = r['norm_context']

        passive_stats = calculate_passive_stats(r['owned_collectibles'], context)

        stats = best_gear.get_stats(context)
        for k, v in passive_stats.items():
            stats[k] = stats.get(k, 0.0) + v

        # Calculate travelling-specific metrics
        travel_xp = calculate_travelling_xp(route.distance, agi_lvl)
        total_steps = calculate_travelling_steps(
            route.distance,
            agi_lvl,
            stats.get("work_efficiency", 0),
            stats.get("flat_step_reduction", 0),
            stats.get("percent_step_reduction", 0),
        )
        xp_per_step = travel_xp / total_steps if total_steps > 0 else 0
        actions = 10  # Travelling routes always have exactly 10 actions
        steps_per_action = total_steps / 10

        st.caption(f"Optimized in **{r['elapsed']:.4f}s**")

        # ── Key Metrics ──
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Total Steps", f"{total_steps:,}")
        with m2:
            st.metric("Travelling XP", f"{travel_xp:,.1f}")
        with m3:
            st.metric("XP / Step", f"{xp_per_step:.3f}")
        with m4:
            st.metric("Steps / Action", f"{steps_per_action:,.0f}")

        # ── Stat Badges ──
        da_val = stats.get("double_action", 0)
        dr_val = stats.get("double_rewards", 0)

        badge_data = [
            (StatName.WORK_EFFICIENCY, "WE"),
            (StatName.DOUBLE_ACTION, "DA"),
            (StatName.DOUBLE_REWARDS, "DR"),
            (StatName.STEPS_ADD, "Flat Steps"),
            (StatName.STEPS_PERCENT, "Step %"),
            (StatName.CHEST_FINDING, "CF"),
            (StatName.FIND_COLLECTIBLES, "Collectibles"),
            (StatName.FIND_ADVENTURERS_GUILD_TOKEN, "Tokens"),
            (StatName.FIND_GEMS, "Gems"),
            (StatName.FIND_ECTOPLASM, "Ectoplasm"),
        ]

        badges_html = ""
        for key, label in badge_data:
            is_percent = key in PERCENTAGE_STATS
            val = stats.get(key, 0)
            if abs(val) > 0.001:
                fmt_val = f"{val*100:.1f}%" if is_percent else f"{val:.2f}"
                badges_html += f"""
                <div class="score-badge">
                    <span class="score-badge-label">{label}</span>
                    <span class="score-badge-val">+{fmt_val}</span>
                </div>
                """

        if badges_html:
            st.html(f"""
            <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px;">
                {badges_html}
            </div>
            """)

        # ── Global Drops per Step ──
        da_mult = 1.0 + min(1.0, da_val)
        dr_mult = 1.0 + min(1.0, dr_val)

        drop_rows = []

        # Chest finding
        cf = stats.get("chest_finding", 0)
        if cf > 0:
            chest_rolls_per_action = (1.0 + cf) * da_mult * dr_mult
            steps_per_chest = total_steps / (actions * chest_rolls_per_action) if actions > 0 else 0
            drop_rows.append(("Chest Finding", f"+{cf*100:.1f}%", f"~{steps_per_chest:.0f} steps/chest"))

        # Special find stats
        find_stats = [
            (StatName.FIND_ADVENTURERS_GUILD_TOKEN, "Adventurer's Guild Token"),
            (StatName.FIND_COLLECTIBLES, "Collectibles"),
            (StatName.FIND_GEMS, "Gems"),
            (StatName.FIND_ECTOPLASM, "Ectoplasm"),
            (StatName.FIND_SKILL_CHEST, "Skill Chest"),
            (StatName.FIND_COIN_POUCH, "Coin Pouch"),
            (StatName.FIND_SEA_SHELLS, "Sea Shells"),
            (StatName.FIND_GOLD, "Gold"),
        ]

        for stat_key, label in find_stats:
            val = stats.get(stat_key, 0)
            if val > 0.001:
                # These are flat % chances per action
                chance_per_action = val  # already in decimal from PERCENTAGE_STATS
                if stat_key in PERCENTAGE_STATS:
                    display_chance = f"{val*100:.2f}%/action"
                else:
                    display_chance = f"{val:.2f}/action"
                effective = chance_per_action * da_mult * dr_mult * actions
                drop_rows.append((label, display_chance, f"~{effective:.2f} total"))

        if drop_rows:
            st.write("**Global Drops**")
            for name, chance, total in drop_rows:
                st.caption(f"- **{name}**: {chance} ({total})")

        # ── Passive XP Gains ──
        gain_stats = [
            (StatName.GAIN_AGILITY_XP, "Agility"),
            (StatName.GAIN_TRAVELING_XP, "Traveling"),
            (StatName.GAIN_CARPENTRY_XP, "Carpentry"),
            (StatName.GAIN_COOKING_XP, "Cooking"),
            (StatName.GAIN_CRAFTING_XP, "Crafting"),
            (StatName.GAIN_FISHING_XP, "Fishing"),
            (StatName.GAIN_FORAGING_XP, "Foraging"),
            (StatName.GAIN_MINING_XP, "Mining"),
            (StatName.GAIN_SMITHING_XP, "Smithing"),
            (StatName.GAIN_TRINKETRY_XP, "Trinketry"),
            (StatName.GAIN_WOODCUTTING_XP, "Woodcutting"),
            (StatName.GAIN_HUNTING_XP, "Hunting"),
            (StatName.GAIN_TAILORING_XP, "Tailoring"),
        ]

        passive_xp_rows = []
        for stat_key, label in gain_stats:
            val = stats.get(stat_key, 0)
            if val > 0.001:
                total = val * da_mult * actions
                passive_xp_rows.append((label, f"{val:.2f}/action", f"{total:.1f} total"))

        if passive_xp_rows:
            st.write("**Passive XP Gains**")
            for name, per_action, total in passive_xp_rows:
                st.caption(f"- **{name} XP**: {per_action} ({total})")

        # ── Gear Set Display ──
        st.write("**Optimized Gear Set**")
        _render_gearset(best_gear, r.get('filler_slots', set()))


def _render_gearset(gear_set: GearSet, filler_slots: set):
    """Render the optimized gear set in a compact grid."""
    slot_labels = [
        ("head", "Head"), ("chest", "Chest"), ("legs", "Legs"),
        ("feet", "Feet"), ("back", "Back"), ("cape", "Cape"),
        ("neck", "Neck"), ("hands", "Hands"),
        ("primary", "Primary"), ("secondary", "Secondary"),
    ]

    cols = st.columns(5)
    for i, (slot_attr, label) in enumerate(slot_labels):
        item = getattr(gear_set, slot_attr, None)
        with cols[i % 5]:
            name = item.name if item else "-"
            is_filler = slot_attr in filler_slots
            suffix = " *(filler)*" if is_filler else ""
            st.caption(f"**{label}**\n{name}{suffix}")

    # Rings
    ring_names = [r.name if r else "-" for r in gear_set.rings]
    ring_str = ", ".join(ring_names)
    st.caption(f"**Rings:** {ring_str}")

    # Tools
    tool_names = [t.name for t in gear_set.tools if t]
    if tool_names:
        st.caption(f"**Tools:** {', '.join(tool_names)}")

    # Pet & Consumable
    if gear_set.pet:
        st.caption(f"**Pet:** {gear_set.pet.name} (Lv {gear_set.pet.active_level})")
    if gear_set.consumable:
        st.caption(f"**Consumable:** {gear_set.consumable.name}")
