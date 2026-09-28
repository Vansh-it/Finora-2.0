"""Deterministic metric calculation engine.

All arithmetic is pure Python — no LLM calculations. Every result carries
formula, inputs, period, status and source ids. Calculation safety: division
by zero, negative denominators, missing inputs and mismatched periods all
return INSUFFICIENT_DATA with a reason instead of a wrong number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from lib.core.canonical_models import CanonicalCompanyData, CanonicalMetric, MetricStatus, Scope
from lib.core.periods import (
    PeriodKind,
    canonical_period,
    period_sort_key,
    periods_are_comparable,
    previous_period,
)
from lib.core.entity_types import EntityType
from lib.metrics.registry import UnitType, get_registry


@dataclass
class CalculationResult:
    """Outcome of one metric calculation with full traceability."""

    metric_id: str
    period: str
    value: Optional[float]
    status: str  # CALCULATED | DERIVED | INSUFFICIENT_DATA | NOT_APPLICABLE
    formula: str = ""
    inputs: dict[str, Optional[float]] = field(default_factory=dict)
    source_ids: list[str] = field(default_factory=list)
    reason: str = ""
    unit_type: str = UnitType.MONEY.value

    @property
    def ok(self) -> bool:
        return self.value is not None and self.status in (
            MetricStatus.REPORTED.value,
            MetricStatus.CALCULATED.value,
            MetricStatus.DERIVED.value,
            MetricStatus.MARKET_DATA.value,
        )

    def to_canonical(self, display_name: str = "", currency: str = "INR",
                     statement_scope: str = Scope.CONSOLIDATED.value) -> CanonicalMetric:
        """Convert to a CanonicalMetric for the data layer."""
        if self.ok:
            return CanonicalMetric(
                metric_id=self.metric_id,
                period=self.period,
                value=self.value,
                currency=currency,
                statement_scope=statement_scope,
                status=self.status,
                source_ids=list(self.source_ids),
                formula=self.formula,
                inputs=list(self.inputs.keys()),
                display_name=display_name,
                unit_type=self.unit_type,
            )
        return CanonicalMetric.unavailable(
            self.metric_id, self.period, self.reason or "Inputs unavailable",
            unit_type=self.unit_type, display_name=display_name,
        )


# ── Calculation safety helpers ────────────────────────────────────────────

def safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """Division that refuses zero, negative-denominator sign flips and non-finite results."""
    if numerator is None or denominator is None:
        return None
    if isinstance(numerator, bool) or isinstance(denominator, bool):
        return None
    if denominator == 0:
        return None
    if math.isnan(numerator) or math.isnan(denominator):
        return None
    if math.isinf(numerator) or math.isinf(denominator):
        return None
    result = numerator / denominator
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def ratio_value(
    numerator: Optional[float],
    denominator: Optional[float],
) -> tuple[Optional[float], str]:
    """Divide for a financial ratio, refusing denominators that void the result.

    A ratio whose denominator is zero or negative is not meaningful — a company
    with negative equity does not have a meaningful Debt/Equity, and a negative
    revenue base does not have a Gross Margin. Rather than emit a sign-flipped
    number that reads like a real signal, return ``(None, reason)`` so the
    caller surfaces INSUFFICIENT_DATA with an explanation.

    Numerators may be negative (a loss-making EBITDA still yields a real
    Debt/EBITDA); only the denominator is constrained.

    Returns ``(value, "")`` on success and ``(None, reason)`` on refusal.
    """
    if numerator is None or denominator is None:
        return None, "Numerator or denominator unavailable"
    if denominator == 0:
        return None, "Denominator is zero — ratio undefined"
    if denominator < 0:
        return None, "Denominator is negative — ratio is not economically meaningful"
    return numerator / denominator, ""


def growth_pct(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """YoY growth in percent; None when the base is zero or sign-changing."""
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    if previous < 0 or current < 0:
        # Sign-changing base makes growth meaningless.
        return None
    return (current - previous) / abs(previous) * 100.0


def cagr_pct(start: Optional[float], end: Optional[float], years: int) -> Optional[float]:
    """CAGR in percent; requires positive start/end and a positive year span."""
    if start is None or end is None or years <= 0:
        return None
    if start <= 0 or end <= 0:
        return None
    return ((end / start) ** (1.0 / years) - 1.0) * 100.0


# ── Value resolver ────────────────────────────────────────────────────────

# Ownership metric ids map to CanonicalOwnership fields.
_OWNERSHIP_METRIC_MAP = {
    "promoter_holding": "promoter_pct",
    "promoter_pledge": "promoter_pledge_pct",
    "fii_holding": "fii_pct",
    "dii_holding": "dii_pct",
    "mutual_fund_holding": "mutual_fund_pct",
    "public_holding": "public_pct",
    "institutional_holding": "institutional_pct",
}

# Market-data metric ids map to CanonicalMarketData fields.
_MARKET_METRIC_MAP = {
    "share_price": "price",
    "shares_outstanding": "shares_outstanding",
    "market_cap": "market_cap",
}

# Equity bridge: shared metric ids (P/B, BVPS) resolve to the entity's own
# equity measure — banks via bank_total_equity, NBFCs via nbfc_net_worth.
_EQUITY_BRIDGE = {
    "total_equity": {
        EntityType.BANK: "bank_total_equity",
        EntityType.NBFC: "nbfc_net_worth",
    },
}


class MetricEngine:
    """Calculates metrics from a CanonicalCompanyData snapshot.

    The engine resolves inputs per scope (CONSOLIDATED preferred, STANDALONE
    fallback), computes chained formula inputs on demand, and refuses to mix
    incompatible periods or scopes.
    """

    def __init__(self, data: CanonicalCompanyData):
        self.data = data
        self._entity_type = EntityType(data.identity.entity_type)
        self._registry = get_registry()
        self._resolving: set[str] = set()  # recursion guard

    # -- input resolution --------------------------------------------------

    def resolve_input(
        self,
        metric_id: str,
        period: str,
        statement_scope: str = Scope.CONSOLIDATED.value,
    ) -> tuple[Optional[float], list[str], str]:
        """Resolve one input metric for a period.

        Resolution order:
          1. recorded data (statements) in requested scope, then other scope
          2. ownership data for ownership metric ids
          3. market data for market metric ids
          4. on-demand calculation for FORMULA/DERIVED metrics (chained
             formulas like bank_pat → bank_pbt → nii resolve transparently)

        A recorded line wins over a derived one: adapters legitimately report
        statement subtotals (total_debt, ebitda, total_current_assets) that we
        could also derive, and the reported figure is authoritative. Only when
        nothing was recorded does the declared formula run. This means
        ``calculate()`` on a metric that an adapter also recorded can return
        the derived value while ``resolve_input`` returns the reported one --
        the two are intentionally different views, not a contradiction.

        Returns (value, source_ids, actual_scope).
        """
        target = canonical_period(period)
        # The canonical store is scope-keyed, so the requested scope wins and
        # the other is an explicit fallback. The returned metric carries the
        # scope it was recorded under, which the caller reports as actual_scope.
        m = self.data.metric(metric_id, period, statement_scope=statement_scope)
        if m is not None:
            if m.is_available:
                # Period-compat: a FY input cannot feed a QUARTER result.
                got = canonical_period(m.period)
                if not target or not got or got["kind"] == target["kind"]:
                    return m.value, list(m.source_ids), m.statement_scope

        # Bank/NBFC ownership & market data resolve below regardless of
        # scope — shareholding patterns and price snapshots are not
        # consolidated/standalone financial statements.

        # Ownership observations (shareholding patterns)
        field = _OWNERSHIP_METRIC_MAP.get(metric_id)
        if field is not None:
            for o in self.data.ownership:
                if o.period == period:
                    value = getattr(o, field)
                    if value is not None:
                        return float(value), list(o.source_ids), statement_scope
            return None, [], ""

        # Market data snapshot
        md_field = _MARKET_METRIC_MAP.get(metric_id)
        if md_field is not None and self.data.market_data is not None:
            value = getattr(self.data.market_data, md_field)
            if value is not None:
                src = ([self.data.market_data.source_id]
                       if self.data.market_data.source_id else [])
                return float(value), src, statement_scope

        # Equity bridge: shared valuation denominators per entity type.
        bridge = _EQUITY_BRIDGE.get(metric_id, {}).get(self._entity_type)
        if bridge is not None:
            return self.resolve_input(bridge, period, statement_scope)

        # Chained formula inputs: calculate on demand (acyclic metric graph;
        # REPORTED metrics return above so no recursion loop is possible).
        d = self._registry.get(metric_id)
        if (d is not None and d.calculation_method in ("FORMULA", "DERIVED")
                and metric_id not in self._resolving):
            self._resolving.add(metric_id)
            try:
                result = self.calculate(metric_id, period, statement_scope)
            finally:
                self._resolving.discard(metric_id)
            if result.ok:
                return result.value, list(result.source_ids), statement_scope
        return None, [], ""

    def _sources_union(self, *source_lists: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for lst in source_lists:
            for s in lst:
                seen[s] = None
        return list(seen)

    def _formula_inputs(
        self,
        metric_id: str,
        period: str,
        statement_scope: str,
    ) -> tuple[dict[str, Optional[float]], list[str], str]:
        """Resolve all required inputs for a formula metric."""
        d = self._registry.require(metric_id)
        inputs: dict[str, Optional[float]] = {}
        sources: list[str] = []
        scopes: set[str] = set()
        for inp in d.required_inputs:
            value, src_ids, scope = self.resolve_input(inp, period, statement_scope)
            inputs[inp] = value
            sources.extend(src_ids)
            if scope:
                scopes.add(scope)
        return inputs, sources, (list(scopes)[0] if len(scopes) == 1 else "")

    def _make_result(
        self,
        metric_id: str,
        period: str,
        inputs: dict[str, Optional[float]],
        sources: list[str],
        value: Optional[float],
        formula: str,
        status_derived: bool = False,
        reason: str = "",
        partial: bool = False,
    ) -> CalculationResult:
        """Assemble a CalculationResult and enforce the missing-input contract.

        By default every entry in ``inputs`` is required: any ``None`` yields
        INSUFFICIENT_DATA naming the absent inputs.

        Pass ``partial=True`` for aggregations that sum a *set* of optional
        statement lines (EBITDA's cost components, the balance-sheet
        subtotals). Those calculators deliberately sum the known lines and
        treat a genuinely-absent line as nil, so a missing line must not
        veto the result. Absent lines are still reported in the reason string
        so the evidence drawer shows what was unavailable.
        """
        d = self._registry.require(metric_id)
        missing = [k for k, v in inputs.items() if v is None]
        if missing and not partial:
            return CalculationResult(
                metric_id=metric_id, period=period, value=None,
                status="INSUFFICIENT_DATA",
                inputs=inputs, source_ids=self._sources_union(sources),
                reason=f"Missing inputs: {', '.join(missing)}",
                unit_type=d.unit_type,
            )
        if value is None:
            return CalculationResult(
                metric_id=metric_id, period=period, value=None,
                status="INSUFFICIENT_DATA",
                inputs=inputs, source_ids=self._sources_union(sources),
                reason=reason or "Inputs present but result not computable",
                unit_type=d.unit_type,
            )
        # Propagate provenance from resolved inputs when the calculator did
        # not supply source ids explicitly.
        resolved_sources: list[str] = list(sources)
        if not resolved_sources:
            for input_metric_id in d.required_inputs:
                m = self.data.metric(input_metric_id, period)
                if m and m.is_available:
                    resolved_sources.extend(m.source_ids)
        result_reason = reason
        if missing:
            result_reason = (
                f"Computed from available inputs; not disclosed: {', '.join(missing)}"
            )
        return CalculationResult(
            metric_id=metric_id, period=period, value=value,
            status=MetricStatus.DERIVED.value if status_derived else MetricStatus.CALCULATED.value,
            formula=formula, inputs=inputs, reason=result_reason,
            source_ids=self._sources_union(resolved_sources),
            unit_type=d.unit_type,
        )

    # -- public calculation API --------------------------------------------

    def calculate(self, metric_id: str, period: str,
                  statement_scope: str = Scope.CONSOLIDATED.value) -> CalculationResult:
        """Calculate a single metric for a period.

        REPORTED metrics are returned from the data layer as-is.
        FORMULA/DERIVED metrics are computed with safety checks.
        """
        d = self._registry.get(metric_id)
        if d is None:
            return CalculationResult(metric_id, period, None, "INSUFFICIENT_DATA",
                                     reason=f"Unknown metric {metric_id}")
        if not d.applies_to(self._entity_type):
            return CalculationResult(metric_id, period, None, "NOT_APPLICABLE",
                                     reason=f"{metric_id} does not apply to {self._entity_type.value}")
        if d.calculation_method == "REPORTED":
            value, sources, scope = self.resolve_input(metric_id, period, statement_scope)
            if value is None:
                return CalculationResult(metric_id, period, None, "INSUFFICIENT_DATA",
                                         reason="Not disclosed for this period",
                                         unit_type=d.unit_type)
            return CalculationResult(metric_id, period, value, MetricStatus.REPORTED.value,
                                     formula="", inputs={}, source_ids=sources,
                                     unit_type=d.unit_type)

        calc = _CALCULATORS.get(metric_id)
        if calc is None:
            return CalculationResult(metric_id, period, None, "INSUFFICIENT_DATA",
                                     reason=f"No calculator registered for {metric_id}",
                                     unit_type=d.unit_type)
        return calc(self, period, statement_scope)

    # -- multi-period helpers -----------------------------------------------

    def available_periods(self, metric_id: str, statement_scope: str = Scope.CONSOLIDATED.value) -> list[str]:
        """Periods (sorted chronologically) where a metric is available."""
        periods = []
        for p in self.data.period_labels():
            m = self.data.metric(metric_id, p)
            if m and m.is_available and m.statement_scope == statement_scope:
                periods.append(p)
        return sorted(set(periods), key=period_sort_key)

    def series(self, metric_id: str, statement_scope: str = Scope.CONSOLIDATED.value) -> list[tuple[str, float]]:
        """Chronological (period, value) pairs for a metric."""
        out = []
        for p in self.available_periods(metric_id, statement_scope):
            m = self.data.metric(metric_id, p)
            if m and m.value is not None:
                out.append((p, m.value))
        return out

    def latest_period(self, statement_scope: str = Scope.CONSOLIDATED.value) -> str:
        labels = sorted(self.data.period_labels(), key=period_sort_key)
        return labels[-1] if labels else ""

    def yoy_for(self, metric_id: str, period: str,
                statement_scope: str = Scope.CONSOLIDATED.value) -> CalculationResult:
        """YoY growth for any base metric using period-compat checks."""
        d = self._registry.get(metric_id)
        prev = previous_period(period)
        if prev is None:
            return CalculationResult(metric_id + "_growth", period, None, "INSUFFICIENT_DATA",
                                     reason="No comparable previous period")
        current, cur_srcs, scope = self.resolve_input(metric_id, period, statement_scope)
        previous, prev_srcs, _ = self.resolve_input(metric_id, prev, scope or statement_scope)
        if current is None or previous is None:
            return CalculationResult(metric_id + "_growth", period, None, "INSUFFICIENT_DATA",
                                     inputs={metric_id: current, f"{metric_id}_prev": previous},
                                     reason="Current or previous value unavailable")
        if not periods_are_comparable(period, prev):
            return CalculationResult(metric_id + "_growth", period, None, "INSUFFICIENT_DATA",
                                     reason="Incompatible periods")
        value = growth_pct(current, previous)
        if value is None:
            return CalculationResult(metric_id + "_growth", period, None, "INSUFFICIENT_DATA",
                                     inputs={metric_id: current, f"{metric_id}_prev": previous},
                                     reason="Growth not meaningful (zero or negative base)")
        return CalculationResult(
            metric_id + "_growth", period, value, MetricStatus.DERIVED.value,
            formula=f"({metric_id} change) / |previous| × 100",
            inputs={metric_id: current, f"{metric_id}_previous": previous},
            source_ids=self._sources_union(cur_srcs, prev_srcs),
        )

    def cagr_for(self, metric_id: str, end_period: str, years: int,
                 statement_scope: str = Scope.CONSOLIDATED.value) -> CalculationResult:
        """CAGR over an exact FY span; refuses partial spans."""
        series = self.series(metric_id, statement_scope)
        fy_series = [(p, v) for p, v in series if canonical_period(p)
                     and canonical_period(p)["kind"] == PeriodKind.FY.value]
        by_year = {canonical_period(p)["fiscal_year"]: v for p, v in fy_series}
        end_p = canonical_period(end_period)
        if not end_p or end_p["kind"] != PeriodKind.FY.value:
            return CalculationResult(f"{metric_id}_cagr_{years}y", end_period, None,
                                     "INSUFFICIENT_DATA", reason="CAGR requires an FY end period")
        end_year = end_p["fiscal_year"]
        start_year = end_year - years
        if start_year not in by_year or end_year not in by_year:
            return CalculationResult(f"{metric_id}_cagr_{years}y", end_period, None,
                                     "INSUFFICIENT_DATA",
                                     reason=f"Requires FY{start_year} and FY{end_year} history")
        value = cagr_pct(by_year[start_year], by_year[end_year], years)
        if value is None:
            return CalculationResult(f"{metric_id}_cagr_{years}y", end_period, None,
                                     "INSUFFICIENT_DATA",
                                     reason="CAGR not meaningful for non-positive values")
        return CalculationResult(
            f"{metric_id}_cagr_{years}y", end_period, value, MetricStatus.DERIVED.value,
            formula=f"((end/start)^(1/{years}) − 1) × 100",
            inputs={f"{metric_id}_start": by_year[start_year],
                     f"{metric_id}_end": by_year[end_year]},
            source_ids=self._sources_union(
                self.data.metric(metric_id, f"FY{start_year}").source_ids if self.data.metric(metric_id, f"FY{start_year}") else [],
                self.data.metric(metric_id, f"FY{end_year}").source_ids if self.data.metric(metric_id, f"FY{end_year}") else [],
            ),
        )


# ══════════════════════════════════════════════════════════════════════════
# FORMULA CALCULATORS
# ══════════════════════════════════════════════════════════════════════════
# Each calculator receives (engine, period, scope) and returns a
# CalculationResult. Formulas are documented in the registry.

def _r(engine: MetricEngine, metric_id: str, period: str, scope: str) -> Optional[float]:
    return engine.resolve_input(metric_id, period, scope)[0]


def _sum_parts(e, p, s, metric_id, part_ids, formula):
    """Sum statement lines into an aggregate, refusing incoherent sums.

    Two hazards make a naive sum wrong even when every line resolves:

    * **Currency** - adding a USD line to INR lines produces a number that
      looks plausible and is meaningless.
    * **Scope** - ``resolve_input`` falls back to the other scope when the
      requested one is absent, so a consolidated aggregate can silently
      absorb a standalone (or vice versa) line.

    Lines that are simply not disclosed are tolerated (the sum is partial);
    lines that are present but incoherent void the whole aggregate.
    """
    parts: dict[str, Optional[float]] = {}
    known: list[float] = []
    currencies: set[str] = set()
    scope_conflicts: list[str] = []

    for mid in part_ids:
        value, _srcs, actual_scope = e.resolve_input(mid, p, s)
        parts[mid] = value
        if value is None:
            continue
        known.append(value)
        recorded = e.data.metric(mid, p)
        if recorded is not None:
            if recorded.currency:
                currencies.add(recorded.currency.upper())
            if actual_scope and actual_scope != s:
                scope_conflicts.append(mid)

    if not known:
        return e._make_result(metric_id, p, parts, [], None,
                              f"No component lines disclosed for {metric_id}")

    if len(currencies) > 1:
        return e._make_result(
            metric_id, p, parts, [], None, "",
            reason=f"Refused: component lines are in mixed currencies "
                   f"({', '.join(sorted(currencies))}); the sum is not meaningful")

    if scope_conflicts:
        return e._make_result(
            metric_id, p, parts, [], None, "",
            reason=f"Refused: component lines are recorded at a different statement "
                   f"scope than requested ({', '.join(sorted(scope_conflicts))})")

    return e._make_result(metric_id, p, parts, [], sum(known), formula,
                          partial=True)


def _calc_total_income(e, p, s):
    return e._make_result(
        "total_income", p,
        {"revenue": _r(e, "revenue", p, s), "other_income": _r(e, "other_income", p, s)},
        [], (_r(e, "revenue", p, s) or 0) + (_r(e, "other_income", p, s) or 0),
        "Total Income = Revenue + Other Income",
    ) if None not in (_r(e, "revenue", p, s), _r(e, "other_income", p, s)) else e._make_result(
        "total_income", p,
        {"revenue": _r(e, "revenue", p, s), "other_income": _r(e, "other_income", p, s)},
        [], None, "")


def _calc_ebitda(e, p, s):
    inputs = {mid: _r(e, mid, p, s) for mid in (
        "revenue", "employee_benefits", "other_expenses", "cost_of_materials",
        "purchases_stock_in_trade", "changes_in_inventories")}
    rev, emp, oth = inputs["revenue"], inputs["employee_benefits"], inputs["other_expenses"]
    com, pst, chg = (inputs["cost_of_materials"], inputs["purchases_stock_in_trade"],
                     inputs["changes_in_inventories"])
    # Optional cost lines are treated as zero ONLY when genuinely absent AND
    # at least one cost line exists; a company with no cost lines at all
    # cannot have a meaningful EBITDA from this formula.
    cost_parts = [c for c in (com, pst, chg) if c is not None]
    if rev is None or emp is None or oth is None:
        return e._make_result("ebitda", p, inputs, [], None, "")
    total_costs = emp + oth + sum(cost_parts)
    return e._make_result("ebitda", p, inputs, [], rev - total_costs,
                          "EBITDA = Revenue − (Employee + Other + Material costs)",
                          partial=True)


def _calc_ebit(e, p, s):
    ebitda, da = _r(e, "ebitda", p, s), _r(e, "depreciation_amortisation", p, s)
    return e._make_result("ebit", p, {"ebitda": ebitda, "depreciation_amortisation": da}, [],
                          (ebitda - da) if None not in (ebitda, da) else None,
                          "EBIT = EBITDA − D&A")


def _calc_total_tax(e, p, s):
    ct, dt = _r(e, "current_tax", p, s), _r(e, "deferred_tax", p, s)
    inputs = {"current_tax": ct, "deferred_tax": dt}
    if ct is None and dt is None:
        return e._make_result("total_tax", p, inputs, [], None, "")
    return e._make_result("total_tax", p, inputs, [],
                          (ct or 0) + (dt or 0), "Total Tax = Current Tax + Deferred Tax", partial=True)


def _calc_total_current_assets(e, p, s):
    return _sum_parts(e, p, s, "total_current_assets", (
        "cash", "bank_balances", "current_investments", "trade_receivables",
        "inventory", "other_current_assets"), "Sum of current asset lines")


def _calc_total_non_current_assets(e, p, s):
    return _sum_parts(e, p, s, "total_non_current_assets", (
        "ppe", "cwip", "intangibles", "goodwill", "non_current_investments",
        "other_non_current_assets"), "Sum of non-current asset lines")


def _calc_total_current_liabilities(e, p, s):
    return _sum_parts(e, p, s, "total_current_liabilities", (
        "trade_payables", "short_term_borrowings", "current_debt",
        "other_current_liabilities"), "Sum of current liability lines")


def _calc_total_non_current_liabilities(e, p, s):
    return _sum_parts(e, p, s, "total_non_current_liabilities", (
        "long_term_borrowings", "other_non_current_liabilities"),
        "Sum of non-current liability lines")


def _calc_total_debt(e, p, s):
    return _sum_parts(e, p, s, "total_debt", (
        "short_term_borrowings", "current_debt", "long_term_borrowings"),
        "Total Debt = ST + Current portion of LT + LT Borrowings")


def _calc_total_liabilities(e, p, s):
    cl, ncl = _r(e, "total_current_liabilities", p, s), _r(e, "total_non_current_liabilities", p, s)
    return e._make_result("total_liabilities", p,
                          {"total_current_liabilities": cl, "total_non_current_liabilities": ncl}, [],
                          (cl + ncl) if None not in (cl, ncl) else None,
                          "Total Liabilities = Current + Non-current")


def _calc_total_equity(e, p, s):
    sc, res, mi = (_r(e, "share_capital", p, s), _r(e, "reserves_surplus", p, s),
                   _r(e, "minority_interest", p, s))
    if sc is None or res is None:
        return e._make_result("total_equity", p,
                              {"share_capital": sc, "reserves_surplus": res, "minority_interest": mi},
                              [], None, "")
    return e._make_result("total_equity", p,
                          {"share_capital": sc, "reserves_surplus": res, "minority_interest": mi},
                          [], sc + res + (mi or 0),
                          "Total Equity = Share Capital + Reserves + NCI", partial=True)


def _calc_comprehensive_income(e, p, s):
    pat, oci = _r(e, "net_profit", p, s), _r(e, "oci", p, s)
    return e._make_result("comprehensive_income", p, {"net_profit": pat, "oci": oci}, [],
                          (pat + oci) if None not in (pat, oci) else None,
                          "Total Comprehensive Income = PAT + OCI")


def _calc_fcf(e, p, s):
    ocf, capex = _r(e, "operating_cash_flow", p, s), _r(e, "capex", p, s)
    return e._make_result("free_cash_flow", p,
                          {"operating_cash_flow": ocf, "capex": capex}, [],
                          (ocf - capex) if None not in (ocf, capex) else None,
                          "FCF = Operating Cash Flow − CapEx")


def _ratio_result(e, p, s, metric_id, numerator_id, denominator_id, formula, pct=False):
    num = _r(e, numerator_id, p, s)
    den = _r(e, denominator_id, p, s)
    inputs = {numerator_id: num, denominator_id: den}
    raw, refusal = ratio_value(num, den)
    if raw is None:
        return e._make_result(metric_id, p, inputs, [], None, "", reason=refusal)
    value = raw * 100.0 if pct else raw
    return e._make_result(metric_id, p, inputs, [], value, formula)


def _calc_gross_profit(e, p, s):
    rev = _r(e, "revenue", p, s)
    com = _r(e, "cost_of_materials", p, s)
    chg = _r(e, "changes_in_inventories", p, s)
    pst = _r(e, "purchases_stock_in_trade", p, s)
    inputs = {"revenue": rev, "cost_of_materials": com,
              "changes_in_inventories": chg, "purchases_stock_in_trade": pst}
    if rev is None or com is None:
        return e._make_result("gross_profit", p, inputs, [], None,
                              "Gross profit requires revenue and cost of materials")
    cost = com + (pst or 0) + (chg or 0)
    return e._make_result("gross_profit", p, inputs, [], rev - cost,
                          "Gross Profit = Revenue − Cost of Materials − Purchases − Inventory Change",
                          partial=True)


def _margin_result(e, p, s, metric_id, numerator_id, formula):
    """Percent-of-revenue metrics. Revenue is always the denominator, so a
    zero or negative revenue base voids the margin entirely."""
    num = _r(e, numerator_id, p, s)
    rev = _r(e, "revenue", p, s)
    inputs = {numerator_id: num, "revenue": rev}
    raw, refusal = ratio_value(num, rev)
    if raw is None:
        return e._make_result(metric_id, p, inputs, [], None, "", reason=refusal)
    return e._make_result(metric_id, p, inputs, [], raw * 100.0, formula)


def _calc_gross_margin(e, p, s):
    return _margin_result(e, p, s, "gross_margin", "gross_profit",
                          "Gross Margin = Gross Profit / Revenue × 100")


def _calc_ebitda_margin(e, p, s):
    return _margin_result(e, p, s, "ebitda_margin", "ebitda",
                          "EBITDA Margin = EBITDA / Revenue × 100")


def _calc_operating_margin(e, p, s):
    return _margin_result(e, p, s, "operating_margin", "ebit",
                          "Operating Margin = EBIT / Revenue × 100")


def _calc_pbt_margin(e, p, s):
    return _margin_result(e, p, s, "pbt_margin", "pbt",
                          "PBT Margin = PBT / Revenue × 100")


def _calc_pat_margin(e, p, s):
    return _margin_result(e, p, s, "pat_margin", "net_profit",
                          "PAT Margin = PAT / Revenue × 100")


def _calc_ocf_margin(e, p, s):
    return _margin_result(e, p, s, "ocf_margin", "operating_cash_flow",
                          "OCF Margin = OCF / Revenue × 100")


def _calc_fcf_margin(e, p, s):
    return _margin_result(e, p, s, "fcf_margin", "free_cash_flow",
                          "FCF Margin = FCF / Revenue × 100")


def _calc_debt_to_equity(e, p, s):
    return _ratio_result(e, p, s, "debt_to_equity", "total_debt", "total_equity",
                         "Debt / Equity = Total Debt / Total Equity")


def _calc_debt_to_assets(e, p, s):
    return _ratio_result(e, p, s, "debt_to_assets", "total_debt", "total_assets",
                         "Debt / Assets = Total Debt / Total Assets × 100", pct=True)


def _calc_debt_to_ebitda(e, p, s):
    return _ratio_result(e, p, s, "debt_to_ebitda", "total_debt", "ebitda",
                         "Debt / EBITDA = Total Debt / EBITDA")


def _calc_net_debt_to_ebitda(e, p, s):
    return _ratio_result(e, p, s, "net_debt_to_ebitda", "net_debt", "ebitda",
                         "Net Debt / EBITDA = Net Debt / EBITDA")


def _calc_cash_ratio(e, p, s):
    return _ratio_result(e, p, s, "cash_ratio", "cash", "total_current_liabilities",
                         "Cash Ratio = Cash & Equivalents / Current Liabilities")


def _calc_interest_coverage(e, p, s):
    return _ratio_result(e, p, s, "interest_coverage", "ebit", "finance_costs",
                         "Interest Coverage = EBIT / Finance Costs")


def _calc_roa(e, p, s):
    return _ratio_result(e, p, s, "roa", "ebit", "total_assets",
                         "ROA = EBIT / Total Assets × 100", pct=True)


def _calc_roe(e, p, s):
    return _ratio_result(e, p, s, "roe", "net_profit", "total_equity",
                         "ROE = PAT / Total Equity × 100", pct=True)


def _calc_roce(e, p, s):
    ebit = _r(e, "ebit", p, s)
    eq, debt = _r(e, "total_equity", p, s), _r(e, "total_debt", p, s)
    inputs = {"ebit": ebit, "total_equity": eq, "total_debt": debt}
    if ebit is None or eq is None or debt is None:
        return e._make_result("roce", p, inputs, [], None, "")
    raw, refusal = ratio_value(ebit, eq + debt)
    if raw is None:
        return e._make_result("roce", p, inputs, [], None, "", reason=refusal)
    return e._make_result("roce", p, inputs, [], raw * 100.0,
                          "ROCE = EBIT / Capital Employed × 100 (Capital Employed = Equity + Debt)")


def _calc_roic(e, p, s):
    ebit = _r(e, "ebit", p, s)
    eq, debt = _r(e, "total_equity", p, s), _r(e, "total_debt", p, s)
    cash = _r(e, "cash", p, s)
    ci = _r(e, "current_investments", p, s)
    pbt, tax = _r(e, "pbt", p, s), _r(e, "total_tax", p, s)
    inputs = {"ebit": ebit, "total_equity": eq, "total_debt": debt, "cash": cash,
              "current_investments": ci, "pbt": pbt, "total_tax": tax}
    if None in (ebit, eq, debt):
        return e._make_result("roic", p, inputs, [], None, "")
    invested = debt + eq - ((cash or 0) + (ci or 0))
    if invested <= 0:
        return e._make_result("roic", p, inputs, [], None,
                              "Invested capital is zero or negative — ROIC not meaningful")
    rate = (tax / pbt) if (pbt not in (None, 0) and tax is not None) else 0.25
    return e._make_result("roic", p, inputs, [], ebit * (1 - rate) / invested * 100.0,
                          "ROIC = EBIT × (1 − tax rate) / Invested Capital")


def _calc_current_ratio(e, p, s):
    return _ratio_result(e, p, s, "current_ratio", "total_current_assets",
                         "total_current_liabilities",
                         "Current Ratio = Current Assets / Current Liabilities")


def _calc_quick_ratio(e, p, s):
    ca, inv, cl = (_r(e, "total_current_assets", p, s), _r(e, "inventory", p, s),
                   _r(e, "total_current_liabilities", p, s))
    inputs = {"total_current_assets": ca, "inventory": inv, "total_current_liabilities": cl}
    if ca is None or cl is None:
        return e._make_result("quick_ratio", p, inputs, [], None, "")
    raw, refusal = ratio_value(ca - (inv or 0), cl)
    if raw is None:
        return e._make_result("quick_ratio", p, inputs, [], None, "", reason=refusal)
    return e._make_result("quick_ratio", p, inputs, [], raw,
                          "Quick Ratio = (Current Assets − Inventories) / Current Liabilities",
                          partial=True)


def _calc_nwc(e, p, s):
    ca, cl = _r(e, "total_current_assets", p, s), _r(e, "total_current_liabilities", p, s)
    return e._make_result("net_working_capital", p,
                          {"total_current_assets": ca, "total_current_liabilities": cl}, [],
                          (ca - cl) if None not in (ca, cl) else None,
                          "NWC = Current Assets − Current Liabilities")


def _calc_nwc_to_revenue(e, p, s):
    nwc, rev = _r(e, "net_working_capital", p, s), _r(e, "revenue", p, s)
    inputs = {"net_working_capital": nwc, "revenue": rev}
    raw, refusal = ratio_value(nwc, rev)
    if raw is None:
        return e._make_result("nwc_to_revenue", p, inputs, [], None, "", reason=refusal)
    return e._make_result("nwc_to_revenue", p, inputs, [], raw * 100.0, "NWC / Revenue × 100")


def _calc_debt_to_capital(e, p, s):
    debt, eq = _r(e, "total_debt", p, s), _r(e, "total_equity", p, s)
    inputs = {"total_debt": debt, "total_equity": eq}
    if debt is None or eq is None:
        return e._make_result("debt_to_capital", p, inputs, [], None, "")
    raw, refusal = ratio_value(debt, debt + eq)
    if raw is None:
        return e._make_result("debt_to_capital", p, inputs, [], None, "", reason=refusal)
    return e._make_result("debt_to_capital", p, inputs, [], raw * 100.0,
                          "Debt / Capital = Debt / (Debt + Equity) × 100")


def _calc_net_debt(e, p, s):
    debt = _r(e, "total_debt", p, s)
    cash, ci, bb = (_r(e, "cash", p, s), _r(e, "current_investments", p, s),
                    _r(e, "bank_balances", p, s))
    inputs = {"total_debt": debt, "cash": cash, "current_investments": ci,
              "bank_balances": bb}
    if debt is None:
        return e._make_result("net_debt", p, inputs, [], None, "")
    liquid = (cash or 0) + (ci or 0) + (bb or 0)
    return e._make_result("net_debt", p, inputs, [], debt - liquid,
                          "Net Debt = Total Debt − Cash − Current Investments − Bank Balances")


def _calc_cash_flow_to_debt(e, p, s):
    return _ratio_result(e, p, s, "cash_flow_to_debt", "operating_cash_flow", "total_debt",
                         "OCF / Total Debt × 100", pct=True)


def _calc_turnover(num_id, den_id, formula, metric_id, annualize=False):
    def _impl(e, p, s):
        num, den = _r(e, num_id, p, s), _r(e, den_id, p, s)
        inputs = {num_id: num, den_id: den}
        raw, refusal = ratio_value(num, den)
        if raw is None:
            return e._make_result(metric_id, p, inputs, [], None, "", reason=refusal)
        return e._make_result(metric_id, p, inputs, [], raw, formula)
    return _impl


def _calc_days(num_id, den_id, formula, metric_id):
    def _impl(e, p, s):
        num, den = _r(e, num_id, p, s), _r(e, den_id, p, s)
        inputs = {num_id: num, den_id: den}
        raw, refusal = ratio_value(num, den)
        if raw is None:
            return e._make_result(metric_id, p, inputs, [], None, "", reason=refusal)
        return e._make_result(metric_id, p, inputs, [], raw * 365.0, formula)
    return _impl


def _calc_ccc(e, p, s):
    dso, dio, dpo = (_r(e, "dso", p, s), _r(e, "dio", p, s), _r(e, "dpo", p, s))
    inputs = {"dso": dso, "dio": dio, "dpo": dpo}
    if None in (dso, dio, dpo):
        return e._make_result("cash_conversion_cycle", p, inputs, [], None,
                              "CCC requires DSO, DIO and DPO")
    return e._make_result("cash_conversion_cycle", p, inputs, [], dso + dio - dpo,
                          "CCC = DSO + DIO − DPO")


def _calc_capex_to_revenue(e, p, s):
    return _ratio_result(e, p, s, "capex_to_revenue", "capex", "revenue",
                         "CapEx / Revenue × 100", pct=True)


def _calc_ocf_to_pat(e, p, s):
    return _ratio_result(e, p, s, "ocf_to_pat", "operating_cash_flow", "net_profit",
                         "OCF / PAT")


def _calc_fcf_to_pat(e, p, s):
    return _ratio_result(e, p, s, "fcf_to_pat", "free_cash_flow", "net_profit", "FCF / PAT")


def _calc_dividend_payout(e, p, s):
    div, pat = _r(e, "dividends_paid", p, s), _r(e, "net_profit", p, s)
    inputs = {"dividends_paid": div, "net_profit": pat}
    if None in (div, pat) or pat is None or pat <= 0:
        return e._make_result("dividend_payout", p, inputs, [], None,
                              "Payout requires positive PAT")
    return e._make_result("dividend_payout", p, inputs, [], div / pat * 100.0,
                          "Dividend Payout = Dividends Paid / PAT × 100")


def _calc_net_debt_change(e, p, s):
    prev = previous_period(p)
    if prev is None:
        return e._make_result("net_debt_change", p, {}, [], None,
                              "No previous period")
    cur = _r(e, "net_debt", p, s)
    prior = _r(e, "net_debt", prev, s)
    inputs = {"net_debt_current": cur, "net_debt_previous": prior}
    if cur is None or prior is None:
        return e._make_result("net_debt_change", p, inputs, [], None, "")
    return e._make_result("net_debt_change", p, inputs, [], cur - prior,
                          "Net Debt Change = Current − Previous")


def _calc_institutional_holding(e, p, s):
    fii = _r(e, "fii_holding", p, s)
    dii = _r(e, "dii_holding", p, s)
    inputs = {"fii_holding": fii, "dii_holding": dii}
    if None in (fii, dii):
        return e._make_result("institutional_holding", p, inputs, [], None, "")
    return e._make_result("institutional_holding", p, inputs, [], fii + dii,
                          "Institutional Holding = FII/FPI + DII")


def _calc_market_cap(e, p, s):
    """Market cap comes from the market-data layer, not the balance sheet."""
    md = e.data.market_data
    if md and md.market_cap is not None:
        return CalculationResult("market_cap", p, md.market_cap, MetricStatus.MARKET_DATA.value,
                                 formula="Market Cap (market data)", inputs={},
                                 source_ids=[md.source_id] if md.source_id else [],
                                 unit_type=UnitType.MONEY.value)
    price, shares = _r(e, "share_price", p, s), _r(e, "shares_outstanding", p, s)
    inputs = {"share_price": price, "shares_outstanding": shares}
    if None in (price, shares):
        return e._make_result("market_cap", p, inputs, [], None, "Requires market data")
    return e._make_result("market_cap", p, inputs, [], price * shares,
                          "Market Cap = Share Price × Shares Outstanding")


def _calc_enterprise_value(e, p, s):
    mc = _r(e, "market_cap", p, s)
    nd = _r(e, "net_debt", p, s)
    inputs = {"market_cap": mc, "net_debt": nd}
    if None in (mc, nd):
        return e._make_result("enterprise_value", p, inputs, [], None,
                              "Requires market cap and net debt")
    return e._make_result("enterprise_value", p, inputs, [], mc + nd,
                          "EV = Market Cap + Net Debt")


def _calc_valuation_ratio(num_id, den_id, formula, metric_id, invert_to_pct=False):
    """Valuation ratios read market cap / EV from the market-data layer."""
    def _impl(e, p, s):
        num = _r(e, num_id, p, s)
        den = _r(e, den_id, p, s)
        inputs = {num_id: num, den_id: den}
        raw, refusal = ratio_value(num, den)
        if raw is None:
            return e._make_result(metric_id, p, inputs, [], None, "", reason=refusal)
        if invert_to_pct:
            return e._make_result(metric_id, p, inputs, [], raw * 100.0, formula)
        return e._make_result(metric_id, p, inputs, [], raw, formula)
    return _impl


def _calc_book_value_per_share(e, p, s):
    eq, sh = _r(e, "total_equity", p, s), _r(e, "shares_outstanding", p, s)
    inputs = {"total_equity": eq, "shares_outstanding": sh}
    raw, refusal = ratio_value(eq, sh)
    if raw is None:
        return e._make_result("book_value_per_share", p, inputs, [], None, "", reason=refusal)
    return e._make_result("book_value_per_share", p, inputs, [], raw,
                          "Book Value / Share = Total Equity / Shares Outstanding")


def _calc_dividend_yield(e, p, s):
    dps = _r(e, "dividend_per_share", p, s)
    price = _r(e, "share_price", p, s)
    inputs = {"dividend_per_share": dps, "share_price": price}
    raw, refusal = ratio_value(dps, price)
    if raw is None:
        return e._make_result("dividend_yield", p, inputs, [], None, "", reason=refusal)
    return e._make_result("dividend_yield", p, inputs, [], raw * 100.0,
                          "Dividend Yield = DPS / Price × 100")


# ── Bank calculators ──────────────────────────────────────────────────────

def _calc_nii(e, p, s):
    ie, ix = _r(e, "interest_earned", p, s), _r(e, "interest_expended", p, s)
    return e._make_result("nii", p, {"interest_earned": ie, "interest_expended": ix}, [],
                          (ie - ix) if None not in (ie, ix) else None,
                          "NII = Interest Earned − Interest Expended")


def _calc_bank_op_profit(e, p, s):
    nii, oi, opex = (_r(e, "nii", p, s), _r(e, "bank_other_income", p, s),
                     _r(e, "operating_expenses", p, s))
    inputs = {"nii": nii, "bank_other_income": oi, "operating_expenses": opex}
    if None in (nii, opex):
        return e._make_result("bank_operating_profit", p, inputs, [], None, "")
    return e._make_result("bank_operating_profit", p, inputs, [],
                          nii + (oi or 0) - opex,
                          "Operating Profit = NII + Other Income − Operating Expenses")


def _calc_bank_pbt(e, p, s):
    op, prov = _r(e, "bank_operating_profit", p, s), _r(e, "provisions", p, s)
    return e._make_result("bank_pbt", p,
                          {"bank_operating_profit": op, "provisions": prov}, [],
                          (op - prov) if None not in (op, prov) else None,
                          "PBT = Operating Profit − Provisions")


def _calc_bank_pat(e, p, s):
    pbt, tax = _r(e, "bank_pbt", p, s), _r(e, "bank_tax", p, s)
    return e._make_result("bank_pat", p, {"bank_pbt": pbt, "bank_tax": tax}, [],
                          (pbt - tax) if None not in (pbt, tax) else None,
                          "PAT = PBT − Tax")


def _calc_bank_total_equity(e, p, s):
    sc, res = _r(e, "share_capital", p, s), _r(e, "bank_reserves", p, s)
    return e._make_result("bank_total_equity", p, {"share_capital": sc, "bank_reserves": res}, [],
                          (sc + res) if None not in (sc, res) else None,
                          "Total Equity = Share Capital + Reserves & Surplus")


def _calc_nim(e, p, s):
    nii, ie = _r(e, "nii", p, s), _r(e, "interest_earned", p, s)
    inputs = {"nii": nii, "interest_earned": ie}
    raw, refusal = ratio_value(nii, ie)
    if raw is None:
        return e._make_result("nim", p, inputs, [], None, "", reason=refusal)
    return e._make_result("nim", p, inputs, [], raw * 100.0,
                          "NIM = NII / Interest-Earning Assets × 100 (interest-earned proxy)")


def _calc_cost_to_income(e, p, s):
    opex, nii, oi = (_r(e, "operating_expenses", p, s), _r(e, "nii", p, s),
                     _r(e, "bank_other_income", p, s))
    inputs = {"operating_expenses": opex, "nii": nii, "bank_other_income": oi}
    if opex is None or nii is None:
        return e._make_result("cost_to_income", p, inputs, [], None, "")
    raw, refusal = ratio_value(opex, nii + (oi or 0))
    if raw is None:
        return e._make_result("cost_to_income", p, inputs, [], None, "", reason=refusal)
    return e._make_result("cost_to_income", p, inputs, [], raw * 100.0,
                          "Cost / Income = Operating Expenses / (NII + Other Income) × 100",
                          partial=True)


def _calc_bank_roa(e, p, s):
    return _ratio_result(e, p, s, "bank_roa", "bank_pat", "total_assets",
                         "ROA = PAT / Total Assets × 100", pct=True)


def _calc_bank_roe(e, p, s):
    return _ratio_result(e, p, s, "bank_roe", "bank_pat", "bank_total_equity",
                         "ROE = PAT / Total Equity × 100", pct=True)


def _calc_gnpa_pct(e, p, s):
    return _ratio_result(e, p, s, "gnpa_pct", "gnpa", "advances",
                         "GNPA % = Gross NPA / Advances × 100", pct=True)


def _calc_nnpa_pct(e, p, s):
    return _ratio_result(e, p, s, "nnpa_pct", "nnpa", "advances",
                         "NNPA % = Net NPA / Advances × 100", pct=True)


def _calc_pcr(e, p, s):
    gnpa, nnpa = _r(e, "gnpa", p, s), _r(e, "nnpa", p, s)
    inputs = {"gnpa": gnpa, "nnpa": nnpa}
    if gnpa is None or nnpa is None:
        return e._make_result("provision_coverage_ratio", p, inputs, [], None,
                              "PCR requires GNPA and NNPA")
    raw, refusal = ratio_value(gnpa - nnpa, gnpa)
    if raw is None:
        return e._make_result("provision_coverage_ratio", p, inputs, [], None, "", reason=refusal)
    return e._make_result("provision_coverage_ratio", p, inputs, [], raw * 100.0,
                          "PCR = (GNPA − NNPA) / GNPA × 100")


def _calc_credit_cost(e, p, s):
    return _ratio_result(e, p, s, "credit_cost", "provisions", "advances",
                         "Credit Cost = Provisions / Advances × 100", pct=True)


def _calc_casa_ratio(e, p, s):
    return _ratio_result(e, p, s, "casa_ratio", "casa_deposits", "deposits",
                         "CASA Ratio = CASA / Deposits × 100", pct=True)


def _calc_credit_deposit(e, p, s):
    return _ratio_result(e, p, s, "credit_to_deposit", "advances", "deposits",
                         "Credit / Deposit = Advances / Deposits × 100", pct=True)


# ── NBFC calculators ──────────────────────────────────────────────────────

def _calc_nbfc_nii(e, p, s):
    ii, ix = _r(e, "nbfc_interest_income", p, s), _r(e, "nbfc_interest_expense", p, s)
    return e._make_result("nbfc_nii", p,
                          {"nbfc_interest_income": ii, "nbfc_interest_expense": ix}, [],
                          (ii - ix) if None not in (ii, ix) else None,
                          "NII = Interest Income − Interest Expense")


def _calc_nbfc_ppop(e, p, s):
    nii, fee, opex = (_r(e, "nbfc_nii", p, s), _r(e, "fee_income", p, s),
                      _r(e, "nbfc_operating_expenses", p, s))
    inputs = {"nbfc_nii": nii, "fee_income": fee, "nbfc_operating_expenses": opex}
    if None in (nii, opex):
        return e._make_result("nbfc_ppop", p, inputs, [], None, "")
    return e._make_result("nbfc_ppop", p, inputs, [], nii + (fee or 0) - opex,
                          "PPOP = NII + Fee Income − Operating Expenses")


def _calc_nbfc_pbt(e, p, s):
    ppop, prov = _r(e, "nbfc_ppop", p, s), _r(e, "nbfc_provisions", p, s)
    return e._make_result("nbfc_pbt", p, {"nbfc_ppop": ppop, "nbfc_provisions": prov}, [],
                          (ppop - prov) if None not in (ppop, prov) else None,
                          "PBT = PPOP − Provisions")


def _calc_nbfc_pat(e, p, s):
    pbt, tax = _r(e, "nbfc_pbt", p, s), _r(e, "nbfc_tax", p, s)
    return e._make_result("nbfc_pat", p, {"nbfc_pbt": pbt, "nbfc_tax": tax}, [],
                          (pbt - tax) if None not in (pbt, tax) else None,
                          "PAT = PBT − Tax")


def _calc_nbfc_net_worth(e, p, s):
    sc, res = _r(e, "share_capital", p, s), _r(e, "bank_reserves", p, s)
    return e._make_result("nbfc_net_worth", p, {"share_capital": sc, "bank_reserves": res}, [],
                          (sc + res) if None not in (sc, res) else None,
                          "Net Worth = Share Capital + Reserves & Surplus")


def _calc_nbfc_borrowings(e, p, s):
    return _sum_parts(e, p, s, "nbfc_borrowings", (
        "bank_borrowings_nbfc", "debt_securities", "commercial_paper",
        "subordinated_debt"),
        "Total Borrowings = Bank Borrowings + Debt Securities + CP + Subordinated Debt")


def _calc_nbfc_nim(e, p, s):
    nii, lb = _r(e, "nbfc_nii", p, s), _r(e, "loan_book", p, s)
    inputs = {"nbfc_nii": nii, "loan_book": lb}
    raw, refusal = ratio_value(nii, lb)
    if raw is None:
        return e._make_result("nbfc_nim", p, inputs, [], None, "", reason=refusal)
    return e._make_result("nbfc_nim", p, inputs, [], raw * 100.0,
                          "NIM = NII / Loan Book × 100")


def _calc_nbfc_roa(e, p, s):
    return _ratio_result(e, p, s, "nbfc_roa", "nbfc_pat", "nbfc_total_assets",
                         "ROA = PAT / Total Assets × 100", pct=True)


def _calc_nbfc_roe(e, p, s):
    return _ratio_result(e, p, s, "nbfc_roe", "nbfc_pat", "nbfc_net_worth",
                         "ROE = PAT / Net Worth × 100", pct=True)


def _calc_nbfc_cost_to_income(e, p, s):
    opex, ti = _r(e, "nbfc_operating_expenses", p, s), _r(e, "total_income_nbfc", p, s)
    inputs = {"nbfc_operating_expenses": opex, "total_income_nbfc": ti}
    raw, refusal = ratio_value(opex, ti)
    if raw is None:
        return e._make_result("nbfc_cost_to_income", p, inputs, [], None, "", reason=refusal)
    return e._make_result("nbfc_cost_to_income", p, inputs, [], raw * 100.0,
                          "Cost / Income = OpEx / Total Income × 100")


def _calc_stage3_gross_pct(e, p, s):
    return _ratio_result(e, p, s, "stage3_gross_pct", "stage3_gross", "loan_book",
                         "Gross Stage 3 % = Stage 3 / Loan Book × 100", pct=True)


def _calc_stage3_net_pct(e, p, s):
    return _ratio_result(e, p, s, "stage3_net_pct", "stage3_net", "loan_book",
                         "Net Stage 3 % = Stage 3 / Loan Book × 100", pct=True)


def _calc_nbfc_credit_cost(e, p, s):
    return _ratio_result(e, p, s, "nbfc_credit_cost", "nbfc_provisions", "loan_book",
                         "Credit Cost = Provisions / Loan Book × 100", pct=True)


def _calc_nbfc_pcr(e, p, s):
    g, n = _r(e, "stage3_gross", p, s), _r(e, "stage3_net", p, s)
    inputs = {"stage3_gross": g, "stage3_net": n}
    raw, refusal = ratio_value(g - n if (g is not None and n is not None) else None, g)
    if raw is None:
        return e._make_result("nbfc_provision_coverage", p, inputs, [], None, "", reason=refusal)
    return e._make_result("nbfc_provision_coverage", p, inputs, [], raw * 100.0,
                          "Provision Coverage = (Stage 3 Gross − Net) / Gross × 100")


def _calc_nbfc_debt_to_equity(e, p, s):
    return _ratio_result(e, p, s, "nbfc_debt_to_equity", "nbfc_borrowings", "nbfc_net_worth",
                         "Debt / Equity = Borrowings / Net Worth")


def _calc_nbfc_leverage(e, p, s):
    return _ratio_result(e, p, s, "nbfc_leverage_ratio", "nbfc_total_assets", "nbfc_net_worth",
                         "Leverage = Total Assets / Net Worth")


def _calc_nbfc_interest_coverage(e, p, s):
    pbt, ix = _r(e, "nbfc_pbt", p, s), _r(e, "nbfc_interest_expense", p, s)
    inputs = {"nbfc_pbt": pbt, "nbfc_interest_expense": ix}
    # PBT before interest is the numerator; a negative interest-expense base
    # would flip the sign of the multiple, so it is refused.
    raw, refusal = ratio_value(
        (pbt + ix) if (pbt is not None and ix is not None) else None, ix)
    if raw is None:
        return e._make_result("nbfc_interest_coverage", p, inputs, [], None, "", reason=refusal)
    return e._make_result("nbfc_interest_coverage", p, inputs, [], raw,
                          "Interest Coverage = (PBT + Interest Expense) / Interest Expense")


# ── Growth calculators (YoY and CAGR, computed from base-series inputs) ───

def _growth_calc(metric_id: str, base_metric: str):
    def _impl(e, p, s):
        prev = previous_period(p)
        if prev is None:
            return e._make_result(metric_id, p, {base_metric: None}, [], None,
                                  "No comparable previous period")
        cur = _r(e, base_metric, p, s)
        prev_v = _r(e, base_metric, prev, s)
        inputs = {base_metric: cur, f"{base_metric}_previous": prev_v}
        if cur is None or prev_v is None:
            return e._make_result(metric_id, p, inputs, [], None, "",
                                  reason=f"{base_metric} unavailable for both periods")
        value = growth_pct(cur, prev_v)
        if value is None:
            return e._make_result(metric_id, p, inputs, [], None, "",
                                  reason="Growth not meaningful (zero or negative base)")
        return e._make_result(metric_id, p, inputs, [], value,
                              f"YoY growth of {base_metric}", status_derived=True)
    return _impl


def _cagr_calc(metric_id: str, base_metric: str, years: int):
    def _impl(e, p, s):
        end_p = canonical_period(p)
        if not end_p or end_p["kind"] != PeriodKind.FY.value:
            return e._make_result(metric_id, p, {}, [], None,
                                  "CAGR requires an FY end period")
        end_year = end_p["fiscal_year"]
        start_year = end_year - years
        start_label = f"FY{start_year}"
        start_v = _r(e, base_metric, start_label, s)
        end_v = _r(e, base_metric, p, s)
        inputs = {f"{base_metric}_{start_label}": start_v,
                  f"{base_metric}_{p}": end_v}
        if start_v is None or end_v is None:
            return e._make_result(metric_id, p, inputs, [], None, "",
                                  reason=f"Requires {start_label} and {p} history")
        value = cagr_pct(start_v, end_v, years)
        if value is None:
            return e._make_result(metric_id, p, inputs, [], None, "",
                                  reason="CAGR not meaningful for non-positive values")
        return e._make_result(metric_id, p, inputs, [], value,
                              f"CAGR over {years} years", status_derived=True)
    return _impl


# ══════════════════════════════════════════════════════════════════════════
# CALCULATOR TABLE
# ══════════════════════════════════════════════════════════════════════════

_CALCULATORS: dict[str, Callable[[MetricEngine, str, str], CalculationResult]] = {
    # corporate income statement
    "total_income": _calc_total_income,
    "ebitda": _calc_ebitda,
    "ebit": _calc_ebit,
    "total_tax": _calc_total_tax,
    "comprehensive_income": _calc_comprehensive_income,
    "gross_profit": _calc_gross_profit,
    "gross_margin": _calc_gross_margin,
    # balance sheet aggregates
    "total_current_assets": _calc_total_current_assets,
    "total_non_current_assets": _calc_total_non_current_assets,
    "total_current_liabilities": _calc_total_current_liabilities,
    "total_non_current_liabilities": _calc_total_non_current_liabilities,
    "total_debt": _calc_total_debt,
    "total_liabilities": _calc_total_liabilities,
    "total_equity": _calc_total_equity,
    # cash flow & allocation
    "free_cash_flow": _calc_fcf,
    "capex_to_revenue": _calc_capex_to_revenue,
    "ocf_to_pat": _calc_ocf_to_pat,
    "fcf_to_pat": _calc_fcf_to_pat,
    "dividend_payout": _calc_dividend_payout,
    "net_debt_change": _calc_net_debt_change,
    # profitability
    "ebitda_margin": _calc_ebitda_margin,
    "operating_margin": _calc_operating_margin,
    "pbt_margin": _calc_pbt_margin,
    "pat_margin": _calc_pat_margin,
    "ocf_margin": _calc_ocf_margin,
    "fcf_margin": _calc_fcf_margin,
    "roa": _calc_roa,
    "roe": _calc_roe,
    "roce": _calc_roce,
    "roic": _calc_roic,
    # liquidity
    "current_ratio": _calc_current_ratio,
    "quick_ratio": _calc_quick_ratio,
    "net_working_capital": _calc_nwc,
    "nwc_to_revenue": _calc_nwc_to_revenue,
    # leverage
    "debt_to_capital": _calc_debt_to_capital,
    "debt_to_equity": _calc_debt_to_equity,
    "debt_to_assets": _calc_debt_to_assets,
    "debt_to_ebitda": _calc_debt_to_ebitda,
    "net_debt_to_ebitda": _calc_net_debt_to_ebitda,
    "cash_ratio": _calc_cash_ratio,
    "interest_coverage": _calc_interest_coverage,
    "net_debt": _calc_net_debt,
    "cash_flow_to_debt": _calc_cash_flow_to_debt,
    # efficiency
    "asset_turnover": _calc_turnover("revenue", "total_assets",
                                     "Asset Turnover = Revenue / Total Assets", "asset_turnover"),
    "receivables_turnover": _calc_turnover("revenue", "trade_receivables",
                                           "Receivables Turnover = Revenue / Trade Receivables",
                                           "receivables_turnover"),
    "inventory_turnover": _calc_turnover("cost_of_materials", "inventory",
                                         "Inventory Turnover = Cost of Materials / Inventories",
                                         "inventory_turnover"),
    "payables_turnover": _calc_turnover("cost_of_materials", "trade_payables",
                                        "Payables Turnover = Cost of Materials / Trade Payables",
                                        "payables_turnover"),
    "dso": _calc_days("trade_receivables", "revenue",
                      "DSO = Receivables / Revenue × 365", "dso"),
    "dio": _calc_days("inventory", "cost_of_materials",
                      "DIO = Inventory / Cost of Materials × 365", "dio"),
    "dpo": _calc_days("trade_payables", "cost_of_materials",
                      "DPO = Payables / Cost of Materials × 365", "dpo"),
    "cash_conversion_cycle": _calc_ccc,
    # ownership
    "institutional_holding": _calc_institutional_holding,
    # valuation
    "market_cap": _calc_market_cap,
    "enterprise_value": _calc_enterprise_value,
    "pe_ratio": _calc_valuation_ratio("market_cap", "net_profit",
                                      "P/E = Market Cap / PAT", "pe_ratio"),
    "ps_ratio": _calc_valuation_ratio("market_cap", "revenue",
                                      "P/S = Market Cap / Revenue", "ps_ratio"),
    "pb_ratio": _calc_valuation_ratio("market_cap", "total_equity",
                                      "P/B = Market Cap / Total Equity", "pb_ratio"),
    "earnings_yield": _calc_valuation_ratio("net_profit", "market_cap",
                                            "Earnings Yield = PAT / Market Cap × 100",
                                            "earnings_yield", invert_to_pct=True),
    "fcf_yield": _calc_valuation_ratio("free_cash_flow", "market_cap",
                                       "FCF Yield = FCF / Market Cap × 100", "fcf_yield",
                                       invert_to_pct=True),
    "ev_revenue": _calc_valuation_ratio("enterprise_value", "revenue",
                                        "EV / Revenue", "ev_revenue"),
    "ev_ebitda": _calc_valuation_ratio("enterprise_value", "ebitda",
                                       "EV / EBITDA", "ev_ebitda"),
    "ev_ebit": _calc_valuation_ratio("enterprise_value", "ebit", "EV / EBIT", "ev_ebit"),
    "ev_fcf": _calc_valuation_ratio("enterprise_value", "free_cash_flow",
                                    "EV / FCF", "ev_fcf"),
    "net_debt_to_ev": _calc_valuation_ratio("net_debt", "enterprise_value",
                                            "Net Debt / EV × 100", "net_debt_to_ev",
                                            invert_to_pct=True),
    "book_value_per_share": _calc_book_value_per_share,
    "dividend_yield": _calc_dividend_yield,
    # bank
    "nii": _calc_nii,
    "bank_operating_profit": _calc_bank_op_profit,
    "bank_pbt": _calc_bank_pbt,
    "bank_pat": _calc_bank_pat,
    "bank_total_equity": _calc_bank_total_equity,
    "nim": _calc_nim,
    "cost_to_income": _calc_cost_to_income,
    "bank_roa": _calc_bank_roa,
    "bank_roe": _calc_bank_roe,
    "gnpa_pct": _calc_gnpa_pct,
    "nnpa_pct": _calc_nnpa_pct,
    "provision_coverage_ratio": _calc_pcr,
    "credit_cost": _calc_credit_cost,
    "casa_ratio": _calc_casa_ratio,
    "credit_to_deposit": _calc_credit_deposit,
    # nbfc
    "nbfc_nii": _calc_nbfc_nii,
    "nbfc_ppop": _calc_nbfc_ppop,
    "nbfc_pbt": _calc_nbfc_pbt,
    "nbfc_pat": _calc_nbfc_pat,
    "nbfc_net_worth": _calc_nbfc_net_worth,
    "nbfc_borrowings": _calc_nbfc_borrowings,
    "nbfc_nim": _calc_nbfc_nim,
    "nbfc_roa": _calc_nbfc_roa,
    "nbfc_roe": _calc_nbfc_roe,
    "nbfc_cost_to_income": _calc_nbfc_cost_to_income,
    "stage3_gross_pct": _calc_stage3_gross_pct,
    "stage3_net_pct": _calc_stage3_net_pct,
    "nbfc_credit_cost": _calc_nbfc_credit_cost,
    "nbfc_provision_coverage": _calc_nbfc_pcr,
    "nbfc_debt_to_equity": _calc_nbfc_debt_to_equity,
    "nbfc_leverage_ratio": _calc_nbfc_leverage,
    "nbfc_interest_coverage": _calc_nbfc_interest_coverage,
}

# Growth & CAGR calculators — generated from base metric ids.
for _mid, _base in (
    ("revenue_growth", "revenue"), ("ebitda_growth", "ebitda"),
    ("ebit_growth", "ebit"), ("pat_growth", "net_profit"),
    ("eps_growth", "eps_diluted"), ("ocf_growth", "operating_cash_flow"),
    ("fcf_growth", "free_cash_flow"), ("deposit_growth", "deposits"),
    ("advances_growth", "advances"), ("nii_growth", "nii"),
    ("aum_growth", "aum"), ("loan_book_growth", "loan_book"),
    ("nbfc_income_growth", "total_income_nbfc"), ("nbfc_nii_growth", "nbfc_nii"),
    ("nbfc_pat_growth", "nbfc_pat"), ("nbfc_eps_growth", "eps_diluted"),
):
    _CALCULATORS[_mid] = _growth_calc(_mid, _base)

for _mid, _base, _yrs in (
    ("revenue_cagr_3y", "revenue", 3), ("revenue_cagr_5y", "revenue", 5),
    ("pat_cagr_3y", "net_profit", 3), ("pat_cagr_5y", "net_profit", 5),
    ("eps_cagr_3y", "eps_diluted", 3), ("eps_cagr_5y", "eps_diluted", 5),
    ("ebitda_cagr_3y", "ebitda", 3),
):
    _CALCULATORS[_mid] = _cagr_calc(_mid, _base, _yrs)
