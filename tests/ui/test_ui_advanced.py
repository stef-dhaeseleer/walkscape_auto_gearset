import pytest

def get_selectbox_by_label(at, label_text):
    for sb in at.selectbox:
        if label_text in sb.label: return sb
    raise ValueError(f"Selectbox '{label_text}' not found.")

def click_button_by_label(at, label_text):
    for btn in at.button:
        if label_text in btn.label: return btn.click().run()
    raise ValueError(f"Button '{label_text}' not found.")

def test_locking_persistence_ui_and_state(patched_app_test):
    """Scenario 5: Lock items and verify both UI and session state."""
    at = patched_app_test
    at.run()
    
    # 1. Select item in UI
    sb_head = get_selectbox_by_label(at, "Head")
    sb_head.select("Mining Helmet").run()
    
    # 2. Verify Session State dictionary (Internal mapping)
    assert 'head' in at.session_state['locked_items_state']
    assert at.session_state['locked_items_state']['head'].name == "Mining Helmet"
    
    # 3. Lock a Tool (Testing tool_0 logic)
    sb_tool1 = get_selectbox_by_label(at, "Tool 1")
    sb_tool1.select("Basic Pickaxe").run()
    
    assert 'tool_0' in at.session_state['locked_items_state']
    assert at.session_state['locked_items_state']['tool_0'].name == "Basic Pickaxe"

def test_blacklist_interaction(patched_app_test):
    """Scenario 6: Verify blacklist filter and session state."""
    at = patched_app_test
    at.run()
    
    # Directly inject into state to verify optimizer respects it
    at.session_state['blacklist_state'] = ["mining_helmet"]
    at.run()
    
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")
    
    # Verify Mining Helmet is not in the results loadout
    for df in at.dataframe:
        if "Item" in df.value.columns:
            assert "Mining Helmet" not in df.value["Item"].values

def test_debugger_swapper_with_composite(patched_app_test):
    """Scenario 8: Test Item Swapper comparison logic."""
    at = patched_app_test
    at.run()
    
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")
    
    # Interact with debugger swapper
    get_selectbox_by_label(at, "Select Slot to Swap").select("Head").run()
    
    # Swap to a candidate
    sb_swap = get_selectbox_by_label(at, "Swap with:")
    if len(sb_swap.options) > 0:
        # Avoid selecting None
        target_item = [o for o in sb_swap.options if o != "None"]
        if target_item:
            sb_swap.select(target_item[0]).run()
        
    assert not at.exception
    # Check for comparison results
    assert any("Comparison" in md.value for md in at.markdown)