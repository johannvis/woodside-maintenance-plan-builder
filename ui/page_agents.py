"""Step 4: AI Review — multi-agent maintenance plan analysis with inline agent config."""

import json
import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from db.database import get_session
from db.models import AgentProfile, AgentDecision, JudgeDecision
from engine.agent_orchestrator import ROLE_ICONS, run_agent_review, _seed_default_agents_if_needed

_ROLE_LABEL = {
    "safety": "Safety",
    "cost": "Cost",
    "efficiency": "Efficiency",
    "integrity": "Integrity",
    "coverage": "Coverage",
    "route": "Route",
}

_ROLE_ORDER = ["safety", "cost", "efficiency", "integrity", "coverage", "route"]

ACTION_EMOJI = {
    "keep": "✅",
    "split": "✂️",
    "merge": "🔗",
    "reclassify": "🏷️",
}


def _score_bar(score: float, label: str) -> str:
    pct = min(score / 10 * 100, 100)
    colour = "#2ecc71" if score >= 7 else "#f39c12" if score >= 4 else "#e74c3c"
    return (
        f'<span style="font-size:0.75rem;color:#888;">{label}</span> '
        f'<span style="font-weight:600;">{score:.1f}</span> '
        f'<span style="display:inline-block;width:60px;height:8px;background:#eee;'
        f'border-radius:4px;vertical-align:middle;">'
        f'<span style="display:inline-block;width:{pct:.0f}%;height:8px;'
        f'background:{colour};border-radius:4px;"></span></span>'
    )


def _render_item_result(result: dict) -> None:
    action = result.get("final_action", "keep")
    emoji = ACTION_EMOJI.get(action, "✅")
    consensus = result.get("has_consensus", True)
    judge_icon = "🤝" if consensus else "⚖️"
    desc = result.get("item_description", "")[:60]
    scores = result.get("scores", {})

    score_html = " &nbsp; ".join(
        _score_bar(v, f"{ROLE_ICONS.get(k, '')} {_ROLE_LABEL.get(k, k)}")
        for k, v in scores.items()
    )
    judge_text = ""
    if not consensus and result.get("judge_rationale"):
        judge_text = (
            f'<div style="font-size:0.8rem;color:#555;margin-top:4px;">'
            f'{judge_icon} <strong>Judge:</strong> {result["judge_rationale"][:180]}…</div>'
        )
    elif consensus:
        judge_text = (
            f'<div style="font-size:0.8rem;color:#555;margin-top:4px;">'
            f'{judge_icon} Consensus ({action}) — no judge required</div>'
        )
    error_text = (
        f'<div style="color:#e74c3c;font-size:0.8rem;">⚠ {result["error"]}</div>'
        if result.get("error") else ""
    )

    st.markdown(
        f"""<div style="border:1px solid #dee2e6;border-radius:8px;padding:10px 14px;margin-bottom:8px;">
  <div>{emoji} <strong>{desc}</strong> &nbsp;<span style="color:#888;font-size:0.8rem;">{action.upper()}</span></div>
  <div style="margin-top:6px;">{score_html}</div>
  {judge_text}{error_text}
</div>""",
        unsafe_allow_html=True,
    )


# ── Agent config panel ────────────────────────────────────────────────────────

