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
    available = [b.label for b in at.button]
    raise ValueError(f"Button '{label_text}' not found. Available: {available}")

def test_optimize_activity_composite_targets(patched_app_test):
    """Scenario 3: Add multiple targets and optimize."""
    at = patched_app_test
    at.run()

    # 1. Select Activity
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    
    # 2. Add a second target row
    click_button_by_label(at, "➕ Add Target")
    
    # 3. Configure targets - keys are target_sel_0, target_sel_1 etc.
    at.selectbox(key="target_sel_0").select("Xp").run() 
    
    # Verify second row exists
    assert any(sb.key == "target_sel_1" for sb in at.selectbox)
    at.selectbox(key="target_sel_1").select("Fine").run()
    at.slider(key="target_slider_1").set_value(50).run()
    
    click_button_by_label(at, "Optimize")
    
    assert not at.exception
    
    # 4. Verify results
    found_score = False
    
    # Strategy 1: Check markdown (standard text output)
    for md in at.markdown:
        if "Total Score" in md.value:
            found_score = True
            break
            
    # Strategy 2: Check HTML elements (safely handling attributes)
    if not found_score:
        html_elements = at.get("html")
        for el in html_elements:
            # st.html content is usually in .body for HtmlElement, 
            # or we convert the proto object to string if attributes are missing.
            content = getattr(el, "body", "")
            if not content:
                # Fallback for UnknownElement: try accessing the internal proto string
                content = str(el)
            
            if "Total Score" in content:
                found_score = True
                break
    
    assert found_score, "Score badge (Total Score) not found in rendered output."

def test_reputation_requirement_filtering(patched_app_test):
    """Verify items requiring higher reputation are filtered out."""
    at = patched_app_test
    at.run()
    
    user_data = {
        "name": "Newbie",
        "reputation": {"guild": 100} 
    }
    at.text_area(key="user_json_text").input(json.dumps(user_data)).run()
    
    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")
    
    for df in at.dataframe:
        if "Item" in df.value.columns:
            assert "Master Cape" not in df.value["Item"].values

def test_normalization_math_tab(patched_app_test):
    """Verify normalization math table exists and contains scoring columns."""
    at = patched_app_test
    at.run()

    get_selectbox_by_label(at, "Select Activity or Recipe").select("[Activity] Mining Copper").run()
    click_button_by_label(at, "Optimize")

    found_math_df = False
    for df in at.dataframe:
        if "normalized" in df.value.columns or "contribution" in df.value.columns:
            found_math_df = True
            break
    assert found_math_df, "Normalization breakdown table not found in Math tab."