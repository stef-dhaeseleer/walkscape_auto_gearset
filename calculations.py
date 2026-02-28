import math
from typing import Dict, List, Optional, Any, Set, Tuple, Union
from collections import defaultdict
from models import Activity, GearSet, Collectible, ConditionType, StatName, GATHERING_SKILLS, ARTISAN_SKILLS
from utils.constants import OPTIMAZATION_TARGET, PERCENTAGE_STATS

# ============================================================================
# CORE CALCULATIONS
# ============================================================================

def calculate_steps(
   activity: Activity,
   player_skill_level: int,
   player_work_efficiency: float,
   player_minus_steps: int,
   player_minus_steps_percent: float,
) -> int:
    """
    Calculates steps based on the Wiki Formula.
    """
    level_diff = max(0, player_skill_level - activity.level)
    level_eff = min(0.25, level_diff * 0.0125)

    total_added_eff = level_eff + player_work_efficiency
    effective_eff = min(total_added_eff, activity.max_efficiency)

    efficiency_multiplier = 1.0 + effective_eff
    step_multiplier_factor = 1.0 - player_minus_steps_percent

    base_over_eff = activity.base_steps / efficiency_multiplier
    after_percent = base_over_eff * step_multiplier_factor
    after_flat = after_percent - float(player_minus_steps)
    
    val_floored = max(10.0, after_flat)
    return int(math.ceil(val_floored))

def calculate_quality_probabilities(
    activity_min_level: int,
    player_skill_level: int,
    quality_bonus: float
) -> dict[str, float]:
    """Calculates the probability of each quality tier."""
    level_diff_bonus = max(0, player_skill_level - activity_min_level)
    total_outcome = level_diff_bonus + quality_bonus
    
    band_starts = [0, 100, 200, 300, 400, 500]
    start_weights = [1000.0, 200.0, 50.0, 10.0, 2.5, 0.05]
    min_weights = [4.0, 4.0, 4.0, 4.0, 2.0, 0.05]
    quality_names = ["Normal", "Good", "Great", "Excellent", "Perfect", "Eternal"]
    
    current_weights = []

    for i in range(6):
        tier_mult = i + 1
        band_start = band_starts[i]
        
        if total_outcome > band_start:
            band_end = (100 + activity_min_level) * tier_mult
            denom = band_start - band_end
            slope = 0 if denom == 0 else (start_weights[i] - min_weights[i]) / denom
            calculated_weight = start_weights[i] + (slope * (total_outcome - band_start))
            current_weights.append(max(calculated_weight, min_weights[i]))
        else:
            current_weights.append(start_weights[i])

    for i in range(4, -1, -1):
        if current_weights[i] < current_weights[i+1]:
             current_weights[i] = current_weights[i+1]

    total_weight = sum(current_weights)
    if total_weight == 0: return {k: 0.0 for k in quality_names}
    
    return {quality_names[i]: (w / total_weight) for i, w in enumerate(current_weights)}

# ============================================================================
# SCORING LOGIC
# ============================================================================

def calculate_score(
    gear_set: GearSet, 
    activity: Activity, 
    player_skill_level: int, 
    target: Union[OPTIMAZATION_TARGET, List[Tuple[OPTIMAZATION_TARGET, float]]], 
    context: Dict, 
    ignore_requirements: bool = False, 
    passive_stats: Dict[str, float] = None,
    normalization_context: Dict[OPTIMAZATION_TARGET, Tuple[float, float]] = None
) -> float:
    """
    The Master Score Function.
    Calculates the 'Utility Value' of a gear set based on the optimization target.
    Supports single OPTIMAZATION_TARGET or a list of weighted targets for composite scoring.
    """
    # 1. Check Requirements
    if not ignore_requirements:
        required_keywords = context.get("required_keywords", {})
        if required_keywords:
            set_keywords = gear_set.get_requirement_counts(list(required_keywords.keys()))
            deficit = 0
            for req_kw, req_count in required_keywords.items():
                curr_count = set_keywords.get(req_kw, 0)
                if curr_count < req_count: 
                    deficit += (req_count - curr_count)
            if deficit > 0: 
                return -10000.0 * deficit

    # 2. Get Stats
    stats = gear_set.get_stats(context)
    if passive_stats:
        for k, v in passive_stats.items():
            stats[k] = stats.get(k, 0.0) + v

    # 3. Handle Composite Scoring
    if isinstance(target, list):
        if not normalization_context:
            # Fallback: Treat as sum of raw scores (not recommended due to magnitude mismatch)
            total_score = 0.0
            for sub_target, weight in target:
                raw_score = _calculate_single_target_score(sub_target, activity, player_skill_level, stats,context)
                total_score += raw_score * weight
            return total_score
        
        composite_score = 0.0
        for sub_target, weight in target:
            raw_score = _calculate_single_target_score(sub_target, activity, player_skill_level, stats, context)
            baseline, range_val = normalization_context.get(sub_target, (0.0, 1.0))
            
            # Normalize: (Score - Baseline) / (Max - Baseline)
            # 0% = Baseline, 100% = Max
            if range_val == 0: normalized = 0.0
            else: normalized = (raw_score - baseline) / range_val
            
            composite_score += normalized * weight
            
        return composite_score

    # 4. Handle Single Target Scoring
    else:
        return _calculate_single_target_score(target, activity, player_skill_level, stats, context)

