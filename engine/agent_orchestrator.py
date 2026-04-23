"""Agent orchestrator — runs multi-agent review of a packaged maintenance plan."""

import json
import queue
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from db.database import get_session
from db.models import (
    AgentProfile, AgentDecision, JudgeDecision,
    MaintenancePlan, MaintenancePlanItem, Operation, Task, FailureMode,
    FunctionalLocation,
)
from engine.agents.safety_agent import SafetyAgent
from engine.agents.cost_agent import CostAgent
from engine.agents.efficiency_agent import EfficiencyAgent
from engine.agents.integrity_agent import IntegrityAgent
from engine.agents.coverage_agent import CoverageAgent
from engine.agents.route_agent import RouteAgent
from engine.agents.judge_agent import JudgeAgent


ROLE_TO_CLASS = {
    "safety": SafetyAgent,
    "cost": CostAgent,
    "efficiency": EfficiencyAgent,
    "integrity": IntegrityAgent,
    "coverage": CoverageAgent,
    "route": RouteAgent,
}

ROLE_ICONS = {
    "safety": "🔒",
    "cost": "💰",
    "efficiency": "⚡",
    "integrity": "🔩",
    "coverage": "📋",
    "route": "🗺️",
}


def _build_item_context(session, item: MaintenancePlanItem) -> dict:
    """Build the context dict passed to every agent for an item."""
    tl = item.task_list
    ops_raw = tl.operations if tl else []

    operations = []
    source_tasks = []
    for op in ops_raw:
        operations.append({
            "op_no": op.operation_no,
            "description": op.description or "",
            "resource": op.resource_type or "",
            "duration_hours": op.duration_hours or 0,
            "materials": op.materials or "",
        })
        src = session.get(Task, op.source_task_id) if op.source_task_id else None
        if src:
            fm = session.get(FailureMode, src.failure_mode_id) if src.failure_mode_id else None
            source_tasks.append({
                "failure_mode": fm.failure_mode if fm else "",
                "criticality": fm.criticality if fm else "",
                "task_type": src.task_type or "",
                "interval": src.interval,
                "interval_unit": src.interval_unit or "",
                "is_online": src.is_online,
                "is_regulatory": src.is_regulatory,
                "resource_type": src.resource_type or "",
            })

    # Adjacent items in the same plan
    plan = item.plan
    adjacent_items = []
    if plan:
        for adj in plan.items:
            if adj.id != item.id:
                adj_tl = adj.task_list
                adj_op_count = len(adj_tl.operations) if adj_tl else 0
                adjacent_items.append({
                    "id": adj.id,
                    "description": adj.description or "",
                    "frequency": adj.frequency,
                    "frequency_unit": adj.frequency_unit or "",
                    "total_duration_hours": adj.total_duration_hours or 0,
                    "is_online": adj.is_online,
                    "resource_type": (
                        source_tasks[0]["resource_type"] if source_tasks else ""
                    ),
                })

    shutdown_items = [a for a in adjacent_items if not a["is_online"]
                      and a["frequency"] == item.frequency
                      and a["frequency_unit"] == item.frequency_unit]
    online_items = [a for a in adjacent_items if a["is_online"]
                    and a["frequency"] == item.frequency
                    and a["frequency_unit"] == item.frequency_unit]

    # ── Spatial / coverage context ────────────────────────────────────────────
    # Resolve FLOC hierarchy for the first source task
    floc_hierarchy = {"l1": "", "l2": "", "l3": "", "l4": ""}
    floc_ids_in_item = set()
    l3_floc_id = None

    for op in ops_raw:
        src = session.get(Task, op.source_task_id) if op.source_task_id else None
        if not src:
            continue
        fm = session.get(FailureMode, src.failure_mode_id) if src.failure_mode_id else None
        if not fm:
            continue
        floc_ids_in_item.add(fm.functional_location_id)
        # Walk up to L3
        cur_id = fm.functional_location_id
        visited = set()
        while cur_id and cur_id not in visited:
            visited.add(cur_id)
            floc = session.get(FunctionalLocation, cur_id)
            if not floc:
                break
            level_key = {1: "l1", 2: "l2", 3: "l3", 4: "l4"}.get(floc.level)
            if level_key and not floc_hierarchy[level_key]:
                floc_hierarchy[level_key] = floc.name
            if floc.level == 3 and l3_floc_id is None:
                l3_floc_id = floc.id
            cur_id = floc.parent_id

    # Count all equipment (L4) under the same L3 parent
    total_equipment_in_l3 = 0
    if l3_floc_id:
        total_equipment_in_l3 = (
            session.query(FunctionalLocation)
            .filter(
                FunctionalLocation.parent_id == l3_floc_id,
                FunctionalLocation.level == 4,
            )
            .count()
        )

    # Coverage: all disciplines + task types in the FMECA for this L3 area
    all_disciplines_in_floc = set()
    all_task_types_in_floc = set()
    disciplines_covered_by_other_items = set()

    if l3_floc_id and plan:
        # All tasks for FLOCs under this L3
        l4_flocs = session.query(FunctionalLocation).filter(
            FunctionalLocation.parent_id == l3_floc_id
        ).all()
        l4_ids = {f.id for f in l4_flocs}

        all_fms = session.query(FailureMode).filter(
            FailureMode.functional_location_id.in_(l4_ids)
        ).all()
        for fm in all_fms:
            for t in fm.tasks:
                if t.resource_type:
                    all_disciplines_in_floc.add(t.resource_type.upper())
                if t.task_type:
                    all_task_types_in_floc.add(t.task_type.upper())

        # Disciplines covered by OTHER plan items
        for adj in plan.items:
            if adj.id == item.id:
                continue
            adj_tl = adj.task_list
            if not adj_tl:
                continue
            for op in adj_tl.operations:
                if op.resource_type:
                    disciplines_covered_by_other_items.add(op.resource_type.upper())

    # Route: other plan items in the same session with same L3 + same resource + same interval
    item_resource = source_tasks[0]["resource_type"].upper() if source_tasks else ""
    same_area_same_resource_items = []

    if l3_floc_id and plan:
        # Get all items in the packaging session
        session_items = (
            session.query(MaintenancePlanItem)
            .filter(MaintenancePlanItem.session_id == item.session_id)
            .all()
        )
        for si in session_items:
            if si.id == item.id:
                continue
            if si.frequency != item.frequency or si.frequency_unit != item.frequency_unit:
                continue
            si_tl = si.task_list
            if not si_tl:
                continue
            # Check if any operation in this item is under the same L3
            si_resource = ""
            si_in_same_area = False
            for op in si_tl.operations:
                if op.resource_type:
                    si_resource = op.resource_type.upper()
                src = session.get(Task, op.source_task_id) if op.source_task_id else None
                if not src:
                    continue
                fm = session.get(FailureMode, src.failure_mode_id) if src.failure_mode_id else None
                if not fm:
                    continue
                cur_id = fm.functional_location_id
                visited = set()
                while cur_id and cur_id not in visited:
                    visited.add(cur_id)
                    floc = session.get(FunctionalLocation, cur_id)
                    if not floc:
                        break
                    if floc.level == 3 and floc.id == l3_floc_id:
                        si_in_same_area = True
                        break
                    cur_id = floc.parent_id
                if si_in_same_area:
                    break

            if si_in_same_area and si_resource == item_resource:
                same_area_same_resource_items.append({
                    "id": si.id,
                    "description": si.description or "",
                    "frequency": si.frequency,
                    "frequency_unit": si.frequency_unit or "",
                    "total_duration_hours": si.total_duration_hours or 0,
                    "op_count": len(si_tl.operations),
                })

    return {
        "operations": operations,
        "source_tasks": source_tasks,
        "adjacent_items": adjacent_items,
        "items_in_plan": len(plan.items) if plan else 0,
        "resource_type": item_resource,
        "shutdown_items_in_plan": len(shutdown_items),
        "online_items_in_plan": len(online_items),
        # Spatial
        "floc_hierarchy": floc_hierarchy,
        "equipment_count_in_item": len(floc_ids_in_item),
        "total_equipment_in_l3": total_equipment_in_l3,
        "same_area_same_resource_items": same_area_same_resource_items,
        # Coverage
        "all_disciplines_in_floc": list(all_disciplines_in_floc),
        "all_task_types_in_floc": list(all_task_types_in_floc),
        "disciplines_covered_by_other_items": disciplines_covered_by_other_items,
    }


