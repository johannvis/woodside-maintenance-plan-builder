"""Plan mutation executor — applies agent-recommended structural changes."""

from collections import Counter

from db.models import AgentDecision, JudgeDecision, MaintenancePlanItem


def dismiss_decision(session, judge_decision_id: str) -> None:
    """Remove a decision from the pending queue without applying it."""
    jd = session.get(JudgeDecision, judge_decision_id)
    if jd:
        jd.modified = True
        session.commit()


def apply_merge(session, judge_decision_id: str) -> dict:
    """
    Move all operations from the source item to the agent-nominated target item.
    Source item is left empty (but not deleted — planner can clean up on re-run).
    Returns {"ok": True, "ops_moved": N, "target": desc} or {"ok": False, "error": msg}.
    """
    jd = session.get(JudgeDecision, judge_decision_id)
    if not jd:
        return {"ok": False, "error": "Decision not found"}

    source_item_id = jd.maintenance_plan_item_id

    # Find merge target from agent decisions (most common target_item_id)
    merge_ads = (
        session.query(AgentDecision)
        .filter(
            AgentDecision.maintenance_plan_item_id == source_item_id,
            AgentDecision.session_id == jd.session_id,
            AgentDecision.recommended_action == "merge",
            AgentDecision.target_item_id.isnot(None),
        )
        .all()
    )

    if not merge_ads:
        return {"ok": False, "error": "No merge target specified by agents — review manually"}

    target_item_id = Counter(d.target_item_id for d in merge_ads).most_common(1)[0][0]

    source_item = session.get(MaintenancePlanItem, source_item_id)
    target_item = session.get(MaintenancePlanItem, target_item_id)

    if not source_item or not target_item:
        return {"ok": False, "error": "Source or target item no longer exists"}

    source_tl = source_item.task_list
    target_tl = target_item.task_list

    if not source_tl or not target_tl:
        return {"ok": False, "error": "Task list missing on source or target"}

    ops_moved = 0
    duration_moved = 0.0
    for op in list(source_tl.operations):
        op.task_list_id = target_tl.id
        duration_moved += op.duration_hours or 0
        ops_moved += 1

    # Re-number operations on target to avoid duplicates
    all_ops = sorted(target_tl.operations, key=lambda o: o.operation_no or 0)
    for i, op in enumerate(all_ops):
        op.operation_no = (i + 1) * 10

    source_item.total_duration_hours = max(0.0, (source_item.total_duration_hours or 0) - duration_moved)
    target_item.total_duration_hours = (target_item.total_duration_hours or 0) + duration_moved

    jd.modified = True
    session.commit()

    return {
        "ok": True,
        "ops_moved": ops_moved,
        "target": (target_item.description or target_item_id)[:50],
    }