def _calculate_single_target_score(target: OPTIMAZATION_TARGET, activity: Activity, player_skill_level: int, stats: Dict[str, float], context: Dict = None) -> float:
    """Helper to calculate raw score for a single target from stats."""
    if context is None: context = {}
    # Calculate Steps
    steps = calculate_steps(
        activity=activity,
        player_skill_level=player_skill_level, 
        player_work_efficiency=stats.get("work_efficiency", 0),
        player_minus_steps=stats.get("flat_step_reduction", 0),
        player_minus_steps_percent=stats.get("percent_step_reduction", 0)
    )
    steps = max(1, steps)

    # Multipliers
    da_val = min(1.0, stats.get("double_action", 0))
    dr_val = stats.get("double_rewards", 0) 
    nmc_val = min(0.99, stats.get("no_materials_consumed", 0)) 
    
    da_mult = 1.0 + da_val
    dr_mult = 1.0 + dr_val
    nmc_mult = 1.0 / (1.0 - nmc_val)
    
    val = 0.0
    if target == OPTIMAZATION_TARGET.reward_rolls:
        val = (da_mult * dr_mult) / steps
    elif target == OPTIMAZATION_TARGET.reward_rolls_no_steps:
        val = (da_mult * dr_mult)
    elif target == OPTIMAZATION_TARGET.xp:
        base_xp = activity.base_xp or 0
        xp_mult = 1.0 + stats.get("xp_percent", 0)
        flat_xp = stats.get("flat_xp", 0)
        val = ((base_xp * xp_mult + flat_xp) * da_mult) / steps
    elif target == OPTIMAZATION_TARGET.exp_no_steps:
        base_xp = activity.base_xp or 0
        xp_mult = 1.0 + stats.get("xp_percent", 0)
        flat_xp = stats.get("flat_xp", 0)
        val = ((base_xp * xp_mult + flat_xp) * da_mult)
    elif target == OPTIMAZATION_TARGET.chests:
        val = ((1.0 + stats.get("chest_finding", 0)) * da_mult * dr_mult) / steps
    elif target == OPTIMAZATION_TARGET.chests_no_steps:
        val = ((1.0 + stats.get("chest_finding", 0)) * da_mult * dr_mult)
    elif target == OPTIMAZATION_TARGET.materials_from_input:
        val = (dr_mult * nmc_mult)
    elif target == OPTIMAZATION_TARGET.fine:
        val = ((1.0 + stats.get("fine_material_finding", 0)) * da_mult * dr_mult) / steps
    elif target == OPTIMAZATION_TARGET.fine_no_steps:
        val = ((1.0 + stats.get("fine_material_finding", 0)) * da_mult * dr_mult)
    elif target == OPTIMAZATION_TARGET.eternal_per_input:
        flat_quality_bonus = stats.get("quality_outcome", 0)
        probs = calculate_quality_probabilities(
            activity_min_level=activity.level, 
            player_skill_level=player_skill_level,
            quality_bonus=flat_quality_bonus
        )
        score_q = probs.get("Eternal", 0.0)
        val = score_q * dr_mult * nmc_mult
        
    elif target in [OPTIMAZATION_TARGET.good_per_step, OPTIMAZATION_TARGET.great_per_step, 
                    OPTIMAZATION_TARGET.excellent_per_step, OPTIMAZATION_TARGET.perfect_per_step, 
                    OPTIMAZATION_TARGET.eternal_per_step]:
        flat_quality_bonus = stats.get("quality_outcome", 0)
        probs = calculate_quality_probabilities(
            activity_min_level=activity.level, 
            player_skill_level=player_skill_level,
            quality_bonus=flat_quality_bonus
        )
        
        if target == OPTIMAZATION_TARGET.good_per_step:
            score_q = probs.get("Good", 0.0)
        elif target == OPTIMAZATION_TARGET.great_per_step:
            score_q = probs.get("Great", 0.0)
        elif target == OPTIMAZATION_TARGET.excellent_per_step:
            score_q = probs.get("Excellent", 0.0)
        elif target == OPTIMAZATION_TARGET.perfect_per_step:
            score_q = probs.get("Perfect", 0.0)
        elif target == OPTIMAZATION_TARGET.eternal_per_step:
            score_q = probs.get("Eternal", 0.0)
            
        val = (score_q * da_mult * dr_mult) / steps

    elif target == OPTIMAZATION_TARGET.tokens_per_step:
        chance = stats.get("find_adventurers_guild_token", 0) / 100.0
        val = (chance * da_mult * dr_mult) / steps
    elif target == OPTIMAZATION_TARGET.ectoplasm_per_step:
        chance = stats.get("find_ectoplasm", 0) / 100.0
        val = (chance * da_mult * dr_mult) / steps
    elif target == OPTIMAZATION_TARGET.gems:
        val = ((1.0 + stats.get("find_gems", 0)) * da_mult * dr_mult) / steps

    elif target == OPTIMAZATION_TARGET.collectibles:
        val = ((1.0 + stats.get("find_collectibles", 0)) * da_mult * dr_mult) / steps
 

    elif target in [OPTIMAZATION_TARGET.coins, OPTIMAZATION_TARGET.coins_no_chests, 
                    OPTIMAZATION_TARGET.coins_no_fines, OPTIMAZATION_TARGET.coins_no_chests_no_fines]:
        
        base_normal = getattr(activity, 'normal_roll_worth', 0.0)
        base_chest = getattr(activity, 'chest_roll_worth', 0.0)
        base_fine = getattr(activity, 'fine_roll_worth', 0.0)
        
        allow_chests = target in [OPTIMAZATION_TARGET.coins, OPTIMAZATION_TARGET.coins_no_fines]
        allow_fines = target in [OPTIMAZATION_TARGET.coins, OPTIMAZATION_TARGET.coins_no_chests]
        
        fine_bonus = stats.get("fine_material_finding", 0.0)
        chest_bonus = stats.get("chest_finding", 0.0)

        if allow_fines:
            fine_conversion_rate = min(1.0, 0.01 * (1.0 + fine_bonus))
            ev_normal = base_normal * (1.0 - fine_conversion_rate)
            ev_fine = base_fine * fine_conversion_rate
        else:
            fine_conversion_rate = 0.0
            ev_normal = base_normal
            ev_fine = 0.0
            
        ev_chest = (base_chest * (1.0 + chest_bonus)) if allow_chests else 0.0
            
        ev_special = 0.0
        special_ev_map = context.get("special_ev_map", {})
        
        for stat_key, ev_data in special_ev_map.items():
            chance = stats.get(stat_key, 0.0) / 100.0
            if chance <= 0: continue
            
            is_chest = stat_key in ["chance_to_find_bird_nest", "find_coin_pouch", "find_skill_chest"]
            if is_chest and not allow_chests:
                continue
                
            if allow_fines and not is_chest:
                ev_special += chance * (ev_data["normal"] * (1.0 - fine_conversion_rate) + ev_data["fine"] * fine_conversion_rate)
            else:
                ev_special += chance * ev_data["normal"]
        
        # Total EV per activity roll
        total_ev_per_roll = ev_normal + ev_fine + ev_chest + ev_special        
        total_ev_per_roll = ev_normal + ev_fine + ev_chest + ev_special
        
        val = (total_ev_per_roll * da_mult * dr_mult) / steps
    
    return val

