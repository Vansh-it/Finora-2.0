"""Tests for metric registry, applicability, calculations and completeness."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.core.canonical_models import CanonicalCompanyData, CanonicalCompanyIdentity, Scope
from lib.core.entity_types import EntityType
from lib.metrics.registry import get_registry, MetricRegistry
from lib.metrics.applicability import applicability_for, filter_applicable
from lib.metrics.engine import MetricEngine, safe_div, growth_pct, cagr_pct
from lib.metrics.completeness import (
    CompletenessEngine,
    CoverageStatus,
)
from lib.india.fixtures import get_fixture
from lib.india.models import schema_for


def _corporate_engine() -> MetricEngine:
    return MetricEngine(get_fixture("corporate"))


# ── Metric registry ───────────────────────────────────────────────────────

class TestMetricRegistry:
    def test_registry_populates(self):
        reg = get_registry()
        assert len(reg) > 100

    def test_every_metric_declares_a_source_priority(self):
        """Unranked provenance is how a fixture ends up outranking a filing."""
        empty = [mid for mid, d in get_registry().all_metrics().items()
                 if not d.source_priority]
        assert not empty, f"metrics with no source_priority: {empty}"

    def test_source_priority_names_only_real_source_types(self):
        from lib.metrics.registry import SourceType
        valid = {s.value for s in SourceType}
        bad = {mid: [t for t in d.source_priority if t not in valid]
               for mid, d in get_registry().all_metrics().items()
               if any(t not in valid for t in d.source_priority)}
        assert not bad, f"invalid source types: {bad}"

    def test_fixture_never_outranks_a_filing(self):
        from lib.metrics.registry import SourceType
        for mid, d in get_registry().all_metrics().items():
            if SourceType.FIXTURE.value in d.source_priority:
                assert d.source_priority[-1] == SourceType.FIXTURE.value, (
                    f"{mid} ranks FIXTURE above {d.source_priority[-1]}"
                )

    def test_market_metrics_prefer_market_data(self):
        from lib.metrics.registry import SourceType
        d = get_registry().require("market_cap")
        assert d.source_priority[0] == SourceType.MARKET_DATA.value

    def test_statement_metrics_prefer_machine_readable_filings(self):
        from lib.metrics.registry import SourceType
        d = get_registry().require("revenue")
        assert d.source_priority[0] == SourceType.NSE_XBRL.value

    def test_source_ordering_ranks_most_authoritative_first(self):
        reg = get_registry()
        ordered = reg.order_sources("revenue", {
            "c": "FIXTURE", "b": "ANNUAL_REPORT", "a": "NSE_XBRL",
        })
        assert ordered == ["a", "b", "c"]

    def test_source_ordering_demotes_rather_than_drops_unknown_types(self):
        reg = get_registry()
        ordered = reg.order_sources("revenue", {
            "mystery": "SOME_UNDOCUMENTED_TYPE", "a": "ANNUAL_REPORT",
        })
        assert set(ordered) == {"a", "mystery"}, "unknown source was dropped"
        assert ordered[-1] == "mystery", "unknown source outranked a filing"

    def test_source_ordering_is_stable_for_unranked_sources(self):
        reg = get_registry()
        ordered = reg.order_sources("revenue", {"b": "X", "a": "Y", "c": "Z"})
        assert ordered == sorted(["a", "b", "c"])

    def test_source_ordering_handles_unknown_metric(self):
        assert get_registry().order_sources("not_a_metric", {"a": "NSE_XBRL"}) == ["a"]

    def test_evidence_trail_is_ordered_in_the_dashboard(self):
        """The ordering must reach the payload, not just exist in the registry."""
        from lib.india.dashboard_builder import build_india_dashboard
        payload = build_india_dashboard(get_fixture("corporate"))
        revenue = next(k for k in payload["kpis"] if k["metric_id"] == "revenue")
        assert revenue["source_ids"], "revenue must carry evidence"
        by_id = {s["source_id"]: s["source_type"] for s in payload["sources"]}
        types = [by_id[i] for i in revenue["source_ids"]]
        rank = {t: i for i, t in enumerate(get_registry().require("revenue").source_priority)}
        assert types == sorted(types, key=lambda t: rank.get(t, len(rank)))

    def test_registry_is_singleton(self):
        assert get_registry() is get_registry()

    def test_conflicting_definition_raises(self):
        from lib.metrics.registry import MetricDefinition
        reg = MetricRegistry()
        d = MetricDefinition(metric_id="x", display_name="X", category="c",
                             entity_types=frozenset({EntityType.CORPORATE}))
        reg.register(d)
        with pytest.raises(ValueError):
            reg.register(MetricDefinition(
                metric_id="x", display_name="Different", category="c",
                entity_types=frozenset({EntityType.CORPORATE})))

    def test_identical_definition_is_idempotent(self):
        from lib.metrics.registry import MetricDefinition
        reg = MetricRegistry()
        d = MetricDefinition(metric_id="x", display_name="X", category="c",
                             entity_types=frozenset({EntityType.CORPORATE}))
        reg.register(d)
        reg.register(d)  # same content — OK
        assert len(reg.all_metrics()) == 1

    def test_definitions_carry_methodology(self):
        reg = get_registry()
        for mid in ("free_cash_flow", "roce", "roic", "net_debt", "nim", "credit_cost"):
            d = reg.get(mid)
            assert d is not None, mid
            assert d.methodology, f"{mid} missing methodology"

    def test_registry_coverage_of_schemas(self):
        """Every schema metric must exist in the registry."""
        reg = get_registry()
        for entity in (EntityType.CORPORATE, EntityType.BANK, EntityType.NBFC):
            for mid in schema_for(entity).expected_metric_ids():
                assert reg.get(mid) is not None, f"{mid} not in registry"


# ── Applicability ─────────────────────────────────────────────────────────

class TestApplicability:
    def test_inventory_turnover_not_applicable_to_bank(self):
        assert applicability_for("inventory_turnover", EntityType.BANK) == "NOT_APPLICABLE"

    def test_inventory_turnover_not_applicable_to_nbfc(self):
        assert applicability_for("inventory_turnover", EntityType.NBFC) == "NOT_APPLICABLE"

    def test_inventory_turnover_applicable_to_corporate(self):
        assert applicability_for("inventory_turnover", EntityType.CORPORATE) == "APPLICABLE"

    def test_gnpa_applicable_to_bank_only(self):
        assert applicability_for("gnpa", EntityType.BANK) == "APPLICABLE"
        assert applicability_for("gnpa", EntityType.CORPORATE) == "NOT_APPLICABLE"
        assert applicability_for("gnpa", EntityType.NBFC) == "NOT_APPLICABLE"

    def test_stage3_applicable_to_nbfc(self):
        assert applicability_for("stage3_gross_pct", EntityType.NBFC) == "APPLICABLE"

    def test_dso_not_applicable_to_bank(self):
        assert applicability_for("dso", EntityType.BANK) == "NOT_APPLICABLE"

    def test_gross_margin_bank_not_applicable(self):
        assert applicability_for("gross_margin", EntityType.BANK) == "NOT_APPLICABLE"

    def test_filter_applicable_split(self):
        applicable, not_applicable = filter_applicable(
            ["inventory_turnover", "nim", "gnpa_pct", "revenue"], EntityType.BANK)
        assert "nim" in applicable and "gnpa_pct" in applicable
        assert "inventory_turnover" in not_applicable

    def test_promoter_holding_conditional(self):
        from lib.metrics.registry import Requirement
        d = get_registry().get("promoter_holding")
        assert d.requirement == Requirement.CONDITIONAL.value


# ── Calculation safety ────────────────────────────────────────────────────

class TestCalculationSafety:
    def test_safe_div_by_zero(self):
        assert safe_div(10.0, 0.0) is None

    def test_safe_div_missing(self):
        assert safe_div(None, 10.0) is None
        assert safe_div(10.0, None) is None

    def test_growth_zero_base(self):
        assert growth_pct(100.0, 0.0) is None

    def test_growth_sign_change(self):
        assert growth_pct(50.0, -100.0) is None

    def test_cagr_negative_values(self):
        assert cagr_pct(-10.0, 10.0, 3) is None
        assert cagr_pct(10.0, -10.0, 3) is None

    def test_engine_refuses_mismatched_periods(self):
        # A QUARTER result cannot be fed FY inputs: with no quarterly data
        # the calculation must return INSUFFICIENT_DATA, not guess.
        e = _corporate_engine()
        r = e.calculate("current_ratio", "Q1 FY2027")
        assert r.status == "INSUFFICIENT_DATA"

    def test_unknown_metric_insufficient(self):
        e = _corporate_engine()
        r = e.calculate("not_a_metric", "FY2026")
        assert r.status == "INSUFFICIENT_DATA"

    def test_missing_inputs_insufficient_with_reason(self):
        data = CanonicalCompanyData(
            identity=CanonicalCompanyIdentity(name="X", country="IN",
                                              entity_type="CORPORATE"))
        e = MetricEngine(data)
        r = e.calculate("current_ratio", "FY2026")
        assert r.status == "INSUFFICIENT_DATA"
        assert "Missing inputs" in r.reason

    def test_division_by_zero_denominator_insufficient(self):
        data = get_fixture("corporate")
        # Zero revenue → margin undefined
        m = data.metric("revenue", "FY2026")
        m.value = 0.0
        e = MetricEngine(data)
        r = e.calculate("pat_margin", "FY2026")
        assert r.status == "INSUFFICIENT_DATA"
        m.value = 878_000_000_000  # restore


# ── Corporate calculations ────────────────────────────────────────────────

class TestCorporateCalculations:
    def test_fcf(self):
        e = _corporate_engine()
        r = e.calculate("free_cash_flow", "FY2026")
        assert r.ok
        # OCF 31.6bn − capex 47.8bn
        assert r.value == pytest.approx(31_600_000_000 - 47_800_000_000)

    def test_revenue_growth(self):
        e = _corporate_engine()
        r = e.calculate("revenue_growth", "FY2026")
        assert r.ok
        # 878bn vs 815bn
        assert r.value == pytest.approx((878 - 815) / 815 * 100, rel=1e-3)

    def test_cagr_3y(self):
        e = _corporate_engine()
        r = e.calculate("revenue_cagr_3y", "FY2026")
        assert r.ok
        # FY2023 → FY2026 is a 3-year span
        expected = ((878 / 682) ** (1 / 3) - 1) * 100
        assert r.value == pytest.approx(expected, rel=1e-3)

    def test_cagr_5y_requires_full_history(self):
        e = _corporate_engine()
        r = e.calculate("revenue_cagr_5y", "FY2026")
        assert not r.ok
        assert "FY2021" in r.reason

    def test_ebitda_margin(self):
        e = _corporate_engine()
        r = e.calculate("ebitda_margin", "FY2026")
        assert r.ok
        assert r.value == pytest.approx(106.4 / 878 * 100, rel=1e-3)

    def test_operating_margin(self):
        e = _corporate_engine()
        r = e.calculate("operating_margin", "FY2026")
        assert r.ok

    def test_pat_margin(self):
        e = _corporate_engine()
        r = e.calculate("pat_margin", "FY2026")
        assert r.ok
        assert r.value == pytest.approx(29.7 / 878 * 100, rel=1e-3)

    def test_roa(self):
        e = _corporate_engine()
        r = e.calculate("roa", "FY2026")
        assert r.ok

    def test_roe(self):
        e = _corporate_engine()
        r = e.calculate("roe", "FY2026")
        assert r.ok

    def test_roce(self):
        e = _corporate_engine()
        r = e.calculate("roce", "FY2026")
        assert r.ok

    def test_roic(self):
        e = _corporate_engine()
        r = e.calculate("roic", "FY2026")
        assert r.ok

    def test_current_ratio(self):
        e = _corporate_engine()
        r = e.calculate("current_ratio", "FY2026")
        assert r.ok
        assert r.value == pytest.approx(255.8 / 171.5, rel=1e-3)

    def test_quick_ratio_excludes_inventory(self):
        e = _corporate_engine()
        r = e.calculate("quick_ratio", "FY2026")
        assert r.ok
        assert r.value == pytest.approx((255.8 - 88.4) / 171.5, rel=1e-3)

    def test_debt_to_equity(self):
        e = _corporate_engine()
        r = e.calculate("debt_to_equity", "FY2026")
        assert r.ok
        assert r.value == pytest.approx(125.4 / 247.6, rel=1e-3)

    def test_net_debt(self):
        e = _corporate_engine()
        r = e.calculate("net_debt", "FY2026")
        assert r.ok
        expected = (125_400_000_000 - 9_400_000_000 - 8_300_000_000
                    - 4_100_000_000)  # debt − cash − current inv − bank balances
        assert r.value == pytest.approx(expected, rel=1e-6)

    def test_debt_to_ebitda(self):
        e = _corporate_engine()
        r = e.calculate("debt_to_ebitda", "FY2026")
        assert r.ok

    def test_interest_coverage(self):
        e = _corporate_engine()
        r = e.calculate("interest_coverage", "FY2026")
        assert r.ok

    def test_asset_turnover(self):
        e = _corporate_engine()
        r = e.calculate("asset_turnover", "FY2026")
        assert r.ok

    def test_dso(self):
        e = _corporate_engine()
        r = e.calculate("dso", "FY2026")
        assert r.ok
        assert r.value == pytest.approx(132.4 / 878 * 365, rel=1e-3)

    def test_dio(self):
        e = _corporate_engine()
        r = e.calculate("dio", "FY2026")
        assert r.ok

    def test_dpo(self):
        e = _corporate_engine()
        r = e.calculate("dpo", "FY2026")
        assert r.ok

    def test_ccc(self):
        e = _corporate_engine()
        r = e.calculate("cash_conversion_cycle", "FY2026")
        assert r.ok

    def test_capex_intensity(self):
        e = _corporate_engine()
        r = e.calculate("capex_to_revenue", "FY2026")
        assert r.ok

    def test_ocf_to_pat(self):
        e = _corporate_engine()
        r = e.calculate("ocf_to_pat", "FY2026")
        assert r.ok

    def test_fcf_to_pat(self):
        e = _corporate_engine()
        r = e.calculate("fcf_to_pat", "FY2026")
        assert r.ok

    def test_market_cap_from_market_data(self):
        e = _corporate_engine()
        r = e.calculate("market_cap", "FY2026")
        assert r.ok
        assert r.status == "MARKET_DATA"

    def test_ev_and_multiples(self):
        e = _corporate_engine()
        ev = e.calculate("enterprise_value", "FY2026")
        assert ev.ok
        pe = e.calculate("pe_ratio", "FY2026")
        assert pe.ok
        evebitda = e.calculate("ev_ebitda", "FY2026")
        assert evebitda.ok

    def test_calculated_result_traceability(self):
        e = _corporate_engine()
        r = e.calculate("free_cash_flow", "FY2026")
        assert r.formula
        assert "operating_cash_flow" in r.inputs
        assert r.source_ids  # provenance preserved


# ── Completeness engine ───────────────────────────────────────────────────

class TestCompleteness:
    def test_coverage_excludes_not_applicable(self):
        data = get_fixture("bank")
        schema = schema_for(EntityType.BANK)
        comp = CompletenessEngine()
        res = comp.assess_with_engine(data, schema.expected_metric_ids(),
                                      EntityType.BANK, "FY2026")
        assert res.not_applicable > 0
        # N/A metrics must not be in the denominator
        assert res.expected < len(schema.expected_metric_ids())

    def test_bank_coverage_realistic(self):
        data = get_fixture("bank")
        schema = schema_for(EntityType.BANK)
        res = CompletenessEngine().assess_with_engine(
            data, schema.expected_metric_ids(), EntityType.BANK, "FY2026")
        assert res.coverage_pct is not None and res.coverage_pct > 80

    def test_missing_metrics_have_recovery_contract(self):
        data = get_fixture("corporate")
        schema = schema_for(EntityType.CORPORATE)
        res = CompletenessEngine().assess_with_engine(
            data, schema.expected_metric_ids(), EntityType.CORPORATE, "FY2026")
        assert res.missing_metrics
        for m in res.missing_metrics:
            assert m.reason
            assert m.recovery_strategy
            if m.derivable:
                assert m.required_inputs

    def test_missing_metric_example_shape(self):
        """Spec example: free_cash_flow derivable from OCF + capex."""
        data = get_fixture("corporate")
        schema = schema_for(EntityType.CORPORATE)
        res = CompletenessEngine().assess_with_engine(
            data, schema.expected_metric_ids(), EntityType.CORPORATE, "FY2024")
        fcf_missing = [m for m in res.missing_metrics
                       if m.metric_id == "free_cash_flow"]
        # FCF is fully computable in fixtures, so it must NOT be missing
        assert fcf_missing == []

    def test_status_counts_sum(self):
        data = get_fixture("nbfc")
        schema = schema_for(EntityType.NBFC)
        res = CompletenessEngine().assess_with_engine(
            data, schema.expected_metric_ids(), EntityType.NBFC, "FY2026")
        total_classified = len(schema.expected_metric_ids())
        assert (res.available + res.unavailable + res.not_applicable
                + res.pending_source == total_classified)

    def test_category_coverage(self):
        data = get_fixture("corporate")
        schema = schema_for(EntityType.CORPORATE)
        res = CompletenessEngine().assess_with_engine(
            data, schema.expected_metric_ids(), EntityType.CORPORATE, "FY2026")
        cats = {c.category for c in res.categories}
        assert {"growth", "profitability", "liquidity", "leverage",
                "efficiency", "ownership", "valuation"} <= cats

    def test_pending_source_not_punished_as_failure(self):
        # dividend_yield is conditional on market data (DPS missing in fixture)
        data = get_fixture("corporate")
        schema = schema_for(EntityType.CORPORATE)
        res = CompletenessEngine().assess_with_engine(
            data, schema.expected_metric_ids(), EntityType.CORPORATE, "FY2026")
        dy = res.metric_details.get("dividend_yield")
        assert dy in (CoverageStatus.PENDING_SOURCE.value,
                      CoverageStatus.UNAVAILABLE.value)


# ── Standalone / consolidated separation ──────────────────────────────────

class TestScopeSeparation:
    def test_consolidated_default(self):
        from lib.core.canonical_models import MetricStatus
        assert MetricStatus.REPORTED.value == "REPORTED"
        data = get_fixture("corporate")
        m = data.metric("revenue", "FY2026")
        assert m.statement_scope == Scope.CONSOLIDATED.value

    def test_standalone_scope_requestable(self):
        payload_scope = Scope.STANDALONE.value
        assert payload_scope == "STANDALONE"

    def test_scope_mismatch_does_not_cross_contaminate(self):
        """A standalone-only metric must not silently satisfy a consolidated ask."""
        from lib.core.canonical_models import CanonicalStatement, CanonicalMetric
        data = get_fixture("corporate")
        stmt = data.statements["income_statement"]
        stmt.add(CanonicalMetric(
            metric_id="standalone_only_metric", period="FY2026", value=1.0,
            statement_scope=Scope.STANDALONE.value,
        ))
        e = MetricEngine(data)
        v, srcs, scope = e.resolve_input(
            "standalone_only_metric", "FY2026", Scope.CONSOLIDATED.value
        )
        # No consolidated value exists, so resolution must yield nothing and
        # must not invent one. Reporting the scope it fell back to keeps the
        # fallback visible to callers instead of passing it off as a match.
        assert v is None and not srcs


# ── Cash-flow coherence ────────────────────────────────────────────────────

class TestCashFlowCoherence:
    """The cash-flow statement must actually add up.

    The ``fcf_decline`` and ``pat_fcf_divergence`` detectors are only
    meaningful if FCF is a faithful function of the recorded cash-flow lines.
    These tests pin that, so a future fixture edit cannot quietly turn a real
    red flag into a data-entry artifact (or the reverse).
    """

    YEARS = ("FY2022", "FY2023", "FY2024", "FY2025", "FY2026")

    @staticmethod
    def _cash_flow(metric_id: str, period: str):
        m = get_fixture("corporate").statements["cash_flow"].get(metric_id, period)
        return None if m is None else m.value

    def test_operating_investing_financing_sum_to_net_change(self):
        """OCF + ICF + FCF == net change in cash, every period."""
        for y in self.YEARS:
            ocf = self._cash_flow("operating_cash_flow", y)
            icf = self._cash_flow("investing_cash_flow", y)
            fcf = self._cash_flow("financing_cash_flow", y)
            net = self._cash_flow("net_change_in_cash", y)
            assert ocf is not None and icf is not None and fcf is not None, y
            assert net is not None, y
            total = ocf + icf + fcf
            assert abs(total - net) < 1_000.0, (
                f"{y}: cash-flow subtotals sum to {total}, "
                f"but net_change_in_cash is {net}"
            )

    def test_engine_fcf_equals_ocf_minus_capex(self):
        """The engine's FCF must reconcile with its declared formula."""
        engine = _corporate_engine()
        for y in self.YEARS:
            r = engine.calculate("free_cash_flow", y)
            assert r.ok, f"{y}: {r.reason}"
            expected = self._cash_flow("operating_cash_flow", y) - self._cash_flow("capex", y)
            assert r.value == pytest.approx(expected, abs=1.0), y

    def test_fcf_decline_is_real_not_an_artifact(self):
        """FCF genuinely falls across the window, so the detector is warranted.

        If this ever stops holding, the red flag is coming from the data rather
        than from the business and should be revisited.
        """
        engine = _corporate_engine()
        values = [engine.calculate("free_cash_flow", y).value for y in self.YEARS]
        assert all(v is not None for v in values)
        assert values[0] > values[-1], f"FCF did not decline: {values}"
        assert values[-1] < 0, f"FY2026 FCF should be negative, got {values[-1]}"

    def test_fcf_turns_negative_before_net_change_in_cash(self):
        """The FCF red flag leads cash depletion, which is the point of the signal."""
        fcf_negative_years = [
            y for y in self.YEARS
            if (_corporate_engine().calculate("free_cash_flow", y).value or 0) < 0
        ]
        cash_negative_years = [
            y for y in self.YEARS
            if (self._cash_flow("net_change_in_cash", y) or 0) < 0
        ]
        assert fcf_negative_years, "no period has negative FCF"
        assert fcf_negative_years[0] <= (cash_negative_years[0] if cash_negative_years else "FY9999")


