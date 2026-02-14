import pytest
from typing import List
from models import Equipment, Activity, Location, Modifier, Requirement, Condition
from utils.constants import (
    EquipmentSlot, EquipmentQuality, StatName, ConditionType, 
    RequirementType, SkillName, OPTIMAZATION_TARGET
)

@pytest.fixture
def basic_context():
    return {
        "skill": "mining",
        "location_id": "loc_test",
        "location_tags": {"surface"},
        "activity_id": "mining_copper",
        "required_keywords": {},
        "achievement_points": 0,
        "total_skill_level": 100
    }

@pytest.fixture
def mock_locations():
    return [
        Location(id="loc_test", wiki_slug="loc_test", name="Test Location", tags=("surface",))
    ]

@pytest.fixture
def mock_activity():
    """
    Standard Mining Activity with max_efficiency set to 2.0.
    """
    return Activity(
        id="mining_copper", 
        wiki_slug="mining_copper", 
        name="Mining",
        primary_skill="mining", 
        locations=("loc_test",), 
        base_steps=100,
        max_efficiency=2.0
    )

@pytest.fixture
def mock_activity_light_req():
    """
    Mining Activity that requires a Light Source.
    """
    return Activity(
        id="cave_mining", 
        wiki_slug="cave", 
        name="Cave", 
        primary_skill="mining",
        locations=("loc_test",),
        base_steps=100,
        max_efficiency=2.0,
        requirements=[Requirement(type=RequirementType.KEYWORD_COUNT, target="Light Source", value=1)]
    )

@pytest.fixture
def mock_items() -> List[Equipment]:
    return [
        # --- HEAD ---
        Equipment(
            id="helm_basic", wiki_slug="helm_basic", name="Basic Helm", 
            slot=EquipmentSlot.HEAD, quality=EquipmentQuality.NORMAL, value=10,
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=2)] # Buffed 1 -> 2
        ),
        Equipment(
            id="helm_pro", wiki_slug="helm_pro", name="Pro Helm", 
            slot=EquipmentSlot.HEAD, quality=EquipmentQuality.EXCELLENT, value=100,
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=5)] # Buffed 2 -> 5
        ),
        Equipment(
            id="helm_miner", wiki_slug="helm_miner", name="Miner Helm", 
            slot=EquipmentSlot.HEAD, quality=EquipmentQuality.GOOD, value=50,
            modifiers=[
                Modifier(stat=StatName.WORK_EFFICIENCY, value=10, # Buffed 3 -> 10
                         conditions=[Condition(type=ConditionType.SKILL_ACTIVITY, target="mining")])
            ]
        ),

        # --- CHEST ---
        Equipment(
            id="chest_weak", wiki_slug="chest_weak", name="Weak Chest", 
            slot=EquipmentSlot.CHEST, quality=EquipmentQuality.NORMAL, value=10,
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=2)] # Buffed 1 -> 2
        ),
        Equipment(
            id="chest_strong_req", wiki_slug="chest_strong_req", name="Strong Chest (High Lvl)", 
            slot=EquipmentSlot.CHEST, quality=EquipmentQuality.NORMAL, value=100,
            requirements=[Requirement(type=RequirementType.SKILL_LEVEL, target="mining", value=80)],
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=20)] # Buffed 5 -> 20
        ),

        # --- RINGS ---
        Equipment(
            id="ring_gold", wiki_slug="ring_gold", name="Gold Ring", 
            slot=EquipmentSlot.RING, quality=EquipmentQuality.NORMAL, value=50,
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=2)] # Buffed 1 -> 2
        ),
        Equipment(
            id="ring_silver", wiki_slug="ring_silver", name="Silver Ring", 
            slot=EquipmentSlot.RING, quality=EquipmentQuality.NORMAL, value=20,
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=1)] # Buffed 0.5 -> 1
        ),
        Equipment(
            id="ring_trash", wiki_slug="ring_trash", name="Trash Ring", 
            slot=EquipmentSlot.RING, quality=EquipmentQuality.NORMAL, value=1,
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=0.1)]
        ),

        # --- TOOLS ---
        # Note: Tools kept at +2 WE. With the nerfs above, +2 WE will now consistently reduce steps.
        Equipment(
            id="pickaxe_iron", wiki_slug="pickaxe_iron", name="Iron Pickaxe", 
            slot=EquipmentSlot.TOOLS, quality=EquipmentQuality.NORMAL, value=20,
            keywords=("Pickaxe",),
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=2)]
        ),
        Equipment(
            id="hammer_iron", wiki_slug="hammer_iron", name="Iron Hammer", 
            slot=EquipmentSlot.TOOLS, quality=EquipmentQuality.NORMAL, value=20,
            keywords=("Hammer",),
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=2)]
        ),
        Equipment(
            id="tool_generic_a", wiki_slug="tool_generic_a", name="Generic Tool A", 
            slot=EquipmentSlot.TOOLS, quality=EquipmentQuality.NORMAL, value=10,
            keywords=("GenericA",),
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=2)]
        ),
        Equipment(
            id="tool_generic_b", wiki_slug="tool_generic_b", name="Generic Tool B", 
            slot=EquipmentSlot.TOOLS, quality=EquipmentQuality.NORMAL, value=10,
            keywords=("GenericB",),
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=2)]
        ),
        Equipment(
            id="pickaxe_bronze", wiki_slug="pickaxe_bronze", name="Bronze Pickaxe", 
            slot=EquipmentSlot.TOOLS, quality=EquipmentQuality.NORMAL, value=10,
            keywords=("Pickaxe",),
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=1)]
        ),

        # --- SET ITEMS ---
        Equipment(
            id="set_boots", wiki_slug="set_boots", name="Miner Boots", 
            slot=EquipmentSlot.FEET, quality=EquipmentQuality.NORMAL, value=50,
            keywords=("Miner Set",),
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=2)] # Buffed 1 -> 2
        ),
        Equipment(
            id="set_gloves", wiki_slug="set_gloves", name="Miner Gloves", 
            slot=EquipmentSlot.HANDS, quality=EquipmentQuality.NORMAL, value=50,
            keywords=("Miner Set",),
            modifiers=[
                # Set Bonus
                Modifier(stat=StatName.WORK_EFFICIENCY, value=10, # Buffed 5 -> 10
                         conditions=[Condition(type=ConditionType.SET_EQUIPPED, target="Miner Set", value=2)])
            ]
        ),
        
        # --- KEYWORD ITEMS ---
        Equipment(
            id="lantern_offhand", wiki_slug="lantern", name="Lantern", 
            slot=EquipmentSlot.SECONDARY, quality=EquipmentQuality.NORMAL, value=50,
            keywords=("Light Source",),
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=2)] # Buffed 1 -> 2
        ),
         Equipment(
            id="torch_mainhand", wiki_slug="torch", name="Torch", 
            slot=EquipmentSlot.PRIMARY, quality=EquipmentQuality.NORMAL, value=10,
            keywords=("Light Source",),
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=1)] # Buffed 0.5 -> 1
        )
    ]