def _review_item(session, item: MaintenancePlanItem, specialist_agents: list,
                 judge_agent, session_id: str) -> dict:
    """Run all specialist agents on one item, call judge if needed. Returns progress dict."""
    context = _build_item_context(session, item)

    # Run all specialist agents (in-thread parallelism via ThreadPoolExecutor)
    decisions = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(agent.review, item, context): agent for agent in specialist_agents}
        for future in as_completed(futures):
            try:
                result = future.result()
                decisions.append(result)
            except Exception as e:
                decisions.append({
                    "score": 5.0,
                    "recommended_action": "keep",
                    "rationale": f"Agent failed: {e}",
                    "confidence": "low",
                    "agent_role": futures[future].profile.role,
                })

    # Determine consensus
    action_counts = Counter(d.get("recommended_action", "keep") for d in decisions)
    top_action, top_count = action_counts.most_common(1)[0]
    has_consensus = top_count >= 4  # ≥4 of 6 agents agree

    judge_result = None
    if not has_consensus and judge_agent:
        judge_result = judge_agent.adjudicate(item, decisions)
        final_action = judge_result.get("final_action", "keep")
    else:
        final_action = top_action

    # Persist decisions to DB
    agent_profile_map = {a.profile.role: a.profile for a in specialist_agents}
    for d in decisions:
        role = d.get("agent_role", "")
        profile = agent_profile_map.get(role)
        is_winning = d.get("recommended_action") == final_action

        ad = AgentDecision(
            session_id=session_id,
            maintenance_plan_item_id=item.id,
            agent_profile_id=profile.id if profile else None,
            score=d.get("score", 5.0),
            recommended_action=d.get("recommended_action", "keep"),
            target_item_id=d.get("target_item_id"),
            rationale=d.get("rationale", ""),
            confidence=d.get("confidence", "low"),
            was_selected=is_winning,
        )
        session.add(ad)

    # Always write a JudgeDecision for non-keep actions so the pending queue
    # can surface them — even when the result came from agent consensus
    # (no judge invoked) rather than arbitration.
    input_scores = {d["agent_role"]: d.get("score", 0) for d in decisions}
    if judge_result:
        winning_role = judge_result.get("winning_agent", "")
        winning_profile = agent_profile_map.get(winning_role)
        if not winning_profile and judge_agent:
            winning_profile = judge_agent.profile if winning_role == "judge" else None
        jd = JudgeDecision(
            session_id=session_id,
            maintenance_plan_item_id=item.id,
            winning_agent_id=winning_profile.id if winning_profile else None,
            final_action=final_action,
            judge_rationale=judge_result.get("judge_rationale", ""),
            input_scores=json.dumps(input_scores),
            modified=False,
        )
        session.add(jd)
    elif final_action != "keep":
        # Consensus non-keep decision — write a JudgeDecision so it appears in the queue
        agreeing = [d for d in decisions if d.get("recommended_action") == final_action]
        rationale = (
            f"Consensus ({top_count}/6 agents agreed: {final_action}). "
            + (agreeing[0].get("rationale", "") if agreeing else "")
        )
        jd = JudgeDecision(
            session_id=session_id,
            maintenance_plan_item_id=item.id,
            winning_agent_id=None,
            final_action=final_action,
            judge_rationale=rationale[:500],
            input_scores=json.dumps(input_scores),
            modified=False,
        )
        session.add(jd)

    session.commit()

    # Build scores dict for progress reporting
    scores = {d["agent_role"]: d.get("score", 0) for d in decisions}

    return {
        "item_id": item.id,
        "item_description": item.description or item.id[:8],
        "final_action": final_action,
        "has_consensus": has_consensus,
        "scores": scores,
        "judge_rationale": judge_result.get("judge_rationale", "") if judge_result else "",
        "winning_agent": judge_result.get("winning_agent", "") if judge_result else top_action,
    }