def _render_agent_config():
    """Inline expandable agent profile editor."""
    with st.expander("⚙️ Agent Configuration", expanded=False):
        session = get_session()
        try:
            _seed_default_agents_if_needed(session)
            profiles = (
                session.query(AgentProfile)
                .filter(AgentProfile.role != "judge")
                .order_by(AgentProfile.role)
                .all()
            )
            judge = session.query(AgentProfile).filter(AgentProfile.role == "judge").first()

            if not profiles:
                st.info("No agent profiles found.")
                return

            st.caption("Edit prompts here, then run the review. Changes take effect immediately on the next run.")

            # Specialist agents — tabs per role
            role_tabs = st.tabs([
                f"{ROLE_ICONS.get(p.role, '🔬')} {_ROLE_LABEL.get(p.role, p.role).capitalize()}"
                for p in profiles
            ])

            for tab, profile in zip(role_tabs, profiles):
                with tab:
                    col_active, col_model = st.columns([1, 2])
                    with col_active:
                        new_active = st.checkbox(
                            "Active", value=profile.is_active,
                            key=f"cfg_active_{profile.id}"
                        )
                    with col_model:
                        model_options = ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"]
                        cur_model = profile.model_id or "claude-haiku-4-5-20251001"
                        if cur_model not in model_options:
                            model_options.append(cur_model)
                        new_model = st.selectbox(
                            "Model", model_options,
                            index=model_options.index(cur_model),
                            key=f"cfg_model_{profile.id}"
                        )

                    new_prompt = st.text_area(
                        "System Prompt",
                        value=profile.system_prompt or "",
                        height=220,
                        key=f"cfg_prompt_{profile.id}",
                    )

                    if st.button("💾 Save", key=f"cfg_save_{profile.id}", type="primary"):
                        profile.is_active = new_active
                        profile.model_id = new_model
                        profile.system_prompt = new_prompt
                        session.commit()
                        st.success(f"{profile.name} saved.")

            # Judge config
            if judge:
                st.divider()
                st.markdown("**⚖️ Judge Agent**")
                jcol1, jcol2 = st.columns([2, 1])
                with jcol1:
                    try:
                        weights = json.loads(judge.scoring_weights or "{}")
                    except Exception:
                        weights = {}
                    w_cols = st.columns(4)
                    w_labels = [("Safety", "safety_weight", 0.35), ("Integrity", "integrity_weight", 0.25),
                                ("Efficiency", "efficiency_weight", 0.20), ("Cost", "cost_weight", 0.20)]
                    new_weights = {}
                    for col, (label, key, default) in zip(w_cols, w_labels):
                        with col:
                            new_weights[key] = st.slider(
                                label, 0.0, 1.0,
                                float(weights.get(key, default)), 0.05,
                                key=f"cfg_judge_{key}"
                            )
                with jcol2:
                    j_models = ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
                    cur_jm = judge.model_id or "claude-sonnet-4-6"
                    if cur_jm not in j_models:
                        j_models.append(cur_jm)
                    new_jmodel = st.selectbox("Model", j_models,
                                              index=j_models.index(cur_jm),
                                              key="cfg_judge_model")

                if st.button("💾 Save Judge Config", key="cfg_judge_save"):
                    judge.scoring_weights = json.dumps(new_weights)
                    judge.model_id = new_jmodel
                    session.commit()
                    st.success("Judge config saved.")

        finally:
            session.close()


# ── Main render ───────────────────────────────────────────────────────────────