class TestStandaloneScope:
    """Indian filings publish both bases; the fixture must actually carry them.

    The canonical store is scope-keyed so consolidated and standalone values for
    the same metric and period coexist. These tests pin that, plus the rule that
    decides when falling back to the other scope is legitimate.
    """

    def test_canonical_store_holds_both_scopes_for_one_metric_period(self):
        """The key includes scope, so neither value overwrites the other."""
        data = get_fixture("corporate")
        bs = data.statements["balance_sheet"]
        assert bs.get("share_capital", "FY2026", Scope.CONSOLIDATED.value) is not None
        assert set(bs.scopes_for("share_capital", "FY2026")) == {"CONSOLIDATED", "STANDALONE"}

    def test_each_scope_resolves_its_own_value(self):
        e = MetricEngine(get_fixture("corporate"))
        cons, _, cons_actual = e.resolve_input("revenue", "FY2026", Scope.CONSOLIDATED.value)
        sa, _, sa_actual = e.resolve_input("revenue", "FY2026", Scope.STANDALONE.value)
        assert cons_actual == Scope.CONSOLIDATED.value
        assert sa_actual == Scope.STANDALONE.value
        assert cons == 878_000_000_000
        assert sa == 596_000_000_000
        assert cons > sa, "consolidated must include the subsidiary"

    def test_standalone_only_metric_does_not_answer_a_consolidated_request(self):
        """Asking for group figures must never yield parent-only figures."""
        from lib.core.canonical_models import CanonicalMetric
        data = get_fixture("corporate")
        data.statements["income_statement"].add(CanonicalMetric(
            metric_id="standalone_only_metric", period="FY2026", value=1.0,
            statement_scope=Scope.STANDALONE.value,
        ))
        e = MetricEngine(data)
        value, sources, _ = e.resolve_input(
            "standalone_only_metric", "FY2026", Scope.CONSOLIDATED.value
        )
        assert value is None and not sources

    def test_single_scope_dataset_still_answers_both_requests(self):
        """A consolidated-only adapter must not return nothing for standalone.

        Bank and NBFC record one basis only. Returning the recorded figure with
        its true scope beats refusing, which would blank the dashboard.
        """
        data = get_fixture("bank")
        e = MetricEngine(data)
        value, _, actual = e.resolve_input(
            "total_assets", "FY2026", Scope.STANDALONE.value
        )
        assert value is not None
        assert actual == Scope.CONSOLIDATED.value, "fallback must report the real scope"

    def test_available_scopes_reflects_recorded_data(self):
        assert get_fixture("corporate").available_scopes() == ["CONSOLIDATED", "STANDALONE"]
        assert get_fixture("bank").available_scopes() == ["CONSOLIDATED"]
        assert get_fixture("nbfc").available_scopes() == ["CONSOLIDATED"]

    def test_standalone_balance_sheet_balances_exactly(self):
        """Unlike the documented consolidated defect, standalone must tie out.

        This is the control: a correct sheet proving the engine does not
        manufacture the imbalance it reports for the consolidated sheet.
        """
        e = MetricEngine(get_fixture("corporate"))
        s = Scope.STANDALONE.value
        assets = e.resolve_input("total_assets", "FY2026", s)[0]
        tcl = e.resolve_input("total_current_liabilities", "FY2026", s)[0]
        tncl = e.resolve_input("total_non_current_liabilities", "FY2026", s)[0]
        equity = e.resolve_input("total_equity", "FY2026", s)[0]
        assert assets == pytest.approx(tcl + tncl + equity, abs=1.0)

    def test_standalone_components_sum_to_recorded_subtotals(self):
        """The coherence guards must hold on the standalone basis too."""
        e = MetricEngine(get_fixture("corporate"))
        s = Scope.STANDALONE.value
        for subtotal, parts in (
            ("total_current_assets",
             ("cash", "bank_balances", "current_investments",
              "trade_receivables", "inventory", "other_current_assets")),
            ("total_non_current_assets",
             ("ppe", "cwip", "intangibles", "goodwill", "other_non_current_assets")),
            ("total_current_liabilities",
             ("trade_payables", "short_term_borrowings", "current_debt",
              "other_current_liabilities")),
            ("total_non_current_liabilities",
             ("long_term_borrowings", "other_non_current_liabilities")),
        ):
            derived = e.calculate(subtotal, "FY2026", s)
            assert derived.ok, f"{subtotal}: {derived.reason}"
            expected = sum(e.resolve_input(p, "FY2026", s)[0] for p in parts)
            assert derived.value == pytest.approx(expected, abs=1.0), subtotal

    def test_standalone_fcf_is_healthy_while_group_fcf_is_not(self):
        """The scope switch must change the story, or it is not worth offering.

        This is why the fixture bothers with a second basis: the group's
        negative FCF belongs to the subsidiary, and a reader can see that.
        """
        e = MetricEngine(get_fixture("corporate"))
        cons = e.calculate("free_cash_flow", "FY2026", Scope.CONSOLIDATED.value)
        sa = e.calculate("free_cash_flow", "FY2026", Scope.STANDALONE.value)
        assert cons.value < 0, "consolidated FCF should be negative"
        assert sa.value > 0, "standalone FCF should be positive"
        assert sa.value == 26_200_000_000

    def test_standalone_cash_flow_subtotals_still_reconcile(self):
        data = get_fixture("corporate")
        cf = data.statements["cash_flow"]
        s = Scope.STANDALONE.value
        parts = ["operating_cash_flow", "investing_cash_flow", "financing_cash_flow"]
        total = sum(cf.get(p, "FY2026", s).value for p in parts)
        net = cf.get("net_change_in_cash", "FY2026", s).value
        assert total == pytest.approx(net, abs=1.0)

    def test_scope_selector_has_something_to_switch(self):
        """The dashboard only offers a selector when a second scope exists."""
        from lib.india.dashboard_builder import build_india_dashboard
        cons = build_india_dashboard(get_fixture("corporate"), scope=Scope.CONSOLIDATED.value)
        sa = build_india_dashboard(get_fixture("corporate"), scope=Scope.STANDALONE.value)
        assert sa["available_scopes"] == ["CONSOLIDATED", "STANDALONE"]
        # Different bases must actually produce different numbers.
        assert cons["kpis"] != sa["kpis"] or cons["statements"] != sa["statements"]


