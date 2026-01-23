import math
from models import Activity

def calculate_steps(
   activity: Activity,
   player_skill_level: int,
   player_work_efficiency: float,
   player_minus_steps: int,
   player_minus_steps_percent: float,
) -> int:
    """
    Calculates steps based on the Wiki Formula:
    Steps = ceiling(max(((Base Steps / Work Eff) * % Steps Req Mod) - Flat Steps Req Mod, 10))
    """
    
    # 1. Efficiency Calculation
    level_diff = max(0, player_skill_level - activity.level)
    level_eff = min(0.25, level_diff * 0.0125)

    total_added_eff = level_eff + player_work_efficiency
    effective_eff = min(total_added_eff, activity.max_efficiency)

    efficiency_multiplier = 1.0 + effective_eff
    
    # 2. Step Multipliers
    # Wiki: "(100% base - X% steps required)" -> passed as 0.05 for -5%
    step_multiplier_factor = 1.0 - player_minus_steps_percent

    # 3. Core Calculation (Strict Order)
    # A. Base / Efficiency
    base_over_eff = activity.base_steps / efficiency_multiplier
    
    # B. Apply Percent Modifier
    after_percent = base_over_eff * step_multiplier_factor
    
    # C. Apply Flat Modifier 
    # Note: player_minus_steps is positive here (e.g., 2), representing a reduction.
    # Wiki formula adds the modifier (which is negative). Equivalent to subtracting the positive magnitude.
    after_flat = after_percent - float(player_minus_steps)
    
    # D. Global Minimum of 10
    val_floored = max(10.0, after_flat)
    
    # E. Ceiling
    steps = math.ceil(val_floored)

    return int(steps)

def calculate_quality_probabilities(
    activity_min_level: int,
    player_skill_level: int,
    quality_bonus: float
) -> dict[str, float]:
    """
    Calculates the probability of each quality tier.
    """
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

    # Backwards check: lower quality weight cannot be lower than higher quality weight
    for i in range(4, -1, -1):
        if current_weights[i] < current_weights[i+1]:
             current_weights[i] = current_weights[i+1]

    total_weight = sum(current_weights)
    if total_weight == 0: return {k: 0.0 for k in quality_names}
    
    return {
        quality_names[i]: (w / total_weight)
        for i, w in enumerate(current_weights)
    }