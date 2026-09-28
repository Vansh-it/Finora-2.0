"""Canonical financial data model.

The single representation all region adapters populate and all dashboards
consume. Never connect dashboard components to exchange-specific field names.

Key rules:
  - Unavailable data is `value=None` + `status=UNAVAILABLE` + a reason.
    Zero is NEVER used to represent missing data.
  - Every value carries provenance via `source_ids`.
  - Statements/ownership/market data are plain serializable dataclasses so
    payloads are JSON-safe for the frontend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class MetricStatus(str, Enum):
    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    DERIVED = "DERIVED"
    MARKET_DATA = "MARKET_DATA"
    UNAVAILABLE = "UNAVAILABLE"


class Scope(str, Enum):
    CONSOLIDATED = "CONSOLIDATED"
    STANDALONE = "STANDALONE"


# Preferred scope when a caller does not state one. Consolidated is the
# default reporting basis for essentially every dataset Finora ingests, so it
# must win ties.
_SCOPE_ORDER = (Scope.CONSOLIDATED.value, Scope.STANDALONE.value)


class AuditStatus(str, Enum):
    AUDITED = "AUDITED"
    UNAUDITED = "UNAUDITED"


@dataclass
class CanonicalMetric:
    """One financial observation with full provenance."""

    metric_id: str
    period: str  # canonical period label, e.g. "FY2026", "Q2 FY2027"
    value: Optional[float] = None  # full numeric INR (or ratio); None = unavailable
    currency: str = "INR"
    period_type: str = "FY"  # FY | QUARTER | HALF_YEAR | NINE_MONTH | TTM
    cumulative: bool = False  # True for YTD observations
    statement_scope: str = Scope.CONSOLIDATED.value
    audit_status: str = AuditStatus.AUDITED.value
    status: str = MetricStatus.REPORTED.value
    source_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0
    reason: str = ""  # required when status == UNAVAILABLE
    formula: str = ""  # for CALCULATED / DERIVED
    inputs: list[str] = field(default_factory=list)  # input metric_ids
    display_name: str = ""
    unit_type: str = "MONEY"  # MONEY | RATIO | PERCENT | PER_SHARE | COUNT

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "period": self.period,
            "value": self.value,
            "currency": self.currency,
            "period_type": self.period_type,
            "cumulative": self.cumulative,
            "statement_scope": self.statement_scope,
            "audit_status": self.audit_status,
            "status": self.status,
            "source_ids": list(self.source_ids),
            "confidence": self.confidence,
            "reason": self.reason,
            "formula": self.formula,
            "inputs": list(self.inputs),
            "display_name": self.display_name,
            "unit_type": self.unit_type,
        }

    @property
    def is_available(self) -> bool:
        return self.value is not None and self.status != MetricStatus.UNAVAILABLE.value

    @classmethod
    def unavailable(
        cls,
        metric_id: str,
        period: str,
        reason: str,
        unit_type: str = "MONEY",
        statement_scope: str = Scope.CONSOLIDATED.value,
        display_name: str = "",
    ) -> "CanonicalMetric":
        """Factory for missing data — null + reason, never zero."""
        return cls(
            metric_id=metric_id,
            period=period,
            value=None,
            status=MetricStatus.UNAVAILABLE.value,
            reason=reason,
            unit_type=unit_type,
            statement_scope=statement_scope,
            display_name=display_name or metric_id,
        )


@dataclass
class CanonicalPeriod:
    """An explicit reporting period with comparability metadata."""

    label: str  # "FY2026", "Q2 FY2027", "H1 FY2027", "9M FY2027", "TTM"
    kind: str  # FY | QUARTER | HALF_YEAR | NINE_MONTH | TTM
    fiscal_year: int
    start_date: str = ""
    end_date: str = ""
    cumulative: bool = False  # True for YTD/TTM observations
    audit_status: str = AuditStatus.AUDITED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "kind": self.kind,
            "fiscal_year": self.fiscal_year,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "cumulative": self.cumulative,
            "audit_status": self.audit_status,
        }


@dataclass
class CanonicalSource:
    """Source provenance for every externally sourced value."""

    source_id: str
    source_name: str
    source_type: str  # NSE_XBRL | BSE_XBRL | NSE_FILING | BSE_FILING | ANNUAL_REPORT | COMPANY_IR | MARKET_DATA | MACRO_DATA | FIXTURE
    trust_tier: str  # PRIMARY | OFFICIAL | CORROBORATING
    document_type: str = ""
    document_title: str = ""
    period: str = ""
    published_date: str = ""
    url: str = ""
    retrieved_at: str = ""
    used_for: str = ""
    status: str = "VERIFIED"  # VERIFIED | PENDING | UNAVAILABLE | FIXTURE
    is_fixture: bool = False  # True → data is development-only, never live

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "trust_tier": self.trust_tier,
            "document_type": self.document_type,
            "document_title": self.document_title,
            "period": self.period,
            "published_date": self.published_date,
            "url": self.url,
            "retrieved_at": self.retrieved_at,
            "used_for": self.used_for,
            "status": self.status,
            "is_fixture": self.is_fixture,
        }


@dataclass
class CanonicalStatement:
    """A financial statement rendered as ordered line items per period."""

    statement_type: str  # income_statement | balance_sheet | cash_flow
    line_items: list[str] = field(default_factory=list)  # ordered metric_ids
    periods: list[str] = field(default_factory=list)
    # key: f"{metric_id}|{period}|{statement_scope}"
    #
    # Scope is part of the key because a company can report two different
    # values for the same line and period — consolidated includes subsidiaries,
    # standalone does not. Keying on metric_id|period alone made the second
    # value silently overwrite the first, and turned the engine's scope
    # fallback into a no-op that could not ever prefer a scope.
    metrics: dict[str, CanonicalMetric] = field(default_factory=dict)

    @staticmethod
    def _key(
        metric_id: str,
        period: str,
        statement_scope: str = Scope.CONSOLIDATED.value,
    ) -> str:
        return f"{metric_id}|{period}|{statement_scope}"

    def add(self, metric: CanonicalMetric) -> None:
        self.metrics[self._key(metric.metric_id, metric.period, metric.statement_scope)] = metric

    def get(
        self,
        metric_id: str,
        period: str,
        statement_scope: Optional[str] = None,
    ) -> Optional[CanonicalMetric]:
        """Look up one metric.

        With ``statement_scope`` given, the requested scope is authoritative
        and nothing else is substituted for it *if this statement records that
        scope at all*. A dataset that publishes both bases is making a
        deliberate distinction, and answering a group-level question with
        parent-only figures — or the reverse — would be silently wrong by a
        large margin (consolidated revenue is ~1.5x standalone here).

        The fallback exists only for single-scope adapters, and is detected at
        the statement level: if no line in this statement carries the requested
        scope, there is nothing to confuse, so the one scope that *is* present
        answers every request. The returned metric reports the scope it was
        actually recorded under, so callers can tell a fallback from a match.

        With ``statement_scope`` omitted, returns whichever scope is present.
        Callers that do not care about scope (completeness tallies, source
        lookups) should keep omitting it.
        """
        if statement_scope is None:
            for scope in _SCOPE_ORDER:
                m = self.metrics.get(self._key(metric_id, period, scope))
                if m is not None:
                    return m
            return None

        exact = self.metrics.get(self._key(metric_id, period, statement_scope))
        if exact is not None:
            return exact

        # The scope was requested, so if this statement has no line under it
        # the dataset is single-scope and the other basis is all there is.
        if any(key.rsplit("|", 1)[-1] == statement_scope for key in self.metrics):
            return None
        other = next((s for s in _SCOPE_ORDER if s != statement_scope), None)
        if other is None:
            return None
        return self.metrics.get(self._key(metric_id, period, other))

    def value(
        self,
        metric_id: str,
        period: str,
        statement_scope: Optional[str] = None,
    ) -> Optional[float]:
        m = self.get(metric_id, period, statement_scope)
        return m.value if m else None

    def scopes_for(self, metric_id: str, period: str) -> list[str]:
        """Which scopes actually carry this metric/period."""
        return [s for s in _SCOPE_ORDER if self._key(metric_id, period, s) in self.metrics]

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement_type": self.statement_type,
            "line_items": list(self.line_items),
            "periods": list(self.periods),
            "metrics": {k: m.to_dict() for k, m in self.metrics.items()},
        }


@dataclass
class CanonicalOwnership:
    """Shareholding pattern observation (India)."""

    period: str
    promoter_pct: Optional[float] = None
    promoter_change_qoq: Optional[float] = None
    promoter_change_yoy: Optional[float] = None
    promoter_pledge_pct: Optional[float] = None
    fii_pct: Optional[float] = None  # FII / FPI
    dii_pct: Optional[float] = None
    mutual_fund_pct: Optional[float] = None
    public_pct: Optional[float] = None
    institutional_pct: Optional[float] = None  # calculated: FII + DII
    government_pct: Optional[float] = None
    status: str = MetricStatus.REPORTED.value
    source_ids: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "promoter_pct": self.promoter_pct,
            "promoter_change_qoq": self.promoter_change_qoq,
            "promoter_change_yoy": self.promoter_change_yoy,
            "promoter_pledge_pct": self.promoter_pledge_pct,
            "fii_pct": self.fii_pct,
            "dii_pct": self.dii_pct,
            "mutual_fund_pct": self.mutual_fund_pct,
            "public_pct": self.public_pct,
            "institutional_pct": self.institutional_pct,
            "government_pct": self.government_pct,
            "status": self.status,
            "source_ids": list(self.source_ids),
            "reason": self.reason,
        }


@dataclass
class CanonicalMarketData:
    """Market snapshot; fixture data must always self-identify."""

    price: Optional[float] = None
    previous_close: Optional[float] = None
    price_date: str = ""
    percent_change: Optional[float] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None
    currency: str = "INR"
    exchange: str = ""
    source_id: str = ""
    source_name: str = ""
    data_status: str = "DELAYED"  # LIVE | DELAYED | HISTORICAL | FIXTURE
    is_fixture: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": self.price,
            "previous_close": self.previous_close,
            "price_date": self.price_date,
            "percent_change": self.percent_change,
            "market_cap": self.market_cap,
            "shares_outstanding": self.shares_outstanding,
            "currency": self.currency,
            "exchange": self.exchange,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "data_status": self.data_status,
            "is_fixture": self.is_fixture,
            "reason": self.reason,
        }


@dataclass
class CanonicalCompanyIdentity:
    """Resolved company identity used for region/entity routing."""

    name: str
    country: str  # ISO-3166 alpha-2, e.g. "IN"
    legal_name: str = ""
    nse_symbol: str = ""
    bse_code: str = ""
    isin: str = ""
    cin: str = ""
    primary_exchange: str = ""
    sector: str = ""
    industry: str = ""
    currency: str = "INR"
    entity_type: str = EntityType.CORPORATE.value if False else "CORPORATE"
    description: str = ""
    reporting_standard: str = "Ind AS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "country": self.country,
            "legal_name": self.legal_name,
            "nse_symbol": self.nse_symbol,
            "bse_code": self.bse_code,
            "isin": self.isin,
            "cin": self.cin,
            "primary_exchange": self.primary_exchange,
            "sector": self.sector,
            "industry": self.industry,
            "currency": self.currency,
            "entity_type": self.entity_type,
            "description": self.description,
            "reporting_standard": self.reporting_standard,
        }


@dataclass
class CanonicalCompanyData:
    """The complete canonical dataset for one company.

    Region adapters populate this; dashboard builders and the AI context
    consume it. Dashboard components never see exchange field names.
    """

    identity: CanonicalCompanyIdentity
    periods: list[CanonicalPeriod] = field(default_factory=list)
    statements: dict[str, CanonicalStatement] = field(default_factory=dict)
    ownership: list[CanonicalOwnership] = field(default_factory=list)
    market_data: Optional[CanonicalMarketData] = None
    sources: dict[str, CanonicalSource] = field(default_factory=dict)

    def add_source(self, source: CanonicalSource) -> None:
        self.sources[source.source_id] = source

    def metric(
        self,
        metric_id: str,
        period: str,
        statement_type: Optional[str] = None,
        statement_scope: Optional[str] = None,
    ) -> Optional[CanonicalMetric]:
        """Find a metric across statements (or in one specific statement).

        ``statement_scope`` narrows to a reporting basis; the other scope is
        used as a fallback so single-scope adapters still resolve. The metric
        returned carries the scope it was actually recorded under, so callers
        can tell a fallback from a match via ``m.statement_scope``.
        """
        if statement_type:
            stmt = self.statements.get(statement_type)
            return stmt.get(metric_id, period, statement_scope) if stmt else None
        for stmt in self.statements.values():
            m = stmt.get(metric_id, period, statement_scope)
            if m is not None:
                return m
        return None

    def metric_value(
        self,
        metric_id: str,
        period: str,
        statement_type: Optional[str] = None,
        statement_scope: Optional[str] = None,
    ) -> Optional[float]:
        m = self.metric(metric_id, period, statement_type, statement_scope)
        return m.value if m and m.is_available else None

    def available_scopes(self) -> list[str]:
        """Reporting bases actually present in the data.

        Drives the dashboard's scope selector, so it reflects what the adapter
        recorded rather than what the system could theoretically compute.
        """
        found: list[str] = []
        for stmt in self.statements.values():
            for key in stmt.metrics:
                scope = key.rsplit("|", 1)[-1]
                if scope in _SCOPE_ORDER and scope not in found:
                    found.append(scope)
        return [s for s in _SCOPE_ORDER if s in found]

    def period_labels(self) -> list[str]:
        return [p.label for p in self.periods]

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "periods": [p.to_dict() for p in self.periods],
            "statements": {k: s.to_dict() for k, s in self.statements.items()},
            "ownership": [o.to_dict() for o in self.ownership],
            "market_data": self.market_data.to_dict() if self.market_data else None,
            "sources": {k: s.to_dict() for k, s in self.sources.items()},
        }
