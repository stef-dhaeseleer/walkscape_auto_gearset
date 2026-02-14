import pytest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os
import json
import streamlit as st

# Ensure the root directory is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import (
    Equipment, Activity, Recipe, Location, Service, Collectible, 
    Pet, Consumable, EquipmentSlot, EquipmentQuality, 
    RequirementType, ConditionType, Modifier, StatName
)
from utils.constants import SkillName

@pytest.fixture
def mock_game_data():
    """Generates consistent mock data for testing."""
    
    # 1. Items
    items = [
        Equipment(
            id="bronze_sword", wiki_slug="bronze_sword", name="Bronze Sword", 
            slot=EquipmentSlot.PRIMARY, quality=EquipmentQuality.NORMAL, value=10
        ),
        Equipment(
            id="iron_shield", wiki_slug="iron_shield", name="Iron Shield", 
            slot=EquipmentSlot.SECONDARY, quality=EquipmentQuality.NORMAL, value=20
        ),
        Equipment(
            id="mining_helmet", wiki_slug="mining_helmet", name="Mining Helmet", 
            slot=EquipmentSlot.HEAD, quality=EquipmentQuality.NORMAL, value=50,
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=10)]
        ),
        Equipment(
            id="pickaxe", wiki_slug="pickaxe", name="Basic Pickaxe", 
            slot=EquipmentSlot.TOOLS, quality=EquipmentQuality.NORMAL, value=5,
            keywords=("pickaxe",)
        ),
        Equipment(
            id="gold_ring", wiki_slug="gold_ring", name="Gold Ring", 
            slot=EquipmentSlot.RING, quality=EquipmentQuality.NORMAL, value=100
        ), 
        Equipment(
            id="silver_ring", wiki_slug="silver_ring", name="Silver Ring", 
            slot=EquipmentSlot.RING, quality=EquipmentQuality.NORMAL, value=80,
            modifiers=[Modifier(stat=StatName.WORK_EFFICIENCY, value=2)]
        ),
        Equipment(
            id="fishing_rod", wiki_slug="fishing_rod", name="Fishing Rod", 
            slot=EquipmentSlot.TOOLS, quality=EquipmentQuality.NORMAL, value=15,
            keywords=("fishing_rod",)
        ),
        Equipment(
            id="hammer", wiki_slug="hammer", name="Hammer", 
            slot=EquipmentSlot.TOOLS, quality=EquipmentQuality.NORMAL, value=15,
            keywords=("hammer",)
        ),
        Equipment(
            id="master_cape", wiki_slug="master_cape", name="Master Cape", 
            slot=EquipmentSlot.CAPE, quality=EquipmentQuality.EXCELLENT, value=1000,
            # Requires very high reputation or something the mock user won't have by default
            requirements=(dict(type=RequirementType.REPUTATION, target="Guild", value=10000),) 
        )
    ]

    # 2. Activities (Lowercase skill names to match Enum)
    activities = [
        Activity(
            id="mining_copper", wiki_slug="mining_copper", name="Mining Copper",
            primary_skill="mining", locations=("loc_1",), base_steps=100
        ),
        Activity(
            id="cutting_logs", wiki_slug="cutting_logs", name="Cutting Logs",
            primary_skill="woodcutting", locations=("loc_1",), base_steps=80
        ),
        Activity(
            id="deep_fishing", wiki_slug="deep_fishing", name="Deep Sea Fishing",
            primary_skill="fishing", locations=("loc_1",), base_steps=120,
            requirements=[dict(type=RequirementType.KEYWORD_COUNT, target="fishing_rod", value=1)]
        ),
          Activity(
            id="deep_fishing", wiki_slug="deep_fishing", name="Deep Sea Fishing",
            primary_skill="fishing", locations=("loc_1",), base_steps=120,
            requirements=[dict(type=RequirementType.KEYWORD_COUNT, target="fishing_rod", value=1)]
        )

    ]       
    # 3. Recipes & Services
    recipes = [
        Recipe(
            id="smelt_copper", wiki_slug="smelt_copper", name="Smelt Copper",
            skill="smithing", level=1, service="forge_basic", 
            output_item_id="copper_bar", output_quantity=1
        )
    ]
    
    services = [
        Service(
            id="forge_basic", wiki_slug="forge_basic", name="Basic Forge",
            skill="smithing", tier="basic", location="loc_1"
        )
    ]

    # 4. Locations
    locations = [
        Location(id="loc_1", wiki_slug="loc_1", name="Starting Area", tags=("surface",))
    ]

    # 5. Collectibles & Pets & Consumables
    collectibles = [
        Collectible(id="rare_coin", wiki_slug="rare_coin", name="Rare Coin")
    ]
    
    pets = [
        Pet(id="dog", wiki_slug="dog", name="Dog", active_level=1)
    ]
    
    consumables = [
        Consumable(id="apple", wiki_slug="apple", name="Apple", duration=100, value=5)
    ]

    return items, activities, recipes, locations, services, collectibles, pets, consumables

@pytest.fixture
def mock_streamlit_js_eval():
    """Mocks local storage calls since there is no browser."""
    with patch('app.streamlit_js_eval') as mock:
        mock.return_value = None
        yield mock

@pytest.fixture
def patched_app_test(mock_game_data, mock_streamlit_js_eval):
    """
    Returns an AppTest instance with patched data and UI components.
    """
    from streamlit.testing.v1 import AppTest
    
    # 1. Unpack mock data - FIX: Correct variable name
    items, activities, recipes, locations, services, collectibles, pets, consumables = mock_game_data
    
    # load_game_data only returns the first 6 in real app signature
    loader_return = (items, activities, recipes, locations, services, collectibles)

    # 2. Fix for st.segmented_control crash in AppTest
    def mock_segmented_control(*args, **kwargs):
        # Remove args not supported by st.radio
        kwargs.pop("selection_mode", None)
        default_val = kwargs.pop("default", None)
        
        # Determine index for st.radio based on default value
        options = None
        if len(args) >= 2:
            options = args[1]
        elif "options" in kwargs:
            options = kwargs["options"]
            
        index = 0
        if options is not None and default_val is not None:
            try:
                # Handle single select default
                val = default_val
                if isinstance(val, list) and val: val = val[0]
                
                if val in options:
                    index = list(options).index(val)
            except Exception:
                index = 0
        
        return st.radio(*args, index=index, **kwargs)

    # 3. Patching
    # We patch utils.data_loader because app.py imports it
    with patch('utils.data_loader.load_game_data', return_value=loader_return):
        # We patch st.segmented_control to prevent the crash
        with patch('streamlit.segmented_control', side_effect=mock_segmented_control):
            # We patch os.path.exists to False for pets/consumables to avoid FileNotFoundError
            with patch('os.path.exists', return_value=False):
                at = AppTest.from_file("app.py", default_timeout=10)
                yield at