def analyze_score(gear_set: GearSet, activity, player_skill_level, target, context, passive_stats: Dict[str, float] = None, normalization_context=None):
    """Debug helper to explain the score."""
    val = calculate_score(gear_set, activity, player_skill_level, target, context, passive_stats=passive_stats, normalization_context=normalization_context)
    stats = gear_set.get_stats(context)
    if passive_stats:
        for k,v in passive_stats.items(): stats[k] = stats.get(k, 0.0) + v
    
    steps = calculate_steps(
        activity=activity,
        player_skill_level=player_skill_level, 
        player_work_efficiency=stats.get("work_efficiency", 0),
        player_minus_steps=stats.get("flat_step_reduction", 0),
        player_minus_steps_percent=stats.get("percent_step_reduction", 0)
    )
    
    target_breakdown = []
    
    if isinstance(target, list) and normalization_context:
        for sub_target, weight in target:
            raw_score = _calculate_single_target_score(sub_target, activity, player_skill_level, stats, context)
            baseline, range_val = normalization_context.get(sub_target, (0.0, 1.0))
            
            # Normalize
            if range_val == 0: normalized = 0.0
            else: normalized = (raw_score - baseline) / range_val
            
            contribution = normalized * weight
            
            target_breakdown.append({
                "target": sub_target.name.replace("_", " ").title(),
                "weight": weight,
                "raw_value": raw_score,
                "baseline": baseline,
                "max_val": baseline + range_val,
                "normalized": normalized,
                "contribution": contribution
            })
    
    return {
        "score": val,
        "steps": steps,
        "stats": stats,
        "target_breakdown": target_breakdown
    }

