"""India forensic framework.

Deterministic, applicability-gated forensic analysis for India entities:
  - Piotroski F-Score (corporate, when inputs exist)
  - Altman Z / Beneish M applicability metadata (computation reserved for the
    India Adapter phase when real inputs arrive)
  - Earnings-quality signal panel (transparent, no opaque scores)
  - Red-flag detectors with full evidence drawers

Every detector returns one of:
  ACTIVE               — fired with evidence
  INSUFFICIENT_DATA    — inputs missing; never fabricates a signal
  NOT_APPLICABLE       — model does not apply to this entity type
  PENDING_SOURCE_INTEGRATION — requires event/document data not yet ingested
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from lib.core.canonical_models import CanonicalCompanyData
from lib.core.entity_types import EntityType
from lib.core.money import format_inr, format_percent
from lib.core.periods import previous_period
from lib.metrics.engine import MetricEngine, growth_pct, safe_div


class DetectorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEAN = "CLEAN"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_SOURCE_INTEGRATION = "PENDING_SOURCE_INTEGRATION"


@dataclass
class EvidenceRow:
    label: str
    value: str  # pre-formatted for display

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "value": self.value}


@dataclass
class DetectorResult:
    """One forensic detector outcome with its evidence drawer content."""

    flag_id: str
    title: str
    severity: str  # HIGH | MEDIUM | LOW
    status: DetectorStatus
    reason: str = ""
    rule: str = ""
    evidence: list[EvidenceRow] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    category: str = "financial"

    @property
    def fired(self) -> bool:
        return self.status == DetectorStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag_id": self.flag_id,
            "title": self.title,
            "severity": self.severity if self.fired else "",
            "status": self.status.value,
            "reason": self.reason,
            "rule": self.rule,
            "evidence": [e.to_dict() for e in self.evidence],
            "sources": list(self.sources),
            "category": self.category,
        }


def _pct(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    return growth_pct(cur, prev)


# ══════════════════════════════════════════════════════════════════════════
# RED-FLAG DETECTORS (corporate)
# ══════════════════════════════════════════════════════════════════════════

RECEIVABLES_DIVERGENCE_THRESHOLD = 15.0  # pp above revenue growth
INVENTORY_DIVERGENCE_THRESHOLD = 15.0
MARGIN_DROP_THRESHOLD_PP = 3.0  # margin deterioration in percentage points
FCF_DECLINE_THRESHOLD = -10.0  # % YoY
PAT_OCF_DIVERGENCE = 5.0  # PAT growing ≥5% while OCF declining ≥10%
PAT_FCF_DIVERGENCE = 5.0  # PAT growing ≥5% while FCF declining ≥10%
LEVERAGE_JUMP_THRESHOLD = 1.0  # Debt/EBITDA rise of ≥1.0x
COVERAGE_DROP_THRESHOLD = 1.0  # interest coverage falls ≥1.0x
CURRENT_RATIO_DROP = 0.2
CCC_WORSEN_THRESHOLD = 15.0  # days
DILUTION_THRESHOLD = 1.0  # % share count growth
PLEDGE_INCREASE_THRESHOLD = 3.0  # pp
PROMOTER_REDUCTION_THRESHOLD = 2.0  # pp
EXCEPTIONAL_DEPENDENCE_PCT = 25.0  # exceptional items ≥25% of PBT
CONTINGENT_LIABILITY_GROWTH = 30.0  # % YoY


def _detector(
    flag_id: str, title: str, severity: str,
    status: DetectorStatus, reason: str, rule: str = "",
    evidence: Optional[list[EvidenceRow]] = None,
    sources: Optional[list[str]] = None,
    category: str = "financial",
) -> DetectorResult:
    return DetectorResult(flag_id, title, severity, status, reason, rule,
                          evidence or [], sources or [], category)


def _insufficient(flag_id: str, title: str, reason: str,
                  category: str = "financial") -> DetectorResult:
    return _detector(flag_id, title, "", DetectorStatus.INSUFFICIENT_DATA,
                     reason, category=category)


def _clean(flag_id: str, title: str, reason: str = "No material deterioration detected",
           category: str = "financial",
           evidence: Optional[list[EvidenceRow]] = None,
           sources: Optional[list[str]] = None) -> DetectorResult:
    """The detector ran and found nothing wrong.

    Distinct from :func:`_insufficient`, which means the detector could not
    reach a verdict. Reporting a healthy company as INSUFFICIENT_DATA tells
    the user we lack data when in fact we looked and found it clean.

    A clean verdict still carries the evidence that was measured, so the user
    can see what was checked rather than being told only that nothing was.
    """
    return _detector(flag_id, title, "", DetectorStatus.CLEAN, reason,
                     evidence=evidence, sources=sources, category=category)


def _pending(flag_id: str, title: str,
             category: str = "event") -> DetectorResult:
    return _detector(
        flag_id, title, "", DetectorStatus.PENDING_SOURCE_INTEGRATION,
        "Requires document/event ingestion (India Adapter phase)",
        category=category)


def detect_receivables_divergence(e: MetricEngine, period: str) -> DetectorResult:
    """Receivables growth materially above revenue growth."""
    prev = previous_period(period)
    if prev is None:
        return _insufficient("receivables_divergence", "Receivables growth divergence",
                             "No previous period available")
    rev = e.resolve_input("revenue", period)[0]
    rev_p = e.resolve_input("revenue", prev)[0]
    rec = e.resolve_input("trade_receivables", period)[0]
    rec_p = e.resolve_input("trade_receivables", prev)[0]
    if None in (rev, rev_p, rec, rec_p):
        return _insufficient("receivables_divergence", "Receivables growth divergence",
                             "Revenue or trade receivables unavailable for both periods")
    rev_g, rec_g = _pct(rev, rev_p), _pct(rec, rec_p)
    if rev_g is None or rec_g is None:
        return _insufficient("receivables_divergence", "Receivables growth divergence",
                             "Growth not computable from available values")
    gap = rec_g - rev_g
    sources = _union_sources(e, "revenue", "trade_receivables", period, prev)
    evidence = [
        EvidenceRow(f"{prev} Revenue", format_inr(rev_p)),
        EvidenceRow(f"{period} Revenue", format_inr(rev)),
        EvidenceRow("Revenue Growth", format_percent(rev_g)),
        EvidenceRow(f"{prev} Receivables", format_inr(rec_p)),
        EvidenceRow(f"{period} Receivables", format_inr(rec)),
        EvidenceRow("Receivables Growth", format_percent(rec_g)),
    ]
    if gap > RECEIVABLES_DIVERGENCE_THRESHOLD:
        return _detector(
            "receivables_divergence", "Receivables growing faster than revenue",
            "MEDIUM", DetectorStatus.ACTIVE,
            f"Receivables growth {format_percent(rec_g)} exceeded revenue growth "
            f"{format_percent(rev_g)} by {gap:.1f} pp",
            rule="Receivables growth materially exceeded revenue growth.",
            evidence=evidence, sources=sources)
    return _clean("receivables_divergence", "Receivables growth divergence",
                  "No material divergence detected")


def detect_inventory_divergence(e: MetricEngine, period: str) -> DetectorResult:
    """Inventory growth materially above revenue growth."""
    prev = previous_period(period)
    if prev is None:
        return _insufficient("inventory_divergence", "Inventory growth divergence",
                             "No previous period available")
    rev, rev_p = e.resolve_input("revenue", period)[0], e.resolve_input("revenue", prev)[0]
    inv, inv_p = e.resolve_input("inventory", period)[0], e.resolve_input("inventory", prev)[0]
    if None in (rev, rev_p, inv, inv_p):
        return _insufficient("inventory_divergence", "Inventory growth divergence",
                             "Revenue or inventory unavailable for both periods")
    rev_g, inv_g = _pct(rev, rev_p), _pct(inv, inv_p)
    if rev_g is None or inv_g is None:
        return _insufficient("inventory_divergence", "Inventory growth divergence",
                             "Growth not computable")
    gap = inv_g - rev_g
    sources = _union_sources(e, "revenue", "inventory", period, prev)
    evidence = [
        EvidenceRow(f"{prev} Revenue", format_inr(rev_p)),
        EvidenceRow(f"{period} Revenue", format_inr(rev)),
        EvidenceRow("Revenue Growth", format_percent(rev_g)),
        EvidenceRow(f"{prev} Inventory", format_inr(inv_p)),
        EvidenceRow(f"{period} Inventory", format_inr(inv)),
        EvidenceRow("Inventory Growth", format_percent(inv_g)),
    ]
    if gap > INVENTORY_DIVERGENCE_THRESHOLD:
        return _detector(
            "inventory_divergence", "Inventory growing faster than revenue",
            "MEDIUM", DetectorStatus.ACTIVE,
            f"Inventory growth {format_percent(inv_g)} exceeded revenue growth "
            f"{format_percent(rev_g)} by {gap:.1f} pp",
            rule="Inventory growth materially exceeded revenue growth.",
            evidence=evidence, sources=sources)
    return _clean("inventory_divergence", "Inventory growth divergence")


def _margin(e: MetricEngine, metric_id: str, title: str, flag_id: str,
            period: str) -> DetectorResult:
    """Percent-margin deterioration detector, shared by every margin metric.

    Fires when the margin falls by more than ``MARGIN_DROP_THRESHOLD_PP``
    percentage points year over year. Percent margins have no natural
    denominator, so a zero base is not a special case here.
    """
    prev = previous_period(period)
    if prev is None:
        return _insufficient(flag_id, title, "No previous period available")
    cur_v = e.calculate(metric_id, period)
    prev_v = e.calculate(metric_id, prev)
    if not cur_v.ok or not prev_v.ok:
        return _insufficient(flag_id, title,
                             f"{metric_id} not computable for both periods")
    label = metric_id.replace("_", " ").title()
    drop = prev_v.value - cur_v.value
    evidence = [
        EvidenceRow(f"{prev} {label}", format_percent(prev_v.value)),
        EvidenceRow(f"{period} {label}", format_percent(cur_v.value)),
        EvidenceRow("Change", f"{-drop:+.1f} pp"),
    ]
    if drop > MARGIN_DROP_THRESHOLD_PP:
        return _detector(
            flag_id, title, "MEDIUM", DetectorStatus.ACTIVE,
            f"{label} fell {drop:.1f} pp "
            f"({format_percent(prev_v.value)} → {format_percent(cur_v.value)})",
            rule=f"{label} deteriorated materially year over year.",
            evidence=evidence,
            sources=_union_sources(e, metric_id, period, prev))
    return _clean(flag_id, title)


def detect_fcf_decline(e: MetricEngine, period: str) -> DetectorResult:
    """Negative and/or declining FCF."""
    prev = previous_period(period)
    if prev is None:
        return _insufficient("fcf_decline", "Free cash flow deterioration",
                             "No previous period available")
    fcf = e.resolve_input("free_cash_flow", period)[0]
    fcf_p = e.resolve_input("free_cash_flow", prev)[0]
    if fcf is None or fcf_p is None:
        return _insufficient("fcf_decline", "Free cash flow deterioration",
                             "FCF unavailable for both periods")
    g = growth_pct(fcf, fcf_p)
    evidence = [
        EvidenceRow(f"{prev} FCF", format_inr(fcf_p)),
        EvidenceRow(f"{period} FCF", format_inr(fcf)),
        EvidenceRow("YoY Change", format_percent(g) if g is not None else "N/A"),
    ]
    if fcf < 0 and (g is None or g < FCF_DECLINE_THRESHOLD):
        return _detector(
            "fcf_decline", "Negative and declining free cash flow", "HIGH",
            DetectorStatus.ACTIVE,
            f"FCF is negative ({format_inr(fcf)}) and deteriorating "
            f"({format_percent(g) if g is not None else 'N/A'} YoY)",
            rule="Free cash flow is negative and declining.",
            evidence=evidence, sources=_union_sources(e, "free_cash_flow", period, prev))
    if fcf < 0:
        return _detector(
            "fcf_decline", "Negative free cash flow", "MEDIUM", DetectorStatus.ACTIVE,
            f"FCF is negative ({format_inr(fcf)})",
            rule="Free cash flow is negative.",
            evidence=evidence, sources=_union_sources(e, "free_cash_flow", period, prev))
    if g is not None and g < FCF_DECLINE_THRESHOLD:
        return _detector(
            "fcf_decline", "Free cash flow declining", "MEDIUM", DetectorStatus.ACTIVE,
            f"FCF declined {format_percent(g)} YoY",
            rule="Free cash flow declined materially year over year.",
            evidence=evidence, sources=_union_sources(e, "free_cash_flow", period, prev))
    return _clean("fcf_decline", "Free cash flow deterioration", "No deterioration detected")


def _profit_vs_cash_divergence(
    e: MetricEngine, period: str,
    flag_id: str, title: str, rule: str,
    cash_metric: str, cash_label: str,
    growth_threshold: float, decline_threshold: float,
) -> DetectorResult:
    """Shared accruals red flag: profit up while a cash measure is down.

    Reported profit that rises while cash generation falls is the classic
    accrual-quality warning. OCF is the primary signal; FCF adds the
    capital-intensity view, so both cash measures are checked by the same
    rule rather than duplicating the comparison.
    """
    prev = previous_period(period)
    if prev is None:
        return _insufficient(flag_id, title, "No previous period available")
    pat, pat_p = e.resolve_input("net_profit", period)[0], e.resolve_input("net_profit", prev)[0]
    cash, cash_p = e.resolve_input(cash_metric, period)[0], e.resolve_input(cash_metric, prev)[0]
    if None in (pat, pat_p, cash, cash_p):
        return _insufficient(flag_id, title,
                             f"PAT or {cash_label} unavailable for both periods")
    pat_g, cash_g = growth_pct(pat, pat_p), growth_pct(cash, cash_p)
    evidence = [
        EvidenceRow(f"{prev} PAT", format_inr(pat_p)),
        EvidenceRow(f"{period} PAT", format_inr(pat)),
        EvidenceRow("PAT Growth", format_percent(pat_g) if pat_g is not None else "N/A"),
        EvidenceRow(f"{prev} {cash_label}", format_inr(cash_p)),
        EvidenceRow(f"{period} {cash_label}", format_inr(cash)),
        EvidenceRow(f"{cash_label} Growth",
                    format_percent(cash_g) if cash_g is not None else "N/A"),
        EvidenceRow("Cash Conversion (PAT / cash)",
                    format_percent(safe_div(pat, cash)) if safe_div(pat, cash) is not None
                    else "N/A"),
    ]
    if (pat_g is not None and pat_g >= growth_threshold
            and cash_g is not None and cash_g < decline_threshold):
        return _detector(
            flag_id, title, "HIGH", DetectorStatus.ACTIVE,
            f"PAT grew {format_percent(pat_g)} while {cash_label} fell "
            f"{format_percent(cash_g)}",
            rule=rule,
            evidence=evidence,
            sources=_union_sources(e, "net_profit", cash_metric, period, prev))
    return _clean(flag_id, title, "No divergence detected", evidence=evidence,
                  sources=_union_sources(e, "net_profit", cash_metric, period, prev))


def detect_pat_ocf_divergence(e: MetricEngine, period: str) -> DetectorResult:
    """PAT rising while OCF declines."""
    return _profit_vs_cash_divergence(
        e, period, "pat_ocf_divergence",
        "PAT rising while operating cash flow declines",
        "Reported profit is rising while operating cash generation declines — "
        "possible accrual-driven earnings.",
        "operating_cash_flow", "OCF", PAT_OCF_DIVERGENCE, FCF_DECLINE_THRESHOLD)


def detect_pat_fcf_divergence(e: MetricEngine, period: str) -> DetectorResult:
    """PAT rising while FCF declines.

    Stricter than the OCF variant because FCF is what is left after funding
    the asset base: a profit number that cannot be converted to free cash is
    worth less than the accrual that produced it.
    """
    return _profit_vs_cash_divergence(
        e, period, "pat_fcf_divergence",
        "PAT rising while free cash flow declines",
        "Reported profit is rising while free cash flow declines — earnings "
        "are not being converted into cash after capital expenditure.",
        "free_cash_flow", "FCF", PAT_FCF_DIVERGENCE, FCF_DECLINE_THRESHOLD)


def detect_debt_acceleration(e: MetricEngine, period: str) -> DetectorResult:
    """Debt acceleration / net-debt-to-EBITDA deterioration."""
    prev = previous_period(period)
    if prev is None:
        return _insufficient("debt_acceleration", "Leverage deterioration",
                             "No previous period available")
    cur = e.calculate("net_debt_to_ebitda", period)
    prev_r = e.calculate("net_debt_to_ebitda", prev)
    debt_cur = e.resolve_input("total_debt", period)[0]
    debt_prev = e.resolve_input("total_debt", prev)[0]
    if not cur.ok or not prev_r.ok:
        if debt_cur is None or debt_prev is None:
            return _insufficient("debt_acceleration", "Leverage deterioration",
                                 "Debt or EBITDA unavailable for both periods")
        g = growth_pct(debt_cur, debt_prev)
        if g is not None and g > 30.0:
            return _detector(
                "debt_acceleration", "Debt accelerating", "HIGH",
                DetectorStatus.ACTIVE,
                f"Total debt grew {format_percent(g)} YoY "
                f"({format_inr(debt_prev)} → {format_inr(debt_cur)})",
                rule="Total debt grew materially faster than the business.",
                evidence=[EvidenceRow(f"{prev} Total Debt", format_inr(debt_prev)),
                          EvidenceRow(f"{period} Total Debt", format_inr(debt_cur)),
                          EvidenceRow("Debt Growth", format_percent(g))],
                sources=_union_sources(e, "total_debt", period, prev))
        return _clean("debt_acceleration", "Leverage deterioration", "No deterioration detected")
    rise = cur.value - prev_r.value
    evidence = [
        EvidenceRow(f"{prev} Net Debt / EBITDA", f"{prev_r.value:.1f}×"),
        EvidenceRow(f"{period} Net Debt / EBITDA", f"{cur.value:.1f}×"),
        EvidenceRow("Change", f"{rise:+.1f}×"),
    ]
    if rise >= LEVERAGE_JUMP_THRESHOLD:
        return _detector(
            "debt_acceleration", "Leverage deteriorating", "HIGH",
            DetectorStatus.ACTIVE,
            f"Net Debt / EBITDA rose from {prev_r.value:.1f}× to {cur.value:.1f}×",
            rule="Net Debt / EBITDA deteriorated materially.",
            evidence=evidence, sources=_union_sources(e, "total_debt", "ebitda", period, prev))
    return _clean("debt_acceleration", "Leverage deterioration", "No deterioration detected")


def detect_interest_coverage_drop(e: MetricEngine, period: str) -> DetectorResult:
    prev = previous_period(period)
    if prev is None:
        return _insufficient("interest_coverage_drop", "Interest coverage deterioration",
                             "No previous period available")
    cur = e.calculate("interest_coverage", period)
    prev_r = e.calculate("interest_coverage", prev)
    if not cur.ok or not prev_r.ok:
        return _insufficient("interest_coverage_drop", "Interest coverage deterioration",
                             "Interest coverage not computable for both periods")
    drop = prev_r.value - cur.value
    if drop >= COVERAGE_DROP_THRESHOLD:
        return _detector(
            "interest_coverage_drop", "Interest coverage deteriorating", "MEDIUM",
            DetectorStatus.ACTIVE,
            f"Interest coverage fell from {prev_r.value:.1f}× to {cur.value:.1f}×",
            rule="Interest coverage declined materially.",
            evidence=[EvidenceRow(f"{prev} Coverage", f"{prev_r.value:.1f}×"),
                      EvidenceRow(f"{period} Coverage", f"{cur.value:.1f}×")],
            sources=_union_sources(e, "ebit", "finance_costs", period, prev))
    return _clean("interest_coverage_drop", "Interest coverage deterioration", "No deterioration detected")


def detect_current_ratio_drop(e: MetricEngine, period: str) -> DetectorResult:
    prev = previous_period(period)
    if prev is None:
        return _insufficient("current_ratio_drop", "Current ratio deterioration",
                             "No previous period available")
    cur = e.calculate("current_ratio", period)
    prev_r = e.calculate("current_ratio", prev)
    if not cur.ok or not prev_r.ok:
        return _insufficient("current_ratio_drop", "Current ratio deterioration",
                             "Current ratio not computable for both periods")
    drop = prev_r.value - cur.value
    if drop >= CURRENT_RATIO_DROP:
        return _detector(
            "current_ratio_drop", "Liquidity deteriorating", "MEDIUM",
            DetectorStatus.ACTIVE,
            f"Current ratio fell from {prev_r.value:.2f}× to {cur.value:.2f}×",
            rule="Current ratio declined materially.",
            evidence=[EvidenceRow(f"{prev} Current Ratio", f"{prev_r.value:.2f}×"),
                      EvidenceRow(f"{period} Current Ratio", f"{cur.value:.2f}×")],
            sources=_union_sources(e, "total_current_assets", "total_current_liabilities", period, prev))
    return _clean("current_ratio_drop", "Current ratio deterioration", "No deterioration detected")


def detect_nwc_deterioration(e: MetricEngine, period: str) -> DetectorResult:
    prev = previous_period(period)
    if prev is None:
        return _insufficient("nwc_deterioration", "Working capital deterioration",
                             "No previous period available")
    cur = e.resolve_input("net_working_capital", period)[0]
    prev_v = e.resolve_input("net_working_capital", prev)[0]
    if cur is None or prev_v is None:
        return _insufficient("nwc_deterioration", "Working capital deterioration",
                             "Net working capital unavailable for both periods")
    change = cur - prev_v
    rev = e.resolve_input("revenue", period)[0]
    change_pct_of_rev = (change / rev * 100.0) if rev else None
    if change < 0 and (change_pct_of_rev is None or abs(change_pct_of_rev) > 5.0):
        return _detector(
            "nwc_deterioration", "Working capital deteriorating", "MEDIUM",
            DetectorStatus.ACTIVE,
            f"Net working capital fell {format_inr(abs(change))} YoY",
            rule="Working capital consumed cash materially.",
            evidence=[EvidenceRow(f"{prev} NWC", format_inr(prev_v)),
                      EvidenceRow(f"{period} NWC", format_inr(cur)),
                      EvidenceRow("Change", format_inr(change))],
            sources=_union_sources(e, "total_current_assets", "total_current_liabilities", period, prev))
    return _clean("nwc_deterioration", "Working capital deterioration", "No deterioration detected")


def detect_ccc_deterioration(e: MetricEngine, period: str) -> DetectorResult:
    prev = previous_period(period)
    if prev is None:
        return _insufficient("ccc_deterioration", "Cash conversion cycle deterioration",
                             "No previous period available")
    cur = e.calculate("cash_conversion_cycle", period)
    prev_r = e.calculate("cash_conversion_cycle", prev)
    if not cur.ok or not prev_r.ok:
        return _insufficient("ccc_deterioration", "Cash conversion cycle deterioration",
                             "CCC not computable for both periods")
    rise = cur.value - prev_r.value
    if rise >= CCC_WORSEN_THRESHOLD:
        return _detector(
            "ccc_deterioration", "Cash conversion cycle lengthening", "MEDIUM",
            DetectorStatus.ACTIVE,
            f"CCC lengthened by {rise:.0f} days (from {prev_r.value:.0f} to {cur.value:.0f})",
            rule="Cash conversion cycle deteriorated materially.",
            evidence=[EvidenceRow(f"{prev} CCC", f"{prev_r.value:.0f} days"),
                      EvidenceRow(f"{period} CCC", f"{cur.value:.0f} days")],
            sources=_union_sources(e, "trade_receivables", "inventory", "trade_payables", period, prev))
    return _clean("ccc_deterioration", "Cash conversion cycle deterioration", "No deterioration detected")


def detect_dilution(e: MetricEngine, period: str) -> DetectorResult:
    prev = previous_period(period)
    if prev is None:
        return _insufficient("equity_dilution", "Equity dilution",
                             "No previous period available")
    cur = e.resolve_input("shares_outstanding", period)[0]
    prev_v = e.resolve_input("shares_outstanding", prev)[0]
    if cur is None or prev_v is None or prev_v == 0:
        return _insufficient("equity_dilution", "Equity dilution",
                             "Share count unavailable for both periods")
    g = growth_pct(cur, prev_v)
    if g is not None and g >= DILUTION_THRESHOLD:
        return _detector(
            "equity_dilution", "Equity dilution", "MEDIUM", DetectorStatus.ACTIVE,
            f"Shares outstanding grew {format_percent(g)} YoY",
            rule="Share count expanded materially — per-share metrics diluted.",
            evidence=[EvidenceRow(f"{prev} Shares", f"{prev_v:,.0f}"),
                      EvidenceRow(f"{period} Shares", f"{cur:,.0f}"),
                      EvidenceRow("Growth", format_percent(g))],
            sources=_union_sources(e, "shares_outstanding", period, prev))
    return _clean("equity_dilution", "Equity dilution", "No dilution detected")


def detect_promoter_holding_reduction(data: CanonicalCompanyData, period: str) -> DetectorResult:
    """Promoter holding reduction (ownership data, not metric engine)."""
    cur = next((o for o in data.ownership if o.period == period), None)
    prev_label = previous_period(period)
    prev = next((o for o in data.ownership if o.period == prev_label), None) if prev_label else None
    if cur is None or cur.promoter_pct is None:
        return _insufficient("promoter_reduction", "Promoter holding reduction",
                             "Promoter holding unavailable for this period", category="ownership")
    if prev is None or prev.promoter_pct is None:
        return _insufficient("promoter_reduction", "Promoter holding reduction",
                             "Prior-period promoter holding unavailable", category="ownership")
    drop = prev.promoter_pct - cur.promoter_pct
    if drop >= PROMOTER_REDUCTION_THRESHOLD:
        return _detector(
            "promoter_reduction", "Promoter holding reduced", "HIGH",
            DetectorStatus.ACTIVE,
            f"Promoter holding fell {drop:.1f} pp "
            f"({prev.promoter_pct:.1f}% → {cur.promoter_pct:.1f}%)",
            rule="Promoter holding declined materially.",
            evidence=[EvidenceRow(f"{prev_label} Promoter Holding", format_percent(prev.promoter_pct)),
                      EvidenceRow(f"{period} Promoter Holding", format_percent(cur.promoter_pct)),
                      EvidenceRow("Change", f"{-drop:+.1f} pp")],
            sources=cur.source_ids, category="ownership")
    return _clean("promoter_reduction", "Promoter holding reduction", "No reduction detected", category="ownership")


def detect_promoter_pledge_increase(data: CanonicalCompanyData, period: str) -> DetectorResult:
    cur = next((o for o in data.ownership if o.period == period), None)
    prev_label = previous_period(period)
    prev = next((o for o in data.ownership if o.period == prev_label), None) if prev_label else None
    if cur is None or cur.promoter_pledge_pct is None:
        return _insufficient("promoter_pledge_increase", "Promoter pledge increase",
                             "Pledge data unavailable for this period", category="ownership")
    prev_pct = prev.promoter_pledge_pct if prev and prev.promoter_pledge_pct is not None else None
    if prev_pct is None:
        if cur.promoter_pledge_pct >= PROMOTER_PLEDGE_ABSOLUTE_THRESHOLD:
            return _detector(
                "promoter_pledge_increase", "Promoter pledge present", "MEDIUM",
                DetectorStatus.ACTIVE,
                f"{cur.promoter_pledge_pct:.1f}% of promoter holding is pledged",
                rule="Material promoter pledge against shares.",
                evidence=[EvidenceRow(f"{period} Pledge", format_percent(cur.promoter_pledge_pct))],
                sources=cur.source_ids, category="ownership")
        return _insufficient("promoter_pledge_increase", "Promoter pledge increase",
                             "Prior-period pledge unavailable", category="ownership")
    rise = cur.promoter_pledge_pct - prev_pct
    if rise >= PLEDGE_INCREASE_THRESHOLD:
        return _detector(
            "promoter_pledge_increase", "Promoter pledge increased", "HIGH",
            DetectorStatus.ACTIVE,
            f"Pledged promoter holding rose {rise:.1f} pp "
            f"({prev_pct:.1f}% → {cur.promoter_pledge_pct:.1f}%)",
            rule="Promoter pledge increased materially.",
            evidence=[EvidenceRow(f"{prev_label} Pledge", format_percent(prev_pct)),
                      EvidenceRow(f"{period} Pledge", format_percent(cur.promoter_pledge_pct)),
                      EvidenceRow("Change", f"{rise:+.1f} pp")],
            sources=cur.source_ids, category="ownership")
    return _clean("promoter_pledge_increase", "Promoter pledge increase", "No increase detected", category="ownership")


PROMOTER_PLEDGE_ABSOLUTE_THRESHOLD = 10.0  # absolute pledge level worth flagging


def detect_exceptional_dependence(e: MetricEngine, period: str) -> DetectorResult:
    exc = e.resolve_input("exceptional_items", period)[0]
    pbt = e.resolve_input("pbt", period)[0]
    if exc is None or pbt in (None, 0) or pbt <= 0:
        return _insufficient("exceptional_dependence", "Exceptional-item dependence",
                             "Exceptional items or positive PBT unavailable")
    share = abs(exc) / pbt * 100.0
    if share >= EXCEPTIONAL_DEPENDENCE_PCT:
        return _detector(
            "exceptional_dependence", "Earnings dependent on exceptional items", "MEDIUM",
            DetectorStatus.ACTIVE,
            f"Exceptional items equal {format_percent(share)} of PBT",
            rule="Exceptional items form a material share of pre-tax profit.",
            evidence=[EvidenceRow("Exceptional Items", format_inr(exc)),
                      EvidenceRow("PBT", format_inr(pbt)),
                      EvidenceRow("Share of PBT", format_percent(share))],
            sources=_union_sources(e, "exceptional_items", "pbt", period))
    return _clean("exceptional_dependence", "Exceptional-item dependence",
                  "No material dependence")


def _union_sources(e: MetricEngine, *args) -> list[str]:
    """Union source ids for metric ids / periods passed as alternating args.

    Accepts either (metric..., period, prev) or (metric..., period) patterns:
    every arg that looks like a metric id contributes sources for all periods.

    Provenance is read through the engine rather than the data layer so that
    derived metrics (FCF, margins, ratios) inherit the sources of the recorded
    statement lines they were computed from. Reading the data layer directly
    would silently yield no provenance for every calculated detector.
    """
    period = args[-1]
    metric_ids = [a for a in args[:-1] if a != period]
    out: dict[str, None] = {}
    for mid in metric_ids:
        for p in (period, previous_period(period) or period):
            m = e.data.metric(mid, p)
            if m:
                for s in m.source_ids:
                    out[s] = None
                continue
            try:
                result = e.calculate(mid, p)
            except Exception:  # unknown/inapplicable metric: no provenance
                continue
            if result.ok:
                for s in result.source_ids:
                    out[s] = None
    return list(out)


# ══════════════════════════════════════════════════════════════════════════
# EVENT-DRIVEN DETECTORS — contracts now, ingestion later
# ══════════════════════════════════════════════════════════════════════════

def detect_contingent_liability_increase(e: MetricEngine, period: str) -> DetectorResult:
    return _pending("contingent_liability_increase",
                    "Contingent liability increase")


def detect_related_party_signal(e: MetricEngine, period: str) -> DetectorResult:
    return _pending("related_party_signal", "Related-party transaction signal")


def detect_auditor_change(e: MetricEngine, period: str) -> DetectorResult:
    return _pending("auditor_change", "Auditor change / resignation")


def detect_qualified_audit(e: MetricEngine, period: str) -> DetectorResult:
    return _pending("qualified_audit", "Qualified / adverse audit opinion")


# ══════════════════════════════════════════════════════════════════════════
# FORENSIC MODELS — applicability-gated
# ══════════════════════════════════════════════════════════════════════════

def forensic_model_suite(data: CanonicalCompanyData, period: str) -> list[dict[str, Any]]:
    """Applicability-gated forensic model results for the Forensics tab.

    Piotroski runs for corporates when inputs exist. Altman/Beneish report
    applicability metadata now; full computation lands with the India Adapter.
    Banks/NBFCs receive NOT_APPLICABLE for these models with reasons.
    """
    entity = EntityType(data.identity.entity_type)
    engine = MetricEngine(data)
    results: list[dict[str, Any]] = []

    if entity != EntityType.CORPORATE:
        for model in ("piotroski", "altman", "beneish"):
            results.append({
                "model": model,
                "applicable": False,
                "status": DetectorStatus.NOT_APPLICABLE.value,
                "reason": f"{model.upper()} is designed for industrial corporates; "
                          f"not applicable to {entity.value} entities",
                "inputs": [], "calculation": "", "result": None,
            })
        return results

    # Piotroski — reuse the existing US implementation via adapter inputs when possible.
    results.append(_piotroski_india(engine, period))

    # Altman / Beneish — applicability metadata only in this phase.
    results.append({
        "model": "altman",
        "applicable": True,
        "status": DetectorStatus.PENDING_SOURCE_INTEGRATION.value,
        "reason": "Altman Z requires working-capital and market-equity inputs; "
                  "applicable to this corporate. Computation activates in the India Adapter phase.",
        "inputs": [], "calculation": "", "result": None,
    })
    results.append({
        "model": "beneish",
        "applicable": True,
        "status": DetectorStatus.PENDING_SOURCE_INTEGRATION.value,
        "reason": "Beneish M requires multi-period accrual detail; applicable to this corporate. "
                  "Computation activates in the India Adapter phase.",
        "inputs": [], "calculation": "", "result": None,
    })
    return results


def _piotroski_india(e: MetricEngine, period: str) -> dict[str, Any]:
    """Deterministic Piotroski F-Score on canonical India data.

    9 binary signals over profitability / cash flow / leverage / efficiency.
    Returns NOT_APPLICABLE-style INSUFFICIENT_DATA when core inputs are missing.
    """
    prev = previous_period(period)
    required = ["net_profit", "total_assets", "operating_cash_flow",
                "total_debt", "gross_profit"]
    vals = {mid: e.resolve_input(mid, period)[0] for mid in required}
    if prev is None or any(v is None for v in vals.values()):
        missing = [k for k, v in vals.items() if v is None] + (
            ["previous_period"] if prev is None else [])
        return {
            "model": "piotroski",
            "applicable": True,
            "status": DetectorStatus.INSUFFICIENT_DATA.value,
            "reason": f"Piotroski requires two periods and complete inputs; missing: "
                      f"{', '.join(missing)}",
            "inputs": [], "calculation": "", "result": None,
        }

    prev_vals = {mid: e.resolve_input(mid, prev)[0] for mid in required}
    if any(v is None for v in prev_vals.values()):
        return {
            "model": "piotroski",
            "applicable": True,
            "status": DetectorStatus.INSUFFICIENT_DATA.value,
            "reason": "Previous-period inputs incomplete for Piotroski",
            "inputs": [], "calculation": "", "result": None,
        }

    roa, roa_p = safe_div(vals["net_profit"], vals["total_assets"]), safe_div(prev_vals["net_profit"], prev_vals["total_assets"])
    ocf, ocf_p = vals["operating_cash_flow"], prev_vals["operating_cash_flow"]
    debt, debt_p = vals["total_debt"], prev_vals["total_debt"]
    gp, gp_p = vals["gross_profit"], prev_vals["gross_profit"]
    ta, ta_p = vals["total_assets"], prev_vals["total_assets"]

    lev_now = safe_div(debt, ta) or 0
    lev_prev = safe_div(debt_p, ta_p) or 0
    gm_now = safe_div(gp, e.resolve_input("revenue", period)[0] or 0) or 0
    gm_prev = safe_div(gp_p, e.resolve_input("revenue", prev)[0] or 0) or 0
    at_now = safe_div(e.resolve_input("revenue", period)[0] or 0, ta) or 0
    at_prev = safe_div(e.resolve_input("revenue", prev)[0] or 0, ta_p) or 0

    signals = [
        {"label": "Positive ROA", "value": 1 if roa > 0 else 0},
        {"label": "OCF positive", "value": 1 if ocf > 0 else 0},
        {"label": "ROA improving", "value": 1 if (roa_p is not None and roa > roa_p) else 0},
        {"label": "OCF > Net Income", "value": 1 if ocf > vals["net_profit"] else 0},
        {"label": "Leverage reduced", "value": 1 if lev_now < lev_prev else 0},
        {"label": "Current ratio improving", "value": _binary_current_ratio(e, period, prev)},
        {"label": "Gross margin improving", "value": 1 if gm_now > gm_prev else 0},
        {"label": "Asset turnover improving", "value": 1 if at_now > at_prev else 0},
        {"label": "No dilution", "value": _binary_no_dilution(e, period, prev)},
    ]
    score = sum(s["value"] for s in signals)
    status = ("STRONG" if score >= 8 else "STABLE" if score >= 6
              else "WEAK" if score >= 4 else "DISTRESSED")
    return {
        "model": "piotroski",
        "applicable": True,
        "status": DetectorStatus.ACTIVE.value,
        "reason": f"Piotroski F-Score {score}/9 ({status})",
        "inputs": list(vals.keys()),
        "calculation": "9 binary quality signals per Piotroski (2000)",
        "result": {
            "score": score,
            "max": 9,
            "status": status,
            "signals": signals,
        },
    }


def _binary_current_ratio(e: MetricEngine, period: str, prev: str) -> int:
    cur = e.calculate("current_ratio", period)
    prev_r = e.calculate("current_ratio", prev)
    if cur.ok and prev_r.ok:
        return 1 if cur.value > prev_r.value else 0
    return 0


def _binary_no_dilution(e: MetricEngine, period: str, prev: str) -> int:
    cur = e.resolve_input("shares_outstanding", period)[0]
    prev_v = e.resolve_input("shares_outstanding", prev)[0]
    if cur is None or prev_v is None or prev_v == 0:
        return 0
    return 1 if cur <= prev_v else 0


# ══════════════════════════════════════════════════════════════════════════
# EARNINGS QUALITY — transparent signal panel (no opaque scores)
# ══════════════════════════════════════════════════════════════════════════

def earnings_quality_panel(e: MetricEngine, period: str) -> dict[str, Any]:
    """Transparent earnings-quality signals for corporates.

    Each signal shows its inputs and rule. No aggregate mystery score.
    """
    prev = previous_period(period)
    signals: list[dict[str, Any]] = []

    def _sig(sig_id, label, value, rule, ok_when, inputs):
        return {"id": sig_id, "label": label, "value": value,
                "rule": rule, "ok_when": ok_when, "inputs": inputs}

    pat = e.resolve_input("net_profit", period)[0]
    ocf = e.resolve_input("operating_cash_flow", period)[0]
    fcf = e.resolve_input("free_cash_flow", period)[0]
    rec = e.resolve_input("trade_receivables", period)[0]
    inv = e.resolve_input("inventory", period)[0]
    shares = e.resolve_input("shares_outstanding", period)[0]

    if pat is not None and ocf is not None:
        ratio = safe_div(ocf, pat)
        signals.append(_sig(
            "pat_vs_ocf", "OCF / PAT conversion",
            f"{ratio:.2f}×" if ratio is not None else "—",
            "OCF / PAT — cash backing of reported profit",
            "≥ 0.8×",
            {"ocf": ocf, "pat": pat}))
    if pat is not None and fcf is not None:
        ratio = safe_div(fcf, pat)
        signals.append(_sig(
            "pat_vs_fcf", "FCF / PAT conversion",
            f"{ratio:.2f}×" if ratio is not None else "—",
            "FCF / PAT — post-capex cash backing",
            "≥ 0.5×",
            {"fcf": fcf, "pat": pat}))
    if prev:
        rec_p = e.resolve_input("trade_receivables", prev)[0]
        rev = e.resolve_input("revenue", period)[0]
        rev_p = e.resolve_input("revenue", prev)[0]
        if None not in (rec, rec_p, rev, rev_p):
            rg, cg = growth_pct(rev, rev_p), growth_pct(rec, rec_p)
            signals.append(_sig(
                "receivables_behavior", "Receivables vs revenue growth",
                f"{format_percent(cg) if cg is not None else '—'} vs "
                f"{format_percent(rg) if rg is not None else '—'}",
                "Receivables growing materially faster than revenue pressures quality",
                "Receivables growth ≤ revenue growth + 10 pp",
                {"receivables_growth": cg, "revenue_growth": rg}))
        inv_p = e.resolve_input("inventory", prev)[0]
        if None not in (inv, inv_p, rev, rev_p):
            ig = growth_pct(inv, inv_p)
            signals.append(_sig(
                "inventory_behavior", "Inventory vs revenue growth",
                f"{format_percent(ig) if ig is not None else '—'} vs "
                f"{format_percent(rg) if rg is not None else '—'}",
                "Inventory building faster than demand pressures quality",
                "Inventory growth ≤ revenue growth + 10 pp",
                {"inventory_growth": ig, "revenue_growth": rg}))
        pat_p = e.resolve_input("net_profit", prev)[0]
        ocf_p = e.resolve_input("operating_cash_flow", prev)[0]
        if None not in (pat, pat_p, ocf, ocf_p):
            pg, og = growth_pct(pat, pat_p), growth_pct(ocf, ocf_p)
            signals.append(_sig(
                "accrual_behavior", "PAT growth vs OCF growth",
                f"{format_percent(pg) if pg is not None else '—'} vs "
                f"{format_percent(og) if og is not None else '—'}",
                "Profit outgrowing cash generation signals accrual-heavy earnings",
                "OCF growth within 20 pp of PAT growth",
                {"pat_growth": pg, "ocf_growth": og}))
    # Margin stability
    cur_m = e.calculate("ebitda_margin", period)
    if prev and not cur_m.ok:
        pass
    if prev:
        prev_m = e.calculate("ebitda_margin", prev)
        if cur_m.ok and prev_m.ok:
            swing = abs(cur_m.value - prev_m.value)
            signals.append(_sig(
                "margin_stability", "EBITDA margin stability",
                f"{format_percent(cur_m.value)} (prev {format_percent(prev_m.value)})",
                "Large margin swings complicate earnings-quality assessment",
                "|change| ≤ 3 pp",
                {"ebitda_margin": cur_m.value, "ebitda_margin_prev": prev_m.value}))
    # Leverage trend
    if prev:
        lev = e.calculate("net_debt_to_ebitda", period)
        lev_p = e.calculate("net_debt_to_ebitda", prev)
        if lev.ok and lev_p.ok:
            signals.append(_sig(
                "leverage_trend", "Leverage trend",
                f"{lev.value:.1f}× (prev {lev_p.value:.1f}×)",
                "Rising leverage against stable earnings pressures quality",
                "Net Debt/EBITDA stable or falling",
                {"net_debt_to_ebitda": lev.value, "previous": lev_p.value}))
    # Dilution
    if prev:
        shares_p = e.resolve_input("shares_outstanding", prev)[0]
        if shares is not None and shares_p not in (None, 0):
            g = growth_pct(shares, shares_p)
            signals.append(_sig(
                "dilution", "Share count change",
                format_percent(g) if g is not None else "—",
                "Material dilution transfers value away from existing holders",
                "≤ 2% growth",
                {"shares_outstanding": shares, "previous": shares_p}))

    return {
        "available": bool(signals),
        "period": period,
        "signals": signals,
        "methodology": "Transparent signal panel — each signal shows its inputs and rule. "
                       "Finora deliberately does not compress these into a single opaque score.",
    }
