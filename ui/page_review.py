"""Step 3: Review & Refine."""

import os
from collections import defaultdict, Counter

import pandas as pd
import streamlit as st
from db.database import get_session
from db.models import (
    MaintenancePlan, MaintenancePlanItem, TaskList, Operation,
    Task, FailureMode, FunctionalLocation,
    AgentDecision, JudgeDecision, AgentProfile,
)
from engine.packager import package
from engine.plan_mutator import apply_merge, dismiss_decision

_ACTION_EMOJI = {"keep": "✅", "split": "✂️", "merge": "🔗", "reclassify": "🏷️"}
_ACTION_COLOUR = {"split": "#e74c3c", "merge": "#3498db", "reclassify": "#f39c12", "keep": "#2ecc71"}
_ROLE_ICONS = {
    "safety": "🔒", "cost": "💰", "efficiency": "⚡",
    "integrity": "🔩", "coverage": "📋", "route": "🗺️",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_item_detail(session, item_id: str) -> dict:
    item = session.get(MaintenancePlanItem, item_id)
    if not item:
        return {}

    tl = item.task_list
    ops = tl.operations if tl else []

    op_rows = []
    trace_rows = []
    for op in ops:
        op_rows.append({
            "Op#": f"{op.operation_no:03d}",
            "Description": op.description[:80] if op.description else "",
            "Resource": op.resource_type,
            "Duration (hrs)": op.duration_hours,
            "Materials": op.materials or "",
        })
        src_task = session.get(Task, op.source_task_id) if op.source_task_id else None
        if src_task:
            fm = session.get(FailureMode, src_task.failure_mode_id)
            floc = session.get(FunctionalLocation, fm.functional_location_id) if fm else None
            trace_rows.append({
                "Equipment": floc.name if floc else "",
                "Failure Mode": fm.failure_mode[:60] if fm and fm.failure_mode else "",
                "Criticality": fm.criticality if fm else "",
                "Task Type": src_task.task_type,
                "Interval": f"{src_task.interval} {src_task.interval_unit}",
                "Regulatory": "✓" if src_task.is_regulatory else "",
            })

    return {"item": item, "ops": op_rows, "trace": trace_rows, "tl": tl}


def _get_floc_descendants(all_flocs: list, root_id: str) -> set:
    """Return set of FLOC ids that are root_id or any descendant."""
    children_map: dict[str, list] = defaultdict(list)
    for f in all_flocs:
        if f.parent_id:
            children_map[f.parent_id].append(f.id)
    result: set = set()
    stack = [root_id]
    while stack:
        cur = stack.pop()
        result.add(cur)
        stack.extend(children_map.get(cur, []))
    return result


def _build_trace_df(session, packaging_session_id: str) -> pd.DataFrame:
    """Return a DataFrame mapping every operation to its plan/item."""
    ops = (
        session.query(Operation)
        .filter(Operation.session_id == packaging_session_id)
        .all()
    )
    rows = []
    for op in ops:
        src = op.source_task
        fm = src.failure_mode if src else None
        floc = fm.functional_location if fm else None
        tl = op.task_list
        item = tl.item if tl else None
        plan = item.plan if item else None
        rows.append({
            "FLOC": floc.name if floc else "",
            "Failure Mode": (fm.failure_mode[:50] if fm and fm.failure_mode else ""),
            "Criticality": fm.criticality if fm else "",
            "Task": op.description[:60] if op.description else "",
            "Type": src.task_type if src else "",
            "Resource": op.resource_type or "",
            "Interval": f"{src.interval} {src.interval_unit}" if src else "",
            "Online": "✓" if (src and src.is_online) else "",
            "Reg": "✓" if (src and src.is_regulatory) else "",
            "Plan": plan.name if plan else "",
            "Item Description": item.description[:55] if item and item.description else "",
        })
    return pd.DataFrame(rows)


# ── View renderers ────────────────────────────────────────────────────────────

def _get_ai_reviewed_items(session, packaging_session_id: str) -> set:
    """Return set of item IDs that have a JudgeDecision or AgentDecision in this session."""
    jd_ids = {
        row.maintenance_plan_item_id
        for row in session.query(JudgeDecision.maintenance_plan_item_id)
        .filter(JudgeDecision.session_id == packaging_session_id)
        .all()
    }
    ad_ids = {
        row.maintenance_plan_item_id
        for row in session.query(AgentDecision.maintenance_plan_item_id)
        .filter(AgentDecision.session_id == packaging_session_id)
        .all()
    }
    return jd_ids | ad_ids


def _get_agent_review_detail(session, item_id: str, packaging_session_id: str):
    """Return agent decisions and judge decision for an item."""
    decisions = (
        session.query(AgentDecision)
        .filter(
            AgentDecision.maintenance_plan_item_id == item_id,
            AgentDecision.session_id == packaging_session_id,
        )
        .all()
    )
    if not decisions:
        return None

    judge = (
        session.query(JudgeDecision)
        .filter(
            JudgeDecision.maintenance_plan_item_id == item_id,
            JudgeDecision.session_id == packaging_session_id,
        )
        .first()
    )

    return {"decisions": decisions, "judge": judge}


def _render_agent_review_section(agent_data: dict) -> None:
    """Render expandable agent review section in item detail panel."""
    decisions = agent_data["decisions"]
    judge = agent_data["judge"]

    with st.expander("🤖 Agent Review", expanded=True):
        for d in decisions:
            role = d.agent_profile.role if d.agent_profile else "unknown"
            icon = _ROLE_ICONS.get(role, "🔬")
            score = d.score or 0
            pct = min(score / 10 * 100, 100)
            bar_colour = "#2ecc71" if score >= 7 else "#f39c12" if score >= 4 else "#e74c3c"
            action_colour = _ACTION_COLOUR.get(d.recommended_action, "#888")

            st.markdown(
                f"""<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
  <span style="width:90px;font-size:0.8rem;font-weight:600;">{icon} {role.capitalize()}</span>
  <span style="font-size:1rem;font-weight:700;">{score:.1f}</span>
  <div style="flex:1;background:#eee;border-radius:4px;height:10px;">
    <div style="background:{bar_colour};width:{pct:.0f}%;height:10px;border-radius:4px;"></div>
  </div>
  <span style="font-size:0.75rem;font-weight:600;color:{action_colour};width:80px;">{d.recommended_action.upper()}</span>
  <span style="font-size:0.75rem;color:#888;">{d.confidence}</span>
</div>""",
                unsafe_allow_html=True,
            )
            if d.rationale:
                st.caption(d.rationale[:200])

        if judge:
            st.divider()
            action_colour = _ACTION_COLOUR.get(judge.final_action, "#888")
            winning = ""
            if judge.winning_agent:
                winning = f" — driven by **{judge.winning_agent.role}**"
            st.markdown(
                f"⚖️ **Judge Decision:** "
                f"<span style='color:{action_colour};font-weight:700;'>{judge.final_action.upper()}</span>"
                f"{winning}",
                unsafe_allow_html=True,
            )
            if judge.judge_rationale:
                st.caption(judge.judge_rationale)
        else:
            st.divider()
            # Find consensus action
            actions = [d.recommended_action for d in decisions]
            if actions:
                from collections import Counter
                top = Counter(actions).most_common(1)[0][0]
                st.markdown(f"🤝 **Consensus:** {top.upper()} (no judge required)")


def _render_pending_actions(session, packaging_session_id: str) -> None:
    """Pending agent actions queue — shown at top of Plan View when actions exist."""
    pending = (
        session.query(JudgeDecision, MaintenancePlanItem)
        .join(MaintenancePlanItem, JudgeDecision.maintenance_plan_item_id == MaintenancePlanItem.id)
        .filter(
            JudgeDecision.session_id == packaging_session_id,
            JudgeDecision.final_action != "keep",
            JudgeDecision.modified == False,
        )
        .order_by(JudgeDecision.final_action)
        .all()
    )

    if not pending:
        return

    # Batch-load all agent decisions for pending items (avoid N+1 queries)
    pending_item_ids = [item.id for _, item in pending]
    all_ads = (
        session.query(AgentDecision, AgentProfile)
        .join(AgentProfile, AgentDecision.agent_profile_id == AgentProfile.id)
        .filter(
            AgentDecision.session_id == packaging_session_id,
            AgentDecision.maintenance_plan_item_id.in_(pending_item_ids),
        )
        .all()
    )
    # Group by item_id → {role: (action, target_item_id)}
    item_agent_votes: dict = defaultdict(dict)
    item_merge_targets: dict = defaultdict(list)  # item_id → [target_item_id, ...]
    for ad, profile in all_ads:
        item_agent_votes[ad.maintenance_plan_item_id][profile.role] = ad.recommended_action
        if ad.recommended_action == "merge" and ad.target_item_id:
            item_merge_targets[ad.maintenance_plan_item_id].append(ad.target_item_id)

    # Resolve merge target descriptions in one pass
    all_target_ids = {tid for tids in item_merge_targets.values() for tid in tids}
    target_items = {
        t.id: t for t in session.query(MaintenancePlanItem).filter(
            MaintenancePlanItem.id.in_(all_target_ids)
        ).all()
    } if all_target_ids else {}

    action_counts = Counter(jd.final_action for jd, _ in pending)
    badges = " · ".join(
        f"{_ACTION_EMOJI.get(a, '?')} {a.capitalize()}: **{n}**"
        for a, n in sorted(action_counts.items())
    )

    with st.expander(
        f"🤖 Pending Agent Actions — {len(pending)} items waiting  |  {badges}",
        expanded=True,
    ):
        # Bulk apply merges
        merges = [(jd, item) for jd, item in pending if jd.final_action == "merge"]
        col_bulk, col_dismiss_all = st.columns([2, 1])
        with col_bulk:
            if merges and st.button(
                f"✓ Apply All {len(merges)} Merge Recommendations",
                type="primary",
                use_container_width=True,
            ):
                applied = sum(1 for jd, _ in merges if apply_merge(session, jd.id)["ok"])
                st.success(f"Applied {applied} of {len(merges)} merges.")
                st.rerun()
        with col_dismiss_all:
            if st.button("✕ Dismiss All", use_container_width=True):
                for jd, _ in pending:
                    dismiss_decision(session, jd.id)
                st.rerun()

        st.divider()

        for jd, item in pending:
            action = jd.final_action
            colour = _ACTION_COLOUR.get(action, "#888")
            emoji = _ACTION_EMOJI.get(action, "?")
            desc = (item.description or item.id[:12])[:55]
            rationale = (jd.judge_rationale or "—")[:200]

            # Build agent vote summary: group roles by their recommended action
            votes = item_agent_votes.get(item.id, {})
            vote_groups: dict = defaultdict(list)
            for role, voted_action in votes.items():
                icon = _ROLE_ICONS.get(role, "?")
                vote_groups[voted_action].append(icon)
            vote_summary = "  ".join(
                f"{''.join(icons)} → **{act}**"
                for act, icons in sorted(vote_groups.items(), key=lambda x: x[0] != action)
            )

            # Resolve merge target name
            merge_target_label = ""
            if action == "merge":
                tids = item_merge_targets.get(item.id, [])
                if tids:
                    top_tid = Counter(tids).most_common(1)[0][0]
                    t = target_items.get(top_tid)
                    merge_target_label = (t.description or top_tid[:12])[:50] if t else top_tid[:20]

            # Layout: action | item description + votes | rationale + merge target | buttons
            c_act, c_desc, c_rat, c_btns = st.columns([1, 2.5, 3, 1.8])

            with c_act:
                st.markdown(
                    f'<div style="margin-top:6px;">{emoji} '
                    f'<span style="font-weight:700;color:{colour};">{action.upper()}</span></div>',
                    unsafe_allow_html=True,
                )
            with c_desc:
                item_badges = []
                if item.is_regulatory:
                    item_badges.append("🔴")
                if not item.is_online:
                    item_badges.append("🔒")
                item_badges.append(f"⏱️ {item.frequency}{item.frequency_unit[0] if item.frequency_unit else ''}")
                st.markdown(f"**{desc}**  " + " ".join(item_badges))
                if vote_summary:
                    st.caption(vote_summary)
            with c_rat:
                if merge_target_label:
                    st.caption(f"**→ into:** {merge_target_label}")
                st.caption(rationale)
            with c_btns:
                b1, b2 = st.columns(2)
                with b1:
                    if action == "merge":
                        if st.button("✓ Apply", key=f"apply_{jd.id}", type="primary", use_container_width=True):
                            result = apply_merge(session, jd.id)
                            if result["ok"]:
                                st.success(f"Merged: {result['ops_moved']} ops → {result['target'][:25]}")
                                st.rerun()
                            else:
                                st.error(result["error"])
                    else:
                        if st.button("🔍 Review", key=f"review_{jd.id}", use_container_width=True,
                                     help="Jump to this item in the plan tree"):
                            st.session_state["selected_item_id"] = jd.maintenance_plan_item_id
                            st.rerun()
                with b2:
                    if st.button("✕", key=f"dismiss_{jd.id}", use_container_width=True, help="Dismiss"):
                        dismiss_decision(session, jd.id)
                        st.rerun()


def _render_plan_view(session, packaging_session_id: str, plans: list):
    _render_pending_actions(session, packaging_session_id)

    col_tree, col_detail = st.columns([2, 3])

    # Load AI-reviewed item IDs once
    ai_reviewed = _get_ai_reviewed_items(session, packaging_session_id)

    with col_tree:
        st.markdown("**Plan Tree**")
        with st.container(height=700, border=True):
            for plan in plans:
                with st.expander(f"📋 {plan.name}", expanded=False):
                    for item in plan.items:
                        ai_badge = " 🤖" if item.id in ai_reviewed else ""
                        item_label = (
                            f"{'🔴' if item.is_regulatory else ('🟡' if not item.is_online else '🟢')} "
                            f"{item.description[:50] if item.description else item.id[:8]} "
                            f"({item.total_duration_hours:.1f}h){ai_badge}"
                        )
                        if st.button(item_label, key=f"item_{item.id}"):
                            st.session_state["selected_item_id"] = item.id

    with col_detail:
        selected_item_id = st.session_state.get("selected_item_id")
        if not selected_item_id:
            st.info("← Select an item from the plan tree to view details.")
            return

        detail = _get_item_detail(session, selected_item_id)
        if not detail:
            st.warning("Item not found.")
            return

        item = detail["item"]
        with st.container(height=700, border=True):
            st.subheader(f"Item Detail: {item.description[:60] if item.description else ''}")

            badges = []
            if item.is_regulatory:
                badges.append("🔴 Regulatory")
            if not item.is_online:
                badges.append("🔒 Shutdown")
            badges.append(f"⏱️ {item.frequency} {item.frequency_unit}")
            badges.append(f"⏳ {item.total_duration_hours:.1f}h total")
            st.markdown("  ".join(badges))

            max_dur = st.session_state.get("max_duration_display", 8.0)
            pct = min(item.total_duration_hours / max_dur, 1.0) * 100
            bar_color = "#e74c3c" if pct >= 100 else "#f39c12" if pct >= 75 else "#2ecc71"
            st.markdown(
                f"""<div style="background:#eee;border-radius:4px;height:16px;">
                <div style="background:{bar_color};width:{pct:.0f}%;height:16px;border-radius:4px;"></div>
                </div><small>{item.total_duration_hours:.1f}h / {max_dur}h cap</small>""",
                unsafe_allow_html=True,
            )

            st.divider()
            st.markdown("**Operations**")
            if detail["ops"]:
                st.dataframe(pd.DataFrame(detail["ops"]), use_container_width=True, hide_index=True)
            else:
                st.info("No operations.")

            if detail["ops"]:
                st.markdown("**Move Operation to Another Item**")
                all_items = (
                    session.query(MaintenancePlanItem)
                    .filter(MaintenancePlanItem.session_id == packaging_session_id)
                    .order_by(MaintenancePlanItem.description)
                    .all()
                )
                op_labels = [r["Op#"] + " — " + r["Description"][:40] for r in detail["ops"]]
                tl = detail["tl"]
                ops_for_move = tl.operations if tl else []

                move_op_label = st.selectbox("Select operation to move", op_labels, key="move_op_sel")
                target_items = [i for i in all_items if i.id != selected_item_id]
                target_labels = [
                    f"{i.description[:50] if i.description else i.id[:8]}" for i in target_items
                ]
                if target_labels:
                    move_target_label = st.selectbox("Move to item", target_labels, key="move_target_sel")
                    if st.button("Move", key="move_op_btn"):
                        op_idx = op_labels.index(move_op_label)
                        target_idx = target_labels.index(move_target_label)
                        op_to_move = ops_for_move[op_idx]
                        target_item = target_items[target_idx]
                        target_tl = target_item.task_list
                        if target_tl:
                            op_to_move.task_list_id = target_tl.id
                            item.total_duration_hours -= op_to_move.duration_hours or 0
                            target_item.total_duration_hours += op_to_move.duration_hours or 0
                            session.commit()
                            st.session_state["selected_item_id"] = selected_item_id
                            st.success("Operation moved.")
                            st.rerun()

            st.divider()
            st.markdown("**FMECA Traceability**")
            if detail["trace"]:
                st.dataframe(
                    pd.DataFrame(detail["trace"]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No traceability data.")

            # Agent Review section (only if AI review has been run)
            if selected_item_id in ai_reviewed:
                st.divider()
                agent_data = _get_agent_review_detail(session, selected_item_id, packaging_session_id)
                if agent_data:
                    _render_agent_review_section(agent_data)


def _render_equipment_view(session, packaging_session_id: str, dataset_id: str):
    all_flocs = (
        session.query(FunctionalLocation)
        .filter(FunctionalLocation.dataset_id == dataset_id)
        .order_by(FunctionalLocation.level, FunctionalLocation.name)
        .all()
    )

    if not all_flocs:
        st.info("No equipment hierarchy found for this dataset.")
        return

    level_icons = {1: "🏭", 2: "⚙️", 3: "📦", 4: "🔩"}

    # Initialise selection
    if "equip_floc_sel" not in st.session_state:
        st.session_state["equip_floc_sel"] = all_flocs[0].id

    col_left, col_right = st.columns([1, 3])

    # ── Left panel: independently scrollable asset tree ───────────────────────
    with col_left:
        st.markdown("**Asset Hierarchy**")
        with st.container(height=560, border=True):
            for f in all_flocs:
                indent = "\u00a0" * ((f.level - 1) * 4)
                icon = level_icons.get(f.level, "▪️")
                is_selected = st.session_state["equip_floc_sel"] == f.id
                marker = "▶ " if is_selected else ""
                label = f"{indent}{marker}{icon} {f.name}"
                if st.button(label, key=f"floc_btn_{f.id}",
                             use_container_width=True,
                             help=f"Level {f.level}"):
                    st.session_state["equip_floc_sel"] = f.id
                    st.rerun()

    # ── Resolve selected FLOC ─────────────────────────────────────────────────
    selected_floc_id = st.session_state["equip_floc_sel"]
    selected_floc = next((f for f in all_flocs if f.id == selected_floc_id), all_flocs[0])
    desc_ids = _get_floc_descendants(all_flocs, selected_floc_id)

    ops = (
        session.query(Operation)
        .filter(Operation.session_id == packaging_session_id)
        .all()
    )

    rows = []
    for op in ops:
        src = op.source_task
        fm = src.failure_mode if src else None
        if not fm or fm.functional_location_id not in desc_ids:
            continue
        floc = fm.functional_location
        tl = op.task_list
        item = tl.item if tl else None
        plan = item.plan if item else None
        rows.append({
            "Equipment": floc.name if floc else "",
            "Task Type": src.task_type if src else "",
            "Description": op.description[:70] if op.description else "",
            "Interval": f"{src.interval} {src.interval_unit}" if src else "",
            "Duration (h)": op.duration_hours or 0,
            "Resource": op.resource_type or "",
            "Online": "✓" if (src and src.is_online) else "🔒",
            "Regulatory": "✓" if (src and src.is_regulatory) else "",
            "Criticality": fm.criticality if fm else "",
        })

    # ── Right panel: independently scrollable task table ──────────────────────
    with col_right:
        st.markdown(f"**Tasks — {selected_floc.name}**")
        with st.container(height=560, border=True):
            st.caption(f"{len(rows)} task{'s' if len(rows) != 1 else ''} shown")
            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True,
                             height=500)
            else:
                st.info("No operations assigned to this equipment in the current packaging run.")


def _render_packaging_trace(session, packaging_session_id: str):
    st.subheader("Packaging Trace")
    st.caption("Every operation mapped to its source FMECA task and assigned plan/item.")

    cache_key = f"trace_df_{packaging_session_id}"
    if cache_key not in st.session_state:
        with st.spinner("Building trace…"):
            st.session_state[cache_key] = _build_trace_df(session, packaging_session_id)

    df: pd.DataFrame = st.session_state[cache_key]

    if df.empty:
        st.info("No operations found.")
        return

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        resources = ["All"] + sorted(df["Resource"].dropna().unique().tolist())
        filter_res = st.selectbox("Resource", resources, key="trace_res")
    with fc2:
        filter_floc = st.text_input("FLOC contains", "", key="trace_floc")
    with fc3:
        filter_plan = st.text_input("Plan name contains", "", key="trace_plan")

    mask = pd.Series([True] * len(df), index=df.index)
    if filter_res != "All":
        mask &= df["Resource"] == filter_res
    if filter_floc:
        mask &= df["FLOC"].str.contains(filter_floc, case=False, na=False)
    if filter_plan:
        mask &= df["Plan"].str.contains(filter_plan, case=False, na=False)

    filtered = df[mask]
    st.caption(f"Showing {len(filtered):,} of {len(df):,} operations")
    st.dataframe(filtered, use_container_width=True, hide_index=True, height=520)


def _render_ai_insights(result: dict, session, packaging_session_id: str):
    cache_key = f"insights_{packaging_session_id}"

    col_btn, _ = st.columns([1, 3])
    with col_btn:
        run = st.button("✨ Generate AI Insights", key="ai_insights_btn")

    if not run and cache_key not in st.session_state:
        return

    if run or cache_key not in st.session_state:
        try:
            import anthropic
        except ImportError:
            st.warning("Install the `anthropic` package to enable AI insights.")
            return

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            st.warning("Set `ANTHROPIC_API_KEY` in your environment (or Streamlit Secrets) to enable AI insights.")
            return

        items = (
            session.query(MaintenancePlanItem)
            .filter(MaintenancePlanItem.session_id == packaging_session_id)
            .all()
        )
        total_items = max(len(items), 1)
        total_plans = max(result.get("plans", 1), 1)
        total_ops = result.get("operations", 0)

        single_op = sum(
            1 for i in items
            if i.task_list and len(i.task_list.operations) == 1
        )
        shutdown_items = sum(1 for i in items if not i.is_online)
        reg_items = sum(1 for i in items if i.is_regulatory)

        prompt = f"""You are a maintenance planning expert reviewing a maintenance plan packaging output for an industrial process facility (LNG/petrochemical).

Packaging statistics:
- Total maintenance plans: {result.get('plans', 0)}
- Total plan items: {total_items}
- Total operations: {total_ops}
- Avg operations per item: {total_ops / total_items:.1f}
- Single-operation items: {single_op} ({single_op / total_items * 100:.0f}% of all items)
- Shutdown items: {shutdown_items} ({shutdown_items / total_items * 100:.0f}%)
- Regulatory items: {reg_items} ({reg_items / total_items * 100:.0f}%)
- Duration splits (items split due to hour cap): {result.get('splits', 0)}
- Avg items per plan: {total_items / total_plans:.1f}

Provide 4-5 concise bullet-point insights a planner should know about this packaging output. Consider:
- Whether the regulatory task ratio looks reasonable for a process facility
- Whether the very high single-operation proportion suggests rules are too granular
- Shutdown vs online balance
- Plan density (items per plan) — whether plans look rich enough to justify the structure
- Any quick rule changes that could improve plan quality

Be specific and practical. No preamble, just the bullets."""

        with st.spinner("Analysing with Claude…"):
            try:
                client = anthropic.Anthropic(api_key=api_key)
                msg = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=600,
                    messages=[{"role": "user", "content": prompt}],
                )
                st.session_state[cache_key] = msg.content[0].text
            except Exception as e:
                st.warning(f"Could not generate insights: {e}")
                return

    if cache_key in st.session_state:
        st.markdown(st.session_state[cache_key])


# ── Main render ───────────────────────────────────────────────────────────────

def render():
    st.header("Step 3 — Review & Refine")

    dataset_id = st.session_state.get("dataset_id")
    if not dataset_id:
        st.warning("⚠️ Load a dataset in Step 1 first.")
        return

    col_gen, col_rerun = st.columns([2, 1])
    with col_gen:
        generate = st.button("▶ Generate Plans", type="primary", use_container_width=True)
    with col_rerun:
        rerun = st.button("🔄 Re-run with current rules", use_container_width=True)

    if generate or rerun:
        rule_set_id = st.session_state.get("active_rule_set_id")
        plan_prefix = st.session_state.get("plan_prefix", "PM-LNG")
        with st.spinner("Packaging tasks…"):
            try:
                result = package(
                    dataset_id=dataset_id,
                    rule_set_id=rule_set_id,
                    plan_prefix=plan_prefix,
                    dry_run=False,
                )
                st.session_state["packaging_session_id"] = result["session_id"]
                st.session_state["packaging_result"] = result
                # Clear stale caches
                for k in list(st.session_state.keys()):
                    if k.startswith("trace_df_") or k.startswith("insights_"):
                        del st.session_state[k]
                st.success(
                    f"✅ Generated: {result['plans']} plans | "
                    f"{result['items']} items | "
                    f"{result['operations']} operations"
                )
            except Exception as e:
                st.error(f"Packaging failed: {e}")
                return

    packaging_session_id = st.session_state.get("packaging_session_id")
    if not packaging_session_id:
        st.info("Click **Generate Plans** to package the loaded dataset.")
        return

    result = st.session_state.get("packaging_result", {})

    # Summary bar
    m_cols = st.columns(6)
    metrics = [
        ("Plans", result.get("plans", 0)),
        ("Items", result.get("items", 0)),
        ("Task Lists", result.get("task_lists", 0)),
        ("Operations", result.get("operations", 0)),
        ("Duration Splits", result.get("splits", 0)),
        ("Regulatory Items", result.get("regulatory_count", 0)),
    ]
    for col, (label, val) in zip(m_cols, metrics):
        with col:
            st.metric(label, val)

    st.divider()

    session = get_session()
    try:
        plans = (
            session.query(MaintenancePlan)
            .filter(MaintenancePlan.session_id == packaging_session_id)
            .order_by(MaintenancePlan.name)
            .all()
        )

        view_mode = st.radio(
            "View",
            ["📋 Plan View", "🏭 Equipment View", "📊 Packaging Trace"],
            horizontal=True,
            key="review_view_mode",
        )

        st.divider()

        if view_mode == "📋 Plan View":
            _render_plan_view(session, packaging_session_id, plans)

        elif view_mode == "🏭 Equipment View":
            _render_equipment_view(session, packaging_session_id, dataset_id)

        else:
            _render_packaging_trace(session, packaging_session_id)

        st.divider()
        st.subheader("🤖 AI Insights")
        _render_ai_insights(result, session, packaging_session_id)

    finally:
        session.close()