def render():
    st.header("Step 4 — AI Review")
    st.caption(
        "Six specialist agents review each plan item in parallel. "
        "Refine the agent prompts below, then run — repeat as many times as needed."
    )

    packaging_session_id = st.session_state.get("packaging_session_id")
    if not packaging_session_id:
        st.warning("⚠️ Generate a maintenance plan in Step 3 first.")
        return

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        st.warning("Set `ANTHROPIC_API_KEY` in your environment or Streamlit Secrets.")
        return

    # ── Agent config panel ────────────────────────────────────────────────────
    _render_agent_config()

    st.divider()

    # ── Run controls ──────────────────────────────────────────────────────────
    col_toggles = st.columns(6)
    role_checks = {}
    for col, role in zip(col_toggles, _ROLE_ORDER):
        with col:
            role_checks[role] = st.checkbox(
                f"{ROLE_ICONS.get(role, '')} {_ROLE_LABEL.get(role, role)}",
                value=True, key=f"ag_{role}"
            )
    active_roles = [r for r, checked in role_checks.items() if checked]

    col_c, col_m = st.columns(2)
    with col_c:
        concurrency = st.slider("Concurrent items", 1, 20, 5, key="ag_concurrency",
                                help="Items reviewed in parallel.")
    with col_m:
        max_items = st.number_input("Max items (0 = all)", 0, 5000, 50, key="ag_max_items",
                                    help="0 reviews all items. Use small numbers while refining.")

    col_run, col_rerun, col_clear = st.columns([2, 2, 1])
    running = st.session_state.get("agent_review_running", False)

    result_key = f"agent_review_result_{packaging_session_id}"
    feed_key = f"agent_review_feed_{packaging_session_id}"

    with col_run:
        run_btn = st.button("▶ Run AI Review", type="primary",
                            use_container_width=True, disabled=running)
    with col_rerun:
        rerun_btn = st.button("🔄 Clear & Re-run", use_container_width=True, disabled=running,
                              help="Deletes previous decisions for this session and runs fresh.")
    with col_clear:
        clear_btn = st.button("🗑 Clear", use_container_width=True, disabled=running)

    if clear_btn:
        for k in [result_key, feed_key]:
            st.session_state.pop(k, None)
        st.rerun()

    def _delete_prior_decisions():
        """Remove all AgentDecision + JudgeDecision rows for this session."""
        s = get_session()
        try:
            s.query(AgentDecision).filter(
                AgentDecision.session_id == packaging_session_id
            ).delete()
            s.query(JudgeDecision).filter(
                JudgeDecision.session_id == packaging_session_id
            ).delete()
            s.commit()
        finally:
            s.close()

    def _start_run(clear_first: bool):
        if clear_first:
            _delete_prior_decisions()
        st.session_state["agent_review_running"] = True
        st.session_state.pop(result_key, None)
        st.session_state.pop(feed_key, None)
        st.session_state[feed_key] = []

        progress_q: queue.Queue = queue.Queue()

        def _run():
            run_agent_review(
                packaging_session_id=packaging_session_id,
                progress_queue=progress_q,
                active_roles=active_roles if active_roles else None,
                concurrency=int(concurrency),
                max_items=int(max_items),
            )

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_run)

        progress_ph = st.empty()
        feed_ph = st.empty()

        while not future.done() or not progress_q.empty():
            try:
                msg = progress_q.get_nowait()
            except queue.Empty:
                time.sleep(0.15)
                continue

            if msg["type"] == "progress":
                done = msg["done"]
                total = msg["total"]
                st.session_state[feed_key].append(msg["item"])
                with progress_ph.container():
                    st.progress(done / max(total, 1),
                                text=f"Reviewing {done}/{total} plan items…")
                with feed_ph.container():
                    with st.container(height=480, border=False):
                        for r in st.session_state[feed_key][-30:]:
                            _render_item_result(r)
            elif msg["type"] == "done":
                st.session_state[result_key] = msg["summary"]
                break
            elif msg["type"] == "error":
                st.error(f"Agent review error: {msg['message']}")
                break

        st.session_state["agent_review_running"] = False
        executor.shutdown(wait=False)
        st.rerun()

    if run_btn:
        _start_run(clear_first=False)
    elif rerun_btn:
        _start_run(clear_first=True)

    if running:
        st.info("Agent review is running…")
        return

    # ── Persisted results ─────────────────────────────────────────────────────
    feed = st.session_state.get(feed_key, [])
    summary = st.session_state.get(result_key)

    if feed:
        st.divider()
        st.markdown("**Review Feed**")
        with st.container(height=500, border=True):
            for r in feed:
                _render_item_result(r)

    if summary:
        st.divider()
        total = max(summary.get("total", 1), 1)
        cols = st.columns(5)
        for col, (label, key) in zip(cols, [
            ("Total", "total"), ("Kept", "keep"), ("Split", "split"),
            ("Merged", "merge"), ("Reclassified", "reclassify")
        ]):
            val = summary.get(key, 0)
            delta = f"{val/total*100:.0f}%" if key != "total" else None
            with col:
                st.metric(label, val, delta)

        st.caption(
            "Decisions saved. Open **3 · Review & Refine → Plan View** to see 🤖 badges. "
            "Tweak prompts above and click **🔄 Clear & Re-run** to iterate."
        )
