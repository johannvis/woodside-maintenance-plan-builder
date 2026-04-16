"""Step 1: Ingest & Preview."""

import os
import pandas as pd
import streamlit as st
from db.database import init_db, get_session
from db.loader import load_fmeca, get_dataset_stats
from db.models import FunctionalLocation, Task, FailureMode
from config import DEFAULT_DATASET_PATH


def render():
    st.header("Step 1 — Ingest & Preview")

    init_db()

    # ── File upload ──────────────────────────────────────────────────────────
    col1, col2 = st.columns([2, 1])
    with col1:
        uploaded = st.file_uploader(
            "Upload FMECA workbook (.xlsx)",
            type=["xlsx"],
            help="Drag and drop your FMECA Excel file here",
        )
    with col2:
        st.markdown("**Or use default dataset:**")
        use_default = st.button("Load LNG Train Sample", use_container_width=True)

    # ── Load data ────────────────────────────────────────────────────────────
    if uploaded or use_default:
        with st.spinner("Parsing FMECA workbook…"):
            try:
                if uploaded:
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                        tmp.write(uploaded.read())
                        tmp_path = tmp.name
                    result = load_fmeca(tmp_path)
                    os.unlink(tmp_path)
                else:
                    if not os.path.exists(DEFAULT_DATASET_PATH):
                        st.error(f"Default dataset not found at {DEFAULT_DATASET_PATH}")
                        return
                    result = load_fmeca(DEFAULT_DATASET_PATH)

                st.session_state["dataset_id"] = result["dataset_id"]
                st.session_state["load_result"] = result

                if result["warnings"]:
                    with st.expander(f"⚠️ {len(result['warnings'])} parse warnings"):
                        for w in result["warnings"][:20]:
                            st.text(w)

            except Exception as e:
                st.error(f"Failed to load dataset: {e}")
                return

    # ── Display stats ────────────────────────────────────────────────────────
    dataset_id = st.session_state.get("dataset_id")
    if not dataset_id:
        st.info("Upload a workbook or load the sample dataset to begin.")
        return

    stats = get_dataset_stats(dataset_id)

    # Stats chips
    cols = st.columns(5)
    chips = [
        ("Tasks", stats["total_tasks"]),
        ("FLOCs", stats["total_flocs"]),
        ("Asset Classes", stats["asset_classes"]),
        ("Systems", stats["systems"]),
        ("Trains", stats["trains"]),
    ]
    for col, (label, value) in zip(cols, chips):
        with col:
            st.metric(label, value)

    # Validation badge
    if stats["total_tasks"] == 0:
        st.warning("⚠️ No tasks found — check column mapping")
    else:
        st.success(f"✅ Dataset loaded — {stats['total_tasks']} tasks ready for packaging")

    st.divider()

    session = get_session()
    try:
        trains = (
            session.query(FunctionalLocation)
            .filter(
                FunctionalLocation.dataset_id == dataset_id,
                FunctionalLocation.level == 1,
            )
            .all()
        )

        # ── Side-by-side: hierarchy left, tasks right ─────────────────────────
        col_tree, col_tasks = st.columns([1, 2])

        with col_tree:
            st.subheader("Asset Hierarchy")
            for train in trains:
                with st.expander(f"🏭 {train.name}", expanded=len(trains) == 1):
                    systems = (
                        session.query(FunctionalLocation)
                        .filter(FunctionalLocation.parent_id == train.id)
                        .all()
                    )
                    for system in systems:
                        with st.expander(f"⚙️ {system.name}"):
                            subsystems = (
                                session.query(FunctionalLocation)
                                .filter(FunctionalLocation.parent_id == system.id)
                                .all()
                            )
                            for sub in subsystems:
                                task_count_sub = (
                                    session.query(Task)
                                    .join(FailureMode)
                                    .join(FunctionalLocation)
                                    .filter(
                                        (FunctionalLocation.id == sub.id) |
                                        (FunctionalLocation.parent_id == sub.id)
                                    )
                                    .count()
                                )
                                btn_label = f"📦 {sub.name} ({task_count_sub})"
                                if st.button(btn_label, key=f"floc_{sub.id}", use_container_width=True):
                                    st.session_state["selected_floc_id"] = sub.id

        with col_tasks:
            selected_floc = st.session_state.get("selected_floc_id")
            if not selected_floc:
                st.info("← Select a node in the hierarchy to see its tasks.")
            else:
                floc = session.get(FunctionalLocation, selected_floc)
                tasks_q = (
                    session.query(Task, FailureMode, FunctionalLocation)
                    .join(FailureMode, Task.failure_mode_id == FailureMode.id)
                    .join(FunctionalLocation, FailureMode.functional_location_id == FunctionalLocation.id)
                    .filter(
                        (FunctionalLocation.id == selected_floc) |
                        (FunctionalLocation.parent_id == selected_floc)
                    )
                    .limit(200)
                    .all()
                )
                floc_name = floc.name if floc else selected_floc
                st.subheader(f"Tasks — {floc_name}")
                st.caption(f"{len(tasks_q)} tasks shown")
                if tasks_q:
                    rows = []
                    for task, fm, fl in tasks_q:
                        rows.append({
                            "Equipment": fl.name,
                            "Task Type": task.task_type,
                            "Description": task.description[:80] if task.description else "",
                            "Interval": f"{task.interval} {task.interval_unit}",
                            "Duration (hrs)": task.duration_hours,
                            "Resource": task.resource_type,
                            "Online": "✓" if task.is_online else "✗",
                            "Regulatory": "✓" if task.is_regulatory else "",
                            "Criticality": fm.criticality,
                        })
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.info("No tasks found for this selection.")

        # ── Distribution charts ────────────────────────────────────────────────
        st.divider()
        st.subheader("Task Distribution")
        c1, c2, c3 = st.columns(3)

        with c1:
            st.caption("By Task Type")
            if stats["task_types"]:
                st.bar_chart(pd.DataFrame.from_dict(
                    stats["task_types"], orient="index", columns=["count"]
                ))

        with c2:
            st.caption("By Resource Type (Planner Group)")
            if stats["resource_types"]:
                st.bar_chart(pd.DataFrame.from_dict(
                    stats["resource_types"], orient="index", columns=["count"]
                ))

        with c3:
            st.caption("By Criticality")
            if stats["criticalities"]:
                st.bar_chart(pd.DataFrame.from_dict(
                    stats["criticalities"], orient="index", columns=["count"]
                ))

    finally:
        session.close()
