"""Central metric registry.

Every metric is defined ONCE here: display name, category, applicable entity
types, unit, inputs, formula and methodology. This prevents metric logic from
being scattered across frontend components or duplicated between builders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from lib.core.entity_types import EntityType


class UnitType(str, Enum):
    MONEY = "MONEY"
    PERCENT = "PERCENT"
    RATIO = "RATIO"  # multiples like 3.2x
    TIMES = "TIMES"  # turnover ratios like 4.5x — same display as RATIO
    PER_SHARE = "PER_SHARE"
    DAYS = "DAYS"
    COUNT = "COUNT"


class Requirement(str, Enum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    CONDITIONAL = "CONDITIONAL"


class SourceType(str, Enum):
    """Vocabulary for :attr:`CanonicalSource.source_type`.

    Kept here, beside ``MetricDefinition.source_priority``, so a metric can
    declare which source types it trusts most without importing the data layer.
    The two enums are kept in step by ``test_source_type_vocabulary_matches``.
    """

    NSE_XBRL = "NSE_XBRL"
    BSE_XBRL = "BSE_XBRL"
    NSE_FILING = "NSE_FILING"
    BSE_FILING = "BSE_FILING"
    ANNUAL_REPORT = "ANNUAL_REPORT"
    COMPANY_IR = "COMPANY_IR"
    MARKET_DATA = "MARKET_DATA"
    MACRO_DATA = "MACRO_DATA"
    FIXTURE = "FIXTURE"


@dataclass(frozen=True)
class MetricDefinition:
    """A single metric definition — the single source of truth."""

    metric_id: str
    display_name: str
    category: str
    entity_types: frozenset  # EntityType members this metric applies to
    unit_type: str = UnitType.MONEY.value
    requirement: str = Requirement.REQUIRED.value
    calculation_method: str = "REPORTED"  # REPORTED | FORMULA | DERIVED
    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    formula: str = ""
    methodology: str = ""
    higher_is_better: Optional[bool] = None  # None = not meaningful
    source_priority: tuple[str, ...] = ()  # preferred source types
    formatting: str = "inr"  # inr | percent | ratio | eps | days | count
    conditional_when: str = ""  # human-readable condition for CONDITIONAL metrics
    aliases: tuple[str, ...] = ()  # alternate metric_ids seen in filings

    def applies_to(self, entity_type: EntityType) -> bool:
        return entity_type in self.entity_types


class MetricRegistry:
    """Registry of all known Finora metrics."""

    def __init__(self) -> None:
        self._metrics: dict[str, MetricDefinition] = {}

    def register(self, definition: MetricDefinition) -> MetricDefinition:
        if definition.metric_id in self._metrics:
            existing = self._metrics[definition.metric_id]
            if existing != definition:
                raise ValueError(f"Conflicting definition for metric {definition.metric_id}")
            return existing
        self._metrics[definition.metric_id] = definition
        return definition

    def get(self, metric_id: str) -> Optional[MetricDefinition]:
        return self._metrics.get(metric_id)

    def require(self, metric_id: str) -> MetricDefinition:
        d = self._metrics.get(metric_id)
        if d is None:
            raise KeyError(f"Unknown metric: {metric_id}")
        return d

    def all_metrics(self) -> dict[str, MetricDefinition]:
        return dict(self._metrics)

    def for_entity(self, entity_type: EntityType) -> dict[str, MetricDefinition]:
        return {
            mid: d for mid, d in self._metrics.items() if d.applies_to(entity_type)
        }

    def by_category(self, category: str, entity_type: Optional[EntityType] = None) -> dict[str, MetricDefinition]:
        return {
            mid: d
            for mid, d in self._metrics.items()
            if d.category == category and (entity_type is None or d.applies_to(entity_type))
        }

    def order_sources(
        self,
        metric_id: str,
        sources: dict[str, str],
    ) -> list[str]:
        """Order source ids by how much this metric trusts each source type.

        ``sources`` maps source_id -> source_type. Sources whose type the
        metric does not rank are kept, and placed after every ranked one, so
        an unrecognised source is demoted rather than dropped — a value with
        only obscure provenance must still reach the reader, labelled.

        This is presentation order for the evidence trail, not value selection.
        Picking *which* conflicting value to believe needs a multi-candidate
        value model that the canonical store does not have yet; until it does,
        declaring and honouring the order is what the registry can honestly
        guarantee.
        """
        definition = self.get(metric_id)
        priority = definition.source_priority if definition else ()
        rank = {source_type: i for i, source_type in enumerate(priority)}

        def key(source_id: str) -> tuple[int, str]:
            source_type = sources.get(source_id, "")
            return (rank.get(source_type, len(priority)), source_id)

        return sorted(sources, key=key)

    def __len__(self) -> int:
        return len(self._metrics)


# ── Global registry instance ──────────────────────────────────────────────
_registry: Optional[MetricRegistry] = None


def get_registry() -> MetricRegistry:
    """Return the global metric registry, populated on first access."""
    global _registry
    if _registry is None:
        _registry = MetricRegistry()
        from lib.metrics.definitions import populate_registry

        populate_registry(_registry)
    return _registry
