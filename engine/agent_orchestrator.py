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
)
from engine.agents.safety_agent import SafetyAgent
from engine.agents.cost_agent import CostAgent
from engine.agents.efficiency_agent import EfficiencyAgent
from engine.agents.integrity_agent import IntegrityAgent
from engine.agents.judge_agent import JudgeAgent


ROLE_TO_CLASS = {
    "safety": SafetyAgent,
    "cost": CostAgent,
    "efficiency": EfficiencyAgent,
    "integrity": IntegrityAgent,
}

ROLE_ICONS = {
    "safety": "🔒",
    "cost": "💰",
    "efficiency": "⚡",
    "integrity": "🔩",
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

    return {
        "operations": operations,
        "source_tasks": source_tasks,
        "adjacent_items": adjacent_items,
        "items_in_plan": len(plan.items) if plan else 0,
        "resource_type": source_tasks[0]["resource_type"] if source_tasks else "",
        "shutdown_items_in_plan": len(shutdown_items),
        "online_items_in_plan": len(online_items),
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
    has_consensus = top_count >= 3  # ≥3 of 4 agree

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
            rationale=d.get("rationale", ""),
            confidence=d.get("confidence", "low"),
            was_selected=is_winning,
        )
        session.add(ad)

    if judge_result:
        winning_role = judge_result.get("winning_agent", "")
        winning_profile = agent_profile_map.get(winning_role)
        # Also check judge profile
        if not winning_profile and judge_agent:
            winning_profile = judge_agent.profile if winning_role == "judge" else None

        input_scores = {d["agent_role"]: d.get("score", 0) for d in decisions}
        jd = JudgeDecision(
            session_id=session_id,
            maintenance_plan_item_id=item.id,
            winning_agent_id=winning_profile.id if winning_profile else None,
            final_action=final_action,
            judge_rationale=judge_result.get("judge_rationale", ""),
            input_scores=json.dumps(input_scores),
            modified=judge_result.get("modified", False),
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
    """Seed default agent profiles if none exist."""
    count = session.query(AgentProfile).count()
    if count > 0:
        return

    import json as _json
    import os
    seed_path = os.path.join(os.path.dirname(__file__), "..", "db", "seed", "default_agents.json")
    seed_path = os.path.normpath(seed_path)
    if not os.path.exists(seed_path):
        return

    with open(seed_path, "r") as f:
        profiles = _json.load(f)

    for p in profiles:
        ap = AgentProfile(
            name=p["name"],
            role=p["role"],
            model_id=p.get("model_id", "claude-haiku-4-5-20251001"),
            is_active=p.get("is_active", True),
            system_prompt=p.get("system_prompt", ""),
            scoring_weights=_json.dumps(p.get("scoring_weights", {})),
        )
        session.add(ap)
    session.commit()


def run_agent_review(
    packaging_session_id: str,
    progress_queue: queue.Queue,
    active_roles: list[str] | None = None,
    batch_size: int = 10,
) -> dict:
    """
    Run multi-agent review on all plan items for a packaging session.

    Called from Streamlit via ThreadPoolExecutor (runs in separate thread).
    Pushes progress dicts to progress_queue. Returns summary stats.

    Progress dict shape:
        {"type": "progress", "done": int, "total": int, "item": {...}}
        {"type": "done", "summary": {...}}
        {"type": "error", "message": str}
    """
    session = get_session()
    try:
        # Ensure default agents exist
        _seed_default_agents_if_needed(session)

        # Load active agent profiles
        query = session.query(AgentProfile).filter(AgentProfile.is_active == True)
        if active_roles:
            query = query.filter(AgentProfile.role.in_(active_roles + ["judge"]))
        profiles = query.all()

        specialist_profiles = [p for p in profiles if p.role in ROLE_TO_CLASS]
        judge_profiles = [p for p in profiles if p.role == "judge"]

        if not specialist_profiles:
            progress_queue.put({"type": "error", "message": "No active specialist agent profiles found."})
            return {}

        # Instantiate agents
        specialist_agents = [
            ROLE_TO_CLASS[p.role](p) for p in specialist_profiles if p.role in ROLE_TO_CLASS
        ]
        judge_agent = JudgeAgent(judge_profiles[0]) if judge_profiles else None

        # Load all plan items
        items = (
            session.query(MaintenancePlanItem)
            .filter(MaintenancePlanItem.session_id == packaging_session_id)
            .all()
        )

        if not items:
            progress_queue.put({"type": "error", "message": "No plan items found for this session."})
            return {}

        total = len(items)
        done = 0
        action_summary = Counter()

        for i in range(0, total, batch_size):
            batch = items[i: i + batch_size]
            for item in batch:
                try:
                    result = _review_item(session, item, specialist_agents, judge_agent, packaging_session_id)
                    action_summary[result["final_action"]] += 1
                    done += 1
                    progress_queue.put({
                        "type": "progress",
                        "done": done,
                        "total": total,
                        "item": result,
                    })
                except Exception as e:
                    done += 1
                    progress_queue.put({
                        "type": "progress",
                        "done": done,
                        "total": total,
                        "item": {
                            "item_id": item.id,
                            "item_description": item.description or item.id[:8],
                            "final_action": "keep",
                            "has_consensus": True,
                            "scores": {},
                            "error": str(e),
                        },
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

    except Exception as e:
        progress_queue.put({"type": "error", "message": str(e)})
        return {}
    finally:
        session.close()
