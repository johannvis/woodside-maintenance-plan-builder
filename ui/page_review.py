"""Step 3: Review & Refine."""

import os
from collections import defaultdict

import pandas as pd
import streamlit as st
from db.database import get_session
from db.models import (
    MaintenancePlan, MaintenancePlanItem, TaskList, Operation,
    Task, FailureMode, FunctionalLocation,
)
from engine.packager import package


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

def _render_plan_view(session, packaging_session_id: str, plans: list):
    col_tree, col_detail = st.columns([2, 3])

    with col_tree:
        st.markdown("**Plan Tree**")
        with st.container(height=700, border=True):
            for plan in plans:
                with st.expander(f"📋 {plan.name}", expanded=False):
                    for item in plan.items:
                        item_label = (
                            f"{'🔴' if item.is_regulatory else ('🟡' if not item.is_online else '🟢')} "
                            f"{item.description[:50] if item.description else item.id[:8]} "
                            f"({item.total_duration_hours:.1f}h)"
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
