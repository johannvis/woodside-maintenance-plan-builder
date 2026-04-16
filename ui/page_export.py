"""Step 4: Export."""

import io
import json
import pandas as pd
import streamlit as st
from db.database import get_session
from db.models import (
    MaintenancePlan, MaintenancePlanItem, TaskList, Operation,
    Task, FailureMode, FunctionalLocation, Rule, RuleSet,
)
from export.excel_writer import write_excel


def _build_flat_records(session, session_id: str) -> list[dict]:
    rows = []
    plans = (
        session.query(MaintenancePlan)
        .filter(MaintenancePlan.session_id == session_id)
        .all()
    )
    for plan in plans:
        for item in plan.items:
            tl = item.task_list
            ops = tl.operations if tl else []
            for op in ops:
                src_task = session.get(Task, op.source_task_id) if op.source_task_id else None
                fm = session.get(FailureMode, src_task.failure_mode_id) if src_task else None
                floc = session.get(FunctionalLocation, fm.functional_location_id) if fm else None
                rows.append({
                    "Plan Name": plan.name,
                    "Plan Description": plan.description,
                    "Item Description": item.description,
                    "Frequency": item.frequency,
                    "Frequency Unit": item.frequency_unit,
                    "Is Regulatory": item.is_regulatory,
                    "Is Online": item.is_online,
                    "Total Duration (hrs)": item.total_duration_hours,
                    "Task List Name": tl.name if tl else "",
                    "Operation No": f"{op.operation_no:03d}",
                    "Operation Description": op.description,
                    "Resource Type": op.resource_type,
                    "Duration (hrs)": op.duration_hours,
                    "Materials": op.materials or "",
                    "FLOC": floc.name if floc else "",
                    "Failure Mode": fm.failure_mode[:80] if fm and fm.failure_mode else "",
                    "Criticality": fm.criticality if fm else "",
                    "Source Task Type": src_task.task_type if src_task else "",
                })
    return rows


def render():
    st.header("Step 4 — Export")

    session_id = st.session_state.get("packaging_session_id")
    if not session_id:
        st.warning("⚠️ Generate plans in Step 3 first.")
        return

    # Format picker
    fmt = st.radio(
        "Export Format",
        ["Data Mate Staging (.xlsx)", "Flat CSV Bundle", "Full JSON"],
        horizontal=True,
    )

    # Include checkboxes
    st.subheader("Include in Export")
    inc_cols = st.columns(3)
    with inc_cols[0]:
        inc_plans = st.checkbox("Maintenance Plans", value=True)
        inc_items = st.checkbox("Plan Items", value=True)
    with inc_cols[1]:
        inc_tl = st.checkbox("Task Lists", value=True)
        inc_ops = st.checkbox("Operations", value=True)
    with inc_cols[2]:
        inc_trace = st.checkbox("FMECA Traceability", value=True)
        inc_audit = st.checkbox("Rule Audit", value=True)

    session = get_session()
    try:
        records = _build_flat_records(session, session_id)
        if not records:
            st.error("No data found for this session. Please generate plans first.")
            return

        df = pd.DataFrame(records)

        # Preview
        st.subheader("Preview (first 20 rows)")
        st.dataframe(df.head(20), use_container_width=True, hide_index=True)

        # Validation
        n_plans = df["Plan Name"].nunique()
        n_items = df["Item Description"].nunique()
        n_ops = len(df)
        st.success(f"✅ Ready to export: {n_plans} plans | {n_items} items | {n_ops} operations")

        # Download
        if fmt == "Data Mate Staging (.xlsx)":
            # Fetch rule audit info
            rule_set_id = st.session_state.get("active_rule_set_id")
            rules_data = []
            if inc_audit and rule_set_id:
                rs = session.get(RuleSet, rule_set_id)
                if rs:
                    for r in rs.rules:
                        rules_data.append({
                            "Rule Type": r.rule_type,
                            "Description": r.description,
                            "Parameter": r.parameter_key,
                            "Value": r.parameter_value,
                        })

            buf = io.BytesIO()
            write_excel(
                buf,
                records=records,
                rules_audit=rules_data if inc_audit else [],
                include_trace=inc_trace,
            )
            buf.seek(0)
            st.download_button(
                "⬇️ Download Data Mate Staging (.xlsx)",
                data=buf,
                file_name=f"woodside_maintenance_plans_{session_id[:8]}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        elif fmt == "Flat CSV Bundle":
            csv_buf = io.StringIO()
            df.to_csv(csv_buf, index=False)
            st.download_button(
                "⬇️ Download CSV",
                data=csv_buf.getvalue().encode(),
                file_name=f"woodside_maintenance_plans_{session_id[:8]}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        elif fmt == "Full JSON":
            json_str = json.dumps(records, indent=2, default=str)
            st.download_button(
                "⬇️ Download JSON",
                data=json_str.encode(),
                file_name=f"woodside_maintenance_plans_{session_id[:8]}.json",
                mime="application/json",
                use_container_width=True,
            )

    finally:
        session.close()
