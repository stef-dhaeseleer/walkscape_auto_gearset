import streamlit as st
from streamlit_js_eval import streamlit_js_eval

from ui_utils import load_data
from drop_calculator import DropCalculator

# Import our split UI components
from ui_sidebar import render_sidebar, render_user_data_section
from tab_crafting_tree import render_crafting_tree_tab
from tab_optimizer import render_optimizer_tab
from tab_data_entry import render_data_entry_tab
# --- Page Config ---
st.set_page_config(
    page_title="WalkScape Gear Optimizer",
    layout="wide",
    initial_sidebar_state="expanded"
)

try:
    with open("style.css", "r") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    pass

def init_session_state():
    if 'locked_items_state' not in st.session_state:
        st.session_state['locked_items_state'] = {}
    if 'blacklist_state' not in st.session_state:
        st.session_state['blacklist_state'] = []
    if 'user_json_text' not in st.session_state:
        st.session_state['user_json_text'] = ""
    if 'ls_loaded' not in st.session_state:
        st.session_state['ls_loaded'] = False

    if 'opt_targets_list' not in st.session_state:
        st.session_state['opt_targets_list'] = [{"id": 0, "target": "Reward Rolls", "weight": 100}]
        st.session_state['next_target_id'] = 1

    if 'saved_loadouts' not in st.session_state: st.session_state['saved_loadouts'] = {}
    if 'crafting_tree_root' not in st.session_state: st.session_state['crafting_tree_root'] = None

def main():
    init_session_state()

    window_width = streamlit_js_eval(js_expressions='window.innerWidth', key='viewport_width')
    is_mobile = window_width is not None and window_width < 768

    stored_json = streamlit_js_eval(js_expressions="localStorage.getItem('WALKSCAPE_USER_DATA')", key="ls_loader")
    if stored_json and not st.session_state['ls_loaded']:
        st.session_state['user_json_text'] = stored_json
        st.session_state['ls_loaded'] = True
        st.rerun()

    # Load Data globally
    all_items_raw, activities, recipes, locations, services, all_collectibles_raw, all_pets, all_consumables, all_containers = load_data()   
    drop_calc = DropCalculator()
    WIKI_URL = "https://gear.walkscape.app"

    render_sidebar()

    st.title("🛡️ WalkScape Gear Optimizer")

    with st.container():
        user_state = render_user_data_section(is_mobile, all_collectibles_raw)

    tab_opt, tab_tree, tab_entry = st.tabs(["🎯 Single Optimizer", "🌳 Crafting Tree Calculator", "📝 Data Entry"])
    
    with tab_tree:
        render_crafting_tree_tab(
            recipes, all_items_raw, activities, all_containers, 
            user_state, drop_calc, locations, services, all_pets, all_consumables
        )
    with tab_opt:
        render_optimizer_tab(
            is_mobile, user_state, all_items_raw, activities, recipes, 
            locations, services, all_pets, all_consumables, drop_calc, WIKI_URL
        )
    with tab_entry:
        render_data_entry_tab()

if __name__ == "__main__":
    main()