"""Core packaging algorithm — FMECA tasks → SAP PM structures."""

import uuid
from collections import defaultdict
from db.models import (
    FunctionalLocation, FailureMode, Task,
    MaintenancePlan, MaintenancePlanItem, TaskList, Operation,
    RuleSet, Rule,
)
from db.database import get_session
from engine.rules import (
    build_config,
    MaxDurationEvaluator, ShutdownSeparationEvaluator, RegulatoryIsolationEvaluator,
    TaskTypeSeparationEvaluator, CriticalityIsolationEvaluator, MaxOperationsEvaluator,
)
from config import DEFAULT_PLAN_PREFIX


def _get_floc_chain(session, floc_id: str) -> list:
    """Return ordered list of FLOCs from root to the given node."""
    chain = []
    current_id = floc_id
    visited = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        floc = session.get(FunctionalLocation, current_id)
        if not floc:
            break
        chain.insert(0, floc)
        current_id = floc.parent_id
    return chain


def _floc_at_level(chain: list, level: int):
    for f in chain:
        if f.level == level:
            return f
    return chain[-1] if chain else None


def package(
    dataset_id: str,
    rule_set_id=None,
    plan_prefix: str = DEFAULT_PLAN_PREFIX,
    dry_run: bool = False,
    config=None,
) -> dict:
    """
    Package tasks from dataset into SAP PM structures.

    Returns:
        dict with keys: session_id, plans, items, task_lists, operations, splits, regulatory_count
    """
    session = get_session()
    output_session_id = str(uuid.uuid4())

    try:
        # Load rules — use passed config if provided (e.g. for dry-run estimates)
        if config is not None:
            cfg = config
        elif rule_set_id:
            rule_set = session.get(RuleSet, rule_set_id)
            rules = rule_set.rules if rule_set else []
            cfg = build_config(rules)
        else:
            cfg = build_config([])
        max_dur_eval = MaxDurationEvaluator(cfg.max_duration_hours)
        shutdown_eval = ShutdownSeparationEvaluator()
        reg_eval = RegulatoryIsolationEvaluator()
        task_type_eval = TaskTypeSeparationEvaluator()
        crit_eval = CriticalityIsolationEvaluator()
        max_ops_eval = MaxOperationsEvaluator(cfg.max_operations)

        # Load all tasks for this dataset
        tasks = session.query(Task).filter(Task.dataset_id == dataset_id).all()
        if not tasks:
            return {"session_id": output_session_id, "plans": 0, "items": 0,
                    "task_lists": 0, "operations": 0, "splits": 0, "regulatory_count": 0}

        # Build task metadata lookup
        # task → {floc_chain, fm}
        task_meta = {}
        for task in tasks:
            fm = session.get(FailureMode, task.failure_mode_id)
            if not fm:
                continue
            chain = _get_floc_chain(session, fm.functional_location_id)
            task_meta[task.id] = {"task": task, "fm": fm, "chain": chain}

        # ── Step 1: Separate regulatory tasks ──────────────────────────────
        reg_tasks = [t for t in tasks if t.is_regulatory]
        std_tasks = [t for t in tasks if not t.is_regulatory]

        if not cfg.regulatory_isolation:
            std_tasks = tasks
            reg_tasks = []

        all_groups: list[dict] = []  # {tasks, is_regulatory, floc_key, resource_type, interval_key, is_online}

        # ── Step 2–7: Group tasks by level, criticality, online/offline,
        #             resource type, task type, interval, duration, operations ──
        def _group_tasks(task_list, is_regulatory=False):
            groups = []
            # Step 2: Group by hierarchy level
            by_floc: dict[str, list] = defaultdict(list)
            for task in task_list:
                meta = task_meta.get(task.id)
                if not meta:
                    continue
                chain = meta["chain"]
                floc_node = _floc_at_level(chain, cfg.grouping_level)
                key = floc_node.id if floc_node else "unknown"
                by_floc[key].append(task)

            for floc_key, floc_tasks in by_floc.items():
                # Step 3: Separate online/offline
                if cfg.shutdown_separation and not is_regulatory:
                    online_offline = shutdown_eval.split(floc_tasks)
                else:
                    online_offline = {"standard": floc_tasks}

                for ol_key, ol_tasks in online_offline.items():
                    is_online = (ol_key == "online") or not cfg.shutdown_separation

                    # Step 3b: Criticality isolation (A-class vs B/C)
                    if cfg.criticality_isolation and not is_regulatory:
                        crit_buckets = crit_eval.split(ol_tasks, task_meta)
                    else:
                        crit_buckets = {"": ol_tasks}

                    for crit_key, crit_tasks in crit_buckets.items():
                        # Step 4: Split by resource_type
                        by_resource: dict[str, list] = defaultdict(list)
                        for task in crit_tasks:
                            by_resource[task.resource_type or "MISC"].append(task)

                        for resource_type, res_tasks in by_resource.items():
                            # Step 4b: Task type separation
                            if cfg.task_type_separation:
                                type_buckets = task_type_eval.split(res_tasks)
                            else:
                                type_buckets = {"": res_tasks}

                            for task_type_key, typed_tasks in type_buckets.items():
                                # Step 5: Split by interval
                                by_interval: dict[str, list] = defaultdict(list)
                                for task in typed_tasks:
                                    interval_key = f"{task.interval}-{task.interval_unit}"
                                    by_interval[interval_key].append(task)

                                for interval_key, int_tasks in by_interval.items():
                                    # Step 6: Max-duration cap
                                    dur_buckets = max_dur_eval.split(int_tasks)
                                    for dur_bucket in dur_buckets:
                                        # Step 7: Max-operations cap
                                        op_buckets = max_ops_eval.split(dur_bucket)
                                        for bucket in op_buckets:
                                            groups.append({
                                                "tasks": bucket,
                                                "is_regulatory": is_regulatory,
                                                "floc_key": floc_key,
                                                "resource_type": resource_type,
                                                "interval_key": interval_key,
                                                "is_online": is_online,
                                                "criticality_key": crit_key,
                                                "task_type_key": task_type_key,
                                            })
            return groups

        all_groups.extend(_group_tasks(std_tasks, is_regulatory=False))
        all_groups.extend(_group_tasks(reg_tasks, is_regulatory=True))

        # ── Step 7: Assign names and build ORM objects ────────────────────────
        plans_created = []
        items_created = []
        task_lists_created = []
        operations_created = []
        splits = 0
        regulatory_count = sum(1 for g in all_groups if g["is_regulatory"])

        # Group items under plans by (floc_key, resource_type)
        plan_groups: dict[tuple, list] = defaultdict(list)
        for group in all_groups:
            plan_key = (group["floc_key"], group["resource_type"])
            plan_groups[plan_key].append(group)

        plan_seq = 1
        for plan_key, groups in plan_groups.items():
            floc_key, resource_type = plan_key
            floc = session.get(FunctionalLocation, floc_key)
            floc_name = floc.name if floc else floc_key[:8]

            plan_name = f"{plan_prefix}-{floc_name}-{resource_type}-{plan_seq:03d}"
            plan_id = str(uuid.uuid4())
            plan = MaintenancePlan(
                id=plan_id,
                session_id=output_session_id,
                name=plan_name,
                description=f"Maintenance plan for {floc_name} — {resource_type}",
            )
            if not dry_run:
                session.add(plan)

            item_seq = 1
            prev_interval_key = None
            for group in groups:
                if prev_interval_key and prev_interval_key != group["interval_key"]:
                    splits += 1
                prev_interval_key = group["interval_key"]

                interval_parts = group["interval_key"].split("-", 1)
                freq = int(interval_parts[0]) if interval_parts[0].isdigit() else 1
                freq_unit = interval_parts[1] if len(interval_parts) > 1 else "months"

                suffix_parts = []
                if group["is_regulatory"]:
                    suffix_parts.append("REG")
                elif group.get("criticality_key") == "critical":
                    suffix_parts.append("CRIT")
                suffix_parts.append("ONLINE" if group["is_online"] else "SHUTDOWN")
                if group.get("task_type_key"):
                    suffix_parts.append(group["task_type_key"][:8])
                suffix = "-".join(suffix_parts)
                item_desc = f"{floc_name} | {resource_type} | {group['interval_key']} | {suffix}"

                item_id = str(uuid.uuid4())
                item = MaintenancePlanItem(
                    id=item_id,
                    session_id=output_session_id,
                    maintenance_plan_id=plan_id,
                    frequency=freq,
                    frequency_unit=freq_unit,
                    description=item_desc,
                    is_regulatory=group["is_regulatory"],
                    is_online=group["is_online"],
                    total_duration_hours=sum(t.duration_hours or 0 for t in group["tasks"]),
                )
                if not dry_run:
                    session.add(item)

                tl_id = str(uuid.uuid4())
                tl_name = f"TL-{plan_name}-{item_seq:02d}"
                tl = TaskList(
                    id=tl_id,
                    session_id=output_session_id,
                    maintenance_plan_item_id=item_id,
                    name=tl_name,
                )
                if not dry_run:
                    session.add(tl)

                # ── Step 7: Assign operation numbers ─────────────────────────
                for op_idx, task in enumerate(group["tasks"]):
                    op = Operation(
                        id=str(uuid.uuid4()),
                        session_id=output_session_id,
                        task_list_id=tl_id,
                        operation_no=(op_idx + 1) * 10,
                        source_task_id=task.id,
                        description=task.description[:200] if task.description else "",
                        duration_hours=task.duration_hours,
                        resource_type=task.resource_type,
                        materials=task.materials,
                        document_ref=None,
                    )
                    if not dry_run:
                        session.add(op)
                    operations_created.append(op)

                items_created.append(item)
                task_lists_created.append(tl)
                item_seq += 1

            plans_created.append(plan)
            plan_seq += 1

        if not dry_run:
            session.commit()

        return {
            "session_id": output_session_id,
            "plans": len(plans_created),
            "items": len(items_created),
            "task_lists": len(task_lists_created),
            "operations": len(operations_created),
            "splits": splits,
            "regulatory_count": regulatory_count,
        }

    finally:
        session.close()
