import pytest
import json

def get_selectbox_by_label(at, label_text):
    for sb in at.selectbox:
        if label_text in sb.label: return sb
    raise ValueError(f"Selectbox '{label_text}' not found.")

def click_button_by_label(at, label_text):
    for btn in at.button:
        if label_text in btn.label: return btn.click().run()
    raise ValueError(f"Button '{label_text}' not found.")

def test_owned_items_filtering(patched_app_test):
    """Verify 'Only use owned items' correctly limits results."""
    at = patched_app_test
    at.run()
    
    user_data = {
        "name": "Tester",
        "inventory": {"pickaxe": 1} # Mining Helmet omitted
    }
    at.text_area(key="user_json_text").input(json.dumps(user_data)).run()
    
    # Enable owned filter
    found_cb = False
    for cb in at.checkbox:
        if "Only use owned items" in cb.label:
            cb.check().run()
            found_cb = True
            break
    assert found_cb

    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")
    
    # Verify Mining Helmet (not owned) is absent from the results
    for df in at.dataframe:
        if "Item" in df.value.columns:
            assert "Mining Helmet" not in df.value["Item"].values

def test_candidate_inspector_loading(patched_app_test):
    """Verify Candidate Inspector displays scores after optimization."""
    at = patched_app_test
    at.run()
    
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")
    
    # Inspect specific slot
    get_selectbox_by_label(at, "Inspect Slot").select("head").run()
    
    # Verify candidate table data
    found = False
    for df in at.dataframe:
        if "Score" in df.value.columns and "Name" in df.value.columns:
            found = True
            break
    assert found, "Candidate Inspector table failed to load scores"