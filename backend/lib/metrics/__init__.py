"""Finora metric engine — registry, applicability, deterministic calculations
and completeness tracking.

Formulas are defined once in the registry and implemented once in the
calculation engine. Entity types control what is applicable: banks never see
inventory turnover; corporates never see GNPA.
"""

from lib.metrics.registry import MetricDefinition, MetricRegistry, get_registry
from lib.metrics.applicability import applicability_for, filter_applicable
from lib.metrics.engine import MetricEngine, CalculationResult
from lib.metrics.completeness import (
    CompletenessEngine,
    CompletenessResult,
    CategoryCoverage,
    MissingMetric,
    CoverageStatus,
)

__all__ = [
    "MetricDefinition",
    "MetricRegistry",
    "get_registry",
    "applicability_for",
    "filter_applicable",
    "MetricEngine",
    "CalculationResult",
    "CompletenessEngine",
    "CompletenessResult",
    "CategoryCoverage",
    "MissingMetric",
    "CoverageStatus",
]
