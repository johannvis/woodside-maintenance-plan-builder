"""Route specialist agent — checks proximity bundling using FLOC hierarchy."""

from .base_agent import BaseAgent


class RouteAgent(BaseAgent):
    """
    Checks whether tasks for equipment in the same physical area (same L3 sub-system)
    are efficiently bundled so a tradesperson can do a single walk-around route
    rather than making multiple trips to the same area.

    Uses the FLOC hierarchy as a spatial proxy:
      L3 sub-system = same physical area / walking distance
      Same resource type + same L3 parent + same interval = route bundling opportunity
    """

    def _build_prompt(self, item, context: dict) -> str:
        base = self._format_item_context(item, context)

        floc_hierarchy = context.get("floc_hierarchy", {})
        l3_name = floc_hierarchy.get("l3", "unknown")
        l2_name = floc_hierarchy.get("l2", "unknown")
        equipment_count = context.get("equipment_count_in_item", 0)
        total_equipment_in_l3 = context.get("total_equipment_in_l3", 0)

        same_area_items = context.get("same_area_same_resource_items", [])
        same_area_text = "\n".join(
            f"  - {a.get('description', '')[:70]} | {a.get('frequency', '')} {a.get('frequency_unit', '')} "
            f"| {a.get('total_duration_hours', 0):.1f}h | {a.get('op_count', 0)} ops"
            for a in same_area_items[:8]
        ) or "  (none — this item appears to be the only one for this area/resource/interval)"

        flags = []
        if same_area_items:
            total_trips = 1 + len(same_area_items)
            total_duration = sum(a.get("total_duration_hours", 0) for a in same_area_items)
            flags.append(
                f"NOTE: {len(same_area_items)} other item(s) send the same resource type to the same "
                f"L3 area ({l3_name}) at the same interval — {total_trips} separate trips vs. 1 bundled route. "
                f"Combined duration would be {total_duration + (item.total_duration_hours or 0):.1f}h."
            )
        if equipment_count > 0 and total_equipment_in_l3 > 0:
            coverage_pct = equipment_count / total_equipment_in_l3 * 100
            if coverage_pct < 50:
                flags.append(
                    f"NOTE: This item covers only {equipment_count}/{total_equipment_in_l3} equipment items "
                    f"in {l3_name} ({coverage_pct:.0f}%) — other equipment in the same area may have "
                    f"separate items that could be routed together."
                )

        flags_text = "\n".join(flags) if flags else "No route fragmentation detected automatically."

        return f"""Review this maintenance plan item from a ROUTE EFFICIENCY AND PROXIMITY BUNDLING perspective.

{base}

PHYSICAL LOCATION CONTEXT (from FLOC hierarchy):
  System (L2): {l2_name}
  Sub-system / Area (L3): {l3_name}
  Equipment items in this plan item: {equipment_count}
  Total equipment in this L3 area: {total_equipment_in_l3}

OTHER ITEMS SENDING SAME RESOURCE TO SAME AREA AT SAME INTERVAL:
{same_area_text}

AUTOMATED FLAGS:
{flags_text}

Assess:
1. Are tasks for equipment in the same physical area (L3 sub-system) efficiently bundled
   so a tradesperson can complete them in a single walk-around route?
2. Are there multiple plan items that would send the same trade to the same area
   at the same frequency — creating unnecessary separate trips?
3. Would merging same-area same-resource items at this interval reduce travel/mobilisation overhead?
4. Does the current structure make sense from a field execution perspective?

Score 10 = optimal route efficiency, all same-area tasks bundled.
Score 0 = severe fragmentation, same trade makes many separate trips to the same area.
Submit your structured review using the submit_review tool."""
