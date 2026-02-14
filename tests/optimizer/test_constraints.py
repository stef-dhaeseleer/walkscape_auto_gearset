import pytest
from gear_optimizer import GearOptimizer
from utils.constants import OPTIMAZATION_TARGET, EquipmentSlot, EquipmentQuality, StatName
from models import Equipment, Modifier

def test_ownership_constraint(mock_items, mock_locations, mock_activity):
    """
    Scenario: Best item is 'Helm Miner', but user only owns 'Helm Basic'.
    Expected: 'Helm Basic' is chosen.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)
    user_owned = {"helm_basic": 1} 

    best_set, _ = optimizer.optimize(
        activity=mock_activity, 
        player_level=99, 
        player_skill_level=50, 
        optimazation_target=OPTIMAZATION_TARGET.reward_rolls,
        owned_item_counts=user_owned
    )

    assert best_set.head.id == "helm_basic"

def test_manual_locking(mock_items, mock_locations, mock_activity):
    """
    Scenario: User locks 'Helm Basic' (worst helm).
    Expected: 'Helm Basic' is equipped despite better options.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)

    helm_basic = next(i for i in mock_items if i.id == "helm_basic")
    locks = {"head": helm_basic}

    best_set, _ = optimizer.optimize(
        activity=mock_activity, 
        player_level=99, 
        player_skill_level=99, 
        optimazation_target=OPTIMAZATION_TARGET.reward_rolls,
        locked_items=locks
    )

    assert best_set.head.id == "helm_basic"

def test_blacklist(mock_items, mock_locations, mock_activity):
    """
    Scenario: 'Helm Miner' is best. User blacklists it.
    Expected: 'Helm Pro' (2nd best) is chosen.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)

    # Helm Miner is +10 (conditional), Helm Pro is +5, Helm Basic is +2
    blacklist = {"helm_miner"}

    best_set, _ = optimizer.optimize(
        activity=mock_activity, 
        player_level=99, 
        player_skill_level=99, 
        optimazation_target=OPTIMAZATION_TARGET.reward_rolls,
        blacklisted_ids=blacklist
    )

    assert best_set.head.id != "helm_miner"
    assert best_set.head.id == "helm_pro"

def test_tool_slot_limits(mock_locations, mock_activity):
    """
    Scenario: User has 10 tools available.
    Player Level 20 -> 4 Slots.
    Player Level 50 -> 5 Slots.
    """
    # Create 10 dummy tools with increasing value
    tools = []
    for i in range(10):
        tools.append(Equipment(
            id=f"tool_{i}", wiki_slug=f"tool_{i}", name=f"Tool {i}",
            slot=EquipmentSlot.TOOLS, quality=EquipmentQuality.NORMAL, value=10,
            keywords=("Generic",),
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=i+1)]
        ))
    
    optimizer = GearOptimizer(tools, mock_locations)
    
    # Test Level 20 (4 Slots)
    set_lvl_20, _ = optimizer.optimize(
        activity=mock_activity,
        player_level=20,
        player_skill_level=20,
        optimazation_target=OPTIMAZATION_TARGET.reward_rolls
    )
    assert len(set_lvl_20.tools) == 4
    # Should pick tools 9, 8, 7, 6
    assert any(t.id == "tool_9" for t in set_lvl_20.tools)

    # Test Level 50 (5 Slots)
    set_lvl_50, _ = optimizer.optimize(
        activity=mock_activity,
        player_level=50,
        player_skill_level=50,
        optimazation_target=OPTIMAZATION_TARGET.reward_rolls
    )
    assert len(set_lvl_50.tools) == 5