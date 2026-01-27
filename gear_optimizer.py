
import itertools
import math
from typing import Dict, List, Set, Optional, Tuple, Any
from models import Equipment, Activity, GearSet, EquipmentSlot, Location, StatName, RequirementType, ConditionType, Collectible, GATHERING_SKILLS, ARTISAN_SKILLS, Pet, Consumable
from utils.utils import calculate_steps, calculate_quality_probabilities
from collections import Counter as PyCounter, defaultdict
from utils.constants import RESTRICTED_TOOL_KEYWORDS, PERCENTAGE_STATS, OPTIMAZATION_TARGET, TARGET_TO_STATS, STAT_ENUM_TO_KEY, QUALITY_RANK


class GearOptimizer:
    def __init__(self, all_items: List[Equipment], all_locations: List[Location]):
        self.all_items = all_items
        self.location_map = {loc.id: loc for loc in all_locations}
        self.restricted_keywords_lower = {k.lower() for k in RESTRICTED_TOOL_KEYWORDS}
        
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
        
        # locked_items keys: "head", "chest", ..., "ring_0", "ring_1", "tool_0"..."tool_5"

        # Reset Debug Info
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

        # --- PREPARE LOCKS ---
        fixed_single_slots = {} # slot_name -> item
        fixed_rings = []
        fixed_tools = []
        
        locked_item_objects = set() # For filtering logic

        for k, item in locked_items.items():
            if not item: continue
            locked_item_objects.add(item)
            if k.startswith("ring"):
                fixed_rings.append(item)
            elif k.startswith("tool"):
                # Ensure we don't exceed max tools with locks, or handle it gracefully
                if len(fixed_tools) < tool_slots:
                    fixed_tools.append(item)
            else:
                fixed_single_slots[k] = item

        # 5. Get Candidates
        required_keywords = context.get("required_keywords", {})
        candidates = self._get_candidates(
            activity, required_keywords, optimazation_target, context, player_skill_level, 
            owned_item_counts, user_reputation, 
            blacklisted_ids, locked_item_objects
        )
        self.debug_candidates = candidates

        # 6. Generate Skeletons
        # Skeletons help fulfil requirements. 
        # We must respect locks during skeleton generation or merge them after.
        # Strategy: Generate skeletons normally, but if a skeleton conflicts with a lock, discard/adjust?
        # Better Strategy: Initialize the base set with locks, and treat them as 'locked_slots' in the optimization phase.
        
        # We need skeletons to fulfil requirements that MIGHT NOT be fulfilled by locks.
        # But we must ensure skeletons don't overwrite locks.
        skeletons = self._generate_skeletons(candidates, required_keywords)
        
        best_overall_set = GearSet()
        best_overall_score = -float('inf')
        
        # Pre-fill the "Base" structure with locks
        base_locked_set = GearSet()
        base_locked_set.pet = pet 
        base_locked_set.consumable = consumable
        for slot, item in fixed_single_slots.items():
            setattr(base_locked_set, slot, item)
        base_locked_set.rings = list(fixed_rings)
        base_locked_set.tools = list(fixed_tools)

        # Optimization Loop
        # If no requirements, skeletons returns [empty]. We merge that with our locks.
        
        for skeleton_set, skel_locked_slots in skeletons:
            
            current_set = self._clone_set(base_locked_set)
            
            # Merge Skeleton into Current Set ONLY if slot is not user-locked
            # If there is a collision (Skeleton wants Head A, User locked Head B),
            # User lock wins. This might make the skeleton invalid for requirements, 
            # but the Requirement Swapper later will try to fix it, or we fail.
            
            items_from_skeleton_used = []
            
            # 1. Merge Single Slots
            for slot in ["head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary"]:
                skel_item = getattr(skeleton_set, slot)
                if skel_item:
                    # If user hasn't locked this slot, take the skeleton item
                    if slot not in fixed_single_slots:
                        setattr(current_set, slot, skel_item)
                        skel_locked_slots.add(slot) # Mark as filled by skeleton
            
            # 2. Merge Rings (Append skeleton rings if space)
            # Skeleton rings are for requirements. 
            current_ring_slots_left = 2 - len(current_set.rings)
            skel_rings_to_add = skeleton_set.rings[:current_ring_slots_left]
            current_set.rings.extend(skel_rings_to_add)
            
            # 3. Merge Tools
            current_tool_slots_left = tool_slots - len(current_set.tools)
            skel_tools_to_add = skeleton_set.tools[:current_tool_slots_left]
            current_set.tools.extend(skel_tools_to_add)

            # Define Locked Slots for the Optimizer
            # This includes USER LOCKS + SKELETON FILLS
            # The optimizer will try to fill 'None' slots.
            
            optimizer_locked_slots = set(fixed_single_slots.keys())
            # Note: We do NOT add skeleton slots to 'locked' for the general optimizer, 
            # we want the optimizer to potentially upgrade them if they aren't strictly needed 
            # (though skeletons usually suggest minimal needed items). 
            # Actually, standard logic is: Skeleton items are "starting points".
            
            # However, USER LOCKS are immutable.
            
            # A. Standard Optimization (Fills empty slots)
            optimized_set = self._optimize_set(
                current_set, 
                optimizer_locked_slots, # Single slots to ignore
                fixed_rings,            # Fixed rings (do not remove)
                fixed_tools,            # Fixed tools (do not remove)
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
            # Must pass user locks so it doesn't swap them out
            final_set = self._optimize_requirements(
                optimized_set,
                locked_item_objects, # Set of actual Item objects that are locked
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

        # Check for failure (negative score implies requirements not met)
        if best_overall_score < -1000:
             return None, "Requirements could not be met with the current locked items."

        return best_overall_set, None

    # --- New Logic: Requirement Swapper ---

    def _optimize_requirements(self, current_set: GearSet, locked_item_objects: Set[Equipment],
                               candidates: Dict[str, List[Equipment]], 
                               required_keywords: Dict[str, int], activity, lvl, target, context, 
                               tool_slots, owned_counts, passive_stats) -> GearSet:
        
        if not required_keywords:
            return current_set

        best_local_set = current_set
        best_local_score = self.calculate_score(current_set, activity, lvl, target, context, passive_stats=passive_stats)
        
        # Helper to check availability
        def can_equip(item, current_gear):
            if item in locked_item_objects: return True # Locked items always available
            if not owned_counts: return True
            
            needed = 1
            if item in current_gear.get_all_items(): needed += 1
            return self._get_available_count(item, owned_counts) >= needed

        # Flatten candidates
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
        
        provider_pool = self._sort_items_by_utility(provider_pool, best_local_set, activity, lvl, target, context, passive_stats)
        provider_pool = provider_pool[:60]

        # Pre-calculate best fillers for holes created by swaps
        best_fillers = {}
        for slot_key in ["head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary", "ring", "tools"]:
            cands = candidates.get(EquipmentSlot(slot_key) if slot_key not in ["ring", "tools"] else (EquipmentSlot.RING if slot_key=="ring" else EquipmentSlot.TOOLS), [])
            sorted_cands = self._sort_items_by_utility(cands, best_local_set, activity, lvl, target, context, passive_stats)
            best_fillers[slot_key] = sorted_cands[:3] 

        improved = True
        iterations = 0
        while improved and iterations < 3:
            improved = False
            iterations += 1
            
            # Find active providers in current set that are NOT locked
            active_providers = []
            for item in best_local_set.get_all_items():
                if isinstance(item, Pet) or isinstance(item, Consumable): continue 
                if item in locked_item_objects: continue # CANNOT REMOVE LOCKED ITEMS
                
                is_prov = False
                for k in item.keywords:
                    if k.lower().replace("_", " ").strip() in required_keywords:
                        is_prov = True; break
                if is_prov: active_providers.append(item)

            for provider_to_remove in active_providers:
                relevant_reqs = {k.lower().replace("_", " ").strip() for k in provider_to_remove.keywords if k.lower().replace("_", " ").strip() in required_keywords}
                
                for candidate in provider_pool:
                    if candidate.id == provider_to_remove.id: continue
                    if candidate in best_local_set.get_all_items(): continue # Simplification: don't swap in equipped items
                    
                    cand_reqs = {k.lower().replace("_", " ").strip() for k in candidate.keywords}
                    # Only useful if it provides the SAME requirement or helps overlapping ones
                    if not relevant_reqs.intersection(cand_reqs): continue

                    if not can_equip(candidate, best_local_set): continue

                    test_set = self._clone_set(best_local_set)
                    self._unequip_item(test_set, provider_to_remove)
                    
                    if not self._equip_item(test_set, candidate, tool_slots):
                        continue 

                    # Fill holes
                    empty_slots = self._get_empty_slots(test_set, tool_slots)
                    for e_slot in empty_slots:
                        # Don't fill a slot if it was supposed to be locked (though unequip shouldn't touch locks)
                        fillers = best_fillers.get(e_slot if "tool" not in e_slot and "ring" not in e_slot else ("tools" if "tool" in e_slot else "ring"), [])
                        for filler in fillers:
                            if can_equip(filler, test_set):
                                if self._equip_item(test_set, filler, tool_slots):
                                    break 

                    new_score = self.calculate_score(test_set, activity, lvl, target, context, passive_stats=passive_stats)
                    
                    if new_score > best_local_score + 0.0001: 
                        best_local_score = new_score
                        best_local_set = test_set
                        improved = True
                        break 
                
                if improved: break 

        return best_local_set

    def _clone_set(self, gs: GearSet) -> GearSet:
        new_set = GearSet()
        for slot in ["head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary"]:
            setattr(new_set, slot, getattr(gs, slot))
        new_set.rings = list(gs.rings)
        new_set.tools = list(gs.tools)
        new_set.pet = gs.pet
        new_set.consumable = gs.consumable
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
        item_restricted_kws = set()
        for k in new_item.keywords:
            lk = k.lower()
            if lk in self.restricted_keywords_lower:
                item_restricted_kws.add(lk)
        if not item_restricted_kws: return False

        for existing in gs.get_all_items():
            if isinstance(existing, Pet) or isinstance(existing, Consumable): continue 
            for k in existing.keywords:
                if k.lower() in item_restricted_kws:
                    return True
        return False

    def _equip_item(self, gs: GearSet, item: Equipment, max_tools: int) -> bool:
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
        if len(gs.rings) < 2: 
             for _ in range(2 - len(gs.rings)): empty.append("ring")
        if len(gs.tools) < max_tools:
             for _ in range(max_tools - len(gs.tools)):
                 empty.append("tools")
        return empty

    # --- Collectible Logic ---
    
    def _calculate_passive_stats(self, collectibles: List[Collectible], context: Dict) -> Dict[str, float]:
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
                            is_id_match = (c_target == loc_id.lower())
                            is_tag_match = (c_target in loc_tags)
                            if not (is_id_match or is_tag_match): applies = False
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
                    stat_enum = mod.stat
                    stat_key = stat_enum.value
                    value = mod.value
                    if stat_enum in PERCENTAGE_STATS: value = value / 100.0
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
                       owned_item_counts: Optional[Dict[str, int]] = None,
                       user_reputation: Optional[Dict[str, float]] = None,
                       blacklisted_ids: Set[str] = None,
                       locked_item_objects: Set[Equipment] = None) -> Dict[str, List[Equipment]]:
        raw_candidates = {}
        relevant_stats = TARGET_TO_STATS.get(target, set())
        dummy_set = GearSet()

        if blacklisted_ids is None: blacklisted_ids = set()
        if locked_item_objects is None: locked_item_objects = set()

        for item in self.all_items:
            rejection_reason = None
            
            # 0. Check Blacklist
            # Locked items bypass blacklist
            if item.id in blacklisted_ids and item not in locked_item_objects:
                # Check if user locked the same item object or just ID match.
                # Just safe to skip if ID matches and not in locked list.
                is_locked = any(l.id == item.id for l in locked_item_objects)
                if not is_locked:
                    continue # Silently skip blacklisted

            # A. Check Ownership (Pre-filter)
            # Locked items bypass ownership check
            if owned_item_counts is not None and item not in locked_item_objects:
                if self._get_available_count(item, owned_item_counts) <= 0:
                    rejection_reason = "Not Owned"
            
            # B. Check Requirements (Reputation)
            if not rejection_reason:
                for req in item.requirements:
                    if req.type == RequirementType.REPUTATION and user_reputation is not None:
                        target_rep = req.target.lower() if req.target else ""
                        current_val = user_reputation.get(target_rep, 0.0)
                        if current_val < req.value:
                            rejection_reason = f"Low Reputation ({req.target}: {current_val}/{req.value})"
                            break
            
            # C. Check Activity Requirements
            provides_requirement = False
            if not rejection_reason:
                for kw in item.keywords:
                    norm = kw.lower().replace("_", " ").strip()
                    if norm in required_keywords:
                        provides_requirement = True
                        break
            
            # D. Check Actual Stats Utility
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

            if rejection_reason:
                if provides_requirement or has_utility:
                    self.debug_rejected.append({
                        "name": item.name, 
                        "slot": item.slot, 
                        "reason": rejection_reason,
                        "utility": has_utility
                    })
                continue 

            if provides_requirement or has_utility or item in locked_item_objects:
                s_key = item.slot 
                if s_key not in raw_candidates: raw_candidates[s_key] = []
                raw_candidates[s_key].append(item)

        # Phase 2: Refined filtering (Best Versions)
        # We must ALWAYS include Locked Items in the final list, even if they aren't "best score"
        final_candidates = {}
        for slot, items in raw_candidates.items():
            grouped_candidates = defaultdict(list)

            for item in items:
                identity = item.wiki_slug if item.wiki_slug else item.name
                if item.slot == EquipmentSlot.TOOLS: dummy_set.tools = [item]
                elif item.slot == EquipmentSlot.RING: dummy_set.rings = [item]
                else:
                    attr_name = item.slot
                    if hasattr(dummy_set, attr_name): setattr(dummy_set, attr_name, item)
                
                score = self.calculate_score(dummy_set, activity, player_skill_level, target, context, ignore_requirements=True)
                q_rank = QUALITY_RANK.get(item.quality, -1)
                
                dummy_set.tools = []; dummy_set.rings = []
                if item.slot != EquipmentSlot.TOOLS and item.slot != EquipmentSlot.RING:
                     attr_name = item.slot
                     if hasattr(dummy_set, attr_name): setattr(dummy_set, attr_name, None)

                grouped_candidates[identity].append((score, q_rank, item))
            
            slot_candidates = []
            keep_count = 2 if slot == EquipmentSlot.RING else 1

            for identity, entries in grouped_candidates.items():
                entries.sort(key=lambda x: (x[0], x[1]), reverse=True)
                
                # Check if any item in entries is LOCKED. If so, force add it.
                locked_indices = []
                for idx, (_, _, itm) in enumerate(entries):
                    if itm in locked_item_objects:
                        slot_candidates.append(itm)
                        locked_indices.append(idx)
                
                # Add best items (excluding ones we just added to avoid dupes if they are the best)
                added = 0
                for idx, (_, _, itm) in enumerate(entries):
                    if idx in locked_indices: continue # Already added
                    if added < keep_count:
                        slot_candidates.append(itm)
                        added += 1
                    else: break

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
                    if isinstance(i, Pet): continue
                    all_ids.append(i.id)
                sig = tuple(sorted(all_ids))
                if sig not in unique_signatures:
                    unique_signatures.add(sig)
                    results.append((gs, locked_slots.copy()))
                return

            req = req_list[index]
            options = providers.get(req, [])
            found_existing = False
            
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
        if not results: return [(GearSet(), set())]
        return results

    # --- Optimizer Logic ---

    def _optimize_set(self, current_set, locked_slots, fixed_rings, fixed_tools, 
                      candidates, activity, player_skill_level, target, context, tool_slots, owned_counts, passive_stats):
        # locked_slots: set of strings (e.g. "head", "chest")
        # fixed_rings: list of Items that MUST be in rings
        # fixed_tools: list of Items that MUST be in tools
        
        # 1. Capture Initial State 
        # (Current set already contains merged skeleton + locks)
        
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
                    if attr in locked_slots: continue # SKIP LOCKED SLOTS
                    
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
            # fixed_rings contains items that must stay.
            # current_set.rings contains those + potentially skeleton items.
            # We can remove skeleton items if something better is found, but NOT fixed ones.
            
            # Start fresh with fixed rings
            available_ring_slots = 2 - len(fixed_rings)
            
            if available_ring_slots > 0:
                current_rings = list(current_set.rings)
                # Keep fixed rings
                working_rings = list(fixed_rings)
                
                # Add existing non-fixed rings if they fit (prioritizing current state)
                for r in current_rings:
                    if len(working_rings) < 2 and r not in working_rings:
                        working_rings.append(r)
                
                current_set.rings = working_rings
                
                ring_cands = candidates.get(EquipmentSlot.RING, [])
                if ring_cands:
                    top_rings = self._sort_items_by_utility(ring_cands, current_set, activity, player_skill_level, target, context, passive_stats)[:10]
                    
                    # Fill / Swap free slots
                    # Simple approach: If < 2 rings, try adding. Then try swapping the NON-FIXED ring.
                    
                    # 1. Fill empty
                    while len(current_set.rings) < 2:
                        best_r = None
                        max_r = base_score
                        for r in top_rings:
                            if r in current_set.rings: 
                                if owned_counts:
                                    # If fixed ring uses 1, we need 2 total
                                    needed = current_set.rings.count(r) + 1
                                    if self._get_available_count(r, owned_counts) < needed: continue
                                else:
                                    if current_set.rings.count(r) >= 2: continue

                            current_set.rings.append(r)
                            score = self.calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
                            if score > max_r:
                                max_r = score
                                best_r = r
                            current_set.rings.pop()
                        
                        if best_r:
                            current_set.rings.append(best_r)
                            base_score = max_r
                        else:
                            break
                    
                    # 2. Swap non-fixed rings (if any)
                    # Identify indices of fixed rings to skip
                    # It's easier to iterate slots 0, 1. If slot i is fixed, skip.
                    
                    # Since rings is a list, and order doesn't matter, 
                    # we just iterate the Non-Fixed portion.
                    # Re-detect fixed items in current list (by ID match)
                    
                    # Construct a list of indices we can modify
                    fixed_ids = [fr.id for fr in fixed_rings]
                    modifiable_indices = []
                    for i, r in enumerate(current_set.rings):
                        # Simple logic: if we have 1 fixed ring, find it and mark used. The other is modifiable.
                        # Handle duplicate items correctly.
                        if r in fixed_rings:
                            # If duplicate fixed items, we need to be careful.
                            # Just rebuild: fixed rings + free rings.
                            pass
                    
                    # Easier: Always optimize by rebuilding: Fixed + Best Combo of (2 - len(Fixed))
                    # Brute force standard rings is cheap (max 10 choose 2 = 45)
                    
                    best_combo = []
                    if available_ring_slots == 1:
                        # Find 1 best ring to add to Fixed
                        max_r = -float('inf')
                        for r in top_rings:
                            test_rings = fixed_rings + [r]
                            current_set.rings = test_rings
                            score = self.calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
                            if score > max_r:
                                if self._is_valid_ring_set(test_rings, owned_counts, fixed_rings):
                                    max_r = score
                                    best_combo = [r]
                        if best_combo:
                            current_set.rings = fixed_rings + best_combo
                            base_score = max_r
                            
                    elif available_ring_slots == 2:
                        # Find 2 best rings
                        max_r = -float('inf')
                        # Try empty (if allowed? usually we want rings)
                        # Try 1 ring
                        # Try 2 rings
                        import itertools
                        # Add None as option for combinations?
                        # Just iterate combinations of top_rings
                        for r_cnt in range(1, 3):
                            for combo in itertools.combinations(top_rings, r_cnt):
                                test_rings = fixed_rings + list(combo)
                                current_set.rings = test_rings
                                score = self.calculate_score(current_set, activity, player_skill_level, target, context, passive_stats=passive_stats)
                                if score > max_r:
                                    if self._is_valid_ring_set(test_rings, owned_counts, fixed_rings):
                                        max_r = score
                                        best_combo = list(combo)
                        if best_combo:
                            current_set.rings = fixed_rings + best_combo
                            base_score = max_r

            # --- C. Tools ---
            # Same logic: Fixed tools stay. Optimize the rest.
            
            available_tool_slots = tool_slots - len(fixed_tools)
            
            if available_tool_slots > 0:
                tool_cands = candidates.get(EquipmentSlot.TOOLS, [])
                # Filter out fixed tools from candidates only if unique limits apply? 
                # Just let the brute force checker handle validity.
                
                # Valid candidates for filling spots:
                # - Not already in fixed tools (unless duplicates allowed/owned)
                # - Standard sort
                valid_cands = []
                for t in tool_cands:
                    if t not in fixed_tools: valid_cands.append(t)
                    # If it IS in fixed tools, we can only add it again if we own > 1.
                    # The `_optimized_brute_force_tools` does validity checking.
                
                sorted_cands = self._sort_items_by_utility(valid_cands, current_set, activity, player_skill_level, target, context, passive_stats)
                
                # Use the optimized function, passing 'fixed_tools' as the base
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
                    # Fallback for massive lists (unlikely in this game)
                    current_subset = []
                    max_t = base_score
                    for t in sorted_cands:
                        if len(current_subset) >= available_tool_slots: break
                        test_tools = fixed_tools + current_subset + [t]
                        if self._is_valid_tool_set(test_tools, owned_counts, fixed_tools):
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
        
        orig_tools = current_set.tools
        current_set.tools = fixed_tools
        base_stats_gear = current_set.get_stats(context)
        current_set.tools = orig_tools 

        base_stats = defaultdict(float, base_stats_gear)
        for k, v in passive_stats.items():
            base_stats[k] += v

        fixed_slugs = set()
        fixed_keywords = set()
        for t in fixed_tools:
            if t.wiki_slug: fixed_slugs.add(t.wiki_slug)
            for k in t.keywords:
                lk = k.lower()
                if lk in self.restricted_keywords_lower:
                    fixed_keywords.add(lk)
        
        user_ap = context.get("achievement_points", 0)
        total_lvl = context.get("total_skill_level", 0)

        light_candidates = [] 
        
        for item in candidates:
            # Skip if unique slug is already fixed
            if item.wiki_slug and item.wiki_slug in fixed_slugs: 
                 # Unless we own multiple? Wiki slug usually implies uniqueness in equip? 
                 # Actually game logic: Unique items usually can't equip 2.
                 # Assuming wiki_slug implies uniqueness for now.
                 continue
            
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

        best_subset = None
        best_val = current_best_score

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
                         # Check validity including fixed items is handled in _is_valid_tool_set
                         test_tools = fixed_tools + [c["item"] for c in combo]
                         if not self._is_valid_tool_set(test_tools, owned_counts, fixed_tools):
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
        for item in items:
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
            
            score = self.calculate_score(current_set, activity, player_skill_level, target, context, ignore_requirements=True, passive_stats=passive_stats)
            scored.append((score, item))
            
            if added:
                if item.slot == EquipmentSlot.TOOLS: current_set.tools.pop()
                elif item.slot == EquipmentSlot.RING: current_set.rings.pop()
            else:
                attr_name = item.slot
                if hasattr(current_set, attr_name): 
                    setattr(current_set, attr_name, old_val)

        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored]

    def _is_valid_ring_set(self, rings: List[Equipment], owned_counts: Dict[str, int], fixed_rings: List[Equipment]) -> bool:
        # Check ownership validity
        if not owned_counts: return True
        counts = PyCounter()
        for r in rings:
            counts[r.id.lower()] += 1
        
        # NOTE: Fixed rings bypass ownership checks.
        # So we only check if available count (from user) >= needed count (total - fixed matches)
        # But simply: If user forced a lock, we assume they have it (or want to sim it).
        # We only check validity for the NEWLY added items.
        
        # However, if user owns 1 ring, locks it, and we try to add a 2nd identical ring,
        # we must check if they own 2.
        
        # Correct logic:
        # User owned: X
        # Locked: L (Assume infinite supply for L, OR assume L consumes X?)
        # Standard: User locks items they have.
        # But simulation mode: User locks items they DON'T have.
        
        # Implementation:
        # For each unique item ID in 'rings':
        #   total_needed = count in 'rings'
        #   locked_count = count in 'fixed_rings'
        #   freely_added = total_needed - locked_count
        #   if freely_added > available_owned: return False
        
        # But wait, if I have 1 ring, lock it. freely_added = 0. OK.
        # If I have 1 ring, don't lock. freely_added = 1. OK.
        # If I have 1 ring, lock it, and opt tries to add another. freely_added = 1.
        #   User has 1. Locked uses 1 (bypassed). 
        #   Does user have 1 *remaining*? 
        #   The standard `_get_available_count` returns TOTAL owned.
        #   So we should check: owned >= freely_added + locked_real_owned?
        
        # SIMPLIFIED LOGIC per requirements: "manual lock will bypass the user owned items"
        # This implies locked items are "free".
        # So we only validate the items that are NOT locked.
        
        # We need to map object instances to know which are fixed.
        # Since 'rings' is a new list, we match by ID? Or object identity if preserved.
        # Object identity is preserved in my logic.
        
        non_locked_items = []
        # Create a copy of fixed rings to match against
        temp_fixed = list(fixed_rings)
        
        for r in rings:
            if r in temp_fixed:
                temp_fixed.remove(r)
            else:
                non_locked_items.append(r)
        
        if not non_locked_items: return True
        
        # Now check if we own the non-locked items
        needed_counts = PyCounter()
        for x in non_locked_items: needed_counts[x.id.lower()] += 1
        
        # We must also account for the fact that we might own the locked item, 
        # and using it in lock shouldn't consume it from the pool available for non-locked spots?
        # Actually, if I have 1 ring, lock it. I shouldn't be able to equip a 2nd one in free slot.
        # So Locked Items MUST consume ownership if they exist in ownership.
        
        # Re-eval:
        # Total Needed = Count in Ring Set
        # Total Owned = User Inventory
        # Locked Items = Bypass Ownership (count as Owned even if 0)
        
        # Effective Owned = max(Real Owned, Count of Locked instances of this item)
        # Wait, if I have 0, lock 1. Effective = 1.
        # If I have 1, lock 1. Effective = 1.
        
        # Logic:
        # For each item ID:
        #   User Owned = N
        #   Locked Count = L
        #   Total Equipped = T
        #   If T <= L: Valid (all covered by locks)
        #   Else: (T - L) must be <= (N - L_real_owned) ??? No.
        
        #   Let's assume Locks provide "Virtual Copies".
        #   If I lock 1 Ring, I have a virtual copy.
        #   If I want to equip a 2nd Ring (same ID), I need a Real Copy that isn't the Virtual One?
        #   Or does the Virtual Copy consume the Real Copy?
        
        #   Standard Interpretation:
        #   Locks consume real items first. If run out, they use magic.
        #   So Remaining Owned = max(0, Owned - Locked Count).
        #   Free Slots must be filled using Remaining Owned.
        
        id_counts = PyCounter()
        for r in rings: id_counts[r.id.lower()] += 1
        
        fixed_counts = PyCounter()
        for r in fixed_rings: fixed_counts[r.id.lower()] += 1
        
        for item_id, total_needed in id_counts.items():
            locked_c = fixed_counts[item_id]
            
            # We only need to validate the amount EXCEEDING the locked amount
            extra_needed = total_needed - locked_c
            if extra_needed > 0:
                # We need 'extra_needed' more copies from inventory.
                # Does inventory have them?
                # We assume locks consume inventory.
                owned = owned_counts.get(item_id, 0)
                # Suffix check
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

    def _is_valid_tool_set(self, tools: List[Equipment], owned_counts: Optional[Dict[str, int]], fixed_tools: List[Equipment]) -> bool:
        seen_slugs = set()
        seen_keywords = set()
        
        # 1. Unique Restrictions
        for t in tools:
            if t.wiki_slug:
                if t.wiki_slug in seen_slugs: return False
                seen_slugs.add(t.wiki_slug)
            for k in t.keywords:
                if k in RESTRICTED_TOOL_KEYWORDS or k.lower() in self.restricted_keywords_lower:
                    norm_k = k.lower()
                    if norm_k in seen_keywords: return False
                    seen_keywords.add(norm_k)

        # 2. Ownership (with Locks Logic)
        if owned_counts:
            id_counts = PyCounter()
            for t in tools: 
                # Normalize ID logic? _get_available_count logic
                # Just use ID for now, suffixes handled inside count check
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