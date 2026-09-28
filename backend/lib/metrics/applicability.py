"""Metric applicability resolution.

Determines whether a metric applies to an entity type. Feeds the completeness
engine: NOT_APPLICABLE metrics are excluded from expected coverage so entities
are never punished for metrics that make no economic sense.
"""

from __future__ import annotations

from lib.core.entity_types import EntityType
from lib.metrics.registry import MetricDefinition, get_registry


def applicability_for(metric_id: str, entity_type: EntityType) -> str:
    """Resolve applicability of one metric for one entity type.

    Returns one of:
      APPLICABLE      — metric belongs to this entity
      NOT_APPLICABLE  — metric is economically meaningless for this entity
    """
    d = get_registry().get(metric_id)
    if d is None:
        return "APPLICABLE"  # unknown metrics pass through (adapters may add)
    return "APPLICABLE" if d.applies_to(entity_type) else "NOT_APPLICABLE"


def filter_applicable(
    metric_ids: list[str],
    entity_type: EntityType,
) -> tuple[list[str], list[str]]:
    """Split metric ids into (applicable, not_applicable) for an entity type."""
    applicable: list[str] = []
    not_applicable: list[str] = []
    for mid in metric_ids:
        if applicability_for(mid, entity_type) == "APPLICABLE":
            applicable.append(mid)
        else:
            not_applicable.append(mid)
    return applicable, not_applicable


def expected_metrics_for(entity_type: EntityType, categories: list[str] | None = None) -> dict[str, MetricDefinition]:
    """All applicable metric definitions for an entity, optionally by category."""
    defs = get_registry().for_entity(entity_type)
    if categories is None:
        return defs
    return {mid: d for mid, d in defs.items() if d.category in categories}
