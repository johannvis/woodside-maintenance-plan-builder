"""Maintenance Plan Builder — Streamlit entry point."""

import os
import streamlit as st
from config import APP_TITLE, APP_ICON

st.set_page_config(
    page_title=APP_TITLE,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Load secrets into environment before anything else
try:
    for _k in ("ANTHROPIC_API_KEY", "DATABASE_URL"):
        if not os.getenv(_k):
            _v = st.secrets.get(_k)
            if _v:
                os.environ[_k] = _v
except Exception:
    pass

# Ensure all DB tables exist (safe to call on every boot — no-op if already created)
from db.database import init_db
init_db()

# Custom CSS
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        height: 44px; padding: 0 20px;
        border-radius: 6px 6px 0 0;
        font-weight: 600;
    }
    .block-container { padding-top: 1.5rem; }
    div[data-testid="metric-container"] {
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 12px;
    }
</style>
""", unsafe_allow_html=True)

# Login wall — skipped automatically if [auth] not configured in secrets
from auth.helpers import render_login_wall
render_login_wall()

st.title(f"{APP_ICON} {APP_TITLE}")
st.caption("Automated FMECA → SAP PM packaging | Rules engine + human-in-the-loop")

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "1 · Ingest & Preview",
    "2 · Rule Editor",
    "3 · Review & Refine",
    "4 · AI Review",
    "5 · Export",
    "📖 Demo Guide",
    "⚙️ Algorithm",
])

with tab1:
    from ui.page_ingest import render as render_ingest
    render_ingest()

with tab2:
    from ui.page_rules import render as render_rules
    render_rules()

with tab3:
    from ui.page_review import render as render_review
    render_review()

with tab4:
    from ui.page_agents import render as render_agents
    render_agents()

with tab5:
    from ui.page_export import render as render_export
    render_export()

with tab6:
    with open("docs/DEMO_GUIDE.md", "r") as f:
        st.markdown(f.read())

with tab7:
    with open("docs/ALGORITHM.md", "r") as f:
        st.markdown(f.read())
