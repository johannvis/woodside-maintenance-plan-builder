"""Safety specialist agent."""

from .base_agent import BaseAgent


class SafetyAgent(BaseAgent):
    """Assesses regulatory compliance and safety-critical isolation."""

    def _build_prompt(self, item, context: dict) -> str:
        base = self._format_item_context(item, context)
        source_tasks = context.get("source_tasks", [])
        has_regulatory = any(t.get("is_regulatory") for t in source_tasks)
        has_non_regulatory = any(not t.get("is_regulatory") for t in source_tasks)
        has_critical = any(t.get("criticality", "").upper() == "A" for t in source_tasks)

        flags = []
        if has_regulatory and has_non_regulatory:
            flags.append("WARNING: This item mixes regulatory and non-regulatory tasks.")
        if has_critical and not item.is_regulatory:
            flags.append("NOTE: A-class criticality tasks present in a non-regulatory item.")

        flags_text = "\n".join(flags) if flags else "No automatic flags raised."

        return f"""Review this maintenance plan item from a SAFETY AND REGULATORY COMPLIANCE perspective.

{base}

AUTOMATED FLAGS:
{flags_text}

Assess:
1. Are regulatory/statutory tasks properly isolated from routine tasks?
2. Are safety-critical (A-class) failure modes at appropriate frequency?
3. Is the online/shutdown classification correct from a safety standpoint?
4. Are there any task bundling risks (tasks that shouldn't be concurrent)?

Submit your structured review using the submit_review tool."""
