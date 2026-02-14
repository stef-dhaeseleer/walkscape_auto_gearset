import pytest

def get_selectbox_by_label(at, label_text):
    """Helper to find a selectbox by its label."""
    for sb in at.selectbox:
        if sb.label == label_text: return sb
    for sb in at.selectbox:
        if label_text in sb.label: return sb
    available = [sb.label for sb in at.selectbox]
    raise ValueError(f"Selectbox with label '{label_text}' not found. Available: {available}")

def click_button_by_label(at, label_text):
    """Helper to find a button by its label and click it."""
    for btn in at.button:
        if label_text in btn.label:
            return btn.click().run()
    available = [b.label for b in at.button]
    raise ValueError(f"Button with label '{label_text}' not found. Available: {available}")

def test_advanced_locking_mechanic(patched_app_test):
    """Scenario 5: Lock an item in a specific slot."""
    at = patched_app_test
    at.run()
    
    sb_head = get_selectbox_by_label(at, "Head")
    sb_head.select("Mining Helmet").run()
    
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")
    
    assert not at.exception
    
    assert 'locked_items_state' in at.session_state
    locks = at.session_state['locked_items_state']
    assert 'head' in locks
    assert locks['head'].name == "Mining Helmet"

def test_debugger_interaction(patched_app_test):
    """Scenario 8: Interact with Item Swapper after optimization."""
    at = patched_app_test
    at.run()
    
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")
    
    # If optimization fails, the debugger won't load
    if len(at.metric) == 0 and len(at.error) > 0:
        pytest.fail(f"Optimization precondition failed: {at.error[0].value}")

    # Debugger interactions
    get_selectbox_by_label(at, "Select Slot to Swap").select("Head").run()
    
    sb_swap = get_selectbox_by_label(at, "Swap with:")
    # Only swap if we have items
    if "Mining Helmet" in sb_swap.options:
        sb_swap.select("Mining Helmet").run()
    
    assert not at.exception
    
    found_comparison = False
    for md in at.markdown:
        if "Comparison" in md.value:
            found_comparison = True
            break

def test_blacklist_add_via_editor(patched_app_test):
    """Scenario 6: Test Blacklist functionality via Session State injection."""
    at = patched_app_test
    at.run()

    at.session_state['blacklist_state'] = ["bronze_sword"]
    at.run()
    
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")
    
    assert not at.exception
    buttons = [b for b in at.button if "Clear All" in b.label]
    assert len(buttons) > 0