"""Forensic engine tests — deterministic detector scenarios (spec §52).

Each detector is exercised with fixtures engineered to fire (or not fire),
and missing-input scenarios must NOT produce false flags.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.core.canonical_models import (
    CanonicalCompanyData,
    CanonicalCompanyIdentity,
    CanonicalOwnership,
    CanonicalStatement,
    CanonicalMetric,
)
from lib.metrics.engine import MetricEngine
from lib.india import forensics as F
from lib.india.detectors import run_corporate_detectors, run_bank_detectors, run_nbfc_detectors
from lib.india.fixtures import get_fixture
from lib.india.dashboard_builder import build_india_dashboard


def _corp(period: str = "FY2026"):
    data = get_fixture("corporate")
    return data, MetricEngine(data)


def _minimal_corporate(overrides: dict | None = None,
                       ownership_rows: list[CanonicalOwnership] | None = None
                       ) -> tuple[CanonicalCompanyData, MetricEngine]:
    """Build a small synthetic corporate for targeted detector scenarios."""
    data = CanonicalCompanyData(
        identity=CanonicalCompanyIdentity(name="Test Corp", country="IN",
                                          entity_type="CORPORATE"),
        ownership=ownership_rows or [],
        periods=[],
    )
    stmt = CanonicalStatement(statement_type="income_statement")
    bs = CanonicalStatement(statement_type="balance_sheet")
    cf = CanonicalStatement(statement_type="cash_flow")

    def put(stmt_obj, metric_id, period, value):
        stmt_obj.add(CanonicalMetric(metric_id=metric_id, period=period,
                                     value=value, source_ids=["s_test"]))

    defaults = {
        "revenue": {"FY2025": 100.0, "FY2026": 108.0},
        "net_profit": {"FY2025": 10.0, "FY2026": 11.5},
        "operating_cash_flow": {"FY2025": 12.0, "FY2026": 13.0},
        "capex": {"FY2025": 4.0, "FY2026": 4.2},
        "trade_receivables": {"FY2025": 20.0, "FY2026": 21.5},
        "inventory": {"FY2025": 15.0, "FY2026": 16.0},
        "trade_payables": {"FY2025": 12.0, "FY2026": 13.0},
        "total_debt": {"FY2025": 30.0, "FY2026": 31.0},
        "total_equity": {"FY2025": 50.0, "FY2026": 52.0},
        "total_assets": {"FY2025": 100.0, "FY2026": 105.0},
        "shares_outstanding": {"FY2025": 10.0, "FY2026": 10.0},
        "gross_profit": {"FY2025": 30.0, "FY2026": 32.5},
        "ebitda": {"FY2025": 18.0, "FY2026": 19.5},
        "finance_costs": {"FY2025": 2.0, "FY2026": 2.1},
        "cash": {"FY2025": 5.0, "FY2026": 5.5},
        "total_current_assets": {"FY2025": 40.0, "FY2026": 42.0},
        "total_current_liabilities": {"FY2025": 25.0, "FY2026": 26.0},
    }
    merged = {}
    for mid, series in defaults.items():
        merged[mid] = dict(series)
    if overrides:
        for mid, series in overrides.items():
            merged.setdefault(mid, {}).update(series)

    for mid, series in merged.items():
        target = cf if mid in ("operating_cash_flow", "capex") else (
            bs if mid in ("trade_receivables", "inventory", "trade_payables",
                          "total_debt", "total_equity", "total_assets",
                          "shares_outstanding", "cash", "total_current_assets",
                          "total_current_liabilities") else stmt)
        for period, value in series.items():
            if value is not None:
                put(target, mid, period, value)

    data.statements = {"income_statement": stmt, "balance_sheet": bs, "cash_flow": cf}
    from lib.core.canonical_models import CanonicalPeriod
    data.periods = [CanonicalPeriod(label="FY2025", kind="FY", fiscal_year=2025),
                    CanonicalPeriod(label="FY2026", kind="FY", fiscal_year=2026)]
    return data, MetricEngine(data)


# ── Scenario: Receivables +35% vs revenue +8% (spec §52) ─────────────────

class TestReceivablesDivergence:
    def test_fires_when_receivables_outgrow_revenue(self):
        data, e = _minimal_corporate({
            "revenue": {"FY2025": 100.0, "FY2026": 108.0},  # +8%
            "trade_receivables": {"FY2025": 20.0, "FY2026": 27.0},  # +35%
        })
        d = F.detect_receivables_divergence(e, "FY2026")
        assert d.fired
        assert d.status == F.DetectorStatus.ACTIVE
        assert d.severity == "MEDIUM"
        # Evidence drawer content must be present
        labels = [ev.label for ev in d.evidence]
        assert any("Revenue Growth" in l for l in labels)
        assert any("Receivables Growth" in l for l in labels)
        assert d.rule

    def test_silent_when_in_line(self):
        data, e = _minimal_corporate({
            "revenue": {"FY2026": 108.0},
            "trade_receivables": {"FY2026": 21.5},  # +7.5% < revenue +8%
        })
        d = F.detect_receivables_divergence(e, "FY2026")
        assert not d.fired

    def test_missing_input_no_false_flag(self):
        data, e = _minimal_corporate({
            "trade_receivables": {"FY2026": None},
        })
        d = F.detect_receivables_divergence(e, "FY2026")
        assert not d.fired
        assert d.status == F.DetectorStatus.INSUFFICIENT_DATA


# ── Scenario: PAT +15% while OCF −20% (spec §52) ──────────────────────────

class TestPatOcfDivergence:
    def test_fires_on_divergence(self):
        data, e = _minimal_corporate({
            "net_profit": {"FY2025": 10.0, "FY2026": 11.5},  # +15%
            "operating_cash_flow": {"FY2025": 12.0, "FY2026": 9.6},  # −20%
        })
        d = F.detect_pat_ocf_divergence(e, "FY2026")
        assert d.fired
        assert d.severity == "HIGH"

    def test_silent_when_both_grow(self):
        data, e = _minimal_corporate()  # defaults grow together
        d = F.detect_pat_ocf_divergence(e, "FY2026")
        assert not d.fired

    def test_missing_ocf_no_false_flag(self):
        data, e = _minimal_corporate({
            "operating_cash_flow": {"FY2026": None},
        })
        d = F.detect_pat_ocf_divergence(e, "FY2026")
        assert not d.fired
        assert d.status == F.DetectorStatus.INSUFFICIENT_DATA


# ── Scenario: promoter pledge 2% → 15% (spec §52) ─────────────────────────

class TestPromoterPledge:
    def _ownership(self, pledge_prev: float, pledge_cur: float):
        return [
            CanonicalOwnership(period="FY2025", promoter_pct=52.0,
                               promoter_pledge_pct=pledge_prev,
                               source_ids=["s_own"]),
            CanonicalOwnership(period="FY2026", promoter_pct=52.0,
                               promoter_pledge_pct=pledge_cur,
                               source_ids=["s_own"]),
        ]

    def test_fires_on_material_increase(self):
        data, e = _minimal_corporate(
            ownership_rows=self._ownership(2.0, 15.0))
        d = F.detect_promoter_pledge_increase(data, "FY2026")
        assert d.fired
        assert d.severity == "HIGH"
        labels = [ev.label for ev in d.evidence]
        assert any("Change" in l for l in labels)

    def test_silent_on_small_change(self):
        data, e = _minimal_corporate(ownership_rows=self._ownership(2.0, 2.5))
        d = F.detect_promoter_pledge_increase(data, "FY2026")
        assert not d.fired

    def test_missing_pledge_data_no_false_flag(self):
        data, _ = _minimal_corporate(
            ownership_rows=[CanonicalOwnership(period="FY2026", promoter_pct=52.0,
                                               promoter_pledge_pct=None)])
        d = F.detect_promoter_pledge_increase(data, "FY2026")
        assert not d.fired
        assert d.status == F.DetectorStatus.INSUFFICIENT_DATA


# ── Scenario: Debt/EBITDA 2.1× → 4.8× (spec §52) ──────────────────────────

class TestLeverageDeterioration:
    def test_fires_on_material_jump(self):
        data, e = _minimal_corporate({
            "total_debt": {"FY2025": 42.0, "FY2026": 96.0},
            "ebitda": {"FY2025": 20.0, "FY2026": 20.0},
        })
        d = F.detect_debt_acceleration(e, "FY2026")
        assert d.fired
        assert d.severity == "HIGH"

    def test_silent_when_stable(self):
        data, e = _minimal_corporate()
        d = F.detect_debt_acceleration(e, "FY2026")
        assert not d.fired

    def test_missing_debt_no_false_flag(self):
        data, e = _minimal_corporate({
            "total_debt": {"FY2026": None},
        })
        d = F.detect_debt_acceleration(e, "FY2026")
        assert not d.fired


# ── Inventory divergence ──────────────────────────────────────────────────

class TestInventoryDivergence:
    def test_fires_when_inventory_outgrows_revenue(self):
        data, e = _minimal_corporate({
            "revenue": {"FY2025": 100.0, "FY2026": 108.0},
            "inventory": {"FY2025": 15.0, "FY2026": 20.5},  # +37%
        })
        d = F.detect_inventory_divergence(e, "FY2026")
        assert d.fired

    def test_missing_inventory_no_false_flag(self):
        data, e = _minimal_corporate({"inventory": {"FY2026": None}})
        d = F.detect_inventory_divergence(e, "FY2026")
        assert not d.fired


# ── Margin deterioration ──────────────────────────────────────────────────

class TestMarginDeterioration:
    def test_ebitda_margin_deterioration_fires(self):
        data, e = _minimal_corporate({
            "ebitda": {"FY2025": 18.0, "FY2026": 15.0},  # 18% → 13.9%
        })
        d = F._margin(e, "ebitda_margin", "EBITDA margin deterioration",
                      "ebitda_margin_deterioration", "FY2026")
        assert d.fired

    def test_stable_margin_silent(self):
        data, e = _minimal_corporate()
        d = F._margin(e, "ebitda_margin", "EBITDA margin deterioration",
                      "ebitda_margin_deterioration", "FY2026")
        assert not d.fired


# ── FCF decline ───────────────────────────────────────────────────────────

class TestFcfDecline:
    def test_negative_declining_fcf_fires_high(self):
        data, e = _minimal_corporate({
            "operating_cash_flow": {"FY2025": 12.0, "FY2026": 4.0},
            "capex": {"FY2025": 4.0, "FY2026": 4.8},
        })
        d = F.detect_fcf_decline(e, "FY2026")
        assert d.fired
        assert d.severity == "HIGH"

    def test_healthy_fcf_silent(self):
        data, e = _minimal_corporate()
        d = F.detect_fcf_decline(e, "FY2026")
        assert not d.fired


# ── PAT vs free cash flow (accruals quality) ──────────────────────────────

class TestPatFcfDivergence:
    def test_rising_pat_with_falling_fcf_fires(self):
        data, e = _minimal_corporate({
            "net_profit": {"FY2025": 10.0, "FY2026": 12.0},          # +20%
            "operating_cash_flow": {"FY2025": 12.0, "FY2026": 11.5},  # ~-4%
            "capex": {"FY2025": 2.0, "FY2026": 8.0},                  # FCF ~-71%
        })
        d = F.detect_pat_fcf_divergence(e, "FY2026")
        assert d.fired
        assert d.severity == "HIGH"
        assert d.evidence and d.rule
        assert d.sources

    def test_rising_pat_with_rising_fcf_is_clean(self):
        data, e = _minimal_corporate({
            "net_profit": {"FY2025": 10.0, "FY2026": 12.0},
            "operating_cash_flow": {"FY2025": 12.0, "FY2026": 14.0},
            "capex": {"FY2025": 2.0, "FY2026": 2.0},
        })
        d = F.detect_pat_fcf_divergence(e, "FY2026")
        assert d.status == F.DetectorStatus.CLEAN
        assert not d.fired

    def test_ocf_variant_still_shares_the_implementation(self):
        """The OCF and FCF detectors must stay in agreement on the PAT side."""
        overrides = {
            "net_profit": {"FY2025": 10.0, "FY2026": 12.0},
            "operating_cash_flow": {"FY2025": 12.0, "FY2026": 11.0},
            "capex": {"FY2025": 2.0, "FY2026": 2.0},
        }
        data, e = _minimal_corporate(overrides)
        ocf = F.detect_pat_ocf_divergence(e, "FY2026")
        fcf = F.detect_pat_fcf_divergence(e, "FY2026")
        # OCF fell ~8%, under the 10% decline threshold, so both stay clean.
        assert not ocf.fired and not fcf.fired
        # ...and both carry a cash-conversion evidence row.
        assert any("Cash Conversion" in r.label for r in ocf.evidence)
        assert any("Cash Conversion" in r.label for r in fcf.evidence)

    def test_wired_into_corporate_detector_suite(self):
        data = get_fixture("corporate")
        flags = {d.flag_id for d in run_corporate_detectors(
            MetricEngine(data), data, "FY2026")}
        assert "pat_fcf_divergence" in flags


# ── Fixture-driven detector verification ──────────────────────────────────

class TestFixtureDetectors:
    def test_corporate_fixture_fires_expected_flags(self):
        """The corporate fixture encodes receivables divergence + pledge spike
        + FCF deterioration; all three must fire."""
        data = get_fixture("corporate")
        e = MetricEngine(data)
        flags = {d.flag_id: d for d in run_corporate_detectors(e, data, "FY2026")}
        assert flags["receivables_divergence"].fired
        assert flags["promoter_pledge_increase"].fired
        assert flags["fcf_decline"].fired

    def test_corporate_fixture_no_false_positive_flags(self):
        """Dilution and current-ratio detectors must NOT fire on the fixture."""
        data = get_fixture("corporate")
        e = MetricEngine(data)
        flags = {d.flag_id: d for d in run_corporate_detectors(e, data, "FY2026")}
        assert not flags["equity_dilution"].fired
        assert not flags["current_ratio_drop"].fired

    def test_bank_fixture_fires_asset_quality_flags(self):
        data = get_fixture("bank")
        e = MetricEngine(data)
        flags = {d.flag_id: d for d in run_bank_detectors(e, data, "FY2026")}
        assert flags["gnpa_deterioration"].fired
        assert flags["nnpa_deterioration"].fired
        assert flags["capital_adequacy_decline"].fired

    def test_nbfc_fixture_fires_growth_quality_divergence(self):
        data = get_fixture("nbfc")
        e = MetricEngine(data)
        flags = {d.flag_id: d for d in run_nbfc_detectors(e, data, "FY2026")}
        assert flags["aum_quality_divergence"].fired
        assert flags["stage3_deterioration"].fired
        assert flags["funding_concentration"].fired

    def test_pending_detectors_declared(self):
        """Event-driven detectors exist as contracts with pending status."""
        data = get_fixture("corporate")
        e = MetricEngine(data)
        flags = {d.flag_id: d for d in run_corporate_detectors(e, data, "FY2026")}
        for pending_id in ("contingent_liability_increase", "related_party_signal",
                           "auditor_change", "qualified_audit"):
            assert pending_id in flags
            assert flags[pending_id].status == F.DetectorStatus.PENDING_SOURCE_INTEGRATION

    def test_every_detector_has_evidence_drawer_data(self):
        """All ACTIVE flags must carry evidence and rule text (no opaque warnings)."""
        data = get_fixture("corporate")
        e = MetricEngine(data)
        for d in run_corporate_detectors(e, data, "FY2026"):
            if d.fired:
                assert d.evidence, f"{d.flag_id} missing evidence"
                assert d.rule, f"{d.flag_id} missing rule"
                assert d.sources or d.category == "ownership"


# ── Piotroski ─────────────────────────────────────────────────────────────

class TestPiotroski:
    def test_runs_on_corporate_fixture(self):
        data = get_fixture("corporate")
        e = MetricEngine(data)
        result = F._piotroski_india(e, "FY2026")
        assert result["applicable"] is True
        assert result["result"] is not None
        score = result["result"]["score"]
        assert 0 <= score <= 9
        assert len(result["result"]["signals"]) == 9

    def test_insufficient_inputs_returns_not_active(self):
        data = CanonicalCompanyData(
            identity=CanonicalCompanyIdentity(name="X", country="IN",
                                              entity_type="CORPORATE"))
        e = MetricEngine(data)
        result = F._piotroski_india(e, "FY2026")
        assert result["result"] is None
        assert result["status"] == F.DetectorStatus.INSUFFICIENT_DATA.value


# ── Forensic model applicability ──────────────────────────────────────────

class TestModelApplicability:
    def test_bank_not_applicable_to_piotroski(self):
        data = get_fixture("bank")
        models = F.forensic_model_suite(data, "FY2026")
        by_name = {m["model"]: m for m in models}
        assert by_name["piotroski"]["applicable"] is False
        assert by_name["piotroski"]["status"] == F.DetectorStatus.NOT_APPLICABLE.value

    def test_nbfc_not_applicable_to_altman(self):
        data = get_fixture("nbfc")
        models = F.forensic_model_suite(data, "FY2026")
        by_name = {m["model"]: m for m in models}
        assert by_name["altman"]["applicable"] is False

    def test_corporate_altman_beneish_pending_with_applicability(self):
        data = get_fixture("corporate")
        models = F.forensic_model_suite(data, "FY2026")
        by_name = {m["model"]: m for m in models}
        assert by_name["altman"]["applicable"] is True
        assert by_name["altman"]["status"] == F.DetectorStatus.PENDING_SOURCE_INTEGRATION.value
        assert by_name["beneish"]["applicable"] is True


# ── Earnings quality ──────────────────────────────────────────────────────

class TestEarningsQuality:
    def test_transparent_signals_present(self):
        data = get_fixture("corporate")
        e = MetricEngine(data)
        panel = F.earnings_quality_panel(e, "FY2026")
        assert panel["available"]
        sig_ids = {s["id"] for s in panel["signals"]}
        assert "pat_vs_ocf" in sig_ids
        assert "accrual_behavior" in sig_ids
        for s in panel["signals"]:
            assert s["rule"] and s["ok_when"] and s["inputs"]

    def test_no_opaque_score(self):
        """The panel must not contain a single mysterious aggregate score."""
        data = get_fixture("corporate")
        e = MetricEngine(data)
        panel = F.earnings_quality_panel(e, "FY2026")
        assert "score" not in panel
        assert "rating" not in panel

    def test_bank_has_no_corporate_earnings_quality(self):
        """Banks don't get the corporate earnings-quality panel."""
        payload = build_india_dashboard(get_fixture("bank"))
        assert payload["forensics"]["earnings_quality"]["available"] is False


