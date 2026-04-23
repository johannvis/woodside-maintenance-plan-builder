"""Abstract base class for all specialist review agents."""

import json
import os
from abc import ABC, abstractmethod

import anthropic


REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Submit the structured review decision for a maintenance plan item.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "description": "Score from 0 to 10 (10 = fully optimal from this agent's perspective).",
            },
            "recommended_action": {
                "type": "string",
                "enum": ["keep", "split", "merge", "reclassify"],
                "description": "Recommended structural action for this plan item.",
            },
            "target_item_id": {
                "type": "string",
                "description": (
                    "For merge recommendations ONLY: the exact UUID of the target item to merge into. "
                    "Copy it verbatim from the ID shown in the adjacent items or route items list. "
                    "This field is REQUIRED for merge — without a valid target_item_id the merge "
                    "cannot be executed automatically. Null for keep/split/reclassify."
                ),
            },
            "target_item_description": {
                "type": "string",
                "description": "Human-readable description of the merge target (for display only). Null for non-merge actions.",
            },
            "split_spec": {
                "type": "object",
                "description": (
                    "For split recommendations only: specifies which operation numbers go into each new group. "
                    "Provide two non-overlapping lists. Null for keep/merge/reclassify."
                ),
                "properties": {
                    "group_a": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Operation numbers (e.g. 10, 20) that stay in or form the first new item.",
                    },
                    "group_b": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Operation numbers that move to the second new item.",
                    },
                },
            },
            "rationale": {
                "type": "string",
                "description": "Concise explanation (2–4 sentences) for the score and recommendation.",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Confidence level in this assessment.",
            },
        },
        "required": ["score", "recommended_action", "rationale", "confidence"],
    },
}


class BaseAgent(ABC):
    """Abstract base for all specialist maintenance planning agents."""

    def __init__(self, profile):
        self.profile = profile
        self._client = None

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def review(self, item, context: dict) -> dict:
        """
        Review a MaintenancePlanItem and return a decision dict.

        Returns dict with keys: score, recommended_action, target_item_description,
        rationale, confidence, agent_role.
        """
        prompt = self._build_prompt(item, context)
        client = self._get_client()

        try:
            response = client.messages.create(
                model=self.profile.model_id or "claude-haiku-4-5-20251001",
                max_tokens=800,
                system=self.profile.system_prompt or "",
                messages=[{"role": "user", "content": prompt}],
                tools=[REVIEW_TOOL],
                tool_choice={"type": "any"},
            )

            # Extract tool use block
            for block in response.content:
                if block.type == "tool_use" and block.name == "submit_review":
                    result = block.input
                    result["agent_role"] = self.profile.role
                    return result

            # Fallback if tool use not returned
            return {
                "score": 5.0,
                "recommended_action": "keep",
                "target_item_description": None,
                "rationale": "Unable to parse agent response.",
                "confidence": "low",
                "agent_role": self.profile.role,
            }

        except Exception as e:
            return {
                "score": 5.0,
                "recommended_action": "keep",
                "target_item_description": None,
                "rationale": f"Agent error: {e}",
                "confidence": "low",
                "agent_role": self.profile.role,
            }

    @abstractmethod
    def _build_prompt(self, item, context: dict) -> str:
        """Build the user-turn prompt for this agent's perspective."""
        pass

    def _format_item_context(self, item, context: dict) -> str:
        """Format common item context into a structured text block."""
        ops = context.get("operations", [])
        ops_text = "\n".join(
            f"  - Op {op.get('op_no', '?')}: {op.get('description', '')[:80]} "
            f"[{op.get('resource', '')} | {op.get('duration_hours', 0):.1f}h]"
            for op in ops
        ) or "  (none)"

        adjacent = context.get("adjacent_items", [])
        adj_text = "\n".join(
            f"  - [target_item_id: {a.get('id', '')}] {a.get('description', '')[:60]} "
            f"({a.get('total_duration_hours', 0):.1f}h, "
            f"{a.get('frequency', '')} {a.get('frequency_unit', '')})"
            for a in adjacent[:5]
        ) or "  (none)"

        source_tasks = context.get("source_tasks", [])
        tasks_text = "\n".join(
            f"  - FM: {t.get('failure_mode', '')[:60]} | Criticality: {t.get('criticality', '')} "
            f"| Type: {t.get('task_type', '')} | Online: {t.get('is_online', True)} "
            f"| Regulatory: {t.get('is_regulatory', False)}"
            for t in source_tasks
        ) or "  (none)"

        same_area = context.get("same_area_same_resource_items", [])
        route_text = "\n".join(
            f"  - [target_item_id: {r.get('id', '')}] {r.get('description', '')[:60]} "
            f"({r.get('total_duration_hours', 0):.1f}h, {r.get('op_count', 0)} ops)"
            for r in same_area[:5]
        ) or "  (none — no fragmentation detected)"

        floc = context.get("floc_hierarchy", {})
        floc_path = " → ".join(v for v in [floc.get("l1"), floc.get("l2"), floc.get("l3"), floc.get("l4")] if v)

        return f"""
PLAN ITEM:
  Description: {item.description or ''}
  Frequency: {item.frequency} {item.frequency_unit}
  Online: {item.is_online}
  Regulatory: {item.is_regulatory}
  Total Duration: {item.total_duration_hours:.1f}h
  FLOC path: {floc_path or '(unknown)'}

OPERATIONS ({len(ops)} total):
{ops_text}

SOURCE FMECA TASKS:
{tasks_text}

ADJACENT ITEMS IN SAME PLAN (for merge consideration — copy target_item_id exactly):
{adj_text}

SAME-AREA SAME-RESOURCE ITEMS (other plans, same L3 sub-system, same interval — route fragmentation candidates):
{route_text}

PACKAGING STATS:
  Items in same plan: {context.get('items_in_plan', 0)}
  Total operations in this item: {len(ops)}
  All disciplines in this L3 FLOC: {', '.join(context.get('all_disciplines_in_floc', [])) or '(unknown)'}
  Disciplines covered by other items: {', '.join(context.get('disciplines_covered_by_other_items', [])) or '(none)'}
""".strip()
