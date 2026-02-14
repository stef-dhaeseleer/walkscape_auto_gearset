import pytest
import json

def test_app_loads_no_exceptions(patched_app_test):
    """Scenario 1: Smoke test - does the app start?"""
    at = patched_app_test
    at.run()
    assert not at.exception, f"App failed to load: {at.exception}"
    assert "WalkScape Gear Optimizer" in at.title[0].value

def test_user_json_input_valid(patched_app_test):
    """Scenario 2a: Valid User JSON input."""
    at = patched_app_test
    at.run()
    
    valid_data = {
        "name": "TestPlayer",
        "steps": 10000,
        "skills": {"mining": 5000},
        "inventory": {"pickaxe": 1}
    }
    
    at.text_area(key="user_json_text").input(json.dumps(valid_data)).run()
    
    assert not at.exception
    assert len(at.success) > 0
    assert "TestPlayer" in at.success[0].value

def test_user_json_input_invalid(patched_app_test):
    """Scenario 2b: Invalid JSON input."""
    at = patched_app_test
    at.run()
    
    at.text_area(key="user_json_text").input("{ invalid_json: ").run()
    
    assert len(at.error) > 0
    assert "Invalid JSON" in at.error[0].value