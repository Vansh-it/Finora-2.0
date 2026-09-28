"""Canonical period model for India reporting.

India requires explicit period handling: FY, QUARTER, HALF_YEAR, NINE_MONTH
and TTM, with cumulative/YTD semantics, audit status and consolidated /
standalone scope. Incompatible periods must never be compared.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class PeriodKind(str, Enum):
    FY = "FY"
    QUARTER = "QUARTER"
    HALF_YEAR = "HALF_YEAR"
    NINE_MONTH = "NINE_MONTH"
    TTM = "TTM"


class CumulativeKind(str, Enum):
    """Whether an observation covers the whole period or is YTD/cumulative."""

    PERIOD = "PERIOD"  # full-period observation
    CUMULATIVE = "CUMULATIVE"  # YTD within the fiscal year
    TTM = "TTM"  # trailing twelve months


_Q_LABELS = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}


def canonical_period(label: str) -> Optional[dict]:
    """Parse a period label into its canonical parts.

    Supported: FY2026, Q1 FY2027 .. Q4 FY2027, H1 FY2027, H2 FY2027,
    9M FY2027, TTM. Returns None for unparseable labels.
    """
    raw = (label or "").strip().upper()
    if not raw:
        return None
    if raw == "TTM":
        return {
            "label": raw,
            "kind": PeriodKind.TTM.value,
            "cumulative": True,
            "fiscal_year": None,
        }
    if raw.startswith("FY") and raw[2:].isdigit():
        return {
            "label": raw,
            "kind": PeriodKind.FY.value,
            "cumulative": False,
            "fiscal_year": int(raw[2:]),
        }
    parts = raw.split()
    if len(parts) == 2 and parts[1].startswith("FY") and parts[1][2:].isdigit():
        year = int(parts[1][2:])
        head = parts[0]
        if head in _Q_LABELS:
            return {
                "label": raw,
                "kind": PeriodKind.QUARTER.value,
                "cumulative": False,
                "fiscal_year": year,
                "quarter": _Q_LABELS[head],
            }
        if head in ("H1", "H2"):
            return {
                "label": raw,
                "kind": PeriodKind.HALF_YEAR.value,
                "cumulative": head == "H1",  # H1 is YTD at half-year; H2 ≈ full year
                "fiscal_year": year,
            }
        if head == "9M":
            return {
                "label": raw,
                "kind": PeriodKind.NINE_MONTH.value,
                "cumulative": True,
                "fiscal_year": year,
            }
    return None


def period_sort_key(label: str) -> tuple:
    """Deterministic ordering key for canonical period labels."""
    p = canonical_period(label)
    if p is None:
        return (99, 0, 0)
    kind_order = {"FY": 0, "QUARTER": 1, "HALF_YEAR": 2, "NINE_MONTH": 3, "TTM": 4}
    quarter = p.get("quarter", 0) or 0
    # Cumulative intra-year periods sort after quarters of the same year.
    cum = 1 if p.get("cumulative") and p["kind"] != PeriodKind.TTM.value else 0
    return (p["fiscal_year"] or 0, kind_order.get(p["kind"], 9) + cum, quarter)


def sort_periods(labels: list[str]) -> list[str]:
    """Return period labels in canonical chronological order."""
    return sorted(labels, key=period_sort_key)


def periods_are_comparable(a: str, b: str) -> bool:
    """True when two period observations may be compared or differenced.

    Rules:
      - same kind
      - both FY, or both TTM
      - same quarter
      - H1 vs H1 (both cumulative at the same point)
      - 9M vs 9M
    FY vs TTM is NOT comparable (TTM spans fiscal-year boundaries).
    """
    pa, pb = canonical_period(a), canonical_period(b)
    if pa is None or pb is None:
        return False
    if pa["kind"] != pb["kind"]:
        return False
    if pa["kind"] in (PeriodKind.FY.value, PeriodKind.TTM.value):
        return True
    if pa["kind"] == PeriodKind.QUARTER.value:
        return pa.get("quarter") == pb.get("quarter")
    if pa["kind"] == PeriodKind.HALF_YEAR.value:
        return a.upper().startswith("H") and a.split()[0] == b.split()[0]
    if pa["kind"] == PeriodKind.NINE_MONTH.value:
        return True
    return False


def previous_period(label: str) -> Optional[str]:
    """The period immediately before `label` of the same kind.

    FY2026 → FY2025, Q3 FY2027 → Q2 FY2027, H1 FY2027 → H1 FY2026,
    9M FY2027 → 9M FY2026. TTM has no canonical predecessor.
    """
    p = canonical_period(label)
    if p is None:
        return None
    if p["kind"] == PeriodKind.FY.value:
        return f"FY{p['fiscal_year'] - 1}"
    if p["kind"] == PeriodKind.TTM.value:
        return None
    head = label.strip().upper().split()[0]
    return f"{head} FY{p['fiscal_year'] - 1}"


def years_between(start_label: str, end_label: str) -> Optional[int]:
    """Whole fiscal years between two comparable FY labels."""
    pa, pb = canonical_period(start_label), canonical_period(end_label)
    if not pa or not pb or pa["kind"] != PeriodKind.FY.value or pb["kind"] != PeriodKind.FY.value:
        return None
    return pb["fiscal_year"] - pa["fiscal_year"]
