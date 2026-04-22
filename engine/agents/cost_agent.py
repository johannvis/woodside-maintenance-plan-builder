"""Cost optimisation specialist agent."""

from .base_agent import BaseAgent


class CostAgent(BaseAgent):
    """Assesses bundling efficiency and cost of maintenance plan structure."""

    def _build_prompt(self, item, context: dict) -> str:
        base = self._format_item_context(item, context)
        ops = context.get("operations", [])
        adjacent = context.get("adjacent_items", [])

        # Find same-resource, same-interval adjacent items
        same_resource_adj = [
            a for a in adjacent
            if a.get("resource_type") == context.get("resource_type")
            and a.get("frequency") == item.frequency
            and a.get("frequency_unit") == item.frequency_unit
        ]

        merge_hint = ""
        if len(ops) == 1:
            merge_hint = "NOTE: This is a single-operation item — strong candidate for merging."
        elif item.total_duration_hours < 1.0:
            merge_hint = f"NOTE: Very low total duration ({item.total_duration_hours:.2f}h) — overhead may exceed value."

        adj_merge = ""
        if same_resource_adj:
            adj_merge = f"NOTE: {len(same_resource_adj)} adjacent item(s) with same resource type and interval could be merge targets."

        return f"""Review this maintenance plan item from a COST EFFICIENCY perspective.

{base}

{merge_hint}
{adj_merge}

Assess:
1. Is this item efficiently bundled, or is it over-split?
2. Could it be merged with adjacent items with the same resource/interval?
3. Is the overhead of a separate plan item justified by its size/content?
4. What is the cost impact of the current structure vs. an optimised alternative?

Submit your structured review using the submit_review tool."""
