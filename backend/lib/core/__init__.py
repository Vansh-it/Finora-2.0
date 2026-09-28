"""Finora Core — country-aware contracts shared by US and India research.

This package holds the canonical abstractions introduced by the India
Foundation phase: regions, entity types, canonical data models, periods,
source provenance, INR money formatting and the data-conflict model.

US research continues to run unchanged through the existing SEC pipeline;
these contracts are additive and are populated by region adapters over time.
"""

from lib.core.regions import Region, RegionInfo, REGIONS
from lib.core.entity_types import EntityType, EntityApplicability
from lib.core.canonical_models import (
    CanonicalMetric,
    CanonicalPeriod,
    CanonicalSource,
    CanonicalStatement,
    CanonicalOwnership,
    CanonicalMarketData,
    CanonicalCompanyData,
    CanonicalCompanyIdentity,
    MetricStatus,
    Scope,
    AuditStatus,
)
from lib.core.periods import (
    PeriodKind,
    CumulativeKind,
    canonical_period,
    period_sort_key,
    periods_are_comparable,
    previous_period,
)
from lib.core.money import format_inr, format_ratio, format_percent, format_eps

__all__ = [
    "Region",
    "RegionInfo",
    "REGIONS",
    "EntityType",
    "EntityApplicability",
    "CanonicalMetric",
    "CanonicalPeriod",
    "CanonicalSource",
    "CanonicalStatement",
    "CanonicalOwnership",
    "CanonicalMarketData",
    "CanonicalCompanyData",
    "CanonicalCompanyIdentity",
    "MetricStatus",
    "Scope",
    "AuditStatus",
    "PeriodKind",
    "CumulativeKind",
    "canonical_period",
    "period_sort_key",
    "periods_are_comparable",
    "previous_period",
    "format_inr",
    "format_ratio",
    "format_percent",
    "format_eps",
]
