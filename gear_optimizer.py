import itertools
from typing import Dict, List, Set, Optional, Tuple, Any
from collections import Counter as PyCounter, defaultdict

from models import Equipment, Activity, GearSet, EquipmentSlot, Location, RequirementType, ConditionType, Collectible, Pet, Consumable
from utils.constants import RESTRICTED_TOOL_KEYWORDS, PERCENTAGE_STATS, OPTIMAZATION_TARGET, StatName
from calculations import calculate_score, calculate_steps, calculate_passive_stats, calculate_quality_probabilities
from candidates import CandidateSelector

class GearOptimizer:
    def __init__(self, all_items: List[Equipment], all_locations: List[Location]):
        self.all_items = all_items
        self.location_map = {loc.id: loc for loc in all_locations}
        # Delegate filtering and sorting to the component
        self.candidate_selector = CandidateSelector(all_items)
        
        self.debug_candidates = {} 
        self.debug_rejected = []   

    def optimize(self, activity: Activity, player_level: int, player_skill_level: int, 
                 optimazation_target: OPTIMAZATION_TARGET = OPTIMAZATION_TARGET.reward_rolls,
                 owned_item_counts: Optional[Dict[str, int]] = None,
                 achievement_points: int = 0,
                 user_reputation: Optional[Dict[str, float]] = None,
                 owned_collectibles: Optional[List[Collectible]] = None,
                 extra_passive_stats: Optional[Dict[str, float]] = None,
                 context_override: Optional[Dict] = None,
                 pet: Optional[Pet] = None,
                 consumable: Optional[Consumable] = None,
                 locked_items: Optional[Dict[str, Equipment]] = None,
                 blacklisted_ids: Optional[Set[str]] = None) -> Tuple[Optional[GearSet], Optional[str]]:
        
        # Reset Debug
        self.debug_candidates = {}
        self.debug_rejected = []
        
        if locked_items is None: locked_items = {}
        if blacklisted_ids is None: blacklisted_ids = set()

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
            
            # Parse Requirements
            required_keywords = {} 
            for req in activity.requirements:
                if req.type == RequirementType.KEYWORD_COUNT and req.target:
                    norm_target = req.target.lower().replace("_", " ").strip()
                    required_keywords[norm_target] = req.value
            context["required_keywords"] = required_keywords

        # 3. Calculate Passive Stats
        passive_stats = calculate_passive_stats(owned_collectibles or [], context)
        if extra_passive_stats:
            for k, v in extra_passive_stats.items():
                passive_stats[k] = passive_stats.get(k, 0.0) + v

        # 4. Prepare Locks
        fixed_single_slots = {} 
        fixed_rings = []
        fixed_tools = []
        locked_item_objects = set() 

        for k, item in locked_items.items():
            if not item: continue
            locked_item_objects.add(item)
            if k.startswith("ring"):
                fixed_rings.append(item)
            elif k.startswith("tool"):
                if len(fixed_tools) < tool_slots:
                    fixed_tools.append(item)
            else:
                fixed_single_slots[k] = item

        # 5. Get Candidates
        required_keywords = context.get("required_keywords", {})
        
        candidates = self.candidate_selector.get_candidates(
            activity, required_keywords, optimazation_target, context, player_skill_level, 
            owned_item_counts, user_reputation, 
            blacklisted_ids, locked_item_objects
        )
        self.debug_candidates = candidates
        self.debug_rejected = self.candidate_selector.debug_rejected

        # --- PRE-FILL SECONDARY SLOT PATCH ---
        pre_fill_item = None
        if "secondary" not in fixed_single_slots:
            sec_candidates = candidates.get(EquipmentSlot.SECONDARY, [])
            
            dummy_sort_set = GearSet()
            sorted_sec = self.candidate_selector.sort_items_by_utility(
                sec_candidates, dummy_sort_set, activity, player_skill_level, optimazation_target, context, passive_stats
            )
            
            for item in sorted_sec:
                has_req_kw = any(k.lower().replace("_", " ").strip() in required_keywords for k in item.keywords)
                
                dummy_sort_set.secondary = item
                s = calculate_score(dummy_sort_set, activity, player_skill_level, optimazation_target, context, ignore_requirements=True, passive_stats=passive_stats)
                dummy_sort_set.secondary = None 

                if has_req_kw or s > 0.000001:
                    pre_fill_item = item
                    break 

        # 6. Generate Skeletons
        skeletons = self._generate_skeletons(candidates, required_keywords)
        
        best_overall_set = GearSet()
        best_overall_score = -float('inf')
        
        # Base locked set
        base_locked_set = GearSet()
        base_locked_set.pet = pet 
        base_locked_set.consumable = consumable
        for slot, item in fixed_single_slots.items():
            setattr(base_locked_set, slot, item)
        base_locked_set.rings = list(fixed_rings)
        base_locked_set.tools = list(fixed_tools)

        if pre_fill_item:
            base_locked_set.secondary = pre_fill_item

        # 7. Optimization Loop
        for skeleton_set, skel_locked_slots in skeletons:
            
            current_set = base_locked_set.clone()
            
            # Merge Skeleton
            for slot in ["head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary"]:
                skel_item = getattr(skeleton_set, slot)
                if skel_item:
                    if slot not in fixed_single_slots:
                        setattr(current_set, slot, skel_item)
                        skel_locked_slots.add(slot)
            
            current_ring_slots_left = 2 - len(current_set.rings)
            current_set.rings.extend(skeleton_set.rings[:current_ring_slots_left])
            
            current_tool_slots_left = tool_slots - len(current_set.tools)
            current_set.tools.extend(skeleton_set.tools[:current_tool_slots_left])

            optimizer_locked_slots = set(fixed_single_slots.keys()).union(skel_locked_slots)
            
            # A. Standard Optimization
            optimized_set = self._optimize_set(
                current_set, 
                optimizer_locked_slots, 
                fixed_rings,            
                fixed_tools,            
                candidates, 
                activity, 
                player_skill_level, 
                optimazation_target, 
                context,
                tool_slots,
                owned_item_counts,
                passive_stats
            )
            
            # B. Requirement Swapping
            final_set = self._optimize_requirements(
                optimized_set,
                locked_item_objects, 
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
            
            score = calculate_score(final_set, activity, player_skill_level, optimazation_target, context, passive_stats=passive_stats)
            
            if score > best_overall_score:
                best_overall_score = score
                best_overall_set = final_set

        if best_overall_score < -1000:
             return None, "Requirements could not be met with the current locked items."

        return best_overall_set, None

    # =========================================================================
    # OPTIMIZATION SUB-ROUTINES
    # =========================================================================

    def _optimize_requirements(self, current_set: GearSet, locked_item_objects: Set[Equipment],
                               candidates: Dict[str, List[Equipment]], 
                               required_keywords: Dict[str, int], activity, lvl, target, context, 
                               tool_slots, owned_counts, passive_stats) -> GearSet:
        
        # Flatten candidates
        provider_pool = []
        for slot, items in candidates.items():
            for item in items:
                if any(k.lower().replace("_", " ").strip() in required_keywords for k in item.keywords):
                    provider_pool.append(item)
        
        def can_equip(item, current_gear):
            if item in locked_item_objects: return True
            if not owned_counts: return True
            needed = 1
            if item in current_gear.get_all_items(): needed += 1
            return self.candidate_selector._get_available_count(item, owned_counts) >= needed

        # Initial Sort
        provider_pool = self.candidate_selector.sort_items_by_utility(
            provider_pool, current_set, activity, lvl, target, context, passive_stats
        )
        
        # --- PHASE 1: FILL MISSING REQS ---
        max_fill_attempts = 10 
        for _ in range(max_fill_attempts):
            current_counts = current_set.get_keyword_counts()
            missing_reqs = []
            if required_keywords:
                for req, count in required_keywords.items():
                    if current_counts.get(req, 0) < count:
                        missing_reqs.append(req)
            
            if not missing_reqs: break
                
            target_req = missing_reqs[0]
            best_filler = None
            for cand in provider_pool:
                if cand in current_set.get_all_items(): continue
                cand_kws = {k.lower().replace("_", " ").strip() for k in cand.keywords}
                if target_req in cand_kws:
                    if can_equip(cand, current_set):
                        best_filler = cand
                        break 
            
            if not best_filler: break 
            
            temp_set = current_set.clone()
            if temp_set.equip(best_filler, tool_slots):
                current_set = temp_set
                continue
            
            # Swap Logic if equip failed
            best_swap_set = None
            best_swap_score = -float('inf')
            
            victims = []
            if best_filler.slot == EquipmentSlot.TOOLS:
                victims = current_set.tools
            elif best_filler.slot == EquipmentSlot.RING:
                victims = current_set.rings
            else:
                item_in_slot = getattr(current_set, best_filler.slot.value)
                if item_in_slot: victims = [item_in_slot]
            
            swap_occurred = False
            for v in victims:
                if v in locked_item_objects: continue
                test_set = current_set.clone()
                test_set.unequip(v)
                if test_set.equip(best_filler, tool_slots):
                    s = calculate_score(test_set, activity, lvl, target, context, passive_stats=passive_stats, ignore_requirements=True) 
                    if s > best_swap_score:
                        best_swap_score = s
                        best_swap_set = test_set
                        swap_occurred = True
            
            if swap_occurred and best_swap_set:
                current_set = best_swap_set
            else:
                break 

        # --- PHASE 2: OPTIMIZE/SWAP EXISTING REQUIREMENTS ---
        best_local_set = current_set
        best_local_score = calculate_score(current_set, activity, lvl, target, context, passive_stats=passive_stats)

        provider_pool = self.candidate_selector.sort_items_by_utility(
            provider_pool, best_local_set, activity, lvl, target, context, passive_stats
        )
        provider_pool = provider_pool[:60]

        improved = True
        iterations = 0
        while improved and iterations < 3:
            improved = False
            iterations += 1
            
            active_providers = []
            for item in best_local_set.get_all_items():
                if isinstance(item, Pet) or isinstance(item, Consumable): continue 
                if item in locked_item_objects: continue 
                
                is_prov = False
                if required_keywords:
                    for k in item.keywords:
                        if k.lower().replace("_", " ").strip() in required_keywords:
                            is_prov = True; break
                if is_prov: active_providers.append(item)

            for provider_to_remove in active_providers:
                relevant_reqs = {k.lower().replace("_", " ").strip() for k in provider_to_remove.keywords if k.lower().replace("_", " ").strip() in required_keywords} if required_keywords else set()
                
                for candidate in provider_pool:
                    if candidate.id == provider_to_remove.id: continue
                    if candidate in best_local_set.get_all_items(): continue
                    
                    cand_reqs = {k.lower().replace("_", " ").strip() for k in candidate.keywords}
                    if not relevant_reqs.intersection(cand_reqs): continue 

                    if not can_equip(candidate, best_local_set): continue

                    test_set = best_local_set.clone()
                    test_set.unequip(provider_to_remove)
                    
                    if not test_set.equip(candidate, tool_slots): continue 

                    new_score = calculate_score(test_set, activity, lvl, target, context, passive_stats=passive_stats)
                    if new_score > best_local_score + 0.0001: 
                        best_local_score = new_score
                        best_local_set = test_set
                        improved = True
                        break 
                if improved: break 

        # --- PHASE 3: FULL POLISH ---
        current_counts = best_local_set.get_keyword_counts()
        
        def is_essential(item, current_set_counts):
            if not required_keywords: return False
            for k in item.keywords:
                nk = k.lower().replace("_", " ").strip()
                if nk in required_keywords:
                    if current_set_counts[nk] <= required_keywords[nk]:
                        return True
            return False

        slots_to_check = [
            ("head", EquipmentSlot.HEAD), ("chest", EquipmentSlot.CHEST), 
            ("legs", EquipmentSlot.LEGS), ("feet", EquipmentSlot.FEET),
            ("back", EquipmentSlot.BACK), ("cape", EquipmentSlot.CAPE), 
            ("neck", EquipmentSlot.NECK), ("hands", EquipmentSlot.HANDS), 
            ("primary", EquipmentSlot.PRIMARY), ("secondary", EquipmentSlot.SECONDARY),
            ("ring", EquipmentSlot.RING), ("tools", EquipmentSlot.TOOLS)
        ]

        polish_improved = True
        polish_iter = 0
        
        while polish_improved and polish_iter < 3:
            polish_improved = False
            polish_iter += 1
            current_counts = best_local_set.get_keyword_counts()

            for slot_attr, slot_enum in slots_to_check:
                slot_candidates = candidates.get(slot_enum, [])
                if not slot_candidates: continue

                best_candidates = self.candidate_selector.sort_items_by_utility(
                    slot_candidates, best_local_set, activity, lvl, target, context, passive_stats
                )
                best_candidates = best_candidates[:20]

                current_items_in_slot = []
                if slot_attr == "tools": current_items_in_slot = best_local_set.tools
                elif slot_attr == "ring": current_items_in_slot = best_local_set.rings
                else:
                    it = getattr(best_local_set, slot_attr)
                    if it: current_items_in_slot = [it]
                    else: current_items_in_slot = [None]

                for curr_item in current_items_in_slot:
                    if curr_item and curr_item in locked_item_objects: continue
                    if curr_item and is_essential(curr_item, current_counts): continue
                    
                    for cand in best_candidates:
                        if curr_item and cand.id == curr_item.id: continue
                        if cand in best_local_set.get_all_items(): continue
                        if not can_equip(cand, best_local_set): continue

                        test_set = best_local_set.clone()
                        if curr_item: test_set.unequip(curr_item)
                        
                        if test_set.equip(cand, tool_slots):
                            new_score = calculate_score(test_set, activity, lvl, target, context, passive_stats=passive_stats)
                            
                            if new_score > best_local_score + 0.00001:
                                best_local_score = new_score
                                best_local_set = test_set
                                current_counts = best_local_set.get_keyword_counts()
                                polish_improved = True
                                break
                    if polish_improved: break
                if polish_improved: break

        return best_local_set

    def _optimize_set(self, current_set, locked_slots, fixed_rings, fixed_tools, 
                      candidates, activity, player_skill_level, target, context, tool_slots, owned_counts, passive_stats):
        
        for _ in range(2): 
            base_score = calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
            
            # A. Main Slots
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
                    
                    setattr(current_set, attr, None)
                    score_none = calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
                    if score_none > max_s:
                        max_s = score_none
                        best_item = None
                        changed = True

                    for item in cands:
                        setattr(current_set, attr, item)
                        score = calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
                        if score > max_s:
                            max_s = score
                            best_item = item
                            changed = True
                    setattr(current_set, attr, best_item)
                    base_score = max_s
                if not changed: break

            # B. Rings
            original_rings = list(current_set.rings)
            available_ring_slots = 2 - len(fixed_rings)
            
            if available_ring_slots > 0:
                ring_cands = candidates.get(EquipmentSlot.RING, [])
                if ring_cands:
                    top_rings = self.candidate_selector.sort_items_by_utility(
                        ring_cands, current_set, activity, player_skill_level, 
                        target, context, passive_stats
                    )[:12] 

                    best_ring_set = list(original_rings)
                    max_ring_score = base_score
                    
                    from itertools import combinations_with_replacement
                    
                    for r_cnt in range(1, available_ring_slots + 1):
                        for combo in combinations_with_replacement(top_rings, r_cnt):
                            test_rings = fixed_rings + list(combo)
                            if self._is_valid_ring_set(test_rings, owned_counts, fixed_rings):
                                current_set.rings = test_rings
                                score = calculate_score(
                                    current_set, activity, player_skill_level, 
                                    target, context, passive_stats=passive_stats
                                )
                                if score > max_ring_score + 0.00001: 
                                    max_ring_score = score
                                    best_ring_set = list(test_rings)
                    
                    current_set.rings = best_ring_set
                    base_score = max_ring_score
                else:
                    current_set.rings = original_rings
            else:
                current_set.rings = original_rings
            
            # C. Tools
            available_tool_slots = tool_slots - len(fixed_tools)
            
            if available_tool_slots > 0:
                tool_cands = candidates.get(EquipmentSlot.TOOLS, [])
                valid_cands = []
                for t in tool_cands:
                    if t not in fixed_tools: valid_cands.append(t)
                
                sorted_cands = self.candidate_selector.sort_items_by_utility(
                    valid_cands, current_set, activity, player_skill_level, target, context, passive_stats
                )
                
                if len(sorted_cands) <= 40:
                    best_subset, new_score = self._optimized_brute_force_tools(
                        current_set, fixed_tools, sorted_cands, available_tool_slots,
                        activity, player_skill_level, target, context, owned_counts, base_score,
                        passive_stats=passive_stats
                    )
                    if best_subset is not None and new_score > base_score:
                        current_set.tools = fixed_tools + best_subset
                        base_score = new_score
                else:
                    current_subset = []
                    max_t = base_score
                    for t in sorted_cands:
                        if len(current_subset) >= available_tool_slots: break
                        test_tools = fixed_tools + current_subset + [t]
                        if self._is_valid_tool_set(test_tools, owned_counts, fixed_tools):
                            current_set.tools = test_tools
                            score = calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
                            if score >= max_t: 
                                max_t = score
                                current_subset.append(t)
                    current_set.tools = fixed_tools + current_subset
                    base_score = max_t

        return current_set

    # =========================================================================
    # BRUTE FORCE TOOLS (Pre-calculated for speed)
    # =========================================================================

    def _optimized_brute_force_tools(self, current_set: GearSet, fixed_tools: List[Equipment], candidates: List[Equipment], 
                                     slots_count: int, activity, skill_lvl: int, target: OPTIMAZATION_TARGET, context: Dict, 
                                     owned_counts, current_best_score: float, passive_stats: Dict[str, float]) -> Tuple[List[Equipment], float]:
        
        # Snapshot current stats
        orig_tools = current_set.tools
        current_set.tools = fixed_tools
        base_stats_gear = current_set.get_stats(context)
        current_set.tools = orig_tools 

        base_stats = defaultdict(float, base_stats_gear)
        for k, v in passive_stats.items():
            base_stats[k] += v

        # Pre-process fixed tools
        fixed_slugs = set()
        fixed_keywords = set()
        for t in fixed_tools:
            if t.wiki_slug: fixed_slugs.add(t.wiki_slug)
            for k in t.keywords:
                lk = k.lower()
                if lk in self.candidate_selector.restricted_keywords_lower if hasattr(self.candidate_selector, 'restricted_keywords_lower') else set(): # Fallback check, usually handled in validation
                    fixed_keywords.add(lk)
        
        user_ap = context.get("achievement_points", 0)
        total_lvl = context.get("total_skill_level", 0)

        # Create Light Candidates (Pre-calculate stat contribution)
        light_candidates = [] 
        
        restricted_lower = {k.lower() for k in RESTRICTED_TOOL_KEYWORDS}
        
        for item in candidates:
            if item.wiki_slug and item.wiki_slug in fixed_slugs: continue
            
            conflict = False
            item_restr = set()
            for k in item.keywords:
                lk = k.lower()
                if lk in restricted_lower:
                    item_restr.add(lk)
            
            # Simple conflict check with fixed tools
            for ft in fixed_tools:
                 for k in ft.keywords:
                     if k.lower() in item_restr: conflict = True; break
                 if conflict: break
            if conflict: continue

            item_base_stats = defaultdict(float)
            item_cond_mods = []
            
            for mod in item.modifiers:
                applies_always = True
                is_set_bonus = False
                
                for cond in mod.conditions:
                    c_type = cond.type
                    if c_type == ConditionType.GLOBAL: continue
                    
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
                    if mod.stat in PERCENTAGE_STATS: val = val / 100.0
                    
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

        best_subset = None
        best_val = current_best_score

        # Prepare keyword counts for set bonuses
        fixed_kw_counts = PyCounter()
        for t in fixed_tools:
            for k in t.keywords:
                fixed_kw_counts[k.lower().replace("_", " ").strip()] += 1
        for item in current_set.get_all_items():
            if isinstance(item, Pet) or isinstance(item, Consumable) or item.slot != EquipmentSlot.TOOLS:
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
        search_cands = light_candidates[:32] 

        # Iterate Combinations
        for r in range(1, slots_count + 1):
            for combo in itertools.combinations(search_cands, r):
                
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

                curr_stats = defaultdict(float, base_stats)
                for c in combo:
                    for k, v in c["stats"].items():
                        curr_stats[k] += v

                # Handle Set Bonuses
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
                                if mod.stat in PERCENTAGE_STATS: val = val / 100.0
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

                # Steps & Scoring (Inline for speed)
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
                    if owned_counts:
                         test_tools = fixed_tools + [c["item"] for c in combo]
                         if not self._is_valid_tool_set(test_tools, owned_counts, fixed_tools):
                             continue
                    best_val = val
                    best_subset = [c["item"] for c in combo]

        return best_subset, best_val

    def _generate_skeletons(self, candidates, required_keywords) -> List[Tuple[GearSet, Set[str]]]:
        # Part A: Requirement-based Skeletons
        if not required_keywords:
            results = [(GearSet(), set())]
        else:
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
                for _ in range(v): req_list.append(k)
            
            results = []
            unique_signatures = set()

            def solve(index, current_map, locked_slots):
                if index >= len(req_list):
                    gs = GearSet()
                    for attr, val in current_map.items():
                        if attr == "tools": gs.tools = list(val)
                        elif attr == "rings": gs.rings = list(val)
                        else: setattr(gs, attr, val)
                    all_ids = []
                    for i in gs.get_all_items():
                        if isinstance(i, Pet): continue
                        all_ids.append(i.id)
                    sig = tuple(sorted(all_ids))
                    if sig not in unique_signatures:
                        unique_signatures.add(sig)
                        results.append((gs, locked_slots.copy()))
                    return

                req = req_list[index]
                options = providers.get(req, [])
                seen_slots = set()
                diverse_options = []
                for item, attr in options:
                    if attr not in seen_slots or attr in ["tools", "rings"]:
                        diverse_options.append((item, attr))
                        if attr not in ["tools", "rings"]: seen_slots.add(attr)
                
                valid_options = diverse_options[:15]

                for item, attr in valid_options:
                    if len(results) > 20: return 
                    
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
        
        if not results: results = [(GearSet(), set())]

        # Part B: Set Skeletons
        set_groups = defaultdict(list)
        for slot, items in candidates.items():
            if slot == EquipmentSlot.TOOLS: continue
            for item in items:
                found_set = False
                for mod in item.modifiers:
                    for cond in mod.conditions:
                        if cond.type == ConditionType.SET_EQUIPPED and cond.target:
                            t = cond.target.lower().replace("_", " ").strip()
                            set_groups[t].append(item)
                            found_set = True; break
                    if found_set: break
        
        attr_map_simple = {
            EquipmentSlot.HEAD: "head", EquipmentSlot.CHEST: "chest", EquipmentSlot.LEGS: "legs", 
            EquipmentSlot.FEET: "feet", EquipmentSlot.BACK: "back", EquipmentSlot.CAPE: "cape", 
            EquipmentSlot.NECK: "neck", EquipmentSlot.HANDS: "hands",
            EquipmentSlot.PRIMARY: "primary", EquipmentSlot.SECONDARY: "secondary",
            EquipmentSlot.RING: "rings"
        }

        for set_name, set_items in set_groups.items():
            gs = GearSet()
            locked = set()
            for item in set_items:
                attr = attr_map_simple.get(item.slot)
                if not attr: continue
                if attr == "rings":
                    if len(gs.rings) < 2 and item not in gs.rings:
                        gs.rings.append(item)
                else:
                    if getattr(gs, attr) is None:
                        setattr(gs, attr, item)
                        locked.add(attr)
            if locked or gs.rings:
                results.append((gs, locked))

        return results

    # =========================================================================
    # VALIDATORS
    # =========================================================================

    def _is_valid_ring_set(self, rings: List[Equipment], owned_counts: Dict[str, int], fixed_rings: List[Equipment]) -> bool:
        if not owned_counts: return True
        total_needed_counts = PyCounter()
        for r in rings:
            total_needed_counts[r.id.lower()] += 1
        
        locked_provided_counts = PyCounter()
        for r in fixed_rings:
            locked_provided_counts[r.id.lower()] += 1
            
        for item_id, total_needed in total_needed_counts.items():
            locked_amount = locked_provided_counts[item_id]
            needed_from_inventory = total_needed - locked_amount
            
            if needed_from_inventory > 0:
                owned = owned_counts.get(item_id, 0)
                if owned == 0:
                     suffixes = ["_common", "_uncommon", "_rare", "_epic", "_legendary", "_ethereal", "_normal"]
                     for s in suffixes:
                        if item_id.endswith(s):
                            base = item_id.replace(s, "")
                            if base in owned_counts: 
                                owned = owned_counts[base]; break
                if owned < needed_from_inventory:
                    return False
        return True
    
    def _is_valid_tool_set(self, tools: List[Equipment], owned_counts: Optional[Dict[str, int]], fixed_tools: List[Equipment]) -> bool:
        seen_slugs = set()
        seen_keywords = set()
        restricted_lower = {k.lower() for k in RESTRICTED_TOOL_KEYWORDS}

        for t in tools:
            if t.wiki_slug:
                if t.wiki_slug in seen_slugs: return False
                seen_slugs.add(t.wiki_slug)
            for k in t.keywords:
                if k in RESTRICTED_TOOL_KEYWORDS or k.lower() in restricted_lower:
                    norm_k = k.lower()
                    if norm_k in seen_keywords: return False
                    seen_keywords.add(norm_k)

        if owned_counts:
            id_counts = PyCounter()
            for t in tools: 
                id_counts[t.id.lower()] += 1
            
            fixed_counts = PyCounter()
            for t in fixed_tools: fixed_counts[t.id.lower()] += 1
            
            for item_id, total_needed in id_counts.items():
                locked_c = fixed_counts[item_id]
                extra_needed = total_needed - locked_c
                
                if extra_needed > 0:
                    owned = owned_counts.get(item_id, 0)
                    if owned == 0:
                        suffixes = ["_common", "_uncommon", "_rare", "_epic", "_legendary", "_ethereal", "_normal"]
                        for s in suffixes:
                            if item_id.endswith(s):
                                base = item_id.replace(s, "")
                                if base in owned_counts: 
                                    owned = owned_counts[base]; break
                    
                    remaining_owned = max(0, owned - locked_c)
                    if extra_needed > remaining_owned:
                        return False
        return True