import itertools
from typing import Dict, List, Set, Optional, Tuple, Counter
from models import Equipment, Activity, GearSet, EquipmentSlot, Location, StatName, EquipmentQuality, RequirementType, ConditionType
from utils.utils import calculate_steps, calculate_quality_probabilities
from enum import Enum
from collections import Counter as PyCounter

# --- Constants & Config ---

RESTRICTED_TOOL_KEYWORDS = {
    "Pickaxe", "Hatchet", "Fishing tool", "Fishing lure", "Foraging tool", "Basket", "Bellows",
    "Bug catching net", "Chisel", "Climbing gear", "Cooking knife", "Cooking pan",
    "Fishing cage", "Fishing net", "Fishing spear", "Gold pan", "Knife",
    "Life vest", "Local map", "Log Splitter", "Magnetic", "Magnifying lens",
    "Ruler", "Sander", "Saw", "Sickle", "Wrench"
}

QUALITY_RANK = {
    EquipmentQuality.NORMAL: 0, EquipmentQuality.GOOD: 1, EquipmentQuality.GREAT: 2,
    EquipmentQuality.EXCELLENT: 3, EquipmentQuality.PERFECT: 4, EquipmentQuality.ETERNAL: 5,
    EquipmentQuality.NONE: -1
}

OPTIMAZATION_TARGET = Enum("OPTIMAZATION_TARGET", ["reward_rolls", "xp", "chests", "materials_from_input", "fine", "quality", "collectibles"])

# Correct Set Union Syntax using |
REWARD_ROLL_STATS = {StatName.DOUBLE_ACTION, StatName.DOUBLE_REWARDS, StatName.WORK_EFFICIENCY, StatName.STEPS_ADD, StatName.STEPS_PERCENT}

TARGET_TO_STATS = {
    OPTIMAZATION_TARGET.reward_rolls: REWARD_ROLL_STATS,
    OPTIMAZATION_TARGET.xp: {StatName.BONUS_XP_ADD, StatName.BONUS_XP_PERCENT, StatName.DOUBLE_ACTION, StatName.WORK_EFFICIENCY, StatName.STEPS_ADD, StatName.STEPS_PERCENT},
    OPTIMAZATION_TARGET.chests: REWARD_ROLL_STATS | {StatName.CHEST_FINDING},
    OPTIMAZATION_TARGET.materials_from_input: {StatName.DOUBLE_REWARDS, StatName.NO_MATERIALS_CONSUMED},
    OPTIMAZATION_TARGET.fine: REWARD_ROLL_STATS | {StatName.FINE_MATERIAL_FINDING},
    OPTIMAZATION_TARGET.quality: {StatName.QUALITY_OUTCOME, StatName.DOUBLE_REWARDS, StatName.NO_MATERIALS_CONSUMED},
    OPTIMAZATION_TARGET.collectibles: REWARD_ROLL_STATS | {StatName.FIND_COLLECTIBLES}
}

# Mapping StatName Enums to the keys output by GearSet.get_stats()
STAT_ENUM_TO_KEY = {
    StatName.STEPS_ADD: "flat_step_reduction",
    StatName.STEPS_PERCENT: "percent_step_reduction",
    StatName.BONUS_XP_ADD: "flat_xp",
    StatName.BONUS_XP_PERCENT: "xp_percent",
    StatName.XP_PERCENT: "xp_percent"
}

