"""Data-conflict model for cross-source disagreements.

Prepares canonical support for source disagreements (e.g. PAT FY2026 differs
between the annual report and an exchange filing). No heavy reconciliation
here — the model and UI contract only, so future ingestion can populate it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# Tolerance bands (relative) for automatic classification.
MINOR_VARIANCE_TOLERANCE = 0.005  # 0.5%
MATERIAL_MISMATCH_TOLERANCE = 0.05  # 5%


class ConflictStatus(str, Enum):
    MATCH = "MATCH"
    MINOR_VARIANCE = "MINOR_VARIANCE"
    MATERIAL_MISMATCH = "MATERIAL_MISMATCH"
    NOT_COMPARABLE = "NOT_COMPARABLE"  # period/scope/currency mismatch


@dataclass
class SourceValue:
    """One source's claim about a metric/period."""

    source_id: str
    source_name: str
    value: Optional[float]
    period: str
    statement_scope: str = "CONSOLIDATED"
    currency: str = "INR"
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "value": self.value,
            "period": self.period,
            "statement_scope": self.statement_scope,
            "currency": self.currency,
            "url": self.url,
        }


@dataclass
class MetricConflict:
    """A cross-source comparison for one metric/period/scope."""

    metric_id: str
    period: str
    statement_scope: str
    values: list[SourceValue] = field(default_factory=list)
    status: str = ConflictStatus.NOT_COMPARABLE.value
    difference: Optional[float] = None
    difference_pct: Optional[float] = None
    resolution_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "period": self.period,
            "statement_scope": self.statement_scope,
            "values": [v.to_dict() for v in self.values],
            "status": self.status,
            "difference": self.difference,
            "difference_pct": self.difference_pct,
            "resolution_note": self.resolution_note,
        }


def classify_conflict(values: list[SourceValue]) -> tuple[str, Optional[float], Optional[float]]:
    """Classify disagreement across ≥2 comparable source values.

    Returns (status, absolute_difference, relative_difference_pct).
    NOT_COMPARABLE when scopes/currencies/periods differ — never silently
    compare across incompatible dimensions.
    """
    usable = [v for v in values if v.value is not None]
    if len(usable) < 2:
        return ConflictStatus.NOT_COMPARABLE.value, None, None

    first = usable[0]
    if any(
        v.statement_scope != first.statement_scope
        or v.currency != first.currency
        or v.period != first.period
        for v in usable[1:]
    ):
        return ConflictStatus.NOT_COMPARABLE.value, None, None

    base = usable[0].value
    worst = max(usable[1:], key=lambda v: abs(v.value - base))
    diff = worst.value - base
    denom = abs(base) if base != 0 else abs(worst.value)
    diff_pct = (abs(diff) / denom * 100.0) if denom else None

    if diff_pct is None:
        status = ConflictStatus.NOT_COMPARABLE.value
    elif diff_pct <= MINOR_VARIANCE_TOLERANCE * 100.0:
        status = ConflictStatus.MATCH.value
    elif diff_pct <= MATERIAL_MISMATCH_TOLERANCE * 100.0:
        status = ConflictStatus.MINOR_VARIANCE.value
    else:
        status = ConflictStatus.MATERIAL_MISMATCH.value
    return status, diff, diff_pct


def build_conflict(metric_id: str, values: list[SourceValue]) -> MetricConflict:
    """Build a MetricConflict, classifying automatically where possible."""
    scope = values[0].statement_scope if values else "CONSOLIDATED"
    conflict = MetricConflict(
        metric_id=metric_id,
        period=values[0].period if values else "",
        statement_scope=scope,
        values=list(values),
    )
    status, diff, diff_pct = classify_conflict(values)
    conflict.status = status
    conflict.difference = diff
    conflict.difference_pct = diff_pct
    return conflict
