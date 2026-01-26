import itertools
import math
from typing import Dict, List, Set, Optional, Tuple, Counter
from models import Equipment, Activity, GearSet, EquipmentSlot, Location, StatName, EquipmentQuality, RequirementType, ConditionType, Collectible, GATHERING_SKILLS, ARTISAN_SKILLS
from utils.utils import calculate_steps, calculate_quality_probabilities
from enum import Enum
from collections import Counter as PyCounter, defaultdict

# --- Constants & Config ---
RESTRICTED_TOOL_KEYWORDS = {
    "Pickaxe", "Hatchet", "Fishing tool", "Fishing lure", "Foraging tool", "Basket", "Bellows",
    "Bug catching net", "Chisel", "Climbing gear", "Cooking knife", "Cooking pan",
    "Fishing cage", "Fishing net", "Fishing spear", "Gold pan", "Knife",
    "Life vest", "Local map", "Log Splitter", "Magnetic", "Magnifying lens",
    "Ruler", "Sander", "Saw", "Sickle", "Wrench", "Smithing hammer"
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

PERCENTAGE_STATS = {
    StatName.WORK_EFFICIENCY, StatName.DOUBLE_ACTION, StatName.DOUBLE_REWARDS,
    StatName.NO_MATERIALS_CONSUMED, StatName.STEPS_PERCENT, StatName.XP_PERCENT,
    StatName.BONUS_XP_PERCENT, StatName.CHEST_FINDING, StatName.FINE_MATERIAL_FINDING,
    StatName.FIND_BIRD_NESTS, StatName.FIND_COLLECTIBLES, StatName.FIND_GEMS,
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
                 achievement_points: int = 0,
                 owned_collectibles: Optional[List[Collectible]] = None,
                 extra_passive_stats: Optional[Dict[str, float]] = None,
                 context_override: Optional[Dict] = None):
        
        # Reset Debug Info
        self.debug_candidates = {}
        self.debug_rejected = []

        # 1. Determine Slots
        if player_level >= 80: tool_slots = 6
        elif player_level >= 50: tool_slots = 5
        elif player_level >= 20: tool_slots = 4
        else: tool_slots = 3

        # 2. Setup Context
        if context_override:
            context = context_override
        else:
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
                "achievement_points": achievement_points,
                "total_skill_level": 0 
            }
            
            # 3. Parse Requirements
            required_keywords = {} 
            for req in activity.requirements:
                if req.type == RequirementType.KEYWORD_COUNT and req.target:
                    norm_target = req.target.lower().replace("_", " ").strip()
                    required_keywords[norm_target] = req.value
            context["required_keywords"] = required_keywords

        # 4. Calculate Passive Stats
        passive_stats = self._calculate_passive_stats(owned_collectibles or [], context)
        if extra_passive_stats:
            for k, v in extra_passive_stats.items():
                passive_stats[k] = passive_stats.get(k, 0.0) + v

        # 5. Get Candidates
        required_keywords = context.get("required_keywords", {})
        candidates = self._get_candidates(activity, required_keywords, optimazation_target, context, player_skill_level, owned_item_counts)
        self.debug_candidates = candidates

        # 6. Generate Skeletons
        # We now generate simpler skeletons because the post-optimizer will fix bad choices
        skeletons = self._generate_skeletons(candidates, required_keywords)
        
        best_overall_set = GearSet()
        best_overall_score = -float('inf')

        # 7. Main Optimization Loop
        # We iterate skeletons to get decent starting points (e.g. 1 Light from Head, 1 from Chest vs 2 from Rings)
        for skeleton_set, locked_slots in skeletons:
            
            # Start with the skeleton
            current_set = GearSet()
            # Copy attributes manually to avoid reference issues
            for slot in ["head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary"]:
                setattr(current_set, slot, getattr(skeleton_set, slot))
            current_set.rings = list(skeleton_set.rings)
            current_set.tools = list(skeleton_set.tools)

            # A. Standard Optimization (Fills empty slots)
            optimized_set = self._optimize_set(
                current_set, 
                locked_slots, 
                candidates, 
                activity, 
                player_skill_level, 
                optimazation_target, 
                context,
                tool_slots,
                owned_item_counts,
                passive_stats
            )
            
            # B. Requirement Swapping (The Fix for Candlehat vs Sun Stone Ring)
            # This attempts to move requirements to different slots to maximize global score
            final_set = self._optimize_requirements(
                optimized_set,
                candidates,
                required_keywords,
                activity,
                player_skill_level,
                optimazation_target,
                context,
                tool_slots,
                owned_item_counts,
                passive_stats
            )
            
            score = self.calculate_score(final_set, activity, player_skill_level, optimazation_target, context, passive_stats=passive_stats)
            
            if score > best_overall_score:
                best_overall_score = score
                best_overall_set = final_set

        return best_overall_set

    # --- New Logic: Requirement Swapper ---

    def _optimize_requirements(self, current_set: GearSet, candidates: Dict[str, List[Equipment]], 
                               required_keywords: Dict[str, int], activity, lvl, target, context, 
                               tool_slots, owned_counts, passive_stats) -> GearSet:
        """
        Iteratively tries to satisfy requirements using different items to see if the overall score improves.
        Example: Swaps a 'Candlehat' (Head) for a 'Sun Stone Ring' (Ring), then fills the Head slot with best-in-slot.
        """
        if not required_keywords:
            return current_set

        # We do a few passes to allow complex shuffles (e.g. Ring -> Tool -> Head)
        # But usually 1-2 passes is enough.
        best_local_set = current_set
        best_local_score = self.calculate_score(current_set, activity, lvl, target, context, passive_stats=passive_stats)
        
        # Flatten candidates for easy searching
        # We only care about items that provide ANY required keyword
        provider_pool = []
        for slot, items in candidates.items():
            for item in items:
                provides_req = False
                for k in item.keywords:
                    if k.lower().replace("_", " ").strip() in required_keywords:
                        provides_req = True
                        break
                if provides_req:
                    provider_pool.append(item)
        
        # Sort pool by raw utility (heuristic) so we try powerful items first (Gem Shield!)
        provider_pool = self._sort_items_by_utility(provider_pool, best_local_set, activity, lvl, target, context, passive_stats)
        # Limit the pool to prevent slowdowns, but keep it generous (e.g., top 60 providers across all slots)
        provider_pool = provider_pool[:60]

        # Get 'Best in Slot' items (Pure utility, ignoring requirements) to use as backfill
        best_fillers = {}
        for slot_key in ["head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary", "ring", "tools"]:
            cands = candidates.get(EquipmentSlot(slot_key) if slot_key not in ["ring", "tools"] else (EquipmentSlot.RING if slot_key=="ring" else EquipmentSlot.TOOLS), [])
            sorted_cands = self._sort_items_by_utility(cands, best_local_set, activity, lvl, target, context, passive_stats)
            best_fillers[slot_key] = sorted_cands[:3] # Keep top 3 to handle unique restrictions

        # Try to swap requirement providers
        # We identify which items currently provide requirements
        current_providers = []
        current_items = best_local_set.get_all_items()
        
        for item in current_items:
            for k in item.keywords:
                norm_k = k.lower().replace("_", " ").strip()
                if norm_k in required_keywords:
                    current_providers.append(item)
                    break # Counted this item as a provider
        
        # Try replacing each provider with a different item from the pool
        # This is a greedy hill-climb
        
        improved = True
        iterations = 0
        while improved and iterations < 3:
            improved = False
            iterations += 1
            
            # Re-identify providers in the CURRENT best set
            active_providers = []
            for item in best_local_set.get_all_items():
                is_prov = False
                for k in item.keywords:
                    if k.lower().replace("_", " ").strip() in required_keywords:
                        is_prov = True; break
                if is_prov: active_providers.append(item)

            for provider_to_remove in active_providers:
                # Try replacing this specific item with something else from the pool
                # that fulfills at least ONE of the requirements this item was fulfilling.
                
                relevant_reqs = {k.lower().replace("_", " ").strip() for k in provider_to_remove.keywords if k.lower().replace("_", " ").strip() in required_keywords}
                
                for candidate in provider_pool:
                    # Skip if same item
                    if candidate.id == provider_to_remove.id: continue
                    
                    # Skip if candidate is already equipped
                    if candidate in best_local_set.get_all_items(): continue
                    
                    # Does this candidate provide a relevant requirement?
                    cand_reqs = {k.lower().replace("_", " ").strip() for k in candidate.keywords}
                    if not relevant_reqs.intersection(cand_reqs): continue

                    # Ownership check (lazy)
                    if owned_counts:
                        needed = 1
                        if candidate in best_local_set.get_all_items(): needed += 1
                        if self._get_available_count(candidate, owned_counts) < needed: continue

                    # --- SIMULATE SWAP ---
                    test_set = self._clone_set(best_local_set)
                    
                    # 1. Remove the old provider
                    self._unequip_item(test_set, provider_to_remove)
                    
                    # 2. Equip the new provider (Candidate)
                    if not self._equip_item(test_set, candidate, tool_slots):
                        continue # Couldn't equip (e.g. slots full even after removal? shouldn't happen for tools/rings usually)

                    # 3. Backfill the slot we just emptied (if applicable)
                    # If we removed Candlehat (Head) and added Sun Stone (Ring), Head is now empty. Fill it!
                    empty_slots = self._get_empty_slots(test_set, tool_slots)
                    for e_slot in empty_slots:
                        # Find best filler
                        fillers = best_fillers.get(e_slot if "tool" not in e_slot and "ring" not in e_slot else ("tools" if "tool" in e_slot else "ring"), [])
                        for filler in fillers:
                            # Ownership check
                            if owned_counts and self._get_available_count(filler, owned_counts) < 1: continue
                            # Don't equip if already equipped (unless duplicate allowed/owned)
                            if filler in test_set.get_all_items():
                                 if owned_counts and self._get_available_count(filler, owned_counts) < 2: continue
                                 elif not owned_counts: pass # allow duplicate logic if unbounded? usually standard unique constraint applies unless rings/tools
                                 else: continue
                            
                            if self._equip_item(test_set, filler, tool_slots):
                                break # Filled the slot

                    # 4. Score
                    new_score = self.calculate_score(test_set, activity, lvl, target, context, passive_stats=passive_stats)
                    
                    if new_score > best_local_score + 0.0001: # Epsilon for floating point
                        best_local_score = new_score
                        best_local_set = test_set
                        improved = True
                        break # Restart outer loop with new state
                
                if improved: break 

        return best_local_set

    def _clone_set(self, gs: GearSet) -> GearSet:
        new_set = GearSet()
        for slot in ["head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary"]:
            setattr(new_set, slot, getattr(gs, slot))
        new_set.rings = list(gs.rings)
        new_set.tools = list(gs.tools)
        return new_set

    def _unequip_item(self, gs: GearSet, item: Equipment):
        if item in gs.rings:
            gs.rings.remove(item)
        elif item in gs.tools:
            gs.tools.remove(item)
        else:
            for slot in ["head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary"]:
                if getattr(gs, slot) and getattr(gs, slot).id == item.id:
                    setattr(gs, slot, None)
                    break
    def _violates_restricted_keywords(self, gs: GearSet, new_item: Equipment) -> bool:
        """Checks if equipping new_item would violate unique keyword restrictions (e.g. 2 Pickaxes)."""
        # 1. Identify if the new item has any restricted keywords
        item_restricted_kws = set()
        for k in new_item.keywords:
            lk = k.lower()
            if lk in self.restricted_keywords_lower:
                item_restricted_kws.add(lk)
        
        if not item_restricted_kws:
            return False

        # 2. Check if any currently equipped item shares a restricted keyword
        # Note: We check ALL items, though restrictions are usually just on Tools.
        for existing in gs.get_all_items():
            for k in existing.keywords:
                if k.lower() in item_restricted_kws:
                    return True
        return False

    def _equip_item(self, gs: GearSet, item: Equipment, max_tools: int) -> bool:
        """Attempts to equip item into appropriate slot. Returns True if successful."""
        
        # Validation: Check for Restricted Keywords (e.g. Pickaxe, Hatchet uniqueness)
        if self._violates_restricted_keywords(gs, item):
            return False

        if item.slot == EquipmentSlot.TOOLS:
            if len(gs.tools) < max_tools:
                gs.tools.append(item)
                return True
            return False
        elif item.slot == EquipmentSlot.RING:
            if len(gs.rings) < 2:
                gs.rings.append(item)
                return True
            return False
        else:
            attr = item.slot
            if hasattr(gs, attr):
                if getattr(gs, attr) is None:
                    setattr(gs, attr, item)
                    return True
            return False          
    def _get_empty_slots(self, gs: GearSet, max_tools: int) -> List[str]:
        empty = []
        for slot in ["head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary"]:
            if getattr(gs, slot) is None: empty.append(slot)
        if len(gs.rings) < 2: empty.append("ring")
        if len(gs.rings) < 1: empty.append("ring")
        if len(gs.tools) < max_tools:
             for _ in range(max_tools - len(gs.tools)):
                 empty.append("tools")
        return empty

    # --- Collectible Logic ---
    
    def _calculate_passive_stats(self, collectibles: List[Collectible], context: Dict) -> Dict[str, float]:
        """Calculates stats from permanent sources like collectibles."""
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
                    
                    if c_type == ConditionType.GLOBAL:
                        continue 

                    elif c_type == ConditionType.SKILL_ACTIVITY:
                        if not active_skill: 
                            applies = False 
                        elif c_target:
                            if c_target == active_skill: pass
                            elif c_target == "gathering" and active_skill in GATHERING_SKILLS: pass
                            elif c_target == "artisan" and active_skill in ARTISAN_SKILLS: pass
                            else: applies = False

                    elif c_type == ConditionType.LOCATION:
                        if not loc_id: applies = False
                        else:
                            is_id_match = (c_target == loc_id.lower())
                            is_tag_match = (c_target in loc_tags)
                            if not (is_id_match or is_tag_match):
                                applies = False
                            
                    elif c_type == ConditionType.REGION:
                        if not loc_tags: applies = False
                        elif c_target and c_target not in loc_tags:
                            applies = False

                    elif c_type == ConditionType.SPECIFIC_ACTIVITY:
                        if not act_id: applies = False
                        elif c_target and c_target != act_id.lower():
                            applies = False
                    
                    elif c_type == ConditionType.ACHIEVEMENT_POINTS:
                        if user_ap < (c_val or 0): applies = False
                    
                    elif c_type == ConditionType.TOTAL_SKILL_LEVEL:
                        if total_lvl < (c_val or 0): applies = False
                
                if applies:
                    stat_enum = mod.stat
                    stat_key = stat_enum.value
                    value = mod.value

                    if stat_enum in PERCENTAGE_STATS:
                        value = value / 100.0

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

    # --- Core Candidate Logic ---

    def _get_candidates(self, activity: Activity, required_keywords: Dict[str, int], 
                       target: OPTIMAZATION_TARGET, context: Dict, player_skill_level: int,
                       owned_item_counts: Optional[Dict[str, int]] = None) -> Dict[str, List[Equipment]]:
        raw_candidates = {}
        relevant_stats = TARGET_TO_STATS.get(target, set())
        dummy_set = GearSet()

        # Phase 1: Rough filtering (Ownership, Requirements, Utility Check)
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

            # IMPORTANT: We keep items that EITHER provide a requirement OR have utility
            if provides_requirement or has_utility:
                s_key = item.slot 
                if s_key not in raw_candidates: raw_candidates[s_key] = []
                raw_candidates[s_key].append(item)

        # Phase 2: Refined filtering (Best Versions per Slot)
        final_candidates = {}
        for slot, items in raw_candidates.items():
            # Dictionary mapping Identity -> List of (Score, QualityRank, Item)
            # We use a list to keep multiple variations if needed (specifically for Rings)
            grouped_candidates = defaultdict(list)

            for item in items:
                identity = item.wiki_slug if item.wiki_slug else item.name
                
                # Equip to dummy set to calculate score
                if item.slot == EquipmentSlot.TOOLS: dummy_set.tools = [item]
                elif item.slot == EquipmentSlot.RING: dummy_set.rings = [item]
                else:
                    attr_name = item.slot
                    if hasattr(dummy_set, attr_name): setattr(dummy_set, attr_name, item)
                
                # Note: We do NOT pass passive_stats here to keep candidate selection pure to the item's own merit
                score = self.calculate_score(dummy_set, activity, player_skill_level, target, context, ignore_requirements=True)
                q_rank = QUALITY_RANK.get(item.quality, -1)
                
                # Un-equip
                dummy_set.tools = []; dummy_set.rings = []
                if item.slot != EquipmentSlot.TOOLS and item.slot != EquipmentSlot.RING:
                     attr_name = item.slot
                     if hasattr(dummy_set, attr_name): setattr(dummy_set, attr_name, None)

                # Store candidate info
                grouped_candidates[identity].append((score, q_rank, item))
            
            # Select best versions
            slot_candidates = []
            
            # For Rings, we keep the top 2 best versions of the same item (e.g. Perfect Ruby Ring AND Excellent Ruby Ring)
            keep_count = 2 if slot == EquipmentSlot.RING else 1

            for identity, entries in grouped_candidates.items():
                # Sort by Score (Desc), then Quality (Desc)
                entries.sort(key=lambda x: (x[0], x[1]), reverse=True)
                
                # We ALWAYS keep the highest score version
                best_entries = entries[:keep_count]
                for _, _, itm in best_entries:
                    slot_candidates.append(itm)
                
                # ALSO: If this item provides a requirement, ensure we keep at least one valid copy 
                # even if it was pruned (though unlikely given sorting by score).
                # Actually, filtering by Best Score is safe because higher score usually implies better stats.
                # However, if an item has variants, the best score variant is the one we want anyway.

            final_candidates[slot] = slot_candidates

        return final_candidates

    # --- Skeleton Logic ---

    def _generate_skeletons(self, candidates, required_keywords) -> List[Tuple[GearSet, Set[str]]]:
        if not required_keywords:
            return [(GearSet(), set())]

        providers = {k: [] for k in required_keywords}
        attr_map = {
            EquipmentSlot.HEAD: "head", EquipmentSlot.CHEST: "chest", EquipmentSlot.LEGS: "legs", 
            EquipmentSlot.FEET: "feet", EquipmentSlot.BACK: "back", EquipmentSlot.CAPE: "cape", 
            EquipmentSlot.NECK: "neck", EquipmentSlot.HANDS: "hands",
            EquipmentSlot.PRIMARY: "primary", EquipmentSlot.SECONDARY: "secondary",
            EquipmentSlot.TOOLS: "tools", EquipmentSlot.RING: "rings"
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
                    elif attr == "rings":
                        gs.rings = list(val)
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
            
            # Check if already satisfied by current selection (e.g. multi-keyword item)
            # This is complex so we just check if we can skip adding new item
            # For simplicity in this lightweight version, we just add items.
            
            # We filter options to prevent explosion, BUT we pick smarter options.
            # We trust that _optimize_requirements will fix bad choices, so we just need minimal valid sets here.
            # Just take the first few distinct SLOT options to ensure coverage.
            
            # Dedup options by slot to ensure we try "Head" and "Ring" and "Tool"
            seen_slots = set()
            diverse_options = []
            
            # Sort options by item quality/score logic? 
            # We rely on the order from candidates which is roughly sorted, but let's just pick diversity.
            
            for item, attr in options:
                # If we haven't tried this slot yet for this requirement level, pick it
                if attr not in seen_slots or attr in ["tools", "rings"]:
                    diverse_options.append((item, attr))
                    if attr not in ["tools", "rings"]: seen_slots.add(attr)
            
            # Limit diversity to prevent explosion
            valid_options = diverse_options[:15]

            for item, attr in valid_options:
                if len(results) > 20: return # Stop early, rely on post-optimizer
                
                if attr == "tools":
                    current_tools = current_map.get("tools", [])
                    if item not in current_tools:
                        new_map = current_map.copy()
                        new_map["tools"] = current_tools + [item]
                        solve(index + 1, new_map, locked_slots)
                elif attr == "rings":
                    current_rings = current_map.get("rings", [])
                    if len(current_rings) < 2 and item not in current_rings:
                        new_map = current_map.copy()
                        new_map["rings"] = current_rings + [item]
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

    def _optimize_set(self, current_set, locked_slots, candidates, activity, player_skill_level, target, context, tool_slots, owned_counts, passive_stats):
        # 1. Capture Initial State (Skeleton items are "Fixed" for the purpose of this function)
        initial_tools = list(current_set.tools)
        initial_rings = list(current_set.rings)
        
        # 2. Multi-Pass Optimization Loop
        # Pass 1: Optimize empty slots based on Skeleton + Candidates.
        # Pass 2: Re-optimize with context from Pass 1 (enables synergies like NMC from Tools affecting Ring choice).
        for _ in range(2): 
            base_score = self.calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
            
            main_slots = [
                ("head", EquipmentSlot.HEAD), ("chest", EquipmentSlot.CHEST), 
                ("legs", EquipmentSlot.LEGS), ("feet", EquipmentSlot.FEET),
                ("cape", EquipmentSlot.CAPE), ("back", EquipmentSlot.BACK), 
                ("neck", EquipmentSlot.NECK), ("hands", EquipmentSlot.HANDS), 
                ("primary", EquipmentSlot.PRIMARY), ("secondary", EquipmentSlot.SECONDARY)
            ]

            # --- A. Main Slots ---
            for _ in range(3):
                changed = False
                for attr, slot_enum in main_slots:
                    if attr in locked_slots: continue
                    best_item = getattr(current_set, attr)
                    max_s = base_score
                    
                    cands = candidates.get(slot_enum, [])
                    
                    # Try None
                    setattr(current_set, attr, None)
                    score_none = self.calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
                    if score_none > max_s:
                        max_s = score_none
                        best_item = None
                        changed = True

                    for item in cands:
                        setattr(current_set, attr, item)
                        score = self.calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
                        if score > max_s:
                            max_s = score
                            best_item = item
                            changed = True
                    setattr(current_set, attr, best_item)
                    base_score = max_s
                if not changed: break

            # --- B. Rings ---
            # Re-evaluate Rings
            # For skeleton rings, we keep them unless they are not locked (skeleton logic usually implies requirement lock)
            # But here we treat them as optimization targets if space allows
            
            current_rings = list(current_set.rings)
            # Identify fixed rings (from skeleton requirements) vs free slots
            # For simplicity in this logic, we assume skeleton rings are 'suggested' but if we have free slots we fill them
            
            if len(current_rings) < 2:
                ring_cands = candidates.get(EquipmentSlot.RING, [])
                if ring_cands:
                    # Sort candidates in context of CURRENT gear (Main + Tools)
                    top_rings = self._sort_items_by_utility(ring_cands, current_set, activity, player_skill_level, target, context, passive_stats)[:10]
                    
                    # Simple greedy fill for remaining slots
                    while len(current_rings) < 2:
                        best_r = None
                        max_r = base_score
                        for r in top_rings:
                            if r in current_rings: 
                                if owned_counts and self._get_available_count(r, owned_counts) < 2: continue
                                elif not owned_counts: pass
                                else: continue # assume unique otherwise

                            current_set.rings = current_rings + [r]
                            score = self.calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
                            if score > max_r:
                                max_r = score
                                best_r = r
                        
                        if best_r:
                            current_rings.append(best_r)
                            base_score = max_r
                        else:
                            break
                    current_set.rings = current_rings

            # --- C. Tools ---
            # Re-evaluate Tools
            # Similar to rings, fill empty slots
            fixed_tools = list(current_set.tools)
            available_slots = tool_slots - len(fixed_tools)
            
            if available_slots > 0:
                tool_cands = candidates.get(EquipmentSlot.TOOLS, [])
                valid_cands = [t for t in tool_cands if t not in fixed_tools] # simple dedup
                # Sort using CURRENT SET (Main + Rings)
                sorted_cands = self._sort_items_by_utility(valid_cands, current_set, activity, player_skill_level, target, context, passive_stats)
                
                # Use the fast brute force for tools
                if len(sorted_cands) <= 40:
                    best_subset, new_score = self._optimized_brute_force_tools(
                        current_set, fixed_tools, sorted_cands, available_slots,
                        activity, player_skill_level, target, context, owned_counts, base_score,
                        passive_stats=passive_stats
                    )
                    if best_subset is not None and new_score > base_score:
                        current_set.tools = fixed_tools + best_subset
                        base_score = new_score
                else:
                    # Greedy Fallback
                    current_subset = []
                    max_t = base_score
                    
                    for t in sorted_cands:
                        if len(current_subset) >= available_slots: break
                        test_tools = fixed_tools + current_subset + [t]
                        if self._is_valid_tool_set(test_tools, owned_counts):
                            current_set.tools = test_tools
                            score = self.calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
                            if score >= max_t: 
                                max_t = score
                                current_subset.append(t)
                    
                    current_set.tools = fixed_tools + current_subset
                    base_score = max_t

        return current_set

    # --- Fast Tool Optimization (Pre-calculated Logic) ---

    def _optimized_brute_force_tools(self, current_set: GearSet, fixed_tools: List[Equipment], candidates: List[Equipment], 
                                     slots_count: int, activity, skill_lvl: int, target: OPTIMAZATION_TARGET, context: Dict, 
                                     owned_counts, current_best_score: float, passive_stats: Dict[str, float]) -> Tuple[List[Equipment], float]:
        
        # 1. Pre-calculate Base Stats (Current Set with Fixed Tools Only + Passive Stats)
        orig_tools = current_set.tools
        current_set.tools = fixed_tools
        base_stats_gear = current_set.get_stats(context)
        current_set.tools = orig_tools # Restore just in case

        # Merge passive stats into base stats
        base_stats = defaultdict(float, base_stats_gear)
        for k, v in passive_stats.items():
            base_stats[k] += v

        # 2. Analyze Fixed Tools (Restrictions & Slugs)
        fixed_slugs = set()
        fixed_keywords = set()
        for t in fixed_tools:
            if t.wiki_slug: fixed_slugs.add(t.wiki_slug)
            for k in t.keywords:
                lk = k.lower()
                if lk in self.restricted_keywords_lower:
                    fixed_keywords.add(lk)
        
        # Get Context for conditional checks
        user_ap = context.get("achievement_points", 0)
        total_lvl = context.get("total_skill_level", 0)

        # 3. Lightweight Candidate Conversion
        light_candidates = [] # list of (item, base_stats_dict, cond_mods_list, slug, restricted_kw_set)
        
        for item in candidates:
            # Immediate Pruning: Conflict with Fixed Tools
            if item.wiki_slug and item.wiki_slug in fixed_slugs: continue
            
            conflict = False
            item_restr = set()
            for k in item.keywords:
                lk = k.lower()
                if lk in self.restricted_keywords_lower:
                    if lk in fixed_keywords:
                        conflict = True
                        break
                    item_restr.add(lk)
            if conflict: continue

            # Pre-calc Stats
            item_base_stats = defaultdict(float)
            item_cond_mods = []
            
            for mod in item.modifiers:
                applies_always = True
                is_set_bonus = False
                
                for cond in mod.conditions:
                    c_type = cond.type
                    if c_type == ConditionType.GLOBAL: continue
                    
                    # Eval static conditions now
                    if c_type in [ConditionType.SKILL_ACTIVITY, ConditionType.LOCATION, 
                                  ConditionType.REGION, ConditionType.SPECIFIC_ACTIVITY, 
                                  ConditionType.ACHIEVEMENT_POINTS, ConditionType.TOTAL_SKILL_LEVEL]:
                        applies_cond = True
                        c_target = cond.target.lower() if cond.target else None
                        c_val = cond.value
                        
                        if c_type == ConditionType.SKILL_ACTIVITY:
                            act_skill = context.get("skill", "").lower()
                            if not act_skill: applies_cond = False
                            elif c_target:
                                from models import GATHERING_SKILLS, ARTISAN_SKILLS
                                if c_target == act_skill: pass
                                elif c_target == "gathering" and act_skill in GATHERING_SKILLS: pass
                                elif c_target == "artisan" and act_skill in ARTISAN_SKILLS: pass
                                else: applies_cond = False
                        
                        elif c_type == ConditionType.LOCATION:
                            loc_id = context.get("location_id")
                            loc_tags = context.get("location_tags", set())
                            if not loc_id: applies_cond = False
                            else:
                                if not (c_target == loc_id.lower() or c_target in loc_tags): applies_cond = False
                        
                        elif c_type == ConditionType.REGION:
                            loc_tags = context.get("location_tags", set())
                            if not loc_tags or (c_target and c_target not in loc_tags): applies_cond = False
                        
                        elif c_type == ConditionType.SPECIFIC_ACTIVITY:
                             act_id = context.get("activity_id")
                             if not act_id or (c_target and c_target != act_id.lower()): applies_cond = False

                        elif c_type == ConditionType.ACHIEVEMENT_POINTS:
                            if user_ap < (c_val or 0): applies_cond = False

                        elif c_type == ConditionType.TOTAL_SKILL_LEVEL:
                            if total_lvl < (c_val or 0): applies_cond = False
                        
                        if not applies_cond:
                            applies_always = False
                            break
                    
                    elif c_type == ConditionType.SET_EQUIPPED:
                        applies_always = False
                        is_set_bonus = True 
                    
                    else:
                        applies_always = False
                        is_set_bonus = True

                if applies_always:
                    stat_key = mod.stat.value
                    val = mod.value
                    if mod.stat in PERCENTAGE_STATS:
                        val = val / 100.0
                    
                    if stat_key == StatName.BONUS_XP_ADD.value: stat_key = "flat_xp"
                    elif stat_key == StatName.BONUS_XP_PERCENT.value: stat_key = "xp_percent"
                    elif stat_key == StatName.XP_PERCENT.value: stat_key = "xp_percent"
                    elif stat_key == StatName.STEPS_ADD.value: 
                        stat_key = "flat_step_reduction"
                        val = -val 
                    elif stat_key == StatName.STEPS_PERCENT.value: 
                        stat_key = "percent_step_reduction"
                        val = -val
                    
                    item_base_stats[stat_key] += val
                
                elif is_set_bonus:
                    item_cond_mods.append(mod)

            light_candidates.append({
                "item": item,
                "stats": item_base_stats,
                "cond_mods": item_cond_mods,
                "slug": item.wiki_slug,
                "keywords": {k.lower().replace("_", " ").strip() for k in item.keywords},
                "restricted": item_restr
            })

        # 4. Fast Loop
        best_subset = None
        best_val = current_best_score

        # Prepare context for set bonuses
        fixed_kw_counts = PyCounter()
        for t in fixed_tools:
            for k in t.keywords:
                fixed_kw_counts[k.lower().replace("_", " ").strip()] += 1
        for item in current_set.get_all_items():
            if item.slot != EquipmentSlot.TOOLS:
                 for k in item.keywords:
                    fixed_kw_counts[k.lower().replace("_", " ").strip()] += 1
        
        t_id = 0
        if target == OPTIMAZATION_TARGET.reward_rolls: t_id = 0
        elif target == OPTIMAZATION_TARGET.xp: t_id = 1
        elif target == OPTIMAZATION_TARGET.chests: t_id = 2
        elif target == OPTIMAZATION_TARGET.materials_from_input: t_id = 3
        elif target == OPTIMAZATION_TARGET.fine: t_id = 4
        elif target == OPTIMAZATION_TARGET.quality: t_id = 5
        elif target == OPTIMAZATION_TARGET.collectibles: t_id = 6

        act_base_xp = activity.base_xp or 0
        
        # Limit search size for speed
        search_cands = light_candidates[:32] 

        for r in range(1, slots_count + 1):
            for combo in itertools.combinations(search_cands, r):
                
                # A. Validity Check
                valid_combo = True
                seen_slugs = set()
                seen_restr = set()
                
                for c in combo:
                    if c["slug"] and c["slug"] in seen_slugs: 
                        valid_combo = False; break
                    seen_slugs.add(c["slug"])
                    if c["restricted"]:
                        if not seen_restr.isdisjoint(c["restricted"]):
                            valid_combo = False; break
                        seen_restr.update(c["restricted"])
                
                if not valid_combo: continue

                # B. Stats Summation
                # Use defaultdict to handle missing keys gracefully
                curr_stats = defaultdict(float, base_stats)
                
                # Sum unconditional item stats
                for c in combo:
                    for k, v in c["stats"].items():
                        curr_stats[k] += v

                # C. Conditional Mods (Set Bonuses)
                has_cond = False
                for c in combo:
                    if c["cond_mods"]: has_cond = True; break
                
                if has_cond:
                    current_counts = fixed_kw_counts.copy()
                    for c in combo:
                        for k in c["keywords"]:
                            current_counts[k] += 1
                    
                    for c in combo:
                        for mod in c["cond_mods"]:
                            applies = True
                            for cond in mod.conditions:
                                if cond.type == ConditionType.SET_EQUIPPED:
                                    norm_target = cond.target.replace("_", " ").strip()
                                    if current_counts.get(norm_target, 0) < (cond.value or 1):
                                        applies = False; break
                            
                            if applies:
                                stat_key = mod.stat.value
                                val = mod.value
                                if mod.stat in PERCENTAGE_STATS:
                                    val = val / 100.0
                                if stat_key == StatName.BONUS_XP_ADD.value: stat_key = "flat_xp"
                                elif stat_key == StatName.BONUS_XP_PERCENT.value: stat_key = "xp_percent"
                                elif stat_key == StatName.XP_PERCENT.value: stat_key = "xp_percent"
                                elif stat_key == StatName.STEPS_ADD.value: 
                                    stat_key = "flat_step_reduction"
                                    val = -val 
                                elif stat_key == StatName.STEPS_PERCENT.value: 
                                    stat_key = "percent_step_reduction"
                                    val = -val
                                curr_stats[stat_key] += val

                # D. Calculate Score
                steps = calculate_steps(
                    activity=activity,
                    player_skill_level=skill_lvl, 
                    player_work_efficiency=curr_stats.get("work_efficiency", 0),
                    player_minus_steps=curr_stats.get("flat_step_reduction", 0),
                    player_minus_steps_percent=curr_stats.get("percent_step_reduction", 0)
                )
                steps = max(1, steps)

                da_val = min(1.0, curr_stats.get("double_action", 0))
                dr_val = curr_stats.get("double_rewards", 0) 
                nmc_val = min(0.99, curr_stats.get("no_materials_consumed", 0)) 
                
                da_mult = 1.0 + da_val
                dr_mult = 1.0 + dr_val
                nmc_mult = 1.0 / (1.0 - nmc_val)
                
                val = 0.0
                if t_id == 0:
                    val = (da_mult * dr_mult) / steps
                elif t_id == 1:
                    xp_mult = 1.0 + curr_stats.get("xp_percent", 0)
                    flat_xp = curr_stats.get("flat_xp", 0)
                    val = ((act_base_xp * xp_mult + flat_xp) * da_mult) / steps
                elif t_id == 2:
                    val = ((1.0 + curr_stats.get("chest_finding", 0)) * da_mult * dr_mult) / steps
                elif t_id == 3:
                    val = (dr_mult * nmc_mult)
                elif t_id == 4:
                    val = ((1.0 + curr_stats.get("fine_material_finding", 0)) * da_mult * dr_mult) / steps
                elif t_id == 6:
                    val = ((1.0 + curr_stats.get("find_collectibles", 0)) * da_mult * dr_mult) / steps
                elif t_id == 5:
                    flat_q = curr_stats.get("quality_outcome", 0)
                    probs = calculate_quality_probabilities(
                        activity_min_level=activity.level, 
                        player_skill_level=skill_lvl,
                        quality_bonus=flat_q
                    )
                    score_q = probs.get("Eternal", 0.0) * 1000 + probs.get("Perfect", 0.0) * 10 + probs.get("Excellent", 0.0)
                    val = score_q * dr_mult * nmc_mult

                if val > best_val:
                    # E. Post-Check: Ownership (Lazy)
                    if owned_counts:
                         test_tools = [c["item"] for c in combo]
                         if not self._is_valid_tool_set(test_tools, owned_counts):
                             continue
                    
                    best_val = val
                    best_subset = [c["item"] for c in combo]

        return best_subset, best_val

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

    def calculate_score(self, current_set: GearSet, activity, player_skill_level, target, context, ignore_requirements: bool = False, passive_stats: Dict[str, float] = None):
        required_keywords = context.get("required_keywords", {})
        deficit = 0
        if not ignore_requirements and required_keywords:
            set_keywords = current_set.get_keyword_counts()
            for req_kw, req_count in required_keywords.items():
                curr_count = set_keywords.get(req_kw, 0)
                if curr_count < req_count: deficit += (req_count - curr_count)
        if deficit > 0: return -10000.0 * deficit

        stats = current_set.get_stats(context)
        
        # Add passive stats (Collectibles)
        if passive_stats:
            for k, v in passive_stats.items():
                stats[k] = stats.get(k, 0.0) + v

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
    
    def analyze_score(self, current_set: GearSet, activity, player_skill_level, target, context, passive_stats: Dict[str, float] = None):
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
        if passive_stats:
            for k, v in passive_stats.items():
                stats[k] = stats.get(k, 0.0) + v

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
        
        elif target == OPTIMAZATION_TARGET.materials_from_input:
            numerator = dr_mult * nmc_mult
            formula_str = f"({dr_mult:.2f} * {nmc_mult:.2f})"

        # Add other targets as needed... default fallback
        if not formula_str and numerator == 0:
             val = self.calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
             numerator = val * steps
             formula_str = f"{numerator:.4f} / {steps}"

        return {
            "numerator": numerator,
            "denominator": steps,
            "score": numerator / steps if steps else 0,
            "formula": formula_str,
            "stats": stats
        }

    def _sort_items_by_utility(self, items, current_set, activity, player_skill_level, target, context, passive_stats):
        scored = []
        # Use current_set + passive_stats as the baseline to capture non-linear scaling (especially for NMC)
        
        for item in items:
            # Temporarily equip the item
            added = False
            old_val = None
            
            if item.slot == EquipmentSlot.TOOLS: 
                current_set.tools.append(item)
                added = True
            elif item.slot == EquipmentSlot.RING: 
                current_set.rings.append(item)
                added = True
            else:
                attr_name = item.slot
                if hasattr(current_set, attr_name): 
                    old_val = getattr(current_set, attr_name)
                    setattr(current_set, attr_name, item)
            
            # Calculate Score WITH context
            score = self.calculate_score(current_set, activity, player_skill_level, target, context, ignore_requirements=True, passive_stats=passive_stats)
            scored.append((score, item))
            
            # Revert changes
            if added:
                if item.slot == EquipmentSlot.TOOLS: current_set.tools.pop()
                elif item.slot == EquipmentSlot.RING: current_set.rings.pop()
            else:
                attr_name = item.slot
                if hasattr(current_set, attr_name): 
                    setattr(current_set, attr_name, old_val)

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