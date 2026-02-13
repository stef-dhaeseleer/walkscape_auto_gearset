from typing import List, Dict, Set, Optional, Any
from collections import defaultdict
from models import Equipment, Activity, GearSet, EquipmentSlot, RequirementType 
from calculations import calculate_score
from utils.constants import TARGET_TO_STATS, STAT_ENUM_TO_KEY, OPTIMAZATION_TARGET, QUALITY_RANK

class CandidateSelector:
    def __init__(self, all_items: List[Equipment]):
        self.all_items = all_items
        self.debug_rejected = []

    def get_candidates(self, 
                       activity: Activity, 
                       required_keywords: Dict[str, int], 
                       target: OPTIMAZATION_TARGET, 
                       context: Dict, 
                       player_skill_level: int,
                       owned_item_counts: Optional[Dict[str, int]] = None,
                       user_reputation: Optional[Dict[str, float]] = None,
                       blacklisted_ids: Set[str] = None,
                       locked_item_objects: Set[Equipment] = None) -> Dict[str, List[Equipment]]:
        
        self.debug_rejected = []
        raw_candidates = {}
        relevant_stats = TARGET_TO_STATS.get(target, set())
        
        if blacklisted_ids is None: blacklisted_ids = set()
        if locked_item_objects is None: locked_item_objects = set()

        dummy_set = GearSet() # For utility checking

        for item in self.all_items:
            rejection_reason = None
            
            # 0. Check Blacklist
            if item.id in blacklisted_ids and item not in locked_item_objects:
                is_locked = any(l.id == item.id for l in locked_item_objects)
                if not is_locked: continue

            # A. Check Ownership
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
                            rejection_reason = f"Low Reputation ({req.target})"
                            break
            
            # C. Check Activity Requirements (Keywords)
            provides_requirement = False
            if not rejection_reason:
                for kw in item.keywords:
                    norm = kw.lower().replace("_", " ").strip()
                    if norm in required_keywords:
                        provides_requirement = True
                        break
            
            # D. Check Utility
            has_utility = False
            # Clean dummy set
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
                        "name": item.name, "slot": item.slot, "reason": rejection_reason
                    })
                continue 

            if provides_requirement or has_utility or item in locked_item_objects:
                s_key = item.slot 
                if s_key not in raw_candidates: raw_candidates[s_key] = []
                raw_candidates[s_key].append(item)

        # Phase 2: Refined filtering (Best Quality Versions)
        final_candidates = {}
        for slot, items in raw_candidates.items():
            grouped_candidates = defaultdict(list)

            for item in items:
                identity = item.wiki_slug if item.wiki_slug else item.name
                # Setup dummy for scoring
                dummy_set.tools = []; dummy_set.rings = []
                for s in ["head", "chest", "legs", "feet", "back", "cape", "neck", "hands", "primary", "secondary"]:
                    setattr(dummy_set, s, None)

                if item.slot == EquipmentSlot.TOOLS: dummy_set.tools = [item]
                elif item.slot == EquipmentSlot.RING: dummy_set.rings = [item]
                else:
                    attr_name = item.slot
                    if hasattr(dummy_set, attr_name): setattr(dummy_set, attr_name, item)
                
                score = calculate_score(dummy_set, activity, player_skill_level, target, context, ignore_requirements=True)
                q_rank = QUALITY_RANK.get(item.quality, -1)
                grouped_candidates[identity].append((score, q_rank, item))
            
            slot_candidates = []
            keep_count = 2 if slot == EquipmentSlot.RING else 1

            for identity, entries in grouped_candidates.items():
                entries.sort(key=lambda x: (x[0], x[1]), reverse=True)
                
                locked_indices = []
                for idx, (_, _, itm) in enumerate(entries):
                    if itm in locked_item_objects:
                        slot_candidates.append(itm)
                        locked_indices.append(idx)
                
                added = 0
                for idx, (_, _, itm) in enumerate(entries):
                    if idx in locked_indices: continue 
                    if added < keep_count:
                        slot_candidates.append(itm)
                        added += 1
                    else: break

            final_candidates[slot] = slot_candidates

        return final_candidates

    def sort_items_by_utility(self, items: List[Equipment], current_set: GearSet, 
                              activity, player_skill_level, target, context, passive_stats) -> List[Equipment]:
        """Sorts a list of items based on how much they improve the CURRENT set's score."""
        scored = []
        for item in items:
            added = False
            old_val = None
            
            # Temporarily equip
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
            
            score = calculate_score(current_set, activity, player_skill_level, target, context, ignore_requirements=True, passive_stats=passive_stats)
            scored.append((score, item))
            
            # Revert
            if added:
                if item.slot == EquipmentSlot.TOOLS: current_set.tools.pop()
                elif item.slot == EquipmentSlot.RING: current_set.rings.pop()
            else:
                attr_name = item.slot
                if hasattr(current_set, attr_name): 
                    setattr(current_set, attr_name, old_val)

        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored]

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