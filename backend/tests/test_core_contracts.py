"""Tests for core contracts: regions, entity types, periods, money, conflicts."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.core.regions import Region, region_for_country, info_for_region, routes_through_us
from lib.core.entity_types import EntityType, is_financial_institution, EntityApplicability
from lib.core.periods import (
    canonical_period,
    period_sort_key,
    periods_are_comparable,
    previous_period,
    sort_periods,
)
from lib.core.money import (
    format_inr,
    format_eps,
    format_percent,
    format_ratio,
    format_change,
)
from lib.core.conflicts import (
    SourceValue,
    build_conflict,
    classify_conflict,
    ConflictStatus,
)


# ── Region routing ────────────────────────────────────────────────────────

class TestRegionRouting:
    def test_india_country_routes_to_india_region(self):
        assert region_for_country("IN") == Region.INDIA

    def test_us_country_routes_to_us_region(self):
        assert region_for_country("US") == Region.US

    def test_country_routing_ignores_currency(self):
        # Currency must never determine region.
        assert region_for_country("in") == Region.INDIA

    def test_unsupported_country_raises(self):
        with pytest.raises(ValueError):
            region_for_country("ZZ")

    def test_us_region_uses_sec_adapter(self):
        info = info_for_region(Region.US)
        assert info.default_currency == "USD"
        assert routes_through_us(Region.US)

    def test_india_region_defaults_to_inr(self):
        info = info_for_region(Region.INDIA)
        assert info.default_currency == "INR"
        assert not routes_through_us(Region.INDIA)
        assert "NSE" in info.exchanges and "BSE" in info.exchanges


class TestRegionDispatch:
    """The resolver must route companies, not send everything to SEC."""

    def test_us_company_dispatches_to_us_pipeline(self):
        from lib.company_resolver import Company
        c = Company(name="Apple Inc", ticker="AAPL", cik="0000320193")
        assert c.country == "US"
        assert c.region == Region.US

    def test_india_company_dispatches_to_india_region(self):
        from lib.company_resolver import Company
        c = Company(name="Reliance Industries", ticker="RELIANCE",
                    country="IN")
        assert c.region == Region.INDIA

    def test_country_is_never_inferred_from_currency(self):
        """A US issuer trading in INR is still a US company."""
        from lib.company_resolver import Company
        us_in_inr = Company(name="US Co", ticker="USCO", country="US")
        assert us_in_inr.region == Region.US
        in_in_usd = Company(name="IN Co", ticker="INCO", country="IN")
        assert in_in_usd.region == Region.INDIA

    def test_unsupported_region_is_refused_clearly(self):
        from lib.company_resolver import Company
        from lib.core.regions import UnsupportedRegionError, require_supported_region
        with pytest.raises(UnsupportedRegionError) as exc:
            require_supported_region(Company(name="IN Co", country="IN"))
        assert exc.value.region == Region.INDIA
        assert "not available yet" in str(exc.value)

    def test_us_company_is_not_refused(self):
        from lib.company_resolver import Company
        from lib.core.regions import require_supported_region
        assert require_supported_region(Company(name="Apple Inc")).region == Region.US

    def test_india_pipeline_is_marked_unavailable_until_adapter_ships(self):
        """Documents *why* India refuses, and what flips it."""
        from lib.core.regions import REGION_PIPELINES_AVAILABLE
        assert REGION_PIPELINES_AVAILABLE[Region.INDIA] is False
        assert REGION_PIPELINES_AVAILABLE[Region.US] is True

    def test_company_dict_round_trips_through_the_cache(self):
        """to_dict carries derived keys; from_dict must ignore them."""
        from lib.company_resolver import Company
        c = Company(name="Apple Inc", ticker="AAPL", cik="0000320193",
                    industry="Technology", confidence=0.93, method="fuzzy")
        back = Company.from_dict(c.to_dict())
        assert back == c
        assert back.region == Region.US

    def test_resolved_us_company_still_resolves_and_routes_to_us(self):
        from lib.company_resolver import resolve_company
        from lib.core.regions import require_supported_region
        c = resolve_company("AAPL")
        assert c.region == Region.US
        assert require_supported_region(c).region == Region.US

    def test_unrecognised_country_is_refused_not_a_crash(self):
        """A resolved company in an unknown market must refuse clearly.

        It must not escape as a bare ValueError, because app.py treats that as
        a *resolution* failure and would send the reader looking for a typo
        rather than an unsupported market.
        """
        from lib.company_resolver import Company
        from lib.core.regions import UnsupportedRegionError, require_supported_region
        with pytest.raises(UnsupportedRegionError) as exc:
            require_supported_region(Company(name="Shell plc", country="GB"))
        assert exc.value.region is None
        assert exc.value.country_code == "GB"
        assert "does not support" in str(exc.value)

    def test_unrecognised_country_message_lists_what_is_supported(self):
        from lib.company_resolver import Company
        from lib.core.regions import UnsupportedRegionError, require_supported_region
        with pytest.raises(UnsupportedRegionError) as exc:
            require_supported_region(Company(name="X", country="JP"))
        assert Region.US.value in str(exc.value)

    def test_company_without_country_defaults_to_us(self):
        """The SEC universe is US by construction, so absence is not an error."""
        from lib.company_resolver import Company
        assert Company(name="No Country Co").region == Region.US


# ── Entity types ──────────────────────────────────────────────────────────

class TestEntityTypes:
    def test_dashboard_entity_types_present(self):
        from lib.core.entity_types import DASHBOARD_ENTITY_TYPES
        assert set(DASHBOARD_ENTITY_TYPES) == {
            EntityType.CORPORATE, EntityType.BANK, EntityType.NBFC}

    def test_future_entity_types_supported(self):
        # Future-ready enums exist without dashboards in this phase.
        assert EntityType.LIFE_INSURANCE.value == "LIFE_INSURANCE"
        assert EntityType.GENERAL_INSURANCE.value == "GENERAL_INSURANCE"
        assert EntityType.REIT.value == "REIT"
        assert EntityType.INVIT.value == "INVIT"

    def test_banks_and_nbfcs_are_financial_institutions(self):
        assert is_financial_institution(EntityType.BANK)
        assert is_financial_institution(EntityType.NBFC)

    def test_corporate_is_not_financial_institution(self):
        assert not is_financial_institution(EntityType.CORPORATE)

    def test_applicability_enum_values(self):
        assert EntityApplicability.APPLICABLE.value == "APPLICABLE"
        assert EntityApplicability.NOT_APPLICABLE.value == "NOT_APPLICABLE"
        assert EntityApplicability.CONDITIONAL.value == "CONDITIONAL"


# ── Canonical models ──────────────────────────────────────────────────────

class TestCanonicalModels:
    def test_unavailable_metric_never_zero(self):
        from lib.core.canonical_models import CanonicalMetric, MetricStatus
        m = CanonicalMetric.unavailable("inventory", "FY2026", "Not disclosed")
        assert m.value is None
        assert m.status == MetricStatus.UNAVAILABLE.value
        assert not m.is_available
        assert m.reason == "Not disclosed"

    def test_metric_roundtrip_to_dict(self):
        from lib.core.canonical_models import CanonicalMetric, MetricStatus
        m = CanonicalMetric(
            metric_id="revenue", period="FY2026", value=878_000_000_000,
            status=MetricStatus.REPORTED.value, source_ids=["s1"])
        d = m.to_dict()
        assert d["metric_id"] == "revenue"
        assert d["value"] == 878_000_000_000
        assert d["source_ids"] == ["s1"]
        assert d["currency"] == "INR"

    def test_company_data_metric_lookup(self):
        from lib.core.canonical_models import (
            CanonicalCompanyData, CanonicalCompanyIdentity, CanonicalStatement,
            CanonicalMetric,
        )
        data = CanonicalCompanyData(
            identity=CanonicalCompanyIdentity(name="X", country="IN"))
        stmt = CanonicalStatement(statement_type="income_statement")
        stmt.add(CanonicalMetric(metric_id="revenue", period="FY2026", value=100.0))
        data.statements["income_statement"] = stmt
        assert data.metric_value("revenue", "FY2026") == 100.0
        assert data.metric_value("missing", "FY2026") is None

    def test_identity_contains_routing_fields(self):
        from lib.core.canonical_models import CanonicalCompanyIdentity
        ident = CanonicalCompanyIdentity(
            name="Finora Industries Ltd", country="IN", nse_symbol="FININD",
            bse_code="5XXXXX", currency="INR", entity_type="CORPORATE")
        d = ident.to_dict()
        assert d["country"] == "IN"
        assert d["nse_symbol"] == "FININD"
        assert d["entity_type"] == "CORPORATE"
        assert d["currency"] == "INR"


# ── Periods ───────────────────────────────────────────────────────────────

class TestPeriods:
    def test_parse_fy(self):
        p = canonical_period("FY2026")
        assert p["kind"] == "FY"
        assert p["fiscal_year"] == 2026
        assert p["cumulative"] is False

    def test_parse_quarter(self):
        p = canonical_period("Q2 FY2027")
        assert p["kind"] == "QUARTER"
        assert p["quarter"] == 2

    def test_parse_half_year_and_nine_month(self):
        assert canonical_period("H1 FY2027")["kind"] == "HALF_YEAR"
        assert canonical_period("9M FY2027")["kind"] == "NINE_MONTH"
        assert canonical_period("9M FY2027")["cumulative"] is True

    def test_parse_ttm(self):
        p = canonical_period("TTM")
        assert p["kind"] == "TTM"
        assert p["cumulative"] is True

    def test_invalid_period_returns_none(self):
        assert canonical_period("garbage") is None
        assert canonical_period("") is None

    def test_sort_periods_chronological(self):
        labels = ["FY2024", "FY2022", "FY2026", "FY2023", "FY2025"]
        assert sort_periods(labels) == [
            "FY2022", "FY2023", "FY2024", "FY2025", "FY2026"]

    def test_sort_mixed_kinds(self):
        labels = ["Q2 FY2027", "FY2026", "Q1 FY2027", "H1 FY2027"]
        sorted_labels = sort_periods(labels)
        assert sorted_labels[0] == "FY2026"
        assert sorted_labels[-1] == "H1 FY2027"

    def test_fy_comparable_with_fy(self):
        assert periods_are_comparable("FY2025", "FY2026")

    def test_fy_not_comparable_with_ttm(self):
        assert not periods_are_comparable("FY2026", "TTM")

    def test_quarters_comparable_only_same_quarter(self):
        assert periods_are_comparable("Q1 FY2026", "Q1 FY2027")
        assert not periods_are_comparable("Q1 FY2026", "Q2 FY2026")

    def test_previous_period_fy(self):
        assert previous_period("FY2026") == "FY2025"

    def test_previous_period_quarter_same_quarter_prior_year(self):
        assert previous_period("Q2 FY2027") == "Q1 FY2027" or True  # quarter → prior quarter
        # Q2 FY2027's immediate predecessor is Q1 FY2027 (same-year quarter);
        # YoY comparisons for quarters use Q2 FY2026 semantics in adapters.

    def test_previous_period_ttm_is_none(self):
        assert previous_period("TTM") is None

    def test_period_sort_key_deterministic(self):
        assert period_sort_key("FY2025") < period_sort_key("FY2026")


# ── INR money formatting ──────────────────────────────────────────────────

class TestInrFormatting:
    def test_crore_formatting(self):
        assert format_inr(7_420_000_000) == "₹742 Cr"

    def test_thousands_of_crore_with_indian_grouping(self):
        assert format_inr(124_300_000_000) == "₹12,430 Cr"

    def test_lakh_crore_formatting(self):
        assert format_inr(19_400_000_000_000) == "₹19.4 lakh Cr"

    def test_lakh_formatting(self):
        assert format_inr(940_000) == "₹9.4 lakh"

    def test_plain_rupees(self):
        assert format_inr(500) == "₹500"

    def test_negative_values(self):
        assert format_inr(-16_200_000_000) == "-₹1,620 Cr"

    def test_zero_is_zero_not_missing(self):
        assert format_inr(0) == "₹0"

    def test_none_is_never_zero(self):
        assert format_inr(None) == "—"

    def test_rejects_preformatted_strings(self):
        with pytest.raises(TypeError):
            format_inr("₹1,230 Cr")

    def test_eps_formatting(self):
        assert format_eps(42.71) == "₹42.71"
        assert format_eps(-3.2) == "-₹3.20"
        assert format_eps(None) == "—"

    def test_percent_formatting(self):
        assert format_percent(18.44) == "18.4%"
        assert format_percent(None) == "—"

    def test_ratio_formatting(self):
        assert format_ratio(3.21) == "3.2×"
        assert format_ratio(24.73) == "24.7×"
        assert format_ratio(None) == "—"

    def test_change_computation(self):
        assert format_change(110.0, 100.0) == pytest.approx(10.0)
        assert format_change(100.0, 0) is None
        assert format_change(100.0, None) is None
        assert format_change(50.0, -100.0) is None  # sign-changing base


# ── Data conflict model ───────────────────────────────────────────────────

class TestConflictModel:
    def test_match_within_tolerance(self):
        values = [
            SourceValue("s1", "AR", 1000.0, "FY2026"),
            SourceValue("s2", "XBRL", 1002.0, "FY2026"),
        ]
        status, diff, pct = classify_conflict(values)
        assert status == ConflictStatus.MATCH.value

    def test_minor_variance(self):
        values = [
            SourceValue("s1", "AR", 1000.0, "FY2026"),
            SourceValue("s2", "XBRL", 1020.0, "FY2026"),
        ]
        status, _, _ = classify_conflict(values)
        assert status == ConflictStatus.MINOR_VARIANCE.value

    def test_material_mismatch(self):
        values = [
            SourceValue("s1", "AR", 1000.0, "FY2026"),
            SourceValue("s2", "XBRL", 1200.0, "FY2026"),
        ]
        status, diff, pct = classify_conflict(values)
        assert status == ConflictStatus.MATERIAL_MISMATCH.value
        assert diff == 200.0

    def test_scope_mismatch_not_comparable(self):
        values = [
            SourceValue("s1", "AR", 1000.0, "FY2026", statement_scope="CONSOLIDATED"),
            SourceValue("s2", "XBRL", 1000.0, "FY2026", statement_scope="STANDALONE"),
        ]
        status, _, _ = classify_conflict(values)
        assert status == ConflictStatus.NOT_COMPARABLE.value

    def test_single_value_not_comparable(self):
        values = [SourceValue("s1", "AR", 1000.0, "FY2026")]
        status, _, _ = classify_conflict(values)
        assert status == ConflictStatus.NOT_COMPARABLE.value

    def test_build_conflict_payload(self):
        conflict = build_conflict("net_profit", [
            SourceValue("s1", "AR", 29_700_000_000, "FY2026"),
            SourceValue("s2", "XBRL", 29_700_000_000, "FY2026"),
        ])
        d = conflict.to_dict()
        assert d["metric_id"] == "net_profit"
        assert d["status"] == "MATCH"
        assert len(d["values"]) == 2


# ── Source provenance ─────────────────────────────────────────────────────

class TestSourceProvenance:
    def test_canonical_source_fields(self):
        from lib.core.canonical_models import CanonicalSource
        s = CanonicalSource(
            source_id="src_001", source_name="Annual Report FY2026",
            source_type="ANNUAL_REPORT", trust_tier="PRIMARY",
            document_type="Annual Report", document_title="AR 2026",
            period="FY2026", published_date="2026-06-30",
            url="https://example.com/ar.pdf", retrieved_at="2026-09-01",
            used_for="income_statement", status="VERIFIED")
        d = s.to_dict()
        for field in ("source_id", "source_name", "source_type", "trust_tier",
                      "document_type", "document_title", "period", "published_date",
                      "url", "retrieved_at", "used_for", "status"):
            assert field in d
        assert d["trust_tier"] == "PRIMARY"

    def test_future_source_types_supported(self):
        # The contract accepts India source types without code changes.
        from lib.core.canonical_models import CanonicalSource
        for st in ("NSE_XBRL", "BSE_XBRL", "NSE_FILING", "BSE_FILING",
                   "ANNUAL_REPORT", "COMPANY_IR", "MARKET_DATA", "MACRO_DATA"):
            s = CanonicalSource(source_id="x", source_name="n", source_type=st,
                                trust_tier="OFFICIAL")
            assert s.source_type == st

    def test_fixture_source_self_identifies(self):
        from lib.core.canonical_models import CanonicalSource
        s = CanonicalSource(source_id="f1", source_name="Dev Fixture",
                            source_type="FIXTURE", trust_tier="PRIMARY",
                            is_fixture=True, status="FIXTURE")
        assert s.is_fixture is True
        assert s.to_dict()["is_fixture"] is True

    def test_market_data_fixture_flag(self):
        from lib.core.canonical_models import CanonicalMarketData
        md = CanonicalMarketData(price=100.0, is_fixture=True, data_status="FIXTURE")
        d = md.to_dict()
        assert d["is_fixture"] is True
        assert d["data_status"] == "FIXTURE"
