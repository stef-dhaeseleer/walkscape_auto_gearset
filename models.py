from enum import Enum
from typing import List, Optional, Dict, Set, Tuple
from collections import defaultdict, Counter
from pydantic import BaseModel, Field

# ============================================================================
# ENUMS
# ============================================================================

class EquipmentQuality(str, Enum):
    NORMAL = "Normal"
    GOOD = "Good"
    GREAT = "Great"
    EXCELLENT = "Excellent"
    PERFECT = "Perfect"
    ETERNAL = "Eternal"
    NONE = "None" 

class EquipmentSlot(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    HEAD = "head"
    CHEST = "chest"
    LEGS = "legs"
    FEET = "feet"
    TOOLS = "tools"
    RING = "ring"
    NECK = "neck"
    CAPE = "cape"
    BACK = "back"
    HANDS = "hands"
    UNKNOWN = "unknown"

class SkillName(str, Enum):
    AGILITY = "agility"
    CARPENTRY = "carpentry"
    COOKING = "cooking"
    CRAFTING = "crafting"
    FISHING = "fishing"
    FORAGING = "foraging"
    MINING = "mining"
    SMITHING = "smithing"
    TRINKETRY = "trinketry"
    WOODCUTTING = "woodcutting"
    TRAVELING = "traveling"
    NONE = "none"

# --- SKILL CATEGORIES ---
GATHERING_SKILLS = {
    "foraging", "mining", "woodcutting", "fishing"
}

ARTISAN_SKILLS = {
    "smithing", "carpentry", "trinketry", "crafting", "cooking"
}

class ConditionType(str, Enum):
    GLOBAL = "global"
    LOCATION = "location"           
    REGION = "region"               
    SKILL_ACTIVITY = "skill_activity"    
    SPECIFIC_ACTIVITY = "specific_activity" 
    ACHIEVEMENT_POINTS = "achievement_points" 
    ITEM_OWNERSHIP = "item_ownership"
    SET_EQUIPPED = "set_equipped"
    TOTAL_SKILL_LEVEL = "total_skill_level"
    ACTIVITY_COMPLETION = "activity_completion"
    REPUTATION = "reputation"


class RequirementType(str, Enum):
    SKILL_LEVEL = "skill_level"
    QUEST_COMPLETED = "quest_completed"
    REPUTATION = "reputation"
    CHARACTER_LEVEL = "character_level"
    KEYWORD_COUNT = "keyword_count"       
    ACTIVITY_COMPLETION = "activity_completion" 
    ACHIEVEMENT_POINTS = "achievement_points" 
    TOOL_EQUIPPED = "tool_equipped"
    UNIQUE_TOOLS = "unique_tools"

class StatName(str, Enum):
    # Core
    WORK_EFFICIENCY = "work_efficiency"
    DOUBLE_ACTION = "double_action"
    DOUBLE_REWARDS = "double_rewards"
    NO_MATERIALS_CONSUMED = "no_materials_consumed"
    QUALITY_OUTCOME = "quality_outcome"
    
    # Steps
    STEPS_ADD = "steps_add"
    STEPS_PERCENT = "steps_percent"
    XP_PERCENT = "xp_percent" 
    
    # XP (Legacy/Variations)
    BONUS_XP_ADD = "bonus_xp_add"
    BONUS_XP_PERCENT = "bonus_xp_percent"
    
    # Finding
    CHEST_FINDING = "chest_finding"
    FIND_BIRD_NESTS = "find_bird_nests"
    FIND_COLLECTIBLES = "find_collectibles"
    FIND_GEMS = "find_gems"
    FINE_MATERIAL_FINDING = "fine_material_finding"
    
    # Finding Items
    FIND_ADVENTURERS_GUILD_TOKEN = "find_adventurers_guild_token"
    FIND_FISHING_BAIT = "find_fishing_bait"
    FIND_CRUSTACEAN = "find_crustacean"
    FIND_ECTOPLASM = "find_ectoplasm"
    FIND_GOLD = "find_gold"
    FIND_COIN_POUCH = "find_coin_pouch"
    FIND_JUNK = "find_junk"
    FIND_SEA_SHELLS = "find_sea_shells"
    FIND_GOLD_NUGGET = "find_gold_nugget"
    FIND_SKILL_CHEST = "find_skill_chest"
    
    INVENTORY_SPACE = "inventory_space"

# ============================================================================
# MODELS
# ============================================================================

class Condition(BaseModel):
    type: ConditionType
    target: Optional[str] = None 
    value: Optional[int] = None
    
    class Config:
        frozen = True

class Modifier(BaseModel):
    stat: StatName
    value: float
    conditions: Tuple[Condition, ...] = Field(default_factory=tuple)

    class Config:
        frozen = True

class Requirement(BaseModel):
    type: RequirementType
    target: Optional[str] = None     
    value: int             

    class Config:
        frozen = True

class DropEntry(BaseModel):
    item_id: str          
    min_quantity: int
    max_quantity: int
    chance: Optional[float] = None 
    
    class Config:
        frozen = True

class FactionReward(BaseModel):
    faction_id: str       
    amount: float

    class Config:
        frozen = True

class BaseEntity(BaseModel):
    id: str
    wiki_slug: str
    name: str

    class Config:
        frozen = True

class BaseItem(BaseEntity):      
    value: int          
    keywords: Tuple[str, ...] = Field(default_factory=tuple)

class Collectible(BaseEntity):
    modifiers: Tuple[Modifier, ...] = Field(default_factory=tuple)

    class Config:
        use_enum_values = True
        frozen = True

class Service(BaseEntity):
    skill: SkillName
    tier: str
    location: str
    requirements: Tuple[Requirement, ...] = Field(default_factory=tuple)
    modifiers: Tuple[Modifier, ...] = Field(default_factory=tuple)

    class Config:
        use_enum_values = True
        frozen = True
 
class Equipment(BaseItem):
    uuid: str = ""
    slot: EquipmentSlot
    quality: EquipmentQuality
    requirements: Tuple[Requirement, ...] = Field(default_factory=tuple) 
    modifiers: Tuple[Modifier, ...] = Field(default_factory=tuple)      
    
    @property
    def skill(self) -> str:
        skills = set()
        for req in self.requirements:
            if req.type == RequirementType.SKILL_LEVEL and req.target:
                skills.add(req.target.lower())
        for mod in self.modifiers:
            for cond in mod.conditions:
                if cond.type == ConditionType.SKILL_ACTIVITY and cond.target:
                    skills.add(cond.target.lower())
        return ",".join(skills) if skills else None

    @property
    def region(self) -> Optional[str]:
        for req in self.requirements:
            if req.type == RequirementType.REPUTATION: 
                return req.target 
        return None

    @property
    def is_underwater(self) -> bool:
        return "underwater" in self.keywords

    @property
    def clean_item_name(self) -> str:
        return self.name

    class Config:
        use_enum_values = True
        frozen = True

class Activity(BaseEntity):
    primary_skill: SkillName
    locations: Tuple[str, ...] = Field(default_factory=tuple) 
    base_steps: int = 0
    base_xp: float = 0.0
    secondary_xp: Dict[SkillName, float] = Field(default_factory=dict)
    max_efficiency: float = 0.0 
    requirements: Tuple[Requirement, ...] = Field(default_factory=tuple)
    faction_rewards: Tuple[FactionReward, ...] = Field(default_factory=tuple)
    drops: Tuple[DropEntry, ...] = Field(default_factory=tuple)
    secondary_drops: Tuple[DropEntry, ...] = Field(default_factory=tuple)
    modifiers: Tuple[Modifier, ...] = Field(default_factory=tuple) # Support for synthesized activities
    
    @property
    def level(self) -> int:
        for req in self.requirements:
            if req.type == RequirementType.SKILL_LEVEL and req.target:
                if req.target.lower() == self.primary_skill.lower():
                    return req.value
        return 1 

    class Config:
        use_enum_values = True
        frozen = True

class RecipeMaterial(BaseModel):
    item_id: str
    amount: int
    
    class Config:
        frozen = True

class Recipe(BaseEntity):
    skill: SkillName
    level: int
    service: str 
    output_item_id: str
    output_quantity: int
    materials: Tuple[Tuple[RecipeMaterial, ...], ...] = Field(default_factory=tuple)
    base_xp: float = 0.0
    base_steps: int = 0
    max_efficiency: float = 0.0

    class Config:
        use_enum_values = True
        frozen = True

class Location(BaseEntity):
    tags: Tuple[str, ...] = Field(default_factory=tuple)

    class Config:
        use_enum_values = True
        frozen = True

# ============================================================================
# GEARSET
# ============================================================================

class GearSet(BaseModel):
    head: Optional[Equipment] = None
    chest: Optional[Equipment] = None
    legs: Optional[Equipment] = None
    feet: Optional[Equipment] = None
    back: Optional[Equipment] = None
    cape: Optional[Equipment] = None
    neck: Optional[Equipment] = None
    hands: Optional[Equipment] = None
    primary: Optional[Equipment] = None
    secondary: Optional[Equipment] = None
    
    pet: Optional[Equipment] = None          
    consumable: Optional[Equipment] = None   

    rings: List[Equipment] = Field(default_factory=list)
    tools: List[Equipment] = Field(default_factory=list)

    def get_all_items(self) -> List[Equipment]:
        items = [
            self.head, self.chest, self.legs, self.feet,
            self.back, self.cape, self.neck, self.hands,
            self.primary, self.secondary, self.pet, self.consumable
        ]
        items.extend(self.rings)
        items.extend(self.tools)
        return [i for i in items if i]

    def get_keyword_counts(self) -> Counter:
        counts = Counter()
        for item in self.get_all_items():
            for kw in item.keywords:
                norm_kw = kw.lower().replace("_", " ").strip()
                counts[norm_kw] += 1
        return counts

    def get_stats(self, context: Dict[str, any] = None) -> Dict[str, float]:
        if context is None:
            context = {}

        active_skill = context.get("skill", "").lower() if context.get("skill") else None
        loc_id = context.get("location_id")
        loc_tags = set(t.lower() for t in context.get("location_tags", []))
        act_id = context.get("activity_id")

        stats = defaultdict(float)
        keyword_counts = self.get_keyword_counts()
        
        PERCENTAGE_STATS = {
            StatName.WORK_EFFICIENCY, StatName.DOUBLE_ACTION, StatName.DOUBLE_REWARDS,
            StatName.NO_MATERIALS_CONSUMED, StatName.STEPS_PERCENT, StatName.XP_PERCENT,
            StatName.BONUS_XP_PERCENT, StatName.CHEST_FINDING, StatName.FINE_MATERIAL_FINDING,
            StatName.FIND_BIRD_NESTS, StatName.FIND_COLLECTIBLES, StatName.FIND_GEMS,
        }

        for item in self.get_all_items():
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
                    
                    elif c_type == ConditionType.SET_EQUIPPED:
                        if not c_target: applies = False
                        else:
                            norm_target = c_target.replace("_", " ").strip()
                            if keyword_counts.get(norm_target, 0) < (c_val or 1): applies = False

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