def calculate_passive_stats(collectibles: List[Collectible], context: Dict) -> Dict[str, float]:
    """
    Calculates stats from collected items (Passive).
    """
    stats = defaultdict(float)
    active_skill = context.get("skill", "").lower() if context.get("skill") else None
    loc_id = context.get("location_id")
    loc_tags = context.get("location_tags", set())
    act_id = context.get("activity_id")
    user_ap = context.get("achievement_points", 0)
    total_lvl = context.get("total_skill_level", 0)

    for item in collectibles:
        for mod in item.modifiers:
            applies = True
            for condition in mod.conditions:
                c_type = condition.type
                c_target = condition.target.lower() if condition.target else None
                c_val = condition.value
                if c_type == ConditionType.GLOBAL: continue 
                elif c_type == ConditionType.SKILL_ACTIVITY:
                    if not active_skill: applies = False 
                    elif c_target:
                        if c_target == active_skill: pass
                        elif c_target == "gathering" and active_skill in GATHERING_SKILLS: pass
                        elif c_target == "artisan" and active_skill in ARTISAN_SKILLS: pass
                        else: applies = False
                elif c_type == ConditionType.LOCATION:
                    if not loc_id: applies = False
                    else:
                        if not (c_target == loc_id.lower() or c_target in loc_tags): applies = False
                elif c_type == ConditionType.REGION:
                    if not loc_tags: applies = False
                    elif c_target and c_target not in loc_tags: applies = False
                elif c_type == ConditionType.SPECIFIC_ACTIVITY:
                    if not act_id: applies = False
                    elif c_target and c_target != act_id.lower(): applies = False
                elif c_type == ConditionType.ACHIEVEMENT_POINTS:
                    if user_ap < (c_val or 0): applies = False
                elif c_type == ConditionType.TOTAL_SKILL_LEVEL:
                    if total_lvl < (c_val or 0): applies = False
            
            if applies:
                stat_key = mod.stat.value
                value = mod.value
                if mod.stat in PERCENTAGE_STATS: value = value / 100.0
                if stat_key == StatName.BONUS_XP_ADD.value: stat_key = "flat_xp"
                elif stat_key == StatName.BONUS_XP_PERCENT.value: stat_key = "xp_percent"
                elif stat_key == StatName.XP_PERCENT.value: stat_key = "xp_percent"
                elif stat_key == StatName.STEPS_ADD.value: 
                    stat_key = "flat_step_reduction"
                    value = -value 
                elif stat_key == StatName.STEPS_PERCENT.value: 
                    stat_key = "percent_step_reduction"
                    value = -value
                stats[stat_key] += value
    return dict(stats)