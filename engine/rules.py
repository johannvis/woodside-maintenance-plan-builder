"""Rule evaluator classes — one per rule_type."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleConfig:
    grouping_level: int = 3
    max_duration_hours: float = 8.0
    shutdown_separation: bool = True
    regulatory_isolation: bool = True


def build_config(rules: list) -> RuleConfig:
    """Build a RuleConfig from a list of Rule ORM objects."""
    cfg = RuleConfig()
    for rule in rules:
        rt = rule.rule_type
        val = rule.parameter_value
        if rt == "grouping_level":
            try:
                cfg.grouping_level = int(val)
            except (ValueError, TypeError):
                pass
        elif rt == "max_duration":
            try:
                cfg.max_duration_hours = float(val)
            except (ValueError, TypeError):
                pass
        elif rt == "shutdown_separation":
            cfg.shutdown_separation = val.strip().lower() in ("true", "1", "yes")
        elif rt == "regulatory_isolation":
            cfg.regulatory_isolation = val.strip().lower() in ("true", "1", "yes")
    return cfg


class GroupingLevelEvaluator:
    """Returns the ancestor FLOC id at the configured level for a task."""

    def __init__(self, level: int):
        self.level = level

    def get_group_key(self, floc_chain: list) -> str:
        """floc_chain is ordered root→leaf; return id at self.level (1-based)."""
        target_idx = self.level - 1
        if target_idx < len(floc_chain):
            return floc_chain[target_idx].id
        return floc_chain[-1].id if floc_chain else "unknown"


class MaxDurationEvaluator:
    """Splits a list of tasks into buckets where each bucket ≤ max_hours."""

    def __init__(self, max_hours: float):
        self.max_hours = max_hours

    def split(self, tasks: list) -> list[list]:
        buckets = []
        current_bucket = []
        current_total = 0.0
        for task in tasks:
            d = task.duration_hours or 0.0
            if current_bucket and current_total + d > self.max_hours:
                buckets.append(current_bucket)
                current_bucket = [task]
                current_total = d
            else:
                current_bucket.append(task)
                current_total += d
        if current_bucket:
            buckets.append(current_bucket)
        return buckets


class ShutdownSeparationEvaluator:
    """Splits tasks into online vs offline buckets."""

    def split(self, tasks: list) -> dict[str, list]:
        online = [t for t in tasks if t.is_online]
        offline = [t for t in tasks if not t.is_online]
        result = {}
        if online:
            result["online"] = online
        if offline:
            result["offline"] = offline
        return result


class RegulatoryIsolationEvaluator:
    """Splits tasks into regulatory vs standard buckets."""

    def split(self, tasks: list) -> dict[str, list]:
        regulatory = [t for t in tasks if t.is_regulatory]
        standard = [t for t in tasks if not t.is_regulatory]
        result = {}
        if regulatory:
            result["regulatory"] = regulatory
        if standard:
            result["standard"] = standard
        return result