# ── Dashboard forensics integration ──────────────────────────────────────

class TestDashboardForensics:
    def test_payload_contains_active_flags_with_evidence(self):
        payload = build_india_dashboard(get_fixture("corporate"))
        assert payload["forensics"]["active_flags"]
        for flag in payload["forensics"]["active_flags"]:
            assert flag["evidence"]
            assert flag["rule"]

    def test_flag_payload_serializable(self):
        payload = build_india_dashboard(get_fixture("corporate"))
        for flag in payload["forensics"]["red_flags"]:
            assert flag["status"] in ("ACTIVE", "CLEAN", "INSUFFICIENT_DATA",
                                      "NOT_APPLICABLE", "PENDING_SOURCE_INTEGRATION")

    def test_clean_is_distinct_from_insufficient_data(self):
        """A healthy verdict must not be reported as missing data.

        Both used to collapse to INSUFFICIENT_DATA, which told the user we
        lacked data about a company we had in fact examined and cleared.
        """
        data, e = _minimal_corporate()
        clean = F._margin(e, "ebitda_margin", "EBITDA margin deterioration",
                          "ebitda_margin_deterioration", "FY2026")
        assert clean.status == F.DetectorStatus.CLEAN
        assert not clean.fired

        unavailable = F._margin(e, "no_such_margin", "Missing margin",
                                "missing_margin", "FY2026")
        assert unavailable.status == F.DetectorStatus.INSUFFICIENT_DATA

    def test_dashboard_exposes_clean_count(self):
        payload = build_india_dashboard(get_fixture("corporate"))
        flags = payload["forensics"]["red_flags"]
        statuses = {f["status"] for f in flags}
        assert "CLEAN" in statuses
        assert payload["forensics"]["active_flags"]
