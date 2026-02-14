import pytest
from gear_optimizer import GearOptimizer
from models import Activity

def test_simple_keyword_requirement(mock_items, mock_locations, basic_context, mock_activity_light_req):
    """
    Scenario: Activity requires 1 'Light Source'.
    'Lantern' (Secondary) provides 'Light Source'.
    Expected: Lantern is equipped.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)
    
    # mock_activity_light_req comes from conftest (requires 1 Light Source, max_efficiency=2.0)

    # Note: We must update context to reflect the requirement because optimize() 
    # normally builds context internally unless overridden.
    context = basic_context.copy()
    context["required_keywords"] = {"light source": 1}

    best_set, _ = optimizer.optimize(
        activity=mock_activity_light_req, player_level=99, player_skill_level=99, context_override=context
    )

    assert best_set.secondary is not None
    assert best_set.secondary.id == "lantern_offhand"

def test_set_bonus_calculation(mock_items, mock_locations, basic_context, mock_activity):
    """
    Scenario: 
    - Miner Boots (5 WE)
    - Miner Gloves (50 WE IF 2 Set Items Equipped)
    - Basic Helm (5 WE)
    
    Without the set bonus, gloves provide 0. With it, they are huge.
    The optimizer should recognize that equipping Boots + Gloves > Best individual items.
    """
    optimizer = GearOptimizer(mock_items, mock_locations)

    best_set, _ = optimizer.optimize(
        activity=mock_activity, player_level=99, player_skill_level=99, context_override=basic_context
    )

    # Check if both set items are equipped
    assert best_set.feet.id == "set_boots"
    assert best_set.hands.id == "set_gloves"

def test_requirement_swap_logic(mock_items, mock_locations, basic_context, mock_activity_light_req):
    """
    Scenario: 
    - Activity requires "Light Source".
    - User has "Lantern" (Secondary, provides Light, weak stats).
    - User has "Torch" (Primary, provides Light, very weak stats).
    - User has "Super Pickaxe" (Primary, strong stats).
    
    The optimizer should ideally fill the requirement using the Secondary slot (Lantern)
    to keep the Primary slot open for the strong Pickaxe (or tool slot).
    """
    optimizer = GearOptimizer(mock_items, mock_locations)
    
    context = basic_context.copy()
    context["required_keywords"] = {"light source": 1}

    best_set, error = optimizer.optimize(
        activity=mock_activity_light_req, player_level=99, player_skill_level=99, context_override=context
    )
    
    assert error is None
    
    # We expect one of the light sources to be equipped
    equipped_ids = [i.id for i in best_set.get_all_items() if hasattr(i, 'id')]
    assert "lantern_offhand" in equipped_ids or "torch_mainhand" in equipped_ids