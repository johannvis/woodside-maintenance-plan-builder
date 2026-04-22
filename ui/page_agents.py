"""Step 5: AI Review — multi-agent maintenance plan analysis."""

import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from engine.agent_orchestrator import ROLE_ICONS, run_agent_review

_ROLE_LABEL = {
    "safety": "Safety",
    "cost": "Cost",
    "efficiency": "Efficiency",
    "integrity": "Integrity",
    "coverage": "Coverage",
    "route": "Route",
}

ACTION_EMOJI = {
    "keep": "✅",
    "split": "✂️",
    "merge": "🔗",
    "reclassify": "🏷️",
}


def _score_bar(score: float, label: str) -> str:
    pct = min(score / 10 * 100, 100)
    if score >= 7:
        colour = "#2ecc71"
    elif score >= 4:
        colour = "#f39c12"
    else:
        colour = "#e74c3c"
    return (
        f'<span style="font-size:0.75rem;color:#888;">{label}</span> '
        f'<span style="font-weight:600;">{score:.1f}</span> '
        f'<span style="display:inline-block;width:60px;height:8px;background:#eee;border-radius:4px;vertical-align:middle;">'
        f'<span style="display:inline-block;width:{pct:.0f}%;height:8px;background:{colour};border-radius:4px;"></span>'
        f'</span>'
    )


def _render_item_result(result: dict) -> None:
    """Render one reviewed item in the live feed."""
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
            f'{judge_icon} <strong>Judge:</strong> {result["judge_rationale"][:160]}…</div>'
        )
    elif consensus:
        winning = result.get("winning_agent", "")
        judge_text = (
            f'<div style="font-size:0.8rem;color:#555;margin-top:4px;">'
            f'{judge_icon} Consensus ({action}) — no judge required</div>'
        )

    error_text = ""
    if result.get("error"):
        error_text = f'<div style="color:#e74c3c;font-size:0.8rem;">⚠ {result["error"]}</div>'

    st.markdown(
        f"""<div style="border:1px solid #dee2e6;border-radius:8px;padding:10px 14px;margin-bottom:8px;">
  <div>{emoji} <strong>{desc}</strong> &nbsp;<span style="color:#888;font-size:0.8rem;">{action.upper()}</span></div>
  <div style="margin-top:6px;">{score_html}</div>
  {judge_text}
  {error_text}
</div>""",
        unsafe_allow_html=True,
    )


def render():
    st.header("Step 5 — AI Review")
    st.caption(
        "Four specialist agents (Safety, Cost, Efficiency, Integrity) review each plan item "
        "in parallel. A judge arbitrates when agents disagree."
    )

    packaging_session_id = st.session_state.get("packaging_session_id")
    if not packaging_session_id:
        st.warning("⚠️ Generate a maintenance plan in Step 3 first.")
        return

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        st.warning(
            "Set `ANTHROPIC_API_KEY` in your environment (or Streamlit Secrets) to enable AI Review."
        )
        return

    # ── Sidebar config ────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### Agent Config")
        active_safety = st.checkbox("🔒 Safety", value=True, key="ag_safety")
        active_cost = st.checkbox("💰 Cost", value=True, key="ag_cost")
        active_efficiency = st.checkbox("⚡ Efficiency", value=True, key="ag_eff")
        active_integrity = st.checkbox("🔩 Integrity", value=True, key="ag_integ")
        active_coverage = st.checkbox("📋 Coverage", value=True, key="ag_coverage")
        active_route = st.checkbox("🗺️ Route", value=True, key="ag_route")
        st.divider()
        concurrency = st.slider("Concurrent items", min_value=1, max_value=20, value=5, key="ag_concurrency",
                                help="Items reviewed in parallel. Higher = faster but more API load.")
        max_items = st.number_input("Max items (0 = all)", min_value=0, max_value=5000, value=50, key="ag_max_items",
                                    help="Set to 0 to review all items. Use a small number for quick tests.")

    active_roles = []
    if active_safety:
        active_roles.append("safety")
    if active_cost:
        active_roles.append("cost")
    if active_efficiency:
        active_roles.append("efficiency")
    if active_integrity:
        active_roles.append("integrity")
    if active_coverage:
        active_roles.append("coverage")
    if active_route:
        active_roles.append("route")

    # ── Check for existing results ────────────────────────────────────────────
    result_key = f"agent_review_result_{packaging_session_id}"
    feed_key = f"agent_review_feed_{packaging_session_id}"

    col_run, col_clear = st.columns([2, 1])
    with col_run:
        run_btn = st.button(
            "▶ Run AI Review",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.get("agent_review_running", False),
        )
    with col_clear:
        clear_btn = st.button(
            "🗑 Clear Results",
            use_container_width=True,
            disabled=st.session_state.get("agent_review_running", False),
        )

    if clear_btn:
        for k in [result_key, feed_key]:
            st.session_state.pop(k, None)
        st.rerun()

    if run_btn:
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

        # ── Streaming render ──────────────────────────────────────────────────
        progress_placeholder = st.empty()
        feed_placeholder = st.empty()
        done = 0
        total = 1

        while not future.done() or not progress_q.empty():
            try:
                msg = progress_q.get_nowait()
            except queue.Empty:
                time.sleep(0.15)
                continue

            if msg["type"] == "progress":
                done = msg["done"]
                total = msg["total"]
                item_result = msg["item"]
                st.session_state[feed_key].append(item_result)

                with progress_placeholder.container():
                    st.progress(done / max(total, 1), text=f"Reviewing {done}/{total} plan items…")

                with feed_placeholder.container():
                    with st.container(height=480, border=False):
                        for r in st.session_state[feed_key][-30:]:  # show last 30
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

    # ── Show persisted results ────────────────────────────────────────────────
    if st.session_state.get("agent_review_running"):
        st.info("Agent review is running…")
        return

    summary = st.session_state.get(result_key)
    feed = st.session_state.get(feed_key, [])

    if feed:
        st.divider()
        st.markdown("**Live Review Feed**")
        with st.container(height=500, border=True):
            for r in feed:
                _render_item_result(r)

    if summary:
        st.divider()
        st.markdown("**Review Summary**")
        total = summary.get("total", 1)
        cols = st.columns(5)
        metrics = [
            ("Total Items", total, ""),
            ("Kept", summary.get("keep", 0), f"{summary.get('keep', 0)/total*100:.0f}%"),
            ("Split", summary.get("split", 0), f"{summary.get('split', 0)/total*100:.0f}%"),
            ("Merged", summary.get("merge", 0), f"{summary.get('merge', 0)/total*100:.0f}%"),
            ("Reclassified", summary.get("reclassify", 0), f"{summary.get('reclassify', 0)/total*100:.0f}%"),
        ]
        for col, (label, val, delta) in zip(cols, metrics):
            with col:
                st.metric(label, val, delta or None)

        st.caption(
            "Agent decisions have been saved to the database. "
            "Open **3 · Review & Refine** to see AI badges on affected items."
        )