class GearOptimizer:
    def __init__(self, all_items: List[Equipment], all_locations: List[Location]):
        self.all_items = all_items
        self.location_map = {loc.id: loc for loc in all_locations}
        self.restricted_keywords_lower = {k.lower() for k in RESTRICTED_TOOL_KEYWORDS}
        
        # Debugging Storage
        self.debug_candidates = {} # {slot: [items]}
        self.debug_rejected = []   # List of dicts {name, reason, slot}

    def optimize(self, activity: Activity, player_level: int, player_skill_level: int, 
                 optimazation_target: OPTIMAZATION_TARGET = OPTIMAZATION_TARGET.reward_rolls,
                 owned_item_counts: Optional[Dict[str, int]] = None,
                 achievement_points: int = 0):
        
        # Reset Debug Info
        self.debug_candidates = {}
        self.debug_rejected = []

        # 1. Determine Slots
        if player_level >= 80: tool_slots = 6
        elif player_level >= 50: tool_slots = 5
        elif player_level >= 20: tool_slots = 4
        else: tool_slots = 3

        # 2. Setup Context
        loc_id = activity.locations[0] if activity.locations else None
        location_tags = set()
        if loc_id and loc_id in self.location_map:
            for t in self.location_map[loc_id].tags:
                location_tags.add(t.lower())
            
        context = {
            "skill": activity.primary_skill,
            "location_id": loc_id,
            "location_tags": location_tags,
            "activity_id": activity.id,
            "required_keywords": {},
            "achievement_points": achievement_points
        }
        
        # 3. Parse Requirements
        required_keywords = {} 
        for req in activity.requirements:
            if req.type == RequirementType.KEYWORD_COUNT and req.target:
                norm_target = req.target.lower().replace("_", " ").strip()
                required_keywords[norm_target] = req.value
        context["required_keywords"] = required_keywords

        # 4. Get Candidates (Strict Filtering)
        candidates = self._get_candidates(activity, required_keywords, optimazation_target, context, player_skill_level, owned_item_counts)
        self.debug_candidates = candidates

        # 5. Generate Skeletons (Requirement Coverage)
        skeletons = self._generate_skeletons(candidates, required_keywords)
        
        best_overall_set = GearSet()
        best_overall_score = -float('inf')

        # 6. Main Optimization Loop
        for skeleton_set, locked_slots in skeletons:
            
            # Start with the skeleton
            current_set = GearSet()
            current_set.head = skeleton_set.head
            current_set.chest = skeleton_set.chest
            current_set.legs = skeleton_set.legs
            current_set.feet = skeleton_set.feet
            current_set.back = skeleton_set.back
            current_set.cape = skeleton_set.cape
            current_set.neck = skeleton_set.neck
            current_set.hands = skeleton_set.hands
            current_set.primary = skeleton_set.primary
            current_set.secondary = skeleton_set.secondary
            current_set.rings = list(skeleton_set.rings)
            current_set.tools = list(skeleton_set.tools) 

            # Optimize Free Slots
            optimized_set = self._optimize_set(
                current_set, 
                locked_slots, 
                candidates, 
                activity, 
                player_skill_level, 
                optimazation_target, 
                context,
                tool_slots,
                owned_item_counts
            )
            
            score = self.calculate_score(optimized_set, activity, player_skill_level, optimazation_target, context)
            
            if score > best_overall_score:
                best_overall_score = score
                best_overall_set = optimized_set

        return best_overall_set

    # --- Core Candidate Logic ---

    def _get_candidates(self, activity: Activity, required_keywords: Dict[str, int], 
                       target: OPTIMAZATION_TARGET, context: Dict, player_skill_level: int,
                       owned_item_counts: Optional[Dict[str, int]] = None) -> Dict[str, List[Equipment]]:
        raw_candidates = {}
        relevant_stats = TARGET_TO_STATS.get(target, set())
        dummy_set = GearSet()

        for item in self.all_items:
            rejection_reason = None
            
            # A. Check Ownership (Pre-filter)
            if owned_item_counts is not None:
                if self._get_available_count(item, owned_item_counts) <= 0:
                    rejection_reason = "Not Owned"
            
            # B. Check Requirements
            provides_requirement = False
            for kw in item.keywords:
                norm = kw.lower().replace("_", " ").strip()
                if norm in required_keywords:
                    provides_requirement = True
                    break
            
            # C. Check Actual Stats Utility
            has_utility = False
            
            # Reset Dummy
            dummy_set.head = None; dummy_set.chest = None; dummy_set.legs = None
            dummy_set.feet = None; dummy_set.neck = None; dummy_set.secondary = None
            dummy_set.back = None; dummy_set.cape = None; dummy_set.hands = None
            dummy_set.primary = None; dummy_set.rings = []; dummy_set.tools = []

            if item.slot == EquipmentSlot.TOOLS: dummy_set.tools = [item]
            elif item.slot == EquipmentSlot.RING: dummy_set.rings = [item]
            else:
                attr_name = item.slot
                if attr_name == "gloves": attr_name = "hands"
                if hasattr(dummy_set, attr_name): setattr(dummy_set, attr_name, item)

            stats = dummy_set.get_stats(context)
            
            for s_enum in relevant_stats:
                s_key = STAT_ENUM_TO_KEY.get(s_enum, s_enum.value)
                val = stats.get(s_key, 0)
                
                if abs(val) > 0.0001:
                    has_utility = True
                    break

            # --- DECISION ---
            if rejection_reason:
                if provides_requirement or has_utility:
                    self.debug_rejected.append({
                        "name": item.name, 
                        "slot": item.slot, 
                        "reason": rejection_reason,
                        "utility": has_utility
                    })
                continue 

            if provides_requirement or has_utility:
                s_key = item.slot 
                if s_key not in raw_candidates: raw_candidates[s_key] = []
                raw_candidates[s_key].append(item)

        final_candidates = {}
        for slot, items in raw_candidates.items():
            best_versions = {}
            for item in items:
                identity = item.wiki_slug if item.wiki_slug else item.name
                
                if item.slot == EquipmentSlot.TOOLS: dummy_set.tools = [item]
                elif item.slot == EquipmentSlot.RING: dummy_set.rings = [item]
                else:
                    attr_name = item.slot
                    if attr_name == "gloves": attr_name = "hands"
                    if hasattr(dummy_set, attr_name): setattr(dummy_set, attr_name, item)
                
                score = self.calculate_score(dummy_set, activity, player_skill_level, target, context, ignore_requirements=True)
                q_rank = QUALITY_RANK.get(item.quality, -1)
                
                dummy_set.tools = []; dummy_set.rings = []
                if item.slot != EquipmentSlot.TOOLS and item.slot != EquipmentSlot.RING:
                     attr_name = item.slot
                     if attr_name == "gloves": attr_name = "hands"
                     if hasattr(dummy_set, attr_name): setattr(dummy_set, attr_name, None)

                if identity not in best_versions:
                    best_versions[identity] = (score, item, q_rank)
                else:
                    curr_score, _, curr_rank = best_versions[identity]
                    if score > curr_score:
                        best_versions[identity] = (score, item, q_rank)
                    elif abs(score - curr_score) < 0.001 and q_rank > curr_rank:
                        best_versions[identity] = (score, item, q_rank)
            
            final_candidates[slot] = [v[1] for v in best_versions.values()]

        return final_candidates

    # --- Skeleton Logic ---

    def _generate_skeletons(self, candidates, required_keywords) -> List[Tuple[GearSet, Set[str]]]:
        if not required_keywords:
            return [(GearSet(), set())]

        providers = {k: [] for k in required_keywords}
        attr_map = {
            EquipmentSlot.HEAD: "head", EquipmentSlot.CHEST: "chest", EquipmentSlot.LEGS: "legs", 
            EquipmentSlot.FEET: "feet", EquipmentSlot.BACK: "back", EquipmentSlot.CAPE: "cape", 
            EquipmentSlot.NECK: "neck", EquipmentSlot.HANDS: "hands", EquipmentSlot.GLOVES: "hands",
            EquipmentSlot.PRIMARY: "primary", EquipmentSlot.SECONDARY: "secondary",
            EquipmentSlot.TOOLS: "tools"
        }

        for slot, items in candidates.items():
            attr_name = attr_map.get(slot)
            if not attr_name: continue
            for item in items:
                for k in item.keywords:
                    norm = k.lower().replace("_", " ").strip()
                    if norm in required_keywords:
                        providers[norm].append((item, attr_name))

        req_list = []
        for k, v in required_keywords.items():
            for _ in range(v):
                req_list.append(k)
        
        results = []
        unique_signatures = set()

        def solve(index, current_map, locked_slots):
            if index >= len(req_list):
                gs = GearSet()
                for attr, val in current_map.items():
                    if attr == "tools":
                        gs.tools = list(val)
                    else:
                        setattr(gs, attr, val)
                all_ids = []
                for i in gs.get_all_items():
                    all_ids.append(i.id)
                sig = tuple(sorted(all_ids))
                if sig not in unique_signatures:
                    unique_signatures.add(sig)
                    results.append((gs, locked_slots.copy()))
                return

            req = req_list[index]
            options = providers.get(req, [])
            found_existing = False
            for item, attr in options:
                if attr == "tools":
                    if item in current_map.get("tools", []):
                        solve(index + 1, current_map, locked_slots)
                        found_existing = True
                        break
                else:
                    if current_map.get(attr) == item:
                        solve(index + 1, current_map, locked_slots)
                        found_existing = True
                        break
            if found_existing: return

            valid_options = options[:20] 
            for item, attr in valid_options:
                if len(results) > 40: return
                if attr == "tools":
                    current_tools = current_map.get("tools", [])
                    if item not in current_tools:
                        new_map = current_map.copy()
                        new_map["tools"] = current_tools + [item]
                        solve(index + 1, new_map, locked_slots)
                else:
                    if attr not in current_map:
                        new_map = current_map.copy()
                        new_map[attr] = item
                        new_locked = locked_slots.copy()
                        new_locked.add(attr)
                        solve(index + 1, new_map, new_locked)

        solve(0, {}, set())
        if not results: return [(GearSet(), set())]
        return results

    # --- Optimizer Logic ---

    def _optimize_set(self, current_set, locked_slots, candidates, activity, player_skill_level, target, context, tool_slots, owned_counts):
        base_score = self.calculate_score(current_set, activity, player_skill_level, target, context)
        
        main_slots = [
            ("head", EquipmentSlot.HEAD), ("chest", EquipmentSlot.CHEST), 
            ("legs", EquipmentSlot.LEGS), ("feet", EquipmentSlot.FEET),
            ("cape", EquipmentSlot.CAPE), ("back", EquipmentSlot.BACK), 
            ("neck", EquipmentSlot.NECK), ("hands", EquipmentSlot.HANDS), 
            ("primary", EquipmentSlot.PRIMARY), ("secondary", EquipmentSlot.SECONDARY)
        ]

        for _ in range(3):
            changed = False
            for attr, slot_enum in main_slots:
                if attr in locked_slots: continue
                best_item = getattr(current_set, attr)
                max_s = base_score
                cands = candidates.get(slot_enum, [])
                if slot_enum == EquipmentSlot.HANDS: cands.extend(candidates.get(EquipmentSlot.GLOVES, []))
                
                # Try None
                setattr(current_set, attr, None)
                score_none = self.calculate_score(current_set, activity, player_skill_level, target, context)
                if score_none > max_s:
                    max_s = score_none
                    best_item = None
                    changed = True

                for item in cands:
                    setattr(current_set, attr, item)
                    score = self.calculate_score(current_set, activity, player_skill_level, target, context)
                    if score > max_s:
                        max_s = score
                        best_item = item
                        changed = True
                setattr(current_set, attr, best_item)
                base_score = max_s
            if not changed: break

        # Rings
        if not current_set.rings: 
            ring_cands = candidates.get(EquipmentSlot.RING, [])
            if ring_cands:
                top_rings = self._sort_items_by_utility(ring_cands, current_set, activity, player_skill_level, target, context)[:10]
                best_rings = []
                max_r = base_score
                for r1, r2 in itertools.combinations_with_replacement(top_rings, 2):
                    if owned_counts:
                        if r1.id == r2.id:
                            if self._get_available_count(r1, owned_counts) < 2: continue
                        else:
                            if self._get_available_count(r1, owned_counts) < 1 or self._get_available_count(r2, owned_counts) < 1: continue

                    current_set.rings = [r1, r2]
                    score = self.calculate_score(current_set, activity, player_skill_level, target, context)
                    if score > max_r:
                        max_r = score
                        best_rings = [r1, r2]
                
                if not best_rings:
                    for r1 in top_rings:
                        if owned_counts and self._get_available_count(r1, owned_counts) < 1: continue
                        current_set.rings = [r1]
                        score = self.calculate_score(current_set, activity, player_skill_level, target, context)
                        if score > max_r:
                            max_r = score
                            best_rings = [r1]
                current_set.rings = best_rings if best_rings else []
                if best_rings: base_score = max_r

        # Tools
        fixed_tools = list(current_set.tools)
        available_slots = tool_slots - len(fixed_tools)
        
        if available_slots > 0:
            tool_cands = candidates.get(EquipmentSlot.TOOLS, [])
            valid_cands = [t for t in tool_cands if t not in fixed_tools]
            sorted_cands = self._sort_items_by_utility(valid_cands, current_set, activity, player_skill_level, target, context)
            
            best_tool_subset = []
            max_t = base_score

            # BRUTE FORCE UP TO 28
            if len(sorted_cands) <= 28:
                for r in range(1, available_slots + 1):
                    for subset in itertools.combinations(sorted_cands, r):
                        test_tools = fixed_tools + list(subset)
                        if self._is_valid_tool_set(test_tools, owned_counts):
                            current_set.tools = test_tools
                            score = self.calculate_score(current_set, activity, player_skill_level, target, context)
                            if score > max_t:
                                max_t = score
                                best_tool_subset = list(subset)
            else:
                current_subset = []
                for t in sorted_cands:
                    if len(current_subset) >= available_slots: break
                    test_tools = fixed_tools + current_subset + [t]
                    if self._is_valid_tool_set(test_tools, owned_counts):
                        current_set.tools = test_tools
                        score = self.calculate_score(current_set, activity, player_skill_level, target, context)
                        if score >= max_t: 
                            max_t = score
                            current_subset.append(t)
                
                remaining = [t for t in sorted_cands if t not in current_subset]
                improved = True
                while improved:
                    improved = False
                    for i in range(len(current_subset)):
                        curr_t = current_subset[i]
                        for rem_t in remaining:
                            new_sub = list(current_subset)
                            new_sub[i] = rem_t
                            test_tools = fixed_tools + new_sub
                            if self._is_valid_tool_set(test_tools, owned_counts):
                                current_set.tools = test_tools
                                score = self.calculate_score(current_set, activity, player_skill_level, target, context)
                                if score > max_t:
                                    max_t = score
                                    current_subset = new_sub
                                    improved = True
                                    break 
                        if improved: break
                best_tool_subset = current_subset

            current_set.tools = fixed_tools + best_tool_subset
            base_score = max_t

        return current_set

    def _get_available_count(self, item: Equipment, owned_counts: Dict[str, int]) -> int:
        if not owned_counts: return 999
        item_id = item.id.lower()
        if item_id in owned_counts: return owned_counts[item_id]
        suffixes = ["_common", "_uncommon", "_rare", "_epic", "_legendary", "_ethereal", "_normal"]
        for s in suffixes:
            if item_id.endswith(s):
                base = item_id.replace(s, "")
                if base in owned_counts: return owned_counts[base]
        return 0

    def calculate_score(self, current_set: GearSet, activity, player_skill_level, target, context, ignore_requirements: bool = False):
        required_keywords = context.get("required_keywords", {})
        deficit = 0
        if not ignore_requirements and required_keywords:
            set_keywords = current_set.get_keyword_counts()
            for req_kw, req_count in required_keywords.items():
                curr_count = set_keywords.get(req_kw, 0)
                if curr_count < req_count: deficit += (req_count - curr_count)
        if deficit > 0: return -10000.0 * deficit

        stats = current_set.get_stats(context)
        steps = calculate_steps(
            activity=activity,
            player_skill_level=player_skill_level, 
            player_work_efficiency=stats.get("work_efficiency", 0),
            player_minus_steps=stats.get("flat_step_reduction", 0),
            player_minus_steps_percent=stats.get("percent_step_reduction", 0)
        )
        steps = max(1, steps)

        da_val = min(1.0, stats.get("double_action", 0))
        dr_val = stats.get("double_rewards", 0) 
        nmc_val = min(0.99, stats.get("no_materials_consumed", 0)) 
        
        da_mult = 1.0 + da_val
        dr_mult = 1.0 + dr_val
        nmc_mult = 1.0 / (1.0 - nmc_val)
        
        val = 0.0
        if target == OPTIMAZATION_TARGET.reward_rolls:
            val = (da_mult * dr_mult) / steps
        elif target == OPTIMAZATION_TARGET.xp:
            base_xp = activity.base_xp or 0
            xp_mult = 1.0 + stats.get("xp_percent", 0)
            flat_xp = stats.get("flat_xp", 0)
            val = ((base_xp * xp_mult + flat_xp) * da_mult) / steps
        elif target == OPTIMAZATION_TARGET.chests:
            val = ((1.0 + stats.get("chest_finding", 0)) * da_mult * dr_mult) / steps
        elif target == OPTIMAZATION_TARGET.materials_from_input:
            val = (dr_mult * nmc_mult)
        elif target == OPTIMAZATION_TARGET.fine:
            val = ((1.0 + stats.get("fine_material_finding", 0)) * da_mult * dr_mult) / steps
        elif target == OPTIMAZATION_TARGET.quality:
            flat_quality_bonus = stats.get("quality_outcome", 0)
            probs = calculate_quality_probabilities(
                activity_min_level=activity.level, 
                player_skill_level=player_skill_level,
                quality_bonus=flat_quality_bonus
            )
            score_q = probs.get("Eternal", 0.0) * 1000 + probs.get("Perfect", 0.0) * 10 + probs.get("Excellent", 0.0)
            val = score_q * dr_mult * nmc_mult
        elif target == OPTIMAZATION_TARGET.collectibles:
            val = ((1.0 + stats.get("find_collectibles", 0)) * da_mult * dr_mult) / steps
        return val
    
    def analyze_score(self, current_set: GearSet, activity, player_skill_level, target, context):
        """
        Returns a dictionary decomposing the score calculation for debugging.
        """
        required_keywords = context.get("required_keywords", {})
        deficit = 0
        if required_keywords:
            set_keywords = current_set.get_keyword_counts()
            for req_kw, req_count in required_keywords.items():
                curr_count = set_keywords.get(req_kw, 0)
                if curr_count < req_count: deficit += (req_count - curr_count)
        
        if deficit > 0:
            return {"error": f"Missing {deficit} Requirements"}

        stats = current_set.get_stats(context)
        steps = calculate_steps(
            activity=activity,
            player_skill_level=player_skill_level, 
            player_work_efficiency=stats.get("work_efficiency", 0),
            player_minus_steps=stats.get("flat_step_reduction", 0),
            player_minus_steps_percent=stats.get("percent_step_reduction", 0)
        )
        steps = max(1, steps)

        da_val = min(1.0, stats.get("double_action", 0))
        dr_val = stats.get("double_rewards", 0) 
        nmc_val = min(0.99, stats.get("no_materials_consumed", 0)) 
        
        da_mult = 1.0 + da_val
        dr_mult = 1.0 + dr_val
        nmc_mult = 1.0 / (1.0 - nmc_val)
        
        numerator = 0.0
        formula_str = ""
        
        if target == OPTIMAZATION_TARGET.fine:
            fine_mod = stats.get("fine_material_finding", 0)
            numerator = (1.0 + fine_mod) * da_mult * dr_mult
            formula_str = f"((1.0 + {fine_mod:.2f}) * {da_mult:.2f} * {dr_mult:.2f}) / {steps}"
        
        elif target == OPTIMAZATION_TARGET.reward_rolls:
            numerator = da_mult * dr_mult
            formula_str = f"({da_mult:.2f} * {dr_mult:.2f}) / {steps}"
            
        elif target == OPTIMAZATION_TARGET.xp:
            base_xp = activity.base_xp or 0
            xp_mult = 1.0 + stats.get("xp_percent", 0)
            flat_xp = stats.get("flat_xp", 0)
            numerator = (base_xp * xp_mult + flat_xp) * da_mult
            formula_str = f"(({base_xp} * {xp_mult:.2f} + {flat_xp}) * {da_mult:.2f}) / {steps}"

        # Add other targets as needed... default fallback
        if not formula_str and numerator == 0:
             val = self.calculate_score(current_set, activity, player_skill_level, target, context)
             numerator = val * steps
             formula_str = f"{numerator:.4f} / {steps}"

        return {
            "numerator": numerator,
            "denominator": steps,
            "score": numerator / steps if steps else 0,
            "formula": formula_str,
            "stats": stats
        }

    def _sort_items_by_utility(self, items, current_set, activity, player_skill_level, target, context):
        scored = []
        dummy_set = GearSet()
        for item in items:
            if item.slot == EquipmentSlot.TOOLS: dummy_set.tools = [item]
            elif item.slot == EquipmentSlot.RING: dummy_set.rings = [item]
            else: pass
            
            score = self.calculate_score(dummy_set, activity, player_skill_level, target, context, ignore_requirements=True)
            scored.append((score, item))
            dummy_set.tools = []
            dummy_set.rings = []
        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored]

    def _is_valid_tool_set(self, tools: List[Equipment], owned_counts: Optional[Dict[str, int]] = None) -> bool:
        seen_slugs = set()
        seen_keywords = set()
        
        if owned_counts:
            proposed_counts = PyCounter()
            for t in tools:
                tid = t.id.lower()
                key_to_use = tid
                if tid not in owned_counts:
                    suffixes = ["_common", "_uncommon", "_rare", "_epic", "_legendary", "_ethereal", "_normal"]
                    for s in suffixes:
                        if tid.endswith(s):
                            base = tid.replace(s, "")
                            if base in owned_counts:
                                key_to_use = base
                                break
                proposed_counts[key_to_use] += 1
            for k, req_amt in proposed_counts.items():
                if owned_counts.get(k, 0) < req_amt:
                    return False

        for t in tools:
            if t.wiki_slug in seen_slugs: return False
            seen_slugs.add(t.wiki_slug)
            for k in t.keywords:
                if k in RESTRICTED_TOOL_KEYWORDS or k.lower() in self.restricted_keywords_lower:
                    norm_k = k.lower()
                    if norm_k in seen_keywords: return False
                    seen_keywords.add(norm_k)
        return True
    
    def _prune_excess_tools(self, tools, limit, activity, lvl, target, context):
        if len(tools) <= limit: return tools
        current = list(tools)
        while len(current) > limit:
            best_sub = current
            max_s = -float('inf')
            for i in range(len(current)):
                sub = current[:i] + current[i+1:]
                dummy = GearSet()
                dummy.tools = sub
                s = self.calculate_score(dummy, activity, lvl, target, context)
                if s > max_s:
                    max_s = s
                    best_sub = sub
            current = best_sub
        return current