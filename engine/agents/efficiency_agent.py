"""Scheduling efficiency specialist agent."""

from .base_agent import BaseAgent


class EfficiencyAgent(BaseAgent):
    """Assesses scheduling and operational efficiency of maintenance plan items."""

    def _build_prompt(self, item, context: dict) -> str:
        base = self._format_item_context(item, context)
        ops = context.get("operations", [])
        source_tasks = context.get("source_tasks", [])

        mixed_online = (
            any(t.get("is_online") for t in source_tasks)
            and any(not t.get("is_online") for t in source_tasks)
        )

        shutdown_items_in_plan = context.get("shutdown_items_in_plan", 0)
        online_items_in_plan = context.get("online_items_in_plan", 0)

        flags = []
        if mixed_online:
            flags.append("WARNING: Item appears to mix online and shutdown tasks (check source data).")
        if not item.is_online and shutdown_items_in_plan > 1:
            flags.append(
                f"NOTE: {shutdown_items_in_plan} shutdown items with this interval exist in the plan — "
                "consider consolidation to reduce outage events."
            )
        flags_text = "\n".join(flags) if flags else "No automatic flags raised."

        return f"""Review this maintenance plan item from a SCHEDULING EFFICIENCY perspective.

{base}

Plan context:
  Online items at this interval: {online_items_in_plan}
  Shutdown items at this interval: {shutdown_items_in_plan}

AUTOMATED FLAGS:
{flags_text}

Assess:
1. Are online and shutdown tasks correctly separated?
2. Are shutdown tasks well-consolidated to minimise outage events?
3. Does the interval align with typical plant maintenance windows?
4. Is the operation density reasonable (operations per hour)?

Submit your structured review using the submit_review tool."""
