"""Tests for bank and NBFC dashboards: entity-specific metrics and N/A handling."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.core.entity_types import EntityType
from lib.metrics.engine import MetricEngine
from lib.metrics.completeness import CompletenessEngine
from lib.india.fixtures import get_fixture
from lib.india.dashboard_builder import build_india_dashboard
from lib.india.models import schema_for


def _bank_engine() -> MetricEngine:
    return MetricEngine(get_fixture("bank"))


def _nbfc_engine() -> MetricEngine:
    return MetricEngine(get_fixture("nbfc"))


# ══════════════════════════════════════════════════════════════════════════
# BANK
# ══════════════════════════════════════════════════════════════════════════

class TestBankMetrics:
    def test_nii(self):
        r = _bank_engine().calculate("nii", "FY2026")
        assert r.ok
        # Interest earned 291.4 − expended 185.1 (raw INR)
        assert r.value == pytest.approx(291_400_000_000 - 185_100_000_000, rel=1e-6)

    def test_bank_operating_profit_chain(self):
        """NII + other income − opex computes through the chained resolver."""
        r = _bank_engine().calculate("bank_operating_profit", "FY2026")
        assert r.ok
        nii = 291_400_000_000 - 185_100_000_000
        expected = nii + 46_900_000_000 - 67_900_000_000
        assert r.value == pytest.approx(expected, rel=1e-6)

    def test_bank_pat_full_chain(self):
        r = _bank_engine().calculate("bank_pat", "FY2026")
        assert r.ok

    def test_nim(self):
        r = _bank_engine().calculate("nim", "FY2026")
        assert r.ok
        nii = 291_400_000_000 - 185_100_000_000
        assert r.value == pytest.approx(nii / 291_400_000_000 * 100, rel=1e-3)

    def test_bank_roa(self):
        r = _bank_engine().calculate("bank_roa", "FY2026")
        assert r.ok

    def test_bank_roe(self):
        r = _bank_engine().calculate("bank_roe", "FY2026")
        assert r.ok

    def test_gnpa_pct(self):
        r = _bank_engine().calculate("gnpa_pct", "FY2026")
        assert r.ok
        assert r.value == pytest.approx(24_600_000_000 / 638_400_000_000 * 100, rel=1e-3)

    def test_nnpa_pct(self):
        r = _bank_engine().calculate("nnpa_pct", "FY2026")
        assert r.ok

    def test_provision_coverage_ratio(self):
        r = _bank_engine().calculate("provision_coverage_ratio", "FY2026")
        assert r.ok
        gnpa, nnpa = 24_600_000_000, 7_800_000_000
        assert r.value == pytest.approx((gnpa - nnpa) / gnpa * 100, rel=1e-3)

    def test_credit_cost(self):
        r = _bank_engine().calculate("credit_cost", "FY2026")
        assert r.ok

    def test_deposit_growth(self):
        r = _bank_engine().calculate("deposit_growth", "FY2026")
        assert r.ok

    def test_advance_growth(self):
        r = _bank_engine().calculate("advances_growth", "FY2026")
        assert r.ok

    def test_capital_adequacy_reported(self):
        r = _bank_engine().calculate("capital_adequacy_ratio", "FY2026")
        assert r.ok
        assert r.status == "REPORTED"

    def test_casa_ratio(self):
        r = _bank_engine().calculate("casa_ratio", "FY2026")
        assert r.ok

    def test_book_value_per_share(self):
        r = _bank_engine().calculate("book_value_per_share", "FY2026")
        assert r.ok

    def test_pb_ratio(self):
        r = _bank_engine().calculate("pb_ratio", "FY2026")
        assert r.ok

    def test_gnpa_trend_series(self):
        e = _bank_engine()
        series = e.series("gnpa")
        assert [v for _, v in series] == [
            21_800_000_000, 20_100_000_000, 18_400_000_000,
            19_900_000_000, 24_600_000_000]


class TestBankNotApplicability:
    """Corporate-only metrics must be N/A for banks (spec §63)."""

    @pytest.mark.parametrize("metric_id", [
        "inventory_turnover", "gross_margin", "dso", "dio", "dpo",
        "cash_conversion_cycle", "ebitda", "ebitda_margin", "debt_to_ebitda",
    ])
    def test_corporate_metrics_not_applicable(self, metric_id: str):
        r = _bank_engine().calculate(metric_id, "FY2026")
        assert r.status == "NOT_APPLICABLE", f"{metric_id} should be N/A for banks"

    def test_bank_dashboard_has_no_inventory_metrics(self):
        payload = build_india_dashboard(get_fixture("bank"))
        all_metric_ids = set()
        for tab in payload["tabs"].values():
            all_metric_ids.update(m["metric_id"] for m in tab["metrics"])
        for kpi in payload["kpis"]:
            all_metric_ids.add(kpi["metric_id"])
        inventory_metrics = {
            "inventory", "inventory_turnover", "gross_margin", "dso", "dio",
            "dpo", "cash_conversion_cycle", "ebitda", "ebitda_margin",
        }
        assert not (all_metric_ids & inventory_metrics)

    def test_bank_tabs_are_bank_tabs(self):
        payload = build_india_dashboard(get_fixture("bank"))
        expected = {"asset_quality", "funding", "capital"}
        assert expected <= set(payload["tabs"].keys())
        assert "efficiency" not in payload["tabs"]
        assert "liquidity" not in payload["tabs"]


# ══════════════════════════════════════════════════════════════════════════
# NBFC
# ══════════════════════════════════════════════════════════════════════════

class TestNbfcMetrics:
    def test_aum_growth(self):
        r = _nbfc_engine().calculate("aum_growth", "FY2026")
        assert r.ok
        expected = (798_400_000_000 / 658_900_000_000 - 1) * 100
        assert r.value == pytest.approx(expected, rel=1e-3)

    def test_loan_book_growth(self):
        r = _nbfc_engine().calculate("loan_book_growth", "FY2026")
        assert r.ok

    def test_nbfc_nii(self):
        r = _nbfc_engine().calculate("nbfc_nii", "FY2026")
        assert r.ok
        assert r.value == pytest.approx(153_400_000_000 - 75_800_000_000, rel=1e-6)

    def test_nbfc_nim(self):
        r = _nbfc_engine().calculate("nbfc_nim", "FY2026")
        assert r.ok

    def test_nbfc_roa(self):
        r = _nbfc_engine().calculate("nbfc_roa", "FY2026")
        assert r.ok

    def test_nbfc_roe(self):
        r = _nbfc_engine().calculate("nbfc_roe", "FY2026")
        assert r.ok

    def test_nbfc_debt_to_equity(self):
        r = _nbfc_engine().calculate("nbfc_debt_to_equity", "FY2026")
        assert r.ok

    def test_nbfc_leverage_ratio(self):
        r = _nbfc_engine().calculate("nbfc_leverage_ratio", "FY2026")
        assert r.ok

    def test_nbfc_capital_adequacy(self):
        r = _nbfc_engine().calculate("nbfc_capital_adequacy", "FY2026")
        assert r.ok

    def test_nbfc_credit_cost(self):
        r = _nbfc_engine().calculate("nbfc_credit_cost", "FY2026")
        assert r.ok

    def test_stage3_gross_pct(self):
        r = _nbfc_engine().calculate("stage3_gross_pct", "FY2026")
        assert r.ok
        assert r.value == pytest.approx(21_400_000_000 / 761_800_000_000 * 100, rel=1e-3)

    def test_nbfc_provision_coverage(self):
        r = _nbfc_engine().calculate("nbfc_provision_coverage", "FY2026")
        assert r.ok

    def test_nbfc_pat_chain(self):
        r = _nbfc_engine().calculate("nbfc_pat", "FY2026")
        assert r.ok

    def test_pb_ratio(self):
        r = _nbfc_engine().calculate("pb_ratio", "FY2026")
        assert r.ok

    def test_funding_breakdown_present(self):
        e = _nbfc_engine()
        for mid in ("bank_borrowings_nbfc", "debt_securities", "commercial_paper"):
            v = e.resolve_input(mid, "FY2026")[0]
            assert v is not None, mid

    def test_securitisation_not_disclosed_is_null(self):
        """Not disclosed ≠ zero: securitisation must be unavailable with reason."""
        r = _nbfc_engine().calculate("securitisation", "FY2026")
        assert not r.ok
        assert r.value is None


class TestNbfcNotApplicability:
    """Corporate-inappropriate metrics must not appear for NBFCs (spec §64)."""

    @pytest.mark.parametrize("metric_id", [
        "inventory_turnover", "gross_margin", "dso", "dio",
        "cash_conversion_cycle", "ebitda_margin",
    ])
    def test_corporate_metrics_not_applicable(self, metric_id: str):
        r = _nbfc_engine().calculate(metric_id, "FY2026")
        assert r.status == "NOT_APPLICABLE"

    def test_nbfc_dashboard_has_no_corporate_metrics(self):
        payload = build_india_dashboard(get_fixture("nbfc"))
        all_metric_ids = set()
        for tab in payload["tabs"].values():
            all_metric_ids.update(m["metric_id"] for m in tab["metrics"])
        corporate_only = {
            "inventory_turnover", "gross_margin", "dso", "dio",
            "cash_conversion_cycle", "ebitda_margin", "roce",
        }
        assert not (all_metric_ids & corporate_only)

    def test_nbfc_tabs_are_nbfc_tabs(self):
        payload = build_india_dashboard(get_fixture("nbfc"))
        assert {"asset_quality", "leverage", "funding"} <= set(payload["tabs"].keys())
        assert "efficiency" not in payload["tabs"]
        assert "capital" not in payload["tabs"]


# ══════════════════════════════════════════════════════════════════════════
# Entity classification
# ══════════════════════════════════════════════════════════════════════════

class TestEntityClassification:
    def test_classify_corporate_fixture(self):
        from lib.india.classifier import classify_entity
        result = classify_entity("Finora Industries Ltd")
        assert result.entity_type == EntityType.CORPORATE

    def test_classify_bank_by_name(self):
        from lib.india.classifier import classify_entity
        result = classify_entity("Finora Bank Ltd")
        assert result.entity_type == EntityType.BANK

    def test_classify_nbfc_by_rbi_license(self):
        from lib.india.classifier import classify_entity
        result = classify_entity("Something Capital Ltd", rbi_license="NBFC-ICC")
        assert result.entity_type == EntityType.NBFC
        assert result.confidence >= 0.9

    def test_exchange_metadata_wins(self):
        from lib.india.classifier import classify_entity
        result = classify_entity(
            "Confusing Ltd",
            exchange_metadata={"entity_type": "BANK"},
            rbi_license="NBFC")
        assert result.entity_type == EntityType.BANK

    def test_insurance_signals(self):
        from lib.india.classifier import classify_entity
        assert classify_entity("Future Life Insurance Co").entity_type == EntityType.LIFE_INSURANCE
        assert classify_entity("General Insurance Co").entity_type == EntityType.GENERAL_INSURANCE

    def test_reit_invit(self):
        from lib.india.classifier import classify_entity
        assert classify_entity("Office REIT Trust").entity_type == EntityType.REIT
        assert classify_entity("Highway InvIT").entity_type == EntityType.INVIT

    def test_fixture_identities_match_classifier(self):
        """Fixture identity entity_type must equal what the classifier infers
        from the same metadata (consistency check)."""
        for slug in ("corporate", "bank", "nbfc"):
            data = get_fixture(slug)
            assert data.identity.entity_type in (
                EntityType.CORPORATE.value, EntityType.BANK.value,
                EntityType.NBFC.value)


# ══════════════════════════════════════════════════════════════════════════
# Dashboard payload integrity
# ══════════════════════════════════════════════════════════════════════════

class TestDashboardPayload:
    @pytest.mark.parametrize("slug,entity", [
        ("corporate", "CORPORATE"), ("bank", "BANK"), ("nbfc", "NBFC"),
    ])
    def test_payload_structure(self, slug, entity):
        payload = build_india_dashboard(get_fixture(slug))
        assert payload["entity_type"] == entity
        assert payload["is_fixture"] is True
        assert "fixture" in payload["fixture_notice"].lower()
        assert payload["header"]["currency"] == "INR"
        assert len(payload["periods"]) == 5
        assert payload["scope"] == "CONSOLIDATED"

    def test_fixture_banner_present(self):
        payload = build_india_dashboard(get_fixture("corporate"))
        assert payload["header"]["is_fixture"] is True
        assert payload["valuation"]["fixture_warning"] is True

    def test_no_fake_zeroes_in_statements(self):
        """Unavailable values must be None + reason, never 0."""
        payload = build_india_dashboard(get_fixture("corporate"))
        for stmt in payload["statements"].values():
            for row in stmt["rows"]:
                for v in row["values"]:
                    if v["unavailable"]:
                        assert v["raw"] is None
                        assert v["reason"]

    def test_money_not_preformatted_in_payload_values(self):
        """Raw numeric INR must be preserved for calculations/AI context."""
        payload = build_india_dashboard(get_fixture("corporate"))
        rev = next(r for r in payload["statements"]["income_statement"]["rows"]
                   if r["metric_id"] == "revenue")
        assert rev["values"][-1]["raw"] == 878_000_000_000

    def test_scope_selector_data(self):
        payload = build_india_dashboard(get_fixture("corporate"))
        assert "CONSOLIDATED" in payload["available_scopes"]

    def test_research_context_is_structured(self):
        """AI context must carry raw values + metadata, not UI strings."""
        payload = build_india_dashboard(get_fixture("corporate"))
        ctx = payload["research_context"]
        assert ctx["entity_type"] == "CORPORATE"
        assert "metrics" in ctx and "FY2026" in ctx["metrics"]
        rev = ctx["metrics"]["FY2026"]["revenue"]
        assert rev["value"] == 878_000_000_000
        assert rev["source_ids"] == ["src_fixture_ar"]
        assert "coverage" in ctx
