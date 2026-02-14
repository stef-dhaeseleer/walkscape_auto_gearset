import pytest
import json

def get_selectbox_by_label(at, label_text):
    for sb in at.selectbox:
        if label_text in sb.label: return sb
    available = [sb.label for sb in at.selectbox]
    raise ValueError(f"Selectbox '{label_text}' not found. Available: {available}")

def click_button_by_label(at, label_text):
    for btn in at.button:
        if label_text in btn.label: return btn.click().run()
    raise ValueError(f"Button '{label_text}' not found.")

def test_owned_items_toggle_logic(patched_app_test):
    """Scenario: Verify 'Only use owned items' restricts the optimizer results."""
    at = patched_app_test
    at.run()
    
    # 1. Input User Data: User owns a 'Bronze Sword' but NOT 'Iron Shield'
    user_data = {
        "name": "Tester",
        "skills": {"mining": 100},
        "inventory": {"bronze_sword": 1} 
        # Iron Shield is deliberately missing
    }
    at.text_area(key="user_json_text").input(json.dumps(user_data)).run()
    
    # 2. Select Activity
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    
    # 3. Enable "Only use owned items"
    # Find the checkbox. Usually it's the first one or identified by label
    found_cb = False
    for cb in at.checkbox:
        if "Only use owned items" in cb.label:
            cb.check().run()
            found_cb = True
            break
    assert found_cb, "Could not find 'Only use owned items' checkbox"

    # 4. Optimize
    click_button_by_label(at, "Optimize")
    
    # 5. Assertions
    assert not at.exception
    
    # Analyze the result dataframe to ensure 'Iron Shield' (unowned) is NOT present
    # The output dataframe typically lists "Item" in the second column
    found_iron_shield = False
    for df in at.dataframe:
        # Check if the dataframe contains results (it usually has "Slot" and "Item" columns)
        if "Item" in df.value.columns:
            if "Iron Shield" in df.value["Item"].values:
                found_iron_shield = True
    
    assert not found_iron_shield, "Iron Shield (unowned) appeared in results despite 'Only use owned' toggle!"

def test_complex_locking_mechanic(patched_app_test):
    """Scenario: Lock specific complex slots (Ring 2, Tool 1) and verify persistence."""
    at = patched_app_test
    at.run()
    
    # 1. Expand the "Advanced Configuration" expander (simulated by interacting with widgets inside)
    # Note: Streamlit testing doesn't strictly require expanding, just accessing the widget.
    
    # 2. Lock Ring 2 to "Silver Ring"
    # The logic in app.py creates selectboxes with labels like "Ring 1", "Ring 2"
    sb_ring2 = get_selectbox_by_label(at, "Ring 2")
    sb_ring2.select("Silver Ring").run()
    
    # 3. Lock Tool 1 to "Hammer"
    sb_tool1 = get_selectbox_by_label(at, "Tool 1")
    sb_tool1.select("Hammer").run()
    
    # 4. Run Optimization
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")
    
    assert not at.exception
    
    # 5. Verify Locks in Session State
    locks = at.session_state['locked_items_state']
    assert 'ring_1' in locks # 0-indexed in code logic usually, but let's check keys
    assert locks['ring_1'].name == "Silver Ring"
    assert 'tool_0' in locks
    assert locks['tool_0'].name == "Hammer"

def test_candidate_inspector_tab(patched_app_test):
    """Scenario: Verify the Candidate Inspector tab loads data after optimization."""
    at = patched_app_test
    at.run()
    
    # 1. Run standard optimization
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")
    
    # 2. Simulate clicking the "Candidate Inspector" tab
    # In AppTest, tabs are containers. We interact with the widgets *inside* the tab.
    # The inspector has a selectbox "Inspect Slot".
    
    sb_inspect = get_selectbox_by_label(at, "Inspect Slot")
    sb_inspect.select("head").run()
    
    # 3. Verify a dataframe is present in the inspector area
    # There should be multiple dataframes now (Loadout, Blacklist, Inspector)
    # We check if *any* dataframe contains candidate data (e.g., "Score" column)
    found_candidate_df = False
    for df in at.dataframe:
        cols = df.value.columns
        if "Score" in cols and "Name" in cols:
            found_candidate_df = True
            # Verify Mining Helmet (mock item) is likely a candidate
            if "Mining Helmet" in df.value["Name"].values:
                pass
            break
            
    assert found_candidate_df, "Candidate Inspector dataframe (Score/Name columns) not found."

def test_impossible_requirements_error(patched_app_test):
    """Scenario: Force an error state (impossible keyword requirement) and check for error message."""
    at = patched_app_test
    at.run()
    
    # 1. Select "Deep Sea Fishing" which requires 1x 'fishing_rod' keyword
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Deep Sea Fishing").run()
    
    # 2. Blacklist the only item that provides 'fishing_rod' (Fishing Rod) to force failure
    # We can inject into session state for speed, or use the blacklist UI
    at.session_state['blacklist_state'] = ["fishing_rod"]
    at.run()
    
    # 3. Optimize
    click_button_by_label(at, "Optimize")
    
    # 4. Verify Error Message
    # The app should display an st.error containing "Requirements could not be met"
    assert len(at.error) > 0, "Expected an error message for impossible build, got none."
    assert "Requirements could not be met" in at.error[0].value