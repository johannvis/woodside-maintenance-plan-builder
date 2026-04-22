"""Coverage specialist agent — checks no discipline or task type has been dropped."""

from .base_agent import BaseAgent


class CoverageAgent(BaseAgent):
    """
    Ensures completeness: every discipline (MECH, ELEC, INST, etc.) and task type
    present in the source FMECA for a functional location is represented in the
    packaged plan. Flags gaps where work may have been silently dropped.
    """

    def _build_prompt(self, item, context: dict) -> str:
        base = self._format_item_context(item, context)
        source_tasks = context.get("source_tasks", [])

        # Disciplines present in this item
        item_disciplines = set(t.get("resource_type", "").upper() for t in source_tasks if t.get("resource_type"))
        item_task_types = set(t.get("task_type", "").upper() for t in source_tasks if t.get("task_type"))

        # All disciplines across the full FLOC from context
        all_disciplines = set(d.upper() for d in context.get("all_disciplines_in_floc", []) if d)
        all_task_types = set(tt.upper() for tt in context.get("all_task_types_in_floc", []) if tt)

        missing_disciplines = all_disciplines - item_disciplines
        missing_task_types = all_task_types - item_task_types

        covered_by_other = context.get("disciplines_covered_by_other_items", set())
        truly_missing = missing_disciplines - covered_by_other

        flags = []
        if truly_missing:
            flags.append(
                f"WARNING: The following disciplines appear in the FMECA for this functional location "
                f"but are NOT covered by this or any adjacent plan item: {', '.join(sorted(truly_missing))}"
            )
        if missing_disciplines and not truly_missing:
            flags.append(
                f"NOTE: Disciplines {', '.join(sorted(missing_disciplines))} are not in this item "
                f"but ARE covered by other plan items — coverage is complete."
            )

        other_items_summary = "\n".join(
            f"  - {a.get('description', '')[:60]} | Disciplines: {a.get('disciplines', '')}"
            for a in context.get("adjacent_items", [])[:8]
        ) or "  (none)"

        flags_text = "\n".join(flags) if flags else "No coverage gaps detected automatically."

        return f"""Review this maintenance plan item from a TASK COVERAGE AND COMPLETENESS perspective.

{base}

DISCIPLINE COVERAGE FOR THIS FUNCTIONAL LOCATION:
  All disciplines in FMECA: {', '.join(sorted(all_disciplines)) or 'unknown'}
  Disciplines in this item: {', '.join(sorted(item_disciplines)) or 'none'}
  Disciplines covered by other items: {', '.join(sorted(covered_by_other)) or 'none'}

TASK TYPE COVERAGE:
  All task types in FMECA: {', '.join(sorted(all_task_types)) or 'unknown'}
  Task types in this item: {', '.join(sorted(item_task_types)) or 'none'}

OTHER PLAN ITEMS FOR THIS LOCATION:
{other_items_summary}

AUTOMATED FLAGS:
{flags_text}

Assess:
1. Are all required disciplines (MECH/ELEC/INST/etc.) covered across the full plan?
2. Are there any task types (Inspection/PM/Lubrication/Calibration) that appear missing?
3. Are there failure modes in the FMECA that have no corresponding operations in any plan item?
4. Is the overall coverage complete, or are there gaps that would leave equipment unattended?

Score 10 = complete coverage, nothing missed. Score 0 = significant gaps, equipment/tasks not covered.
Submit your structured review using the submit_review tool."""
