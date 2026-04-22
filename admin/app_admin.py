"""Admin app — agent profile management, test, and decision history.

Deploy on EC2:
    cd /path/to/project
    streamlit run admin/app_admin.py --server.port 8502

Requires DATABASE_URL env var pointing to PostgreSQL (same DB as main app).
Add admin/.streamlit/secrets.toml with [auth_admin] section for login wall.
"""

import json
import os
import sys

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from db.database import get_session
from db.models import AgentProfile, AgentDecision, JudgeDecision, MaintenancePlanItem

st.set_page_config(
    page_title="Maintenance Plan Builder — Admin",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Auth ──────────────────────────────────────────────────────────────────────
from auth.helpers import render_login_wall
render_login_wall(section_key="auth_admin")

st.title("⚙️ Agent Admin")
st.caption("Configure agent profiles, test reviews, and inspect decision history.")

page = st.sidebar.radio(
    "Navigation",
    [
        "Agent Profiles",
        "Test Agent",
        "Judge Config",
        "Decision History",
        "Export Config",
    ],
)

# ── Page: Agent Profiles ──────────────────────────────────────────────────────

def _page_agent_profiles():
    st.header("Agent Profiles")
    st.caption("Edit system prompts, models, and activation status for each agent role.")

    session = get_session()
    try:
        profiles = session.query(AgentProfile).order_by(AgentProfile.role).all()

        if not profiles:
            st.info("No agent profiles found. Click 'Seed defaults' to create them.")
            if st.button("Seed Default Profiles"):
                from engine.agent_orchestrator import _seed_default_agents_if_needed
                _seed_default_agents_if_needed(session)
                st.success("Default profiles seeded.")
                st.rerun()
            return

        selected_name = st.selectbox(
            "Select profile to edit",
            [p.name for p in profiles],
            key="admin_profile_sel",
        )
        profile = next((p for p in profiles if p.name == selected_name), None)
        if not profile:
            return

        with st.form("edit_profile_form"):
            st.subheader(f"Edit: {profile.name}")
            col1, col2 = st.columns(2)
            with col1:
                new_name = st.text_input("Name", value=profile.name)
                new_model = st.selectbox(
                    "Model",
                    [
                        "claude-haiku-4-5-20251001",
                        "claude-sonnet-4-6",
                        "claude-opus-4-6",
                    ],
                    index=["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-6"].index(
                        profile.model_id or "claude-haiku-4-5-20251001"
                    ),
                )
            with col2:
                new_active = st.checkbox("Active", value=profile.is_active)
                new_weights = st.text_area(
                    "Scoring Weights (JSON)",
                    value=profile.scoring_weights or "{}",
                    height=80,
                )

            new_prompt = st.text_area(
                "System Prompt",
                value=profile.system_prompt or "",
                height=300,
            )

            submitted = st.form_submit_button("Save Changes", type="primary")

        if submitted:
            try:
                json.loads(new_weights)  # Validate JSON
                profile.name = new_name
                profile.model_id = new_model
                profile.is_active = new_active
                profile.scoring_weights = new_weights
                profile.system_prompt = new_prompt
                session.commit()
                st.success("Profile updated.")
                st.rerun()
            except json.JSONDecodeError:
                st.error("Scoring Weights must be valid JSON.")

        # Summary table
        st.divider()
        st.markdown("**All Profiles**")
        rows = [
            {
                "Name": p.name,
                "Role": p.role,
                "Model": p.model_id,
                "Active": "✓" if p.is_active else "",
                "Prompt Length": len(p.system_prompt or ""),
            }
            for p in profiles
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    finally:
        session.close()


# ── Page: Test Agent ──────────────────────────────────────────────────────────

def _page_test_agent():
    st.header("Test Agent")
    st.caption("Run a single agent on a sample plan item to validate the prompt and output.")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        st.warning("Set `ANTHROPIC_API_KEY` to enable test runs.")
        return

    session = get_session()
    try:
        profiles = session.query(AgentProfile).filter(AgentProfile.is_active == True).all()
        if not profiles:
            st.info("No active agent profiles.")
            return

        profile_names = [p.name for p in profiles]
        selected_p = st.selectbox("Agent Profile", profile_names, key="test_profile_sel")
        profile = next(p for p in profiles if p.name == selected_p)

        # Load sample items
        items = session.query(MaintenancePlanItem).limit(200).all()
        if not items:
            st.info("No plan items in DB. Run packaging first via the main app.")
            return

        item_labels = [
            f"{i.description[:60] if i.description else i.id[:8]} ({i.total_duration_hours:.1f}h)"
            for i in items
        ]
        selected_item_label = st.selectbox("Plan Item", item_labels, key="test_item_sel")
        item = items[item_labels.index(selected_item_label)]

        if st.button("▶ Run Test Review", type="primary"):
            from engine.agent_orchestrator import _build_item_context, ROLE_TO_CLASS
            from engine.agents.judge_agent import JudgeAgent

            with st.spinner("Running agent…"):
                context = _build_item_context(session, item)

                if profile.role in ROLE_TO_CLASS:
                    agent = ROLE_TO_CLASS[profile.role](profile)
                    result = agent.review(item, context)
                elif profile.role == "judge":
                    st.info("Judge agent requires multiple specialist inputs. Use 'run all' instead.")
                    return
                else:
                    st.error(f"Unknown role: {profile.role}")
                    return

            st.success("Review complete!")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Score", f"{result.get('score', 0):.1f}/10")
            with col2:
                st.metric("Action", result.get("recommended_action", "").upper())
            with col3:
                st.metric("Confidence", result.get("confidence", "").upper())

            st.markdown("**Rationale:**")
            st.info(result.get("rationale", ""))

            with st.expander("Raw Output"):
                st.json(result)

    finally:
        session.close()


# ── Page: Judge Config ────────────────────────────────────────────────────────

def _page_judge_config():
    st.header("Judge Config")
    st.caption("Configure tiebreak weights and the judge model.")

    session = get_session()
    try:
        judge = session.query(AgentProfile).filter(AgentProfile.role == "judge").first()
        if not judge:
            st.info("No judge profile found. Seed defaults from Agent Profiles page.")
            return

        weights = {}
        try:
            weights = json.loads(judge.scoring_weights or "{}")
        except Exception:
            pass

        with st.form("judge_config_form"):
            st.subheader("Tiebreak Weights")
            st.caption("Weights must sum to 1.0. Higher weight = more influence in tie-breaking.")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                w_safety = st.slider("Safety", 0.0, 1.0, float(weights.get("safety_weight", 0.35)), 0.05)
            with col2:
                w_integrity = st.slider("Integrity", 0.0, 1.0, float(weights.get("integrity_weight", 0.25)), 0.05)
            with col3:
                w_efficiency = st.slider("Efficiency", 0.0, 1.0, float(weights.get("efficiency_weight", 0.20)), 0.05)
            with col4:
                w_cost = st.slider("Cost", 0.0, 1.0, float(weights.get("cost_weight", 0.20)), 0.05)

            total = w_safety + w_integrity + w_efficiency + w_cost
            st.metric("Total weight", f"{total:.2f}", delta=f"{total-1.0:+.2f} from 1.0")

            judge_model = st.selectbox(
                "Judge Model",
                ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
                index=["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"].index(
                    judge.model_id or "claude-sonnet-4-6"
                ),
            )

            submitted = st.form_submit_button("Save Judge Config", type="primary")

        if submitted:
            new_weights = {
                "safety_weight": w_safety,
                "integrity_weight": w_integrity,
                "efficiency_weight": w_efficiency,
                "cost_weight": w_cost,
            }
            judge.scoring_weights = json.dumps(new_weights)
            judge.model_id = judge_model
            session.commit()
            st.success("Judge config saved.")
            st.rerun()

    finally:
        session.close()


# ── Page: Decision History ────────────────────────────────────────────────────

def _page_decision_history():
    st.header("Decision History")
    st.caption("Browse agent and judge decisions by packaging session.")

    session = get_session()
    try:
        # Get distinct session IDs from decisions
        sessions = [
            row[0]
            for row in session.query(AgentDecision.session_id).distinct().order_by(
                AgentDecision.session_id.desc()
            ).limit(20).all()
        ]

        if not sessions:
            st.info("No agent decisions recorded yet.")
            return

        selected_session = st.selectbox("Packaging Session", sessions, key="hist_session_sel")

        tab_a, tab_j = st.tabs(["Agent Decisions", "Judge Decisions"])

        with tab_a:
            decisions = (
                session.query(AgentDecision)
                .filter(AgentDecision.session_id == selected_session)
                .all()
            )
            rows = []
            for d in decisions:
                profile = d.agent_profile
                item = d.plan_item
                rows.append({
                    "Agent": profile.name if profile else d.agent_profile_id[:8],
                    "Role": profile.role if profile else "",
                    "Item": (item.description[:50] if item and item.description else d.maintenance_plan_item_id[:8]),
                    "Score": round(d.score or 0, 1),
                    "Action": d.recommended_action,
                    "Confidence": d.confidence,
                    "Selected": "✓" if d.was_selected else "",
                    "Rationale": (d.rationale or "")[:80],
                })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                st.caption(f"{len(rows)} decisions")
            else:
                st.info("No agent decisions for this session.")

        with tab_j:
            judges = (
                session.query(JudgeDecision)
                .filter(JudgeDecision.session_id == selected_session)
                .all()
            )
            rows = []
            for j in judges:
                winning = j.winning_agent
                item = j.plan_item
                rows.append({
                    "Item": (item.description[:50] if item and item.description else j.maintenance_plan_item_id[:8]),
                    "Final Action": j.final_action,
                    "Winning Agent": winning.role if winning else "",
                    "Modified": "✓" if j.modified else "",
                    "Rationale": (j.judge_rationale or "")[:100],
                })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                st.caption(f"{len(rows)} judge decisions")
            else:
                st.info("No judge decisions for this session (all items reached consensus).")

    finally:
        session.close()


# ── Page: Export Config ───────────────────────────────────────────────────────

def _page_export_config():
    st.header("Export Config")
    st.caption("Download all agent profiles as JSON for version control.")

    session = get_session()
    try:
        profiles = session.query(AgentProfile).all()
        if not profiles:
            st.info("No profiles to export.")
            return

        export_data = []
        for p in profiles:
            export_data.append({
                "name": p.name,
                "role": p.role,
                "model_id": p.model_id,
                "is_active": p.is_active,
                "scoring_weights": json.loads(p.scoring_weights or "{}"),
                "system_prompt": p.system_prompt or "",
            })

        json_str = json.dumps(export_data, indent=2)
        st.download_button(
            "⬇️ Download agents_config.json",
            data=json_str,
            file_name="agents_config.json",
            mime="application/json",
        )

        with st.expander("Preview"):
            st.json(export_data)

    finally:
        session.close()


# ── Route ─────────────────────────────────────────────────────────────────────

if page == "Agent Profiles":
    _page_agent_profiles()
elif page == "Test Agent":
    _page_test_agent()
elif page == "Judge Config":
    _page_judge_config()
elif page == "Decision History":
    _page_decision_history()
elif page == "Export Config":
    _page_export_config()