# ── Aggregate coherence: currency and statement scope ─────────────────────

class TestAggregateCoherence:
    """An aggregate is only meaningful if its component lines are commensurable.

    These target ``total_debt``, which the fixture does not record, so the
    engine must derive it from its component lines and the guards apply.
    """

    @staticmethod
    def _tagged(metric_id: str, **fields):
        data = get_fixture("corporate")
        target = data.statements["balance_sheet"].get(metric_id, "FY2026")
        for key, value in fields.items():
            setattr(target, key, value)
        return data

    def test_baseline_aggregate_computes(self):
        r = _corporate_engine().calculate("total_debt", "FY2026")
        assert r.ok and r.value > 0

    def test_mixed_currency_sum_is_refused(self):
        data = self._tagged("long_term_borrowings", currency="USD")
        r = MetricEngine(data).calculate("total_debt", "FY2026")
        assert not r.ok and r.value is None
        assert "mixed currencies" in r.reason

    def test_mixed_scope_sum_is_refused(self):
        data = self._tagged("long_term_borrowings", statement_scope=Scope.STANDALONE.value)
        r = MetricEngine(data).calculate("total_debt", "FY2026")
        assert not r.ok and r.value is None
        assert "scope" in r.reason

    def test_scope_refusal_is_scoped_to_the_aggregate(self):
        """A non-member line must not void an aggregate it does not belong to."""
        data = self._tagged("inventory", statement_scope=Scope.STANDALONE.value)
        r = MetricEngine(data).calculate("total_debt", "FY2026")
        assert r.ok and r.value > 0

    def test_refusal_reason_is_reported_not_just_status(self):
        """Refusals must be explainable in the UI, not a bare status code."""
        data = self._tagged("long_term_borrowings", currency="USD")
        r = MetricEngine(data).calculate("total_debt", "FY2026")
        assert r.reason and "Inputs present but result not computable" not in r.reason

    def test_reported_subtotal_still_wins_over_derived(self):
        """A reported line is authoritative; the engine must not override it."""
        data = get_fixture("corporate")
        # Corrupt a component so the derived total would differ from the
        # subtotal the fixture actually reports.
        data.statements["balance_sheet"].get("short_term_borrowings", "FY2026").value = 1.0
        bs, _srcs, _scope = MetricEngine(data).resolve_input(
            "total_current_assets", "FY2026")
        assert bs == data.metric("total_current_assets", "FY2026").value


