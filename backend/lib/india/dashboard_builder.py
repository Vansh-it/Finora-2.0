"""India dashboard payload builder.

Transforms a CanonicalCompanyData snapshot into a single, schema-driven
dashboard payload consumed by the India frontend. Metric content is
entity-specific; visual components are shared with the US dashboard.

Money is formatted at the presentation edge only — payloads carry raw INR
values plus pre-formatted display strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from lib.core.canonical_models import CanonicalCompanyData, MetricStatus, Scope
from lib.core.entity_types import EntityType
from lib.core.money import (
    format_eps,
    format_inr,
    format_percent,
    format_ratio,
    format_years,
)
from lib.metrics.engine import MetricEngine
from lib.metrics.completeness import CompletenessEngine, CompletenessResult
from lib.india.models import IndiaDashboardSchema, schema_for, fixture_macro_strip
from lib.india.forensics import (
    DetectorStatus,
    earnings_quality_panel,
    forensic_model_suite,
)
from lib.india.detectors import run_corporate_detectors, run_bank_detectors, run_nbfc_detectors

_FORMATTERS = {
    "inr": format_inr,
    "percent": lambda v: format_percent(v),
    "ratio": lambda v: format_ratio(v),
    "eps": format_eps,
    "days": lambda v: format_years(v),
    "count": lambda v: "—" if v is None else f"{v:,.0f}",
}


def _fmt(value: Optional[float], formatting: str) -> str:
    fn = _FORMATTERS.get(formatting, format_inr)
    try:
        return fn(value)
    except (TypeError, ValueError):
        return "—"


@dataclass
class MetricCardData:
    """One rendered metric with full provenance for the evidence drawer."""

    metric_id: str
    display_name: str
    value: Optional[float]
    display_value: str
    status: str  # REPORTED | CALCULATED | DERIVED | MARKET_DATA | UNAVAILABLE
    unit_type: str
    formatting: str
    period: str
    formula: str = ""
    inputs: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "display_name": self.display_name,
            "value": self.value,
            "display_value": self.display_value,
            "status": self.status,
            "unit_type": self.unit_type,
            "formatting": self.formatting,
            "period": self.period,
            "formula": self.formula,
            "inputs": list(self.inputs),
            "source_ids": list(self.source_ids),
            "reason": self.reason,
            "unavailable": self.status == MetricStatus.UNAVAILABLE.value,
        }


def _ordered_sources(engine: MetricEngine, metric_id: str,
                     source_ids: list[str]) -> list[str]:
    """Order a metric's evidence trail by the registry's source ranking.

    Most-authoritative first, so the reader meets the filing before the
    investor-relations summary. Sources of unrecognised type are demoted, not
    dropped.
    """
    if not source_ids:
        return []
    types = {sid: engine.data.sources[sid].source_type
             for sid in source_ids if sid in engine.data.sources}
    return engine._registry.order_sources(metric_id, types)


def _card(engine: MetricEngine, metric_id: str, period: str,
          scope: str) -> MetricCardData:
    registry_metric = engine._registry.get(metric_id)
    if registry_metric is None:
        return MetricCardData(
            metric_id=metric_id, display_name=metric_id, value=None,
            display_value="—", status=MetricStatus.UNAVAILABLE.value,
            unit_type="MONEY", formatting="inr", period=period,
            reason="Unknown metric")
    result = engine.calculate(metric_id, period, scope)
    if result.ok:
        return MetricCardData(
            metric_id=metric_id, display_name=registry_metric.display_name,
            value=result.value, display_value=_fmt(result.value, registry_metric.formatting),
            status=result.status, unit_type=registry_metric.unit_type,
            formatting=registry_metric.formatting, period=period,
            formula=result.formula, inputs=list(result.inputs.keys()),
            source_ids=_ordered_sources(engine, metric_id, list(result.source_ids)))
    # Prefer a reported value recorded in data when engine calc is insufficient.
    m = engine.data.metric(metric_id, period)
    if m and m.is_available:
        return MetricCardData(
            metric_id=metric_id, display_name=registry_metric.display_name,
            value=m.value, display_value=_fmt(m.value, registry_metric.formatting),
            status=m.status, unit_type=registry_metric.unit_type,
            formatting=registry_metric.formatting, period=period,
            formula=m.formula, inputs=list(m.inputs),
            source_ids=_ordered_sources(engine, metric_id, list(m.source_ids)))
    return MetricCardData(
        metric_id=metric_id, display_name=registry_metric.display_name,
        value=None, display_value="—", status=MetricStatus.UNAVAILABLE.value,
        unit_type=registry_metric.unit_type, formatting=registry_metric.formatting,
        period=period,
        reason=result.reason or (m.reason if m else "Not available"))


def _statement_rows(data: CanonicalCompanyData, schema_statements: dict[str, list[str]],
                    statement_type: str, periods: list[str], scope: str) -> dict[str, Any]:
    line_items = schema_statements.get(statement_type, [])
    rows = []
    engine = MetricEngine(data)
    registry = engine._registry
    for mid in line_items:
        d = registry.get(mid)
        if d is None:
            continue
        values = []
        for p in periods:
            card = _card(engine, mid, p, scope)
            values.append({
                "display_value": card.display_value,
                "unavailable": card.status == MetricStatus.UNAVAILABLE.value,
                "reason": card.reason,
                "raw": card.value,
            })
        rows.append({
            "metric_id": mid,
            "label": d.display_name,
            "values": values,
            "is_total": mid.startswith("total_"),
            "formatting": d.formatting,
        })
    return {
        "statement_type": statement_type,
        "rows": rows,
        "periods": periods,
    }


def _spark(data: CanonicalCompanyData, metric_id: str, periods: list[str],
           scope: str) -> list[float]:
    engine = MetricEngine(data)
    out = []
    for p in periods:
        v = engine.resolve_input(metric_id, p, scope)[0]
        out.append(v if v is not None else 0.0)
    # all-zero/empty → empty sparkline (never fabricate shape)
    return out if any(v != 0 for v in out) else []


def _yoy_change(engine: MetricEngine, metric_id: str, period: str, scope: str) -> dict[str, Any]:
    prev_engine_val = None
    from lib.core.periods import previous_period
    prev = previous_period(period)
    cur = engine.resolve_input(metric_id, period, scope)[0]
    prev_v = engine.resolve_input(metric_id, prev, scope)[0] if prev else None
    if cur is None or prev_v in (None, 0):
        return {"value": "—", "direction": "flat"}
    from lib.metrics.engine import growth_pct
    g = growth_pct(cur, prev_v)
    if g is None:
        return {"value": "—", "direction": "flat"}
    return {
        "value": f"{g:+.1f}%",
        "direction": "up" if g > 0 else "down",
        "raw": g,
    }


def _ownership_payload(data: CanonicalCompanyData) -> dict[str, Any]:
    rows = []
    for o in sorted(data.ownership, key=lambda x: x.period):
        rows.append(o.to_dict())
    latest = rows[-1] if rows else None
    prev = rows[-2] if len(rows) >= 2 else None
    changes = {}
    if latest and prev:
        for key in ("promoter_pct", "promoter_pledge_pct", "fii_pct", "dii_pct",
                    "mutual_fund_pct", "public_pct"):
            if latest.get(key) is not None and prev.get(key) is not None:
                changes[key] = round(latest[key] - prev[key], 1)
    return {"rows": rows, "latest": latest, "yoy_changes": changes,
            "available": bool(rows)}


def build_india_dashboard(data: CanonicalCompanyData,
                          scope: str = Scope.CONSOLIDATED.value) -> dict[str, Any]:
    """Build the complete India dashboard payload for one entity."""
    entity = EntityType(data.identity.entity_type)
    schema = schema_for(entity)
    engine = MetricEngine(data)
    periods = sorted(data.period_labels(),
                     key=lambda p: data.periods[[x.label for x in data.periods].index(p)].fiscal_year)
    latest = periods[-1] if periods else ""

    # ── Header ──
    ident = data.identity
    md = data.market_data
    header = {
        "name": ident.name,
        "legal_name": ident.legal_name or ident.name,
        "nse_symbol": ident.nse_symbol,
        "bse_code": ident.bse_code,
        "isin": ident.isin,
        "cin": ident.cin,
        "primary_exchange": ident.primary_exchange,
        "sector": ident.sector,
        "industry": ident.industry,
        "description": ident.description,
        "fiscal_period": latest,
        "scope": scope,
        "reporting_standard": ident.reporting_standard,
        "currency": "INR",
        "country": ident.country,
        "price": md.price if md else None,
        "price_display": _fmt(md.price if md else None, "inr"),
        "price_change": md.percent_change if md else None,
        "price_change_display": (f"{md.percent_change:+.1f}%" if md and md.percent_change is not None else "—"),
        "market_cap": md.market_cap if md else None,
        "market_cap_display": _fmt(md.market_cap if md else None, "inr"),
        "market_data_status": md.data_status if md else "UNAVAILABLE",
        "is_fixture": md.is_fixture if md else True,
        "price_date": md.price_date if md else "",
    }

    # ── Overview KPIs ──
    kpis = []
    for mid in schema.overview_metrics:
        card = _card(engine, mid, latest, scope)
        kpis.append({
            **card.to_dict(),
            "spark": _spark(data, mid, periods, scope),
            "change": _yoy_change(engine, mid, latest, scope),
        })

    # ── Statements ──
    statements = {
        st: _statement_rows(data, schema.statements, st, periods, scope)
        for st in schema.statements
    }

    # ── Tabs ──
    tabs_payload: dict[str, Any] = {}
    for tab_name, metric_ids in schema.tab_metrics.items():
        cards = [_card(engine, mid, latest, scope) for mid in metric_ids]
        tabs_payload[tab_name.lower().replace(" ", "_")] = {
            "title": tab_name,
            "metrics": [c.to_dict() for c in cards],
        }

    # ── Ownership ──
    ownership = _ownership_payload(data)

    # ── Forensics ──
    if entity == EntityType.CORPORATE:
        detectors = run_corporate_detectors(engine, data, latest)
    elif entity == EntityType.BANK:
        detectors = run_bank_detectors(engine, data, latest)
    else:
        detectors = run_nbfc_detectors(engine, data, latest)
    models = forensic_model_suite(data, latest)
    eq = earnings_quality_panel(engine, latest) if entity == EntityType.CORPORATE else {"available": False, "signals": []}

    forensics = {
        "red_flags": [d.to_dict() for d in detectors],
        "active_flags": [d.to_dict() for d in detectors if d.fired],
        "models": models,
        "earnings_quality": eq,
    }

    # ── Valuation ──
    valuation_metrics = [
        _card(engine, mid, latest, scope).to_dict()
        for mid in schema.tab_metrics.get("VALUATION", [])
    ]
    valuation = {
        "market_data": md.to_dict() if md else None,
        "metrics": valuation_metrics,
        "fixture_warning": md.is_fixture if md else True,
    }

    # ── Macro strip ──
    macro = fixture_macro_strip().to_dict()

    # ── Sources ──
    sources = [s.to_dict() for s in data.sources.values()]

    # ── Completeness ──
    comp_engine = CompletenessEngine(
        categories={
            "income_statement": "Financial Statements",
            "balance_sheet": "Balance Sheet",
            "cash_flow": "Cash Flow",
            "growth": "Growth",
            "profitability": "Profitability",
            "liquidity": "Liquidity",
            "leverage": "Leverage",
            "efficiency": "Efficiency",
            "capital_allocation": "Capital Allocation",
            "ownership": "Ownership",
            "asset_quality": "Asset Quality",
            "funding": "Funding",
            "capital": "Capital",
            "valuation": "Valuation",
        })
    completeness = comp_engine.assess_with_engine(
        data, schema.expected_metric_ids(), entity, latest)
    coverage_payload = {
        **completeness.to_dict(),
        "missing_recovery": [m.to_dict() for m in completeness.missing_metrics],
    }

    return {
        "version": "india-1",
        "is_fixture": True,
        "fixture_notice": "Development fixture data — not live company research",
        "entity_type": entity.value,
        "header": header,
        "periods": periods,
        "latest_period": latest,
        "scope": scope,
        "available_scopes": _available_scopes(data),
        "kpis": kpis,
        "statements": statements,
        "tabs": tabs_payload,
        "ownership": ownership,
        "forensics": forensics,
        "valuation": valuation,
        "macro": macro,
        "sources": sources,
        "completeness": coverage_payload,
        "research_context": _research_context(data, entity, completeness),
    }


def _available_scopes(data: CanonicalCompanyData) -> list[str]:
    scopes = set()
    for stmt in data.statements.values():
        for m in stmt.metrics.values():
            scopes.add(m.statement_scope)
    return sorted(scopes)


def _research_context(data: CanonicalCompanyData, entity: EntityType,
                      completeness: CompletenessResult) -> dict[str, Any]:
    """Structured IndiaResearchContext for the existing chat intelligence.

    Raw values + metadata only — no UI-rendered strings.
    """
    engine = MetricEngine(data)
    metrics: dict[str, Any] = {}
    for p in data.period_labels():
        pmetrics: dict[str, Any] = {}
        for stmt in data.statements.values():
            for mid in {m.metric_id for m in stmt.metrics.values()}:
                m = data.metric(mid, p)
                if m and m.is_available:
                    pmetrics[mid] = {
                        "value": m.value,
                        "status": m.status,
                        "source_ids": m.source_ids,
                        "statement_scope": m.statement_scope,
                    }
        metrics[p] = pmetrics
    return {
        "company": data.identity.to_dict(),
        "entity_type": entity.value,
        "periods": data.period_labels(),
        "metrics": metrics,
        "ownership": [o.to_dict() for o in data.ownership],
        "forensics": {
            "active_flags": [
                d.to_dict() for d in run_corporate_detectors(engine, data, data.period_labels()[-1])
                if d.fired
            ] if entity == EntityType.CORPORATE else [],
        },
        "coverage": {
            "coverage_pct": completeness.coverage_pct,
            "available": completeness.available,
            "expected": completeness.expected,
        },
        "sources": [s.to_dict() for s in data.sources.values()],
    }