def _seed_default_agents_if_needed(session):
    """Upsert default agent profiles from seed file (insert missing, update prompts for existing)."""
    import json as _json
    import os
    seed_path = os.path.join(os.path.dirname(__file__), "..", "db", "seed", "default_agents.json")
    seed_path = os.path.normpath(seed_path)
    if not os.path.exists(seed_path):
        return

    with open(seed_path, "r") as f:
        profiles = _json.load(f)

    existing_by_role = {
        r.role: r for r in session.query(AgentProfile).all()
    }

    changed = 0
    for p in profiles:
        existing = existing_by_role.get(p["role"])
        if existing:
            # Update prompt and model if the seed file has changed
            new_prompt = p.get("system_prompt", "")
            new_model = p.get("model_id", "claude-haiku-4-5-20251001")
            new_weights = _json.dumps(p.get("scoring_weights", {}))
            if (existing.system_prompt != new_prompt
                    or existing.model_id != new_model
                    or existing.scoring_weights != new_weights):
                existing.system_prompt = new_prompt
                existing.model_id = new_model
                existing.scoring_weights = new_weights
                changed += 1
        else:
            ap = AgentProfile(
                name=p["name"],
                role=p["role"],
                model_id=p.get("model_id", "claude-haiku-4-5-20251001"),
                is_active=p.get("is_active", True),
                system_prompt=p.get("system_prompt", ""),
                scoring_weights=_json.dumps(p.get("scoring_weights", {})),
            )
            session.add(ap)
            changed += 1

    if changed:
        session.commit()