# ── Ratio denominators must be economically meaningful ────────────────────

class TestRatioDenominatorGuards:
    def test_zero_denominator_refused(self):
        from lib.metrics.engine import ratio_value
        value, reason = ratio_value(100.0, 0.0)
        assert value is None and "zero" in reason

    def test_negative_denominator_refused(self):
        from lib.metrics.engine import ratio_value
        value, reason = ratio_value(100.0, -50.0)
        assert value is None and "negative" in reason

    def test_negative_numerator_is_allowed(self):
        """A loss is a real value; the ratio is still meaningful."""
        from lib.metrics.engine import ratio_value
        value, reason = ratio_value(-100.0, 50.0)
        assert value == -2.0 and reason == ""

    def test_negative_denominator_refused_end_to_end(self):
        data = get_fixture("corporate")
        bs = data.statements["balance_sheet"]
        bs.get("total_current_liabilities", "FY2026").value = -40_000_000.0
        r = MetricEngine(data).calculate("current_ratio", "FY2026")
        assert not r.ok and "negative" in r.reason

    def test_negative_fcf_voids_ev_to_fcf(self):
        """EV/FCF against negative FCF is a nonsense multiple, not a negative one."""
        r = _corporate_engine().calculate("ev_fcf", "FY2026")
        assert r.value is None
        assert r.reason and "negative" in r.reason


# ── Known fixture defect: corporate balance sheet does not reconcile ──────

class TestFixtureIntegrity:
    """Pins a known, deliberately-unfixed defect in the corporate fixture.

    See the "KNOWN DEFECT" section of ``lib/india/fixtures.py``. These tests
    do not assert correctness -- they assert that the discrepancy is still
    exactly the documented one, so that rebalancing the fixture becomes a
    conscious decision with a visible KPI diff rather than a silent change.
    """

    P = "FY2026"
    G = 1_000_000_000

    def _delta(self, aggregate: str, components) -> int:
        e = MetricEngine(get_fixture("corporate"))
        reported = e.resolve_input(aggregate, self.P)[0]
        derived = sum(e.resolve_input(m, self.P)[0] or 0 for m in components)
        return reported - derived

    def test_current_assets_subtotal_gap_is_pinned(self):
        delta = self._delta("total_current_assets", (
            "cash", "bank_balances", "current_investments", "trade_receivables",
            "inventory", "other_current_assets"))
        assert delta == -0.3 * self.G, (
            "corporate current-asset subtotal gap changed; if this was fixed "
            "deliberately, update the KNOWN DEFECT note in lib/india/fixtures.py")

    def test_non_current_assets_subtotal_gap_is_pinned(self):
        delta = self._delta("total_non_current_assets", (
            "ppe", "cwip", "intangibles", "goodwill", "non_current_investments",
            "other_non_current_assets"))
        assert delta == -0.8 * self.G, (
            "corporate non-current-asset subtotal gap changed; if this was "
            "fixed deliberately, update the KNOWN DEFECT note")

    def test_balance_sheet_is_out_of_balance_by_a_known_amount(self):
        e = MetricEngine(get_fixture("corporate"))
        assets = e.resolve_input("total_assets", self.P)[0]
        liabilities = e.resolve_input("total_liabilities", self.P)[0]
        equity = e.resolve_input("total_equity", self.P)[0]
        assert assets - (liabilities + equity) == 22.2 * self.G, (
            "corporate balance sheet imbalance changed; if this was fixed "
            "deliberately, update the KNOWN DEFECT note")

    def test_liability_subtotals_are_internally_consistent(self):
        """The liability and equity sides were authored consistently.

        Only the asset side and the top-level identity are broken, which is
        what keeps this defect from contaminating debt and equity ratios.
        """
        assert self._delta("total_current_liabilities", (
            "trade_payables", "short_term_borrowings", "current_debt",
            "other_current_liabilities")) == 0
        assert self._delta("total_non_current_liabilities", (
            "long_term_borrowings", "other_non_current_liabilities")) == 0
        assert self._delta("total_equity", (
            "share_capital", "reserves_surplus", "minority_interest")) == 0
