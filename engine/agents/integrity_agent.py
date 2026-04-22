"""Asset integrity specialist agent."""

from .base_agent import BaseAgent


class IntegrityAgent(BaseAgent):
    """Assesses risk traceability and asset integrity compliance."""

    def _build_prompt(self, item, context: dict) -> str:
        base = self._format_item_context(item, context)
        source_tasks = context.get("source_tasks", [])

        critical_tasks = [t for t in source_tasks if t.get("criticality", "").upper() == "A"]
        non_critical_tasks = [t for t in source_tasks if t.get("criticality", "").upper() != "A"]

        flags = []
        if critical_tasks and non_critical_tasks:
            flags.append(
                f"NOTE: {len(critical_tasks)} A-class and {len(non_critical_tasks)} B/C-class "
                "failure modes are bundled together — integrity focus may be diluted."
            )
        if critical_tasks and item.frequency and item.frequency > 12:
            flags.append(
                f"WARNING: A-class criticality tasks on a {item.frequency}-month interval — "
                "verify this meets the engineering basis."
            )
        flags_text = "\n".join(flags) if flags else "No automatic flags raised."

        critical_fms = "\n".join(
            f"  - {t.get('failure_mode', '')[:80]} (interval: {t.get('interval', '?')} {t.get('interval_unit', '')})"
            for t in critical_tasks
        ) or "  (none)"

        return f"""Review this maintenance plan item from an ASSET INTEGRITY AND RISK MANAGEMENT perspective.

{base}

A-CLASS (HIGH CRITICALITY) FAILURE MODES IN THIS ITEM:
{critical_fms}

AUTOMATED FLAGS:
{flags_text}

Assess:
1. Are A-class failure modes at appropriate frequency and properly isolated?
2. Is the item sufficiently traceable to specific failure modes?
3. Does mixing B/C-class with A-class dilute the integrity focus?
4. Is the maintenance interval consistent with the risk level?

Submit your structured review using the submit_review tool."""