class _ProfileStub:
    """Lightweight non-ORM copy of AgentProfile safe to pass across threads."""
    __slots__ = ("id", "name", "role", "model_id", "system_prompt", "scoring_weights", "is_active")

    def __init__(self, profile):
        self.id = profile.id
        self.name = profile.name
        self.role = profile.role
        self.model_id = profile.model_id
        self.system_prompt = profile.system_prompt
        self.scoring_weights = profile.scoring_weights
        self.is_active = profile.is_active


def _process_item(item_id, specialist_stubs, judge_stub, packaging_session_id):
    """
    Worker function — runs in its own thread with its own DB session.
    Each item's 4 specialist agents also run in parallel inside here.
    """
    session = get_session()
    try:
        item = session.get(MaintenancePlanItem, item_id)
        if not item:
            return {"item_id": item_id, "item_description": item_id[:8],
                    "final_action": "keep", "has_consensus": True, "scores": {}, "error": "Item not found"}

        specialist_agents = [ROLE_TO_CLASS[s.role](s) for s in specialist_stubs if s.role in ROLE_TO_CLASS]
        judge_agent = JudgeAgent(judge_stub) if judge_stub else None
        return _review_item(session, item, specialist_agents, judge_agent, packaging_session_id)
    except Exception as e:
        return {"item_id": item_id, "item_description": item_id[:8],
                "final_action": "keep", "has_consensus": True, "scores": {}, "error": str(e)}
    finally:
        session.close()


def run_agent_review(
    packaging_session_id: str,
    progress_queue: queue.Queue,
    active_roles=None,
    concurrency: int = 5,
    max_items: int = 0,
) -> dict:
    """
    Run multi-agent review on plan items for a packaging session.

    Items are processed concurrently (`concurrency` at a time).
    Set max_items > 0 to review only a sample.

    Pushes progress dicts to progress_queue:
        {"type": "progress", "done": int, "total": int, "item": {...}}
        {"type": "done", "summary": {...}}
        {"type": "error", "message": str}
    """
    session = get_session()
    try:
        _seed_default_agents_if_needed(session)

        query = session.query(AgentProfile).filter(AgentProfile.is_active == True)
        if active_roles:
            query = query.filter(AgentProfile.role.in_(active_roles + ["judge"]))
        profiles = query.all()

        specialist_profiles = [p for p in profiles if p.role in ROLE_TO_CLASS]
        judge_profiles = [p for p in profiles if p.role == "judge"]

        if not specialist_profiles:
            progress_queue.put({"type": "error", "message": "No active specialist agent profiles found."})
            return {}

        # Serialise ORM profiles to thread-safe stubs
        specialist_stubs = [_ProfileStub(p) for p in specialist_profiles]
        judge_stub = _ProfileStub(judge_profiles[0]) if judge_profiles else None

        items = (
            session.query(MaintenancePlanItem)
            .filter(MaintenancePlanItem.session_id == packaging_session_id)
            .all()
        )

        if not items:
            progress_queue.put({"type": "error", "message": "No plan items found for this session."})
            return {}

        if max_items and max_items < len(items):
            import random
            items = random.sample(items, max_items)

        # Collect just IDs — ORM objects must not cross thread boundaries
        item_ids = [item.id for item in items]

    finally:
        session.close()

    total = len(item_ids)
    done = 0
    action_summary = Counter()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_process_item, iid, specialist_stubs, judge_stub, packaging_session_id): iid
            for iid in item_ids
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as e:
                result = {
                    "item_id": futures[future],
                    "item_description": futures[future][:8],
                    "final_action": "keep",
                    "has_consensus": True,
                    "scores": {},
                    "error": str(e),
                }
            action_summary[result.get("final_action", "keep")] += 1
            done += 1
            progress_queue.put({
                "type": "progress",
                "done": done,
                "total": total,
                "item": result,
            })

    summary = {
        "total": total,
        "keep": action_summary.get("keep", 0),
        "split": action_summary.get("split", 0),
        "merge": action_summary.get("merge", 0),
        "reclassify": action_summary.get("reclassify", 0),
    }
    progress_queue.put({"type": "done", "summary": summary})
    return summary
