import pytest
from gear_optimizer import GearOptimizer
from models import Activity, Equipment, Modifier
from utils.constants import (
    OPTIMAZATION_TARGET, StatName, EquipmentSlot, EquipmentQuality
)

def test_basic_optimization_reward_rolls(mock_items, mock_locations, mock_activity):
    """
    Scenario: Optimize for Reward Rolls (Speed).
    Expected: 'Helm Miner' (+10 Conditional) is chosen over 'Helm Pro' (+5).
    The optimizer should correctly evaluate that the 'mining' condition applies.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)
    
    best_set, error = optimizer.optimize(
        activity=mock_activity,
        player_level=99,
        player_skill_level=50,
        optimazation_target=OPTIMAZATION_TARGET.reward_rolls
    )

    assert error is None
    assert best_set.head is not None
    # Helm Miner provides +10 WE (conditional) vs Helm Pro +5 WE.
    # Since activity is mining, Helm Miner wins.
    assert best_set.head.id == "helm_miner"

def test_composite_target_structure(mock_items, mock_locations, mock_activity):
    """
    Scenario: Use a composite target list (Weighted Multi-Objective).
    Expected: Optimizer runs successfully and returns a valid set.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)
    
    targets = [
        (OPTIMAZATION_TARGET.reward_rolls, 1.0), 
        (OPTIMAZATION_TARGET.chests, 0.5)
    ]

    best_set, error = optimizer.optimize(
        activity=mock_activity,
        player_level=99,
        player_skill_level=50,
        optimazation_target=targets
    )

    assert error is None
    assert best_set.head.id == "helm_miner"

def test_stat_calculations_integration(mock_items, mock_locations, mock_activity):
    """
    Scenario: Verify that the optimizer correctly aggregates stats in the result.
    Note: Percentage stats like Work Efficiency are divided by 100 in the output dictionary.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)
    
    # We force a specific item by locking it to ensure we know the expected stats
    helm_basic = next(i for i in mock_items if i.id == "helm_basic") # +2 WE
    locks = {"head": helm_basic}

    best_set, _ = optimizer.optimize(
        activity=mock_activity,
        player_level=99,
        player_skill_level=50,
        optimazation_target=OPTIMAZATION_TARGET.reward_rolls,
        locked_items=locks
    )

    stats = best_set.get_stats()
    # Helm Basic gives +2 Work Efficiency. 
    # In get_stats(), percentage stats are normalized (val / 100).
    # So we expect >= 0.02, not 2.0.
    assert stats.get("work_efficiency") >= 0.02

def test_normalization_logic_sanity(mock_locations, mock_activity):
    """
    Scenario: Create two items.
    Item A: Huge Efficiency (Good for Reward Rolls)
    Item B: Huge Chest Finding (Good for Chests)
    
    Target: 100% Chests, 1% Reward Rolls.
    Expected: Item B should be picked despite Item A having 'higher' raw numbers 
    if the normalization handles the scale difference correctly.
    """
    item_speed = Equipment(
        id="speed_king", wiki_slug="speed", name="Speed King",
        slot=EquipmentSlot.HEAD, quality=EquipmentQuality.NORMAL, value=10,
        modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=50)]
    )
    item_chest = Equipment(
        id="chest_king", wiki_slug="chest", name="Chest King",
        slot=EquipmentSlot.HEAD, quality=EquipmentQuality.NORMAL, value=10,
        modifiers=[Modifier(stat=StatName.CHEST_FINDING, value=50)] 
    )
    
    optimizer = GearOptimizer([item_speed, item_chest], mock_locations)

    # 1. Test Single Target: Chests
    set_chest, _ = optimizer.optimize(
        mock_activity, 99, 99, OPTIMAZATION_TARGET.chests
    )
    assert set_chest.head.id == "chest_king"

    # 2. Test Single Target: Reward Rolls
    set_speed, _ = optimizer.optimize(
        mock_activity, 99, 99, OPTIMAZATION_TARGET.reward_rolls
    )
    assert set_speed.head.id == "speed_king"

    # 3. Test Composite: Heavy weight on Chests
    targets = [
        (OPTIMAZATION_TARGET.chests, 10.0),
        (OPTIMAZATION_TARGET.reward_rolls, 1.0)
    ]
    
    set_composite, _ = optimizer.optimize(
        mock_activity, 99, 99, targets
    )
    assert set_composite.head.id == "chest_king"