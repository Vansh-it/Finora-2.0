"""Completeness engine.

Each dashboard schema defines expected metrics (required / optional /
conditional). The completeness engine classifies every expected metric and
computes coverage without punishing NOT_APPLICABLE or PENDING_SOURCE metrics
in the denominator — coverage answers: "of what should exist for this entity,
how much is actually populated?"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from lib.core.canonical_models import CanonicalCompanyData, MetricStatus
from lib.core.entity_types import EntityType
from lib.metrics.applicability import applicability_for
from lib.metrics.engine import MetricEngine
from lib.metrics.registry import Requirement, get_registry


class CoverageStatus(str, Enum):
    AVAILABLE_REPORTED = "AVAILABLE_REPORTED"
    AVAILABLE_CALCULATED = "AVAILABLE_CALCULATED"
    AVAILABLE_DERIVED = "AVAILABLE_DERIVED"
    AVAILABLE_MARKET_DATA = "AVAILABLE_MARKET_DATA"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_SOURCE = "PENDING_SOURCE"


# Statuses counted as "available" in the coverage numerator.
AVAILABLE_STATUSES = {
    CoverageStatus.AVAILABLE_REPORTED.value,
    CoverageStatus.AVAILABLE_CALCULATED.value,
    CoverageStatus.AVAILABLE_DERIVED.value,
    CoverageStatus.AVAILABLE_MARKET_DATA.value,
}

# Statuses counted in the denominator (what Finora expects to populate).
EXPECTED_STATUSES = AVAILABLE_STATUSES | {
    CoverageStatus.UNAVAILABLE.value,
}


@dataclass
class MissingMetric:
    """A missing metric with its recovery contract for the India Adapter phase."""

    metric_id: str
    display_name: str
    category: str
    reason: str
    priority: str = "MEDIUM"  # HIGH | MEDIUM | LOW
    possible_sources: list[str] = field(default_factory=list)
    derivable: bool = False
    required_inputs: list[str] = field(default_factory=list)
    recovery_strategy: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "display_name": self.display_name,
            "category": self.category,
            "reason": self.reason,
            "priority": self.priority,
            "possible_sources": list(self.possible_sources),
            "derivable": self.derivable,
            "required_inputs": list(self.required_inputs),
            "recovery_strategy": self.recovery_strategy,
        }


@dataclass
class CategoryCoverage:
    """Coverage rollup for one dashboard category."""

    category: str
    display_name: str
    expected: int
    available: int
    missing: list[MissingMetric] = field(default_factory=list)

    @property
    def coverage_pct(self) -> Optional[float]:
        if self.expected == 0:
            return None
        return round(self.available / self.expected * 100.0, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "display_name": self.display_name,
            "expected": self.expected,
            "available": self.available,
            "coverage_pct": self.coverage_pct,
            "missing": [m.to_dict() for m in self.missing],
        }


@dataclass
class CompletenessResult:
    """Full completeness assessment for one dashboard."""

    entity_type: str
    expected: int
    available: int
    coverage_pct: Optional[float]
    reported: int = 0
    calculated: int = 0
    derived: int = 0
    market_data: int = 0
    unavailable: int = 0
    not_applicable: int = 0
    pending_source: int = 0
    categories: list[CategoryCoverage] = field(default_factory=list)
    missing_metrics: list[MissingMetric] = field(default_factory=list)
    metric_details: dict[str, str] = field(default_factory=dict)  # metric_id → status

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "expected": self.expected,
            "available": self.available,
            "coverage_pct": self.coverage_pct,
            "reported": self.reported,
            "calculated": self.calculated,
            "derived": self.derived,
            "market_data": self.market_data,
            "unavailable": self.unavailable,
            "not_applicable": self.not_applicable,
            "pending_source": self.pending_source,
            "categories": [c.to_dict() for c in self.categories],
            "missing_metrics": [m.to_dict() for m in self.missing_metrics],
            "metric_details": dict(self.metric_details),
        }


class CompletenessEngine:
    """Assesses dashboard coverage against entity-applicable expectations."""

    def __init__(self, categories: Optional[dict[str, str]] = None):
        """categories maps category key → display name (from the dashboard schema)."""
        self.categories = categories or {}

    def _classify(
        self,
        metric_id: str,
        data: CanonicalCompanyData,
        entity_type: EntityType,
        period: str,
    ) -> tuple[CoverageStatus, str]:
        """Classify one metric's coverage status with a human reason."""
        d = get_registry().get(metric_id)
        if d is not None and not d.applies_to(entity_type):
            return CoverageStatus.NOT_APPLICABLE, (
                f"Not applicable to {entity_type.value} entities")

        # Ownership and market-data metrics resolve outside statements.
        from lib.metrics.engine import _OWNERSHIP_METRIC_MAP, _MARKET_METRIC_MAP
        if metric_id in _OWNERSHIP_METRIC_MAP:
            for o in data.ownership:
                if o.period == period:
                    value = getattr(o, _OWNERSHIP_METRIC_MAP[metric_id])
                    if value is not None:
                        return CoverageStatus.AVAILABLE_REPORTED, ""
            return CoverageStatus.PENDING_SOURCE, (
                "Shareholding disclosure unavailable for this period")
        if metric_id in _MARKET_METRIC_MAP and data.market_data is not None:
            value = getattr(data.market_data, _MARKET_METRIC_MAP[metric_id])
            if value is not None:
                return CoverageStatus.AVAILABLE_MARKET_DATA, ""

        m = data.metric(metric_id, period)
        if m is not None and m.is_available:
            status_map = {
                MetricStatus.REPORTED.value: CoverageStatus.AVAILABLE_REPORTED,
                MetricStatus.CALCULATED.value: CoverageStatus.AVAILABLE_CALCULATED,
                MetricStatus.DERIVED.value: CoverageStatus.AVAILABLE_DERIVED,
                MetricStatus.MARKET_DATA.value: CoverageStatus.AVAILABLE_MARKET_DATA,
            }
            cov = status_map.get(m.status)
            if cov:
                return cov, ""

        # Not recorded directly: try the deterministic calculation engine so
        # formula metrics (EBITDA, FCF, ratios, aggregates…) count when their
        # inputs exist. Avoid recursion: formulas resolving inputs call back
        # into data, not into assess().
        if d is not None and d.calculation_method in ("FORMULA", "DERIVED"):
            engine = MetricEngine(data)
            result = engine.calculate(metric_id, period)
            if result.ok:
                cov = {
                    MetricStatus.CALCULATED.value: CoverageStatus.AVAILABLE_CALCULATED,
                    MetricStatus.DERIVED.value: CoverageStatus.AVAILABLE_DERIVED,
                    MetricStatus.MARKET_DATA.value: CoverageStatus.AVAILABLE_MARKET_DATA,
                }.get(result.status, CoverageStatus.AVAILABLE_CALCULATED)
                return cov, ""

        # Not populated: conditional metrics that depend on future data
        # sources are PENDING_SOURCE; genuinely-disclosed-but-absent are
        # UNAVAILABLE.
        if d is not None and d.requirement == Requirement.CONDITIONAL.value:
            # If a required input exists in data, the metric is derivable but
            # currently missing → UNAVAILABLE; otherwise it's pending source.
            has_input = any(
                data.metric_value(inp, period) is not None for inp in d.required_inputs
            ) if d.required_inputs else False
            if not has_input and d.conditional_when:
                return CoverageStatus.PENDING_SOURCE, (
                    f"Pending source integration: {d.conditional_when}")
        return CoverageStatus.UNAVAILABLE, "Not disclosed for this period"

    def assess_with_engine(
        self,
        data: CanonicalCompanyData,
        expected_metric_ids: list[str],
        entity_type: EntityType,
        period: str,
    ) -> CompletenessResult:
        """Assess coverage using the calculation engine for derivable metrics.

        This is the canonical entrypoint for India dashboards: formula
        metrics with available inputs count as AVAILABLE (calculated),
        growth/CAGR count when history permits, and the missing list carries
        recovery contracts for the India Adapter phase.
        """
        engine = MetricEngine(data)
        result = CompletenessResult(entity_type=entity_type.value, expected=0,
                                    available=0, coverage_pct=None)
        by_category: dict[str, CategoryCoverage] = {}
        missing: list[MissingMetric] = []

        for metric_id in expected_metric_ids:
            d = get_registry().get(metric_id)
            category = d.category if d else "other"

            status, reason = self._classify(metric_id, data, entity_type, period)

            # For unavailable formula/derived metrics, attempt calculation.
            if status == CoverageStatus.UNAVAILABLE and d is not None and (
                    d.calculation_method in ("FORMULA", "DERIVED")):
                calc = engine.calculate(metric_id, period)
                if calc.ok:
                    status = (CoverageStatus.AVAILABLE_CALCULATED
                              if calc.status == MetricStatus.CALCULATED.value
                              else CoverageStatus.AVAILABLE_DERIVED)
                    reason = ""
                else:
                    reason = calc.reason or reason

            result.metric_details[metric_id] = status.value
            if category not in by_category:
                by_category[category] = CategoryCoverage(
                    category=category,
                    display_name=self.categories.get(category,
                                                     category.replace("_", " ").title()),
                    expected=0, available=0)
            cat = by_category[category]

            if status.value in AVAILABLE_STATUSES:
                cat.available += 1
                result.available += 1
                result.expected += 1
                cat.expected += 1
                if status == CoverageStatus.AVAILABLE_REPORTED:
                    result.reported += 1
                elif status == CoverageStatus.AVAILABLE_CALCULATED:
                    result.calculated += 1
                elif status == CoverageStatus.AVAILABLE_DERIVED:
                    result.derived += 1
                elif status == CoverageStatus.AVAILABLE_MARKET_DATA:
                    result.market_data += 1
            elif status == CoverageStatus.NOT_APPLICABLE:
                result.not_applicable += 1
            elif status == CoverageStatus.PENDING_SOURCE:
                result.pending_source += 1
                result.expected += 1
                cat.expected += 1
                missing.append(self._missing_metric(metric_id, data, entity_type,
                                                    period, reason, priority="LOW"))
            else:
                result.unavailable += 1
                result.expected += 1
                cat.expected += 1
                missing.append(self._missing_metric(metric_id, data, entity_type,
                                                    period, reason, priority="HIGH"))

        for cat in by_category.values():
            cat.missing = [m for m in missing
                           if (get_registry().get(m.metric_id)
                               and get_registry().get(m.metric_id).category == cat.category)
                           or (not get_registry().get(m.metric_id) and cat.category == "other")]

        result.categories = sorted(by_category.values(), key=lambda c: c.category)
        result.missing_metrics = missing
        if result.expected > 0:
            result.coverage_pct = round(result.available / result.expected * 100.0, 1)
        return result

    def assess(
        self,
        data: CanonicalCompanyData,
        expected_metric_ids: list[str],
        entity_type: EntityType,
        period: str,
    ) -> CompletenessResult:
        """Assess coverage of `expected_metric_ids` for `period`."""
        result = CompletenessResult(entity_type=entity_type.value, expected=0, available=0,
                                    coverage_pct=None)

        by_category: dict[str, CategoryCoverage] = {}
        missing: list[MissingMetric] = []

        for metric_id in expected_metric_ids:
            d = get_registry().get(metric_id)
            display_name = d.display_name if d else metric_id
            category = d.category if d else "other"

            status, reason = self._classify(metric_id, data, entity_type, period)
            result.metric_details[metric_id] = status.value

            if category not in by_category:
                by_category[category] = CategoryCoverage(
                    category=category,
                    display_name=self.categories.get(category, category.replace("_", " ").title()),
                    expected=0, available=0,
                )
            cat = by_category[category]

            if status.value in AVAILABLE_STATUSES:
                cat.available += 1
                result.available += 1
                result.expected += 1
                cat.expected += 1
                if status == CoverageStatus.AVAILABLE_REPORTED:
                    result.reported += 1
                elif status == CoverageStatus.AVAILABLE_CALCULATED:
                    result.calculated += 1
                elif status == CoverageStatus.AVAILABLE_DERIVED:
                    result.derived += 1
                elif status == CoverageStatus.AVAILABLE_MARKET_DATA:
                    result.market_data += 1
            elif status == CoverageStatus.NOT_APPLICABLE:
                result.not_applicable += 1
                # NOT_APPLICABLE metrics are excluded from the denominator.
            elif status == CoverageStatus.PENDING_SOURCE:
                result.pending_source += 1
                result.expected += 1
                cat.expected += 1
                missing.append(self._missing_metric(metric_id, data, entity_type, period,
                                                    reason, priority="LOW"))
            else:  # UNAVAILABLE
                result.unavailable += 1
                result.expected += 1
                cat.expected += 1
                missing.append(self._missing_metric(metric_id, data, entity_type, period,
                                                    reason, priority="HIGH"))

            if category in by_category:
                by_category[category].missing = [
                    m for m in by_category[category].missing
                ]

        # Recompute per-category missing lists
        for cat in by_category.values():
            cat.missing = [m for m in missing if get_registry().get(m.metric_id)
                           and get_registry().get(m.metric_id).category == cat.category]

        result.categories = sorted(by_category.values(), key=lambda c: c.category)
        result.missing_metrics = missing
        if result.expected > 0:
            result.coverage_pct = round(result.available / result.expected * 100.0, 1)
        return result

    def _missing_metric(
        self,
        metric_id: str,
        data: CanonicalCompanyData,
        entity_type: EntityType,
        period: str,
        reason: str,
        priority: str,
    ) -> MissingMetric:
        """Build the recovery contract for one missing metric."""
        d = get_registry().get(metric_id)
        inputs_ok = all(
            data.metric_value(inp, period) is not None
            for inp in (d.required_inputs if d else ())
        ) if d and d.required_inputs else False
        derivable = bool(d and d.required_inputs) and inputs_ok
        strategy = (
            f"Derive from {' + '.join(d.required_inputs)} (inputs present)"
            if derivable
            else (f"Retrieve from {', '.join(d.source_priority)}" if d and d.source_priority
                  else "Await India Adapter ingestion")
        )
        return MissingMetric(
            metric_id=metric_id,
            display_name=d.display_name if d else metric_id,
            category=d.category if d else "other",
            reason=reason,
            priority=priority if not derivable else "LOW",
            possible_sources=list(d.source_priority) if d else [],
            derivable=derivable,
            required_inputs=list(d.required_inputs) if d else [],
            recovery_strategy=strategy,
        )
