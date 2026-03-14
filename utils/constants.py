from enum import Enum

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
    HUNTING = "hunting"        
    TAILORING = "tailoring"   
    NONE = "none"

# --- SKILL CATEGORIES ---
GATHERING_SKILLS = {
    "foraging", "mining", "woodcutting", "fishing" , "hunting"
}

ARTISAN_SKILLS = {
    "smithing", "carpentry", "trinketry", "crafting", "cooking", "tailoring"
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
    SPECIFIC_ACTIVITY = "specific_activity"

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
    CHANCE_TO_FIND_BIRD_NEST = "chance_to_find_bird_nest"
    INVENTORY_SPACE = "inventory_space"

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

class OPTIMAZATION_TARGET(str, Enum):
    reward_rolls = "reward_rolls"
    xp = "xp"
    chests = "chests"
    materials_from_input = "materials_from_input"
    fine = "fine"
    eternal_per_input = "eternal_per_input"
    good_per_step = "good_per_step"
    great_per_step = "great_per_step"
    excellent_per_step = "excellent_per_step"
    perfect_per_step = "perfect_per_step"
    eternal_per_step = "eternal_per_step"
    tokens_per_step = "tokens_per_step"
    ectoplasm_per_step = "ectoplasm_per_step"
    gems = "gems"
    collectibles = "collectibles"
    coins = "coins"
    coins_no_chests = "coins_no_chests"
    coins_no_fines = "coins_no_fines"
    coins_no_chests_no_fines = "coins_no_chests_no_fines"
    
    exp_no_steps = "exp_no_steps"
    chests_no_steps = "chests_no_steps"
    reward_rolls_no_steps = "reward_rolls_no_steps"
    fine_no_steps = "fine_no_steps"

# Correct Set Union Syntax using |
REWARD_ROLL_STATS = {StatName.DOUBLE_ACTION, StatName.DOUBLE_REWARDS, StatName.WORK_EFFICIENCY, StatName.STEPS_ADD, StatName.STEPS_PERCENT}
COIN_BASE_STATS = REWARD_ROLL_STATS | {StatName.FIND_GOLD, StatName.FIND_COIN_POUCH}
TARGET_TO_STATS = {
    OPTIMAZATION_TARGET.reward_rolls: REWARD_ROLL_STATS,
    OPTIMAZATION_TARGET.xp: {StatName.BONUS_XP_ADD, StatName.BONUS_XP_PERCENT, StatName.DOUBLE_ACTION, StatName.WORK_EFFICIENCY, StatName.STEPS_ADD, StatName.STEPS_PERCENT},
    OPTIMAZATION_TARGET.chests: REWARD_ROLL_STATS | {StatName.CHEST_FINDING},
    OPTIMAZATION_TARGET.materials_from_input: {StatName.DOUBLE_REWARDS, StatName.NO_MATERIALS_CONSUMED},
    OPTIMAZATION_TARGET.fine: REWARD_ROLL_STATS | {StatName.FINE_MATERIAL_FINDING},
    OPTIMAZATION_TARGET.collectibles: REWARD_ROLL_STATS | {StatName.FIND_COLLECTIBLES},
    OPTIMAZATION_TARGET.eternal_per_input: {StatName.QUALITY_OUTCOME, StatName.DOUBLE_REWARDS, StatName.NO_MATERIALS_CONSUMED},
    OPTIMAZATION_TARGET.good_per_step: REWARD_ROLL_STATS | {StatName.QUALITY_OUTCOME},
    OPTIMAZATION_TARGET.great_per_step: REWARD_ROLL_STATS | {StatName.QUALITY_OUTCOME},
    OPTIMAZATION_TARGET.excellent_per_step: REWARD_ROLL_STATS | {StatName.QUALITY_OUTCOME},
    OPTIMAZATION_TARGET.perfect_per_step: REWARD_ROLL_STATS | {StatName.QUALITY_OUTCOME},
    OPTIMAZATION_TARGET.eternal_per_step: REWARD_ROLL_STATS | {StatName.QUALITY_OUTCOME},
    
    OPTIMAZATION_TARGET.tokens_per_step: REWARD_ROLL_STATS | {StatName.FIND_ADVENTURERS_GUILD_TOKEN},
    OPTIMAZATION_TARGET.ectoplasm_per_step: REWARD_ROLL_STATS | {StatName.FIND_ECTOPLASM},
    OPTIMAZATION_TARGET.gems: REWARD_ROLL_STATS | {StatName.FIND_GEMS},
    OPTIMAZATION_TARGET.coins: COIN_BASE_STATS | {StatName.CHEST_FINDING, StatName.FINE_MATERIAL_FINDING},
    OPTIMAZATION_TARGET.coins_no_chests: COIN_BASE_STATS | {StatName.FINE_MATERIAL_FINDING},
    OPTIMAZATION_TARGET.coins_no_fines: COIN_BASE_STATS | {StatName.CHEST_FINDING},
    OPTIMAZATION_TARGET.coins_no_chests_no_fines: COIN_BASE_STATS,

    OPTIMAZATION_TARGET.exp_no_steps: {StatName.BONUS_XP_ADD, StatName.BONUS_XP_PERCENT, StatName.DOUBLE_ACTION},
    OPTIMAZATION_TARGET.chests_no_steps: {StatName.DOUBLE_ACTION, StatName.DOUBLE_REWARDS, StatName.CHEST_FINDING},
    OPTIMAZATION_TARGET.reward_rolls_no_steps: {StatName.DOUBLE_ACTION, StatName.DOUBLE_REWARDS},
    OPTIMAZATION_TARGET.fine_no_steps: {StatName.DOUBLE_ACTION, StatName.DOUBLE_REWARDS, StatName.FINE_MATERIAL_FINDING},
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
class ActivityLootTableType(str, Enum):
    MAIN = "main"
    SECONDARY = "secondary"
    GEM = "gem"
    # Fallback for unknown tables
    OTHER = "other"




FISHING_BAIT_TABLE = [
    ("bug_bait", 0.50),
    ("frozen_bait", 0.50)
]

GEM_TABLE = [
    ("rough_opal", 0.29851),
    ("rough_star_pearl", 0.29851),
    ("rough_topaz", 0.14925),
    ("rough_wrentmarine", 0.14925),
    ("rough_jade", 0.04975),
    ("rough_ruby", 0.02985),
    ("rough_sun_stone", 0.01990),
    ("rough_ethernite", 0.00498)
]

JUNK_TABLE = [
    ("trash", 0.51546),
    ("fishbone", 0.10309),
    ("grass", 0.07732),
    ("mud", 0.07732),
    ("milkweed", 0.05155),
    ("moondaisy", 0.05155),
    ("sea_shell", 0.05155),
    ("birch_skis", 0.01546),
    ("clay_skydisc", 0.01546),
    ("rough_opal", 0.01546),
    ("simple_torch", 0.01546),
    ("rusty_chest", 0.00515),
    ("sunken_chest", 0.00515)
]

# Mapping from Stat Key to Item ID (or Table)
SPECIAL_FIND_MAP = {
    "chance_to_find_bird_nest": "bird_nest",
    "find_coin_pouch": "coin_pouch",
    "find_gold_nugget": "gold_nugget",
    "find_adventurers_guild_token": "adventurers_guild_token",
    "find_ectoplasm": "ectoplasm",
    "find_sea_shells": "sea_shell",
    "find_fishing_bait": FISHING_BAIT_TABLE,
    "find_junk": JUNK_TABLE,
}


class ChestTableCategory(str, Enum):
    """Categories for Container/Chest drops."""
    MAIN = "Main"
    VALUABLES = "Valuables"
    COMMON = "Common"
    UNCOMMON = "Uncommon"
    RARE = "Rare"
    EPIC = "Epic"
    LEGENDARY = "Legendary"
    ETHEREAL = "Ethereal"
    OTHER = "Other"

DOMINANCE_EXEMPT_ITEMS = {
    "spectral_saw_common",
    "spectral_saw_uncommon",
    "spectral_saw_rare",
    "spectral_saw_epic",
    "spectral_saw_legendary",
    "spectral_saw_ethereal",

}

INSTANT_ACTION_PET_ABILITIES = {
    "Pecking Order": { # Chicken
        "allowed_source_types": ["activity"],
        "skill": "foraging"
    },
    "Shell Forge": { # Tortoise
        "allowed_source_types": ["recipe"],
        "skill": "smithing",
        "recipe_name_contains": "smelt" 
    },
}