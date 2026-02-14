import pytest
from gear_optimizer import GearOptimizer
from utils.constants import OPTIMAZATION_TARGET

def test_simple_keyword_requirement(mock_items, mock_locations, mock_activity_light_req):
    """
    Scenario: Activity requires 1 'Light Source'.
    'Lantern' (Secondary) provides 'Light Source'.
    Expected: Lantern is equipped.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)
    
    # mock_activity_light_req already has requirements=[KeywordCount("Light Source", 1)]
    # This automatically sets up the context in the new optimizer.

    best_set, _ = optimizer.optimize(
        activity=mock_activity_light_req, 
        player_level=99, 
        player_skill_level=99, 
        optimazation_target=OPTIMAZATION_TARGET.reward_rolls
    )

    assert best_set.secondary is not None
    assert best_set.secondary.id == "lantern_offhand"

def test_set_bonus_calculation(mock_items, mock_locations, mock_activity):
    """
    Scenario: 
    - Miner Boots (2 WE)
    - Miner Gloves (10 WE IF 2 Set Items Equipped)
    - Basic Helm (2 WE) vs Miner Helm (Condition Mining, 10 WE)
    
    Expected: The optimizer should equip both set items to trigger the bonus if valid.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)

    best_set, _ = optimizer.optimize(
        activity=mock_activity, 
        player_level=99, 
        player_skill_level=99, 
        optimazation_target=OPTIMAZATION_TARGET.reward_rolls
    )

    # Check if both set items are equipped
    assert best_set.feet.id == "set_boots"
    assert best_set.hands.id == "set_gloves"

def test_requirement_swap_logic(mock_items, mock_locations, mock_activity_light_req):
    """
    Scenario: 
    - Activity requires "Light Source".
    - User has "Lantern" (Secondary, provides Light, weak stats).
    - User has "Torch" (Primary, provides Light, very weak stats).
    
    The optimizer should prioritize filling the requirement.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)
    
    best_set, error = optimizer.optimize(
        activity=mock_activity_light_req, 
        player_level=99, 
        player_skill_level=99, 
        optimazation_target=OPTIMAZATION_TARGET.reward_rolls
    )
    
    assert error is None
    
    # We expect one of the light sources to be equipped
    equipped_ids = [i.id for i in best_set.get_all_items() if hasattr(i, 'id')]
    assert "lantern_offhand" in equipped_ids or "torch_mainhand" in equipped_ids

def test_requirement_swap_complex(mock_items, mock_locations, mock_activity_light_req):
    """
    Scenario:
    We lock a powerful Secondary that is NOT a light source.
    The optimizer MUST pick the Torch (Primary) to fulfill the Light Source requirement,
    even if there are better Primary tools available, because the Secondary slot is locked.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)
    
    # Lock the Trash Ring in Secondary slot (simulating a user choice or slot conflict)
    # Wait, rings go in ring slot. Let's lock a non-light secondary if we had one.
    # We only have 'lantern_offhand' in mocks.
    # Let's create a dummy strong secondary that provides nothing req-wise.
    from models import Equipment, EquipmentSlot, EquipmentQuality, Modifier, StatName
    strong_offhand = Equipment(
        id="strong_offhand", wiki_slug="strong", name="Strong Offhand",
        slot=EquipmentSlot.SECONDARY, quality=EquipmentQuality.EXCELLENT, value=100,
        modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=50)]
    )
    
    # Re-init optimizer with extra item
    items_plus = mock_items + [strong_offhand]
    optimizer = GearOptimizer(items_plus, mock_locations)
    
    locks = {"secondary": strong_offhand}

    best_set, error = optimizer.optimize(
        activity=mock_activity_light_req,
        player_level=99,
        player_skill_level=99,
        optimazation_target=OPTIMAZATION_TARGET.reward_rolls,
        locked_items=locks
    )

    # 1. Secondary must be the locked item
    assert best_set.secondary.id == "strong_offhand"
    
    # 2. Requirement 'Light Source' must still be met.
    # Since Secondary is occupied, it MUST use 'torch_mainhand' (Primary)
    assert best_set.primary is not None
    assert best_set.primary.id == "torch_mainhand"