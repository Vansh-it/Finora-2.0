"""India red-flag detector runners.

Wires entity-appropriate detector sets. Corporate detectors compute from the
metric engine; bank and NBFC detectors evaluate entity-specific
deterioration. Every detector returns a DetectorResult — missing inputs
produce INSUFFICIENT_DATA, never fabricated signals.
"""

from __future__ import annotations

from typing import Optional

from lib.core.canonical_models import CanonicalCompanyData
from lib.india.forensics import (
    DetectorResult,
    DetectorStatus,
    _clean,
    _detector,
    _insufficient,
    _pending,
    _union_sources,
)
from lib.core.money import format_percent
from lib.core.periods import previous_period
from lib.india.forensics import EvidenceRow
from lib.metrics.engine import MetricEngine, growth_pct


# Corporate detector set (spec §27)
def run_corporate_detectors(e: MetricEngine, data: CanonicalCompanyData,
                            period: str) -> list[DetectorResult]:
    from lib.india.forensics import (
        detect_ccc_deterioration,
        detect_current_ratio_drop,
        detect_debt_acceleration,
        detect_dilution,
        detect_exceptional_dependence,
        detect_fcf_decline,
        detect_inventory_divergence,
        detect_interest_coverage_drop,
        detect_nwc_deterioration,
        detect_pat_fcf_divergence,
        detect_pat_ocf_divergence,
        detect_promoter_holding_reduction,
        detect_promoter_pledge_increase,
        detect_receivables_divergence,
    )
    detectors = [
        detect_receivables_divergence(e, period),
        detect_inventory_divergence(e, period),
        _margin(e, "gross_margin", "Gross margin deterioration", "gross_margin_deterioration", period),
        _margin(e, "ebitda_margin", "EBITDA margin deterioration", "ebitda_margin_deterioration", period),
        _margin(e, "operating_margin", "Operating margin deterioration",
                "operating_margin_deterioration", period),
        detect_fcf_decline(e, period),
        detect_pat_ocf_divergence(e, period),
        detect_pat_fcf_divergence(e, period),
        detect_debt_acceleration(e, period),
        detect_interest_coverage_drop(e, period),
        detect_current_ratio_drop(e, period),
        detect_nwc_deterioration(e, period),
        detect_ccc_deterioration(e, period),
        detect_dilution(e, period),
        detect_promoter_holding_reduction(data, period),
        detect_promoter_pledge_increase(data, period),
        detect_exceptional_dependence(e, period),
        # event-driven contracts (pending source integration)
        _pending("contingent_liability_increase", "Contingent liability increase"),
        _pending("related_party_signal", "Related-party transaction signal"),
        _pending("auditor_change", "Auditor change / resignation"),
        _pending("qualified_audit", "Qualified / adverse audit opinion"),
    ]
    return detectors


def _margin(e: MetricEngine, metric_id: str, title: str, flag_id: str,
            period: str) -> DetectorResult:
    """Re-exported from :mod:`lib.india.forensics`, which owns the logic."""
    from lib.india.forensics import _margin as _impl
    return _impl(e, metric_id, title, flag_id, period)


# ── Bank detectors (spec §32) ─────────────────────────────────────────────

def run_bank_detectors(e: MetricEngine, data: CanonicalCompanyData,
                       period: str) -> list[DetectorResult]:
    prev = previous_period(period)
    detectors: list[DetectorResult] = []

    def _pct_ratio(mid: str, p: str) -> Optional[float]:
        return e.resolve_input(mid, p)[0]

    def _trend_detector(flag_id, title, metric_id, severity, direction, unit="pp"):
        """direction='down' fires when the metric falls; 'up' fires when it rises."""
        if prev is None:
            return _insufficient(flag_id, title, "No previous period available")
        cur = _pct_ratio(metric_id, period)
        prev_v = _pct_ratio(metric_id, prev)
        if cur is None or prev_v is None:
            return _insufficient(flag_id, title,
                                 f"{metric_id} unavailable for both periods")
        change = cur - prev_v
        fired = (direction == "down" and change < 0) or (direction == "up" and change > 0)
        evidence = [
            {"label": f"{prev}", "value": f"{prev_v:.1f}%"},
            {"label": f"{period}", "value": f"{cur:.1f}%"},
        ]
        if fired:
            return DetectorResult(
                flag_id=flag_id, title=title, severity=severity,
                status=DetectorStatus.ACTIVE,
                reason=f"{metric_id.replace('_', ' ').title()} moved "
                       f"{change:+.1f} pp ({prev_v:.1f}% → {cur:.1f}%)",
                rule=f"{metric_id.replace('_', ' ').title()} deteriorated year over year.",
                evidence=[EvidenceRow(e["label"], e["value"]) for e in evidence],
                sources=_union_sources(e, metric_id, period, prev))
        return _clean(flag_id, title, "No deterioration detected")

    detectors.append(_trend_detector("gnpa_deterioration", "GNPA % rising",
                                     "gnpa_pct", "HIGH", "up"))
    detectors.append(_trend_detector("nnpa_deterioration", "NNPA % rising",
                                     "nnpa_pct", "MEDIUM", "up"))
    detectors.append(_trend_detector("provision_coverage_deterioration",
                                     "Provision coverage falling",
                                     "provision_coverage_ratio", "MEDIUM", "down"))
    detectors.append(_trend_detector("nim_compression", "NIM compression",
                                     "nim", "MEDIUM", "down"))
    detectors.append(_trend_detector("credit_cost_increase", "Credit cost rising",
                                     "credit_cost", "MEDIUM", "up"))
    detectors.append(_trend_detector("capital_adequacy_decline", "Capital adequacy declining",
                                     "capital_adequacy_ratio", "HIGH", "down"))
    detectors.append(_trend_detector("roa_deterioration", "ROA deteriorating",
                                     "bank_roa", "MEDIUM", "down"))
    detectors.append(_trend_detector("roe_deterioration", "ROE deteriorating",
                                     "bank_roe", "MEDIUM", "down"))

    # Deposit growth lagging advances growth
    if prev:
        adv_c = e.resolve_input("advances", period)[0]
        adv_p = e.resolve_input("advances", prev)[0]
        dep_c = e.resolve_input("deposits", period)[0]
        dep_p = e.resolve_input("deposits", prev)[0]
        if None in (adv_c, adv_p, dep_c, dep_p):
            detectors.append(_insufficient("deposit_lag", "Deposit growth lagging advances",
                                           "Advances or deposits unavailable for both periods"))
        else:
            adv_g = growth_pct(adv_c, adv_p) or 0.0
            dep_g = growth_pct(dep_c, dep_p) or 0.0
            gap = adv_g - dep_g
            if gap > 5.0:
                detectors.append(DetectorResult(
                    flag_id="deposit_lag", title="Deposit growth lagging advances",
                    severity="MEDIUM", status=DetectorStatus.ACTIVE,
                    reason=f"Advances grew {adv_g:.1f}% vs deposits {dep_g:.1f}% "
                           f"(gap {gap:.1f} pp)",
                    rule="Advances outgrowing deposits pressures funding.",
                    evidence=[EvidenceRow("Advances Growth", f"{adv_g:.1f}%"),
                              EvidenceRow("Deposit Growth", f"{dep_g:.1f}%")],
                    sources=_union_sources(e, "advances", "deposits", period, prev)))
            else:
                detectors.append(_clean("deposit_lag", "Deposit growth lagging advances",
                                           "No material lag"))
    else:
        detectors.append(_insufficient("deposit_lag", "Deposit growth lagging advances",
                                       "No previous period"))

    # Profit vs provisioning divergence
    if prev:
        pat_c = e.resolve_input("bank_pat", period)[0]
        pat_p = e.resolve_input("bank_pat", prev)[0]
        prov_c = e.resolve_input("provisions", period)[0]
        prov_p = e.resolve_input("provisions", prev)[0]
        if None in (pat_c, pat_p, prov_c, prov_p):
            detectors.append(_insufficient("profit_provision_divergence",
                                           "Profit vs provisioning divergence",
                                           "PAT or provisions unavailable"))
        else:
            pat_g = growth_pct(pat_c, pat_p) or 0.0
            prov_g = growth_pct(prov_c, prov_p) or 0.0
            if pat_g > 10.0 and prov_g > pat_g + 5.0:
                detectors.append(DetectorResult(
                    flag_id="profit_provision_divergence",
                    title="Profit rising with faster provisioning growth",
                    severity="MEDIUM", status=DetectorStatus.ACTIVE,
                    reason=f"PAT grew {pat_g:.1f}% while provisions grew {prov_g:.1f}%",
                    rule="Rising profit alongside accelerating provisioning warrants scrutiny.",
                    evidence=[EvidenceRow("PAT Growth", f"{pat_g:.1f}%"),
                              EvidenceRow("Provision Growth", f"{prov_g:.1f}%")],
                    sources=_union_sources(e, "bank_pat", "provisions", period, prev)))
            else:
                detectors.append(_clean("profit_provision_divergence",
                                           "Profit vs provisioning divergence",
                                           "No divergence"))
    else:
        detectors.append(_insufficient("profit_provision_divergence",
                                       "Profit vs provisioning divergence",
                                       "No previous period"))

    return detectors


# ── NBFC detectors (spec §33) ─────────────────────────────────────────────

def run_nbfc_detectors(e: MetricEngine, data: CanonicalCompanyData,
                       period: str) -> list[DetectorResult]:
    prev = previous_period(period)
    detectors: list[DetectorResult] = []

    def _trend_detector(flag_id, title, metric_id, severity, direction):
        if prev is None:
            return _insufficient(flag_id, title, "No previous period available")
        cur = e.resolve_input(metric_id, period)[0]
        prev_v = e.resolve_input(metric_id, prev)[0]
        if cur is None or prev_v is None:
            return _insufficient(flag_id, title,
                                 f"{metric_id} unavailable for both periods")
        change = cur - prev_v
        fired = (direction == "down" and change < 0) or (direction == "up" and change > 0)
        if fired:
            return DetectorResult(
                flag_id=flag_id, title=title, severity=severity,
                status=DetectorStatus.ACTIVE,
                reason=f"{metric_id.replace('_', ' ').title()} moved "
                       f"{change:+.1f} pp ({prev_v:.1f}% → {cur:.1f}%)",
                rule=f"{metric_id.replace('_', ' ').title()} deteriorated year over year.",
                evidence=[EvidenceRow(f"{prev}", f"{prev_v:.1f}%"),
                          EvidenceRow(f"{period}", f"{cur:.1f}%")],
                sources=_union_sources(e, metric_id, period, prev))
        return _detector(flag_id, title, "", DetectorStatus.INSUFFICIENT_DATA,
                         "No deterioration detected")

    detectors.append(_trend_detector("stage3_deterioration", "Asset quality deteriorating (Stage 3 %)",
                                     "stage3_gross_pct", "HIGH", "up"))
    detectors.append(_trend_detector("nbfc_credit_cost_increase", "Credit cost rising",
                                     "nbfc_credit_cost", "MEDIUM", "up"))
    detectors.append(_trend_detector("nbfc_capital_deterioration", "Capital adequacy declining",
                                     "nbfc_capital_adequacy", "HIGH", "down"))
    detectors.append(_trend_detector("nbfc_roa_deterioration", "ROA deteriorating",
                                     "nbfc_roa", "MEDIUM", "down"))
    detectors.append(_trend_detector("nbfc_roe_deterioration", "ROE deteriorating",
                                     "nbfc_roe", "MEDIUM", "down"))

    # Leverage increase
    if prev:
        lev = e.calculate("nbfc_debt_to_equity", period)
        lev_p = e.calculate("nbfc_debt_to_equity", prev)
        if lev.ok and lev_p.ok and lev.value > lev_p.value:
            detectors.append(DetectorResult(
                flag_id="nbfc_leverage_increase", title="Leverage increasing",
                severity="MEDIUM", status=DetectorStatus.ACTIVE,
                reason=f"Debt/Equity rose from {lev_p.value:.2f}× to {lev.value:.2f}×",
                rule="Leverage rising against the same equity base.",
                evidence=[EvidenceRow(f"{prev} Debt/Equity", f"{lev_p.value:.2f}×"),
                          EvidenceRow(f"{period} Debt/Equity", f"{lev.value:.2f}×")],
                sources=_union_sources(e, "nbfc_borrowings", "nbfc_net_worth", period, prev)))
        else:
            detectors.append(_clean("nbfc_leverage_increase", "Leverage increasing",
                                       "No increase detected"))
    else:
        detectors.append(_insufficient("nbfc_leverage_increase", "Leverage increasing",
                                       "No previous period"))

    # AUM growth with worsening asset quality
    if prev:
        aum_c = e.resolve_input("aum", period)[0]
        aum_p = e.resolve_input("aum", prev)[0]
        s3_c = e.resolve_input("stage3_gross_pct", period)[0]
        s3_p = e.resolve_input("stage3_gross_pct", prev)[0]
        if None in (aum_c, aum_p, s3_c, s3_p):
            detectors.append(_insufficient("aum_quality_divergence",
                                           "AUM growth with worsening asset quality",
                                           "AUM or Stage-3 data unavailable"))
        else:
            aum_g = growth_pct(aum_c, aum_p) or 0.0
            if aum_g > 15.0 and s3_c > s3_p:
                detectors.append(DetectorResult(
                    flag_id="aum_quality_divergence",
                    title="AUM growing while asset quality worsens",
                    severity="HIGH", status=DetectorStatus.ACTIVE,
                    reason=f"AUM grew {aum_g:.1f}% while Gross Stage 3 rose "
                           f"({s3_p:.1f}% → {s3_c:.1f}%)",
                    rule="Growth outpacing credit discipline.",
                    evidence=[EvidenceRow("AUM Growth", f"{aum_g:.1f}%"),
                              EvidenceRow(f"{prev} Gross Stage 3", f"{s3_p:.1f}%"),
                              EvidenceRow(f"{period} Gross Stage 3", f"{s3_c:.1f}%")],
                    sources=_union_sources(e, "aum", "stage3_gross", "loan_book", period, prev)))
            else:
                detectors.append(_clean("aum_quality_divergence",
                                           "AUM growth with worsening asset quality",
                                           "No divergence"))
    else:
        detectors.append(_insufficient("aum_quality_divergence",
                                       "AUM growth with worsening asset quality",
                                       "No previous period"))

    # Funding concentration: any single instrument > 35% of borrowings
    borrowings = e.resolve_input("nbfc_borrowings", period)[0]
    if borrowings in (None, 0):
        detectors.append(_insufficient("funding_concentration",
                                       "Funding concentration",
                                       "Borrowings unavailable"))
    else:
        parts = {
            "Bank Borrowings": e.resolve_input("bank_borrowings_nbfc", period)[0],
            "Debt Securities": e.resolve_input("debt_securities", period)[0],
            "Commercial Paper": e.resolve_input("commercial_paper", period)[0],
        }
        biggest_key, biggest_val = None, 0.0
        for k, v in parts.items():
            if v is not None and v > biggest_val:
                biggest_key, biggest_val = k, v
        if biggest_key and biggest_val / borrowings > 0.35:
            detectors.append(DetectorResult(
                flag_id="funding_concentration", title="Funding concentration",
                severity="MEDIUM", status=DetectorStatus.ACTIVE,
                reason=f"{biggest_key} forms {biggest_val / borrowings * 100:.0f}% of borrowings",
                rule="Over-reliance on a single funding channel.",
                evidence=[EvidenceRow(biggest_key, f"{biggest_val / borrowings * 100:.0f}% of borrowings")],
                sources=_union_sources(e, "nbfc_borrowings", period)))
        else:
            detectors.append(_clean("funding_concentration", "Funding concentration",
                                       "No single funding source exceeds 35% of borrowings"))

    # Profit/OCF mismatch only where meaningful — NBFCs rarely disclose OCF
    # separately from financing flows; treat as conditional.
    ocf_m = e.data.metric("operating_cash_flow", period)
    if ocf_m is None or not ocf_m.is_available:
        detectors.append(_detector(
            "nbfc_profit_ocf_mismatch", "Profit vs OCF mismatch", "",
            DetectorStatus.NOT_APPLICABLE,
            "OCF is not separately meaningful for this NBFC's disclosures"))
    else:
        prev_o = e.data.metric("operating_cash_flow", prev) if prev else None
        pat_c = e.resolve_input("nbfc_pat", period)[0]
        if ocf_m.value < 0 and pat_c is not None and pat_c > 0:
            detectors.append(DetectorResult(
                flag_id="nbfc_profit_ocf_mismatch", title="Profit with negative OCF",
                severity="MEDIUM", status=DetectorStatus.ACTIVE,
                reason="Reported PAT is positive while operating cash flow is negative",
                rule="Profit without operating cash backing.",
                evidence=[EvidenceRow("PAT", "positive"),
                          EvidenceRow("OCF", "negative")],
                sources=list(ocf_m.source_ids)))
        else:
            detectors.append(_clean("nbfc_profit_ocf_mismatch",
                                       "Profit vs OCF mismatch",
                                       "No mismatch detected"))

    return detectors
