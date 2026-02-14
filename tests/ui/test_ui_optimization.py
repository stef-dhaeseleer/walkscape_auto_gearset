import pytest

def get_selectbox_by_label(at, label_text):
    """Helper to find a selectbox by its label."""
    # Try exact match
    for sb in at.selectbox:
        if sb.label == label_text:
            return sb
    # Try partial match
    for sb in at.selectbox:
        if label_text in sb.label:
            return sb
            
    available = [sb.label for sb in at.selectbox]
    raise ValueError(f"Selectbox with label '{label_text}' not found. Available: {available}")

def click_button_by_label(at, label_text):
    """Helper to find a button by its label and click it."""
    for btn in at.button:
        if label_text in btn.label:
            return btn.click().run()
    available = [b.label for b in at.button]
    raise ValueError(f"Button with label '{label_text}' not found. Available: {available}")

def test_optimize_activity_simple(patched_app_test):
    """Scenario 3: Select an Activity and Optimize."""
    at = patched_app_test
    at.run()

    target_activity = "[Activity] Mining Copper"
    
    # Use helper to find widget
    sb = get_selectbox_by_label(at, "Select Activity or Recipe")
    sb.select(target_activity).run()
    
    sb_target = get_selectbox_by_label(at, "Target Stat")
    sb_target.select("Reward Rolls").run()
    
    # Click Optimize by label
    click_button_by_label(at, "Optimize")
    
    # Debug: Check for errors if metrics are missing
    if len(at.metric) == 0 and len(at.error) > 0:
        pytest.fail(f"Optimization failed with error: {at.error[0].value}")
    
    assert not at.exception
    
    # Check results
    results_col = at.get("subheader")
    assert any("Results" in h.value for h in results_col)
    assert len(at.metric) >= 2 

def test_optimize_recipe_flow(patched_app_test):
    """Scenario 4: Select Recipe -> Service Selectbox appears -> Optimize."""
    at = patched_app_test
    at.run()

    target_recipe = "[Recipe] Smelt Copper"
    sb = get_selectbox_by_label(at, "Select Activity or Recipe")
    sb.select(target_recipe).run()
    
    # Service selectbox should appear now
    service_select = None
    for sel in at.selectbox:
        if "Select Service" in sel.label:
            service_select = sel
            break
            
    assert service_select is not None, "Service selectbox did not appear for Recipe"
    
    service_val = "Basic Forge (loc_1)"
    service_select.select(service_val).run()
    
    click_button_by_label(at, "Optimize")
    
    if len(at.metric) == 0 and len(at.error) > 0:
        pytest.fail(f"Optimization failed with error: {at.error[0].value}")

    assert not at.exception
    assert len(at.metric) > 0 

def test_optimize_with_buffs(patched_app_test):
    """Scenario 7: Select Pet and Consumable."""
    at = patched_app_test
    at.run()

    # NOTE: Since we mock file loading as False, the pets list might be empty (["None"])
    sb_pet = get_selectbox_by_label(at, "Select Pet")
    if "Dog" in sb_pet.options:
        sb_pet.select("Dog").run()
        try:
            get_selectbox_by_label(at, "Pet Level").select(1).run()
        except:
            pass
    
    sb_cons = get_selectbox_by_label(at, "Select Consumable")
    if "Apple" in sb_cons.options:
        sb_cons.select("Apple").run()
    
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")
    
    assert not at.exception