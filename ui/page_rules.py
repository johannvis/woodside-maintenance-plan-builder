"""Step 2: Rule Editor."""

import json
import streamlit as st
from db.database import init_db, get_session
from db.models import RuleSet, Rule
from engine.packager import package
from engine.rules import RuleConfig
from config import DEFAULT_RULES_PATH, DEFAULT_PLAN_PREFIX


RULE_TYPE_META = {
    "grouping_level": {
        "label": "Primary Grouping",
        "icon": "🌲",
        "desc": "Group tasks by asset hierarchy level (1=Train, 2=System, 3=Sub-system, 4=Equipment)",
        "param_label": "Hierarchy Level",
        "param_type": "int",
        "param_min": 1,
        "param_max": 4,
    },
    "max_duration": {
        "label": "Max Duration Cap",
        "icon": "⏱️",
        "desc": "Split task list items when total duration exceeds cap",
        "param_label": "Max Hours per Item",
        "param_type": "float",
        "param_min": 1.0,
        "param_max": 24.0,
    },
    "shutdown_separation": {
        "label": "Shutdown Separation",
        "icon": "🔒",
        "desc": "Separate online and offline (shutdown) tasks into different items",
        "param_label": "Enabled",
        "param_type": "bool",
    },
    "regulatory_isolation": {
        "label": "Regulatory Isolation",
        "icon": "📋",
        "desc": "Isolate regulatory/statutory tasks into dedicated plan items",
        "param_label": "Enabled",
        "param_type": "bool",
    },
    "task_type_separation": {
        "label": "Task Type Separation",
        "icon": "🔧",
        "desc": "Separate tasks by type (Inspection, Lubrication, PM, CM) into distinct items",
        "param_label": "Enabled",
        "param_type": "bool",
    },
    "criticality_isolation": {
        "label": "Criticality Isolation",
        "icon": "🔴",
        "desc": "Isolate high-criticality (A-class) tasks into dedicated plan items",
        "param_label": "Enabled",
        "param_type": "bool",
    },
    "max_operations": {
        "label": "Max Operations per Item",
        "icon": "🔢",
        "desc": "Split task list items when operation count exceeds cap (0 = disabled)",
        "param_label": "Max Operations (0 = off)",
        "param_type": "int",
        "param_min": 0,
        "param_max": 100,
    },
}


def _load_default_rules(session) -> RuleSet:
    """Load default rules from JSON seed file."""
    with open(DEFAULT_RULES_PATH) as f:
        data = json.load(f)

    # Check if already seeded
    existing = session.query(RuleSet).filter(RuleSet.name == data["name"]).first()
    if existing:
        return existing

    rs = RuleSet(name=data["name"], description=data["description"])
    session.add(rs)
    session.flush()

    for i, r in enumerate(data["rules"]):
        rule = Rule(
            rule_set_id=rs.id,
            rule_type=r["rule_type"],
            description=r["description"],
            parameter_key=r["parameter_key"],
            parameter_value=r["parameter_value"],
            sort_order=i,
        )
        session.add(rule)

    session.commit()
    return rs


def render():
    st.header("Step 2 — Rule Editor")
    init_db()

    dataset_id = st.session_state.get("dataset_id")
    if not dataset_id:
        st.warning("⚠️ Load a dataset in Step 1 first.")
        return

    session = get_session()
    try:
        # Load or create default rule set
        rule_sets = session.query(RuleSet).all()
        if not rule_sets:
            default_rs = _load_default_rules(session)
            rule_sets = [default_rs]

        # Rule set selector
        rs_names = [rs.name for rs in rule_sets]
        selected_rs_name = st.selectbox("Active Rule Set", rs_names)
        active_rs = next(rs for rs in rule_sets if rs.name == selected_rs_name)
        st.session_state["active_rule_set_id"] = active_rs.id

        col_left, col_right = st.columns([3, 2])

        with col_left:
            st.subheader("Rule Cards")

            rules = (
                session.query(Rule)
                .filter(Rule.rule_set_id == active_rs.id)
                .order_by(Rule.sort_order)
                .all()
            )

            updated_rules = {}
            for rule in rules:
                meta = RULE_TYPE_META.get(rule.rule_type, {})
                icon = meta.get("icon", "📌")
                label = meta.get("label", rule.rule_type)

                with st.expander(f"{icon} {label}", expanded=True):
                    st.caption(meta.get("desc", rule.description))

                    param_type = meta.get("param_type", "str")
                    current_val = rule.parameter_value

                    if param_type == "int":
                        new_val = st.number_input(
                            meta.get("param_label", rule.parameter_key),
                            min_value=meta.get("param_min", 1),
                            max_value=meta.get("param_max", 10),
                            value=int(current_val) if current_val.isdigit() else 3,
                            step=1,
                            key=f"rule_{rule.id}_val",
                        )
                        updated_rules[rule.id] = str(int(new_val))

                    elif param_type == "float":
                        try:
                            fval = float(current_val)
                        except (ValueError, TypeError):
                            fval = 8.0
                        new_val = st.number_input(
                            meta.get("param_label", rule.parameter_key),
                            min_value=float(meta.get("param_min", 1.0)),
                            max_value=float(meta.get("param_max", 24.0)),
                            value=fval,
                            step=0.5,
                            key=f"rule_{rule.id}_val",
                        )
                        updated_rules[rule.id] = str(new_val)

                    elif param_type == "bool":
                        bool_val = current_val.strip().lower() in ("true", "1", "yes")
                        new_val = st.toggle(
                            meta.get("param_label", rule.parameter_key),
                            value=bool_val,
                            key=f"rule_{rule.id}_val",
                        )
                        updated_rules[rule.id] = "true" if new_val else "false"

            # Plan prefix
            st.divider()
            plan_prefix = st.text_input(
                "Plan Naming Prefix",
                value=st.session_state.get("plan_prefix", DEFAULT_PLAN_PREFIX),
            )
            st.session_state["plan_prefix"] = plan_prefix

            # Save button
            if st.button("💾 Save Rule Changes", use_container_width=True):
                for rule_id, new_val in updated_rules.items():
                    rule = session.get(Rule, rule_id)
                    if rule:
                        rule.parameter_value = new_val
                session.commit()
                st.success("Rules saved.")

        with col_right:
            st.subheader("Estimated Output")
            st.caption("Live preview based on current rule values (not yet saved)")

            if st.button("🔄 Refresh Estimate", use_container_width=True):
                # Build config directly from current widget values — no DB read needed
                cfg = RuleConfig()
                for rule_id, new_val in updated_rules.items():
                    rule = session.get(Rule, rule_id)
                    if not rule:
                        continue
                    rt = rule.rule_type
                    if rt == "grouping_level":
                        try: cfg.grouping_level = int(new_val)
                        except ValueError: pass
                    elif rt == "max_duration":
                        try: cfg.max_duration_hours = float(new_val)
                        except ValueError: pass
                    elif rt == "shutdown_separation":
                        cfg.shutdown_separation = new_val.lower() in ("true", "1", "yes")
                    elif rt == "regulatory_isolation":
                        cfg.regulatory_isolation = new_val.lower() in ("true", "1", "yes")
                    elif rt == "task_type_separation":
                        cfg.task_type_separation = new_val.lower() in ("true", "1", "yes")
                    elif rt == "criticality_isolation":
                        cfg.criticality_isolation = new_val.lower() in ("true", "1", "yes")
                    elif rt == "max_operations":
                        try: cfg.max_operations = int(new_val)
                        except ValueError: pass

                with st.spinner("Running dry-run…"):
                    try:
                        est = package(
                            dataset_id=dataset_id,
                            plan_prefix=plan_prefix,
                            dry_run=True,
                            config=cfg,
                        )
                        st.metric("Plans", est["plans"])
                        st.metric("Items", est["items"])
                        st.metric("Task Lists", est["task_lists"])
                        st.metric("Operations", est["operations"])
                        st.metric("Duration Splits", est["splits"])
                        st.metric("Regulatory Items", est["regulatory_count"])
                    except Exception as e:
                        st.error(f"Estimation failed: {e}")

    finally:
        session.close()
