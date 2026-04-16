"""Step 3: Review & Refine."""

import pandas as pd
import streamlit as st
from db.database import get_session
from db.models import (
    MaintenancePlan, MaintenancePlanItem, TaskList, Operation,
    Task, FailureMode, FunctionalLocation,
)
from engine.packager import package


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
        # FMECA traceability
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

    return {
        "item": item,
        "ops": op_rows,
        "trace": trace_rows,
        "tl": tl,
    }


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

        col_tree, col_detail = st.columns([2, 3])

        with col_tree:
            st.subheader("Plan Tree")
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
            else:
                detail = _get_item_detail(session, selected_item_id)
                if not detail:
                    st.warning("Item not found.")
                else:
                    item = detail["item"]
                    st.subheader(f"Item Detail: {item.description[:60] if item.description else ''}")

                    badges = []
                    if item.is_regulatory:
                        badges.append("🔴 Regulatory")
                    if not item.is_online:
                        badges.append("🔒 Shutdown")
                    badges.append(f"⏱️ {item.frequency} {item.frequency_unit}")
                    badges.append(f"⏳ {item.total_duration_hours:.1f}h total")
                    st.markdown("  ".join(badges))

                    # Duration bar
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

                    # Operations list
                    st.markdown("**Operations**")
                    if detail["ops"]:
                        ops_df = pd.DataFrame(detail["ops"])
                        st.dataframe(ops_df, use_container_width=True, hide_index=True)
                    else:
                        st.info("No operations.")

                    # Move operation
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
                                    # Recalculate durations
                                    item.total_duration_hours -= op_to_move.duration_hours or 0
                                    target_item.total_duration_hours += op_to_move.duration_hours or 0
                                    session.commit()
                                    st.session_state["selected_item_id"] = selected_item_id
                                    st.success("Operation moved.")
                                    st.rerun()

                    st.divider()

                    # FMECA traceability
                    st.markdown("**FMECA Traceability**")
                    if detail["trace"]:
                        st.dataframe(
                            pd.DataFrame(detail["trace"]),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.info("No traceability data.")

    finally:
        session.close()
