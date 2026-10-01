"""The India research path: one query in, one researched dashboard out.

This is the piece the rest of the India pipeline was built to feed. Every other
module here is a specialist — resolution, discovery, PDF extraction, label
mapping, arithmetic validation, ownership, market data, forensics — and none of
them can be trusted on its own, because a plausible number from a mis-read
column is worse than no number. So this module's job is to run them in the
right order, hold each stage to its own contract, and publish only what
survived.

Three rules shape everything below.

**Partial success is the normal case, not the failure case.** A run publishes
every statement that validated even if the previous filing failed to download,
and publishes ownership even when no financial statement could be read, because
a shareholding pattern is independently authoritative. Conversely a stage that
fails is recorded in ``stages`` with a reason rather than aborting, so the
dashboard can tell the user exactly what is missing instead of showing an
error page.

**Nothing is published that has not been corroborated.** Values pass through
the arithmetic validator before they become canonical metrics. A statement with
no testable identity — no revenue, no totals to reconcile — is quarantined whole
rather than released as individual figures, because a page whose column
assignment is wrong produces numbers that look individually reasonable and are
collectively nonsense.

**No stage knows about any company in particular.** A Reliance figure and a
Bajaj Finance figure travel the same code path, and anything that would have to
branch on a name is a bug in this file rather than a configuration option.

The entry point is :meth:`IndiaAdapter.research`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from lib.core.canonical_models import (
    AuditStatus,
    CanonicalCompanyData,
    CanonicalCompanyIdentity,
    CanonicalMarketData,
    CanonicalMetric,
    CanonicalOwnership,
    CanonicalPeriod,
    CanonicalSource,
    CanonicalStatement,
    MetricStatus,
    Scope,
)
from lib.core.entity_types import EntityType
from lib.india import documents, http_client, live_resolver, market_data_adapter
from lib.india import ownership as ownership_feed
from lib.india import pdf_tables
from lib.india.classifier import classify_entity
from lib.india.dashboard_builder import build_india_dashboard
from lib.india.models import IndiaMacroStrip, unavailable_macro_strip
from lib.india.sources import (
    SOURCE_SHAREHOLDING,
    SOURCE_SHAREHOLDING_XBRL,
    SOURCE_TYPE_TIER,
    TrustTier,
)
from lib.india.statement_validator import StatementValidator, apply_report
from lib.india.taxonomy_mapper import match_label, resolve_metrics, ResolvedLine
from lib.metrics.definitions import UnitType
from lib.metrics.registry import get_registry

logger = logging.getLogger("finora.india.adapter")


def _metric_unit_type(metric_id: str) -> str:
    """The unit a metric is denominated in, or money when it cannot be found.

    A metric the registry does not define is treated as an amount, which is the
    conservative assumption: it is scaled like every other figure in the
    statement.
    """
    try:
        return get_registry().get(metric_id).unit_type or UnitType.MONEY.value
    except Exception:
        return UnitType.MONEY.value


#: A bank prints one profit and loss account, and it prints lines that the
#: generic vocabulary already names: "Total Income", "Tax Expense", "Net Profit
#: for the period". The bank's own measures - operating profit, its profit
#: before tax, its profit after tax - are then formulas over bank-keyed inputs
#: that the filing never prints, so those formulas reported UNAVAILABLE while the
#: figures they were built from sat unread next to them.
#:
#: These are the same printed lines under the names the bank's formulas consume.
#: No value is computed here and none is invented: each entry copies a figure
#: already read from the page, keeping the label it was read from, so the reader
#: sees which line the bank measure came from.
_BANK_LINE_ALIASES: dict[str, str] = {
    "other_income": "bank_other_income",
    "total_tax": "bank_tax",
    "operating_expenses": "operating_expenses",
    "pbt": "bank_pbt",
    "net_profit": "bank_pat",
    "reserves_surplus": "bank_reserves",
}


def _apply_entity_conventions(
    values: dict[str, float],
    provenance: dict[str, dict[str, Any]],
    entity_type: Any,
) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    """Re-key a bank's printed lines to the names the bank's formulas read.

    Only additive: an existing metric is never overwritten, so a filing that
    genuinely prints a bank-keyed line keeps its own figure.
    """
    if str(entity_type) not in (EntityType.BANK.value, EntityType.BANK.name):
        return values, provenance
    for generic, bank_metric in _BANK_LINE_ALIASES.items():
        if generic not in values or bank_metric in values:
            continue
        values[bank_metric] = values[generic]
        provenance[bank_metric] = {
            **provenance.get(generic, {}),
            "alias_of": generic,
        }
    return values, provenance

#: Statement page roles that carry financial statement line items.
_STATEMENT_ROLES = frozenset({"P_AND_L", "BALANCE_SHEET", "CASH_FLOW"})

#: Page role to canonical statement type. Anything else is a segment, a
#: schedule or a note, and is not a consolidated statement.
_PAGE_ROLE_TO_STATEMENT = {
    "P_AND_L": "income_statement",
    "BALANCE_SHEET": "balance_sheet",
    "CASH_FLOW": "cash_flow",
}

#: Reporting bases in order of preference. Group figures are the right default
#: for research on a company, because standalone excludes the subsidiaries that
#: generate most of the revenue.
_SCOPE_PREFERENCE = ("CONSOLIDATED", "STANDALONE")


def _scope_rank(scope: str) -> int:
    """How preferred a reporting basis is; unknown bases sort last but are kept."""
    try:
        return _SCOPE_PREFERENCE.index(scope)
    except ValueError:
        return len(_SCOPE_PREFERENCE)


def _outranked_periods(statement: Any, period: str) -> Optional[str]:
    """The best basis already recorded for a period, if it beats ``scope``.

    Both bases of a period must not end up in one series. A Reliance revenue
    trend that read consolidated Q2 at 258,898 crore, standalone Q4 at 125,741
    and consolidated Q1 at 298,621 would show a collapse of 51% followed by a
    recovery of 137%, and every one of those points would be individually
    correct. Nothing downstream can tell the difference, because the metric
    carries its scope but no consumer of a trend line is expected to check it.
    """
    for scope in _SCOPE_PREFERENCE:
        for metric in statement.metrics.values():
            if metric.period == period and metric.statement_scope == scope:
                return scope
    return None


def _supersede(statement: Any, period: str, keep_scope: str) -> None:
    """Drop the same metrics recorded on a less preferred basis for a period."""
    for key, metric in list(statement.metrics.items()):
        if (
            metric.period == period
            and metric.statement_scope != keep_scope
            and _scope_rank(metric.statement_scope) > _scope_rank(keep_scope)
        ):
            del statement.metrics[key]
            if metric.metric_id in statement.line_items and not any(
                m.metric_id == metric.metric_id and m.statement_scope == keep_scope
                for m in statement.metrics.values()
            ):
                statement.line_items.remove(metric.metric_id)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Stage:
    """The outcome of one step, whether it worked or not.

    ``ok`` false with a reason is a normal, reportable state. The dashboard
    renders these so a user can see that, say, balance sheets were not
    published, instead of quietly seeing an empty tab with no explanation.
    """

    name: str
    ok: bool = False
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"stage": self.name, "ok": self.ok}
        if self.reason:
            payload["reason"] = self.reason
        if self.detail:
            payload.update(self.detail)
        return payload


@dataclass
class IndiaResearchResult:
    """Everything one research run produced, including what it could not."""

    query: str
    status: str = "pending"
    message: str = ""
    company: Optional[Any] = None
    entity_type: str = EntityType.CORPORATE.value
    data: Optional[CanonicalCompanyData] = None
    dashboard: Optional[dict[str, Any]] = None
    stages: list[Stage] = field(default_factory=list)
    retrieved_at: str = ""

    @property
    def usable(self) -> bool:
        """True when the run produced something worth opening.

        Ownership alone qualifies. A promoter or FII trend is real research
        even with no financial statement, and refusing to show it would make
        the user believe nothing exists when a great deal does.
        """
        if self.data is None:
            return False
        if any(s.metrics for s in self.data.statements.values()):
            return True
        return bool(self.data.ownership) or self.data.market_data is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "status": self.status,
            "message": self.message,
            "entity_type": self.entity_type,
            "retrieved_at": self.retrieved_at or _now(),
            "usable": self.usable,
            "stages": [s.to_dict() for s in self.stages],
            "dashboard": self.dashboard,
        }


class IndiaAdapter:
    """Researches one Indian listed company from a free-text query."""

    #: Filings are large and the exchange rate-limits, so a run is bounded.
    #: Four quarters of history is what the trend views need; going deeper
    #: costs the user minutes of waiting for a page they will not scroll to.
    max_filings: int = 4
    max_pages_per_filing: int = 60
    months_back: int = 30
    ownership_quarters: int = 8

    def __init__(
        self,
        *,
        validator: Optional[StatementValidator] = None,
        search_documents: bool = True,
    ) -> None:
        self._validator = validator or StatementValidator()
        self._search_documents = search_documents

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Type-ahead search over the live exchange equity master."""
        try:
            return live_resolver.search(query, limit=limit)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[india.adapter] search failed for %r: %s", query, exc)
            return []

    def research(self, query: str, *, months_back: Optional[int] = None) -> IndiaResearchResult:
        """Run the full research path for ``query``.

        Returns a result object rather than raising. A user typing a company
        name must never receive a stack trace because an exchange returned 403,
        so every stage is contained and reported.
        """
        result = IndiaResearchResult(query=query, retrieved_at=_now())
        months = months_back or self.months_back

        if not query or not query.strip():
            result.status = "invalid_query"
            result.message = "Enter a company name, NSE symbol, BSE code or ISIN."
            return result

        # 1. Who is this?
        try:
            resolution = live_resolver.resolve(query)
        except Exception as exc:
            logger.warning("[india.adapter] resolution failed for %r: %s", query, exc)
            resolution = None
        company = resolution.company if resolution is not None else None

        if company is None:
            result.status = "unresolved"
            result.message = (
                resolution.message
                if resolution is not None and resolution.message
                else f"No listed Indian company matched '{query}'."
            )
            result.stages.append(Stage(
                "resolve", ok=False, reason="no exchange match",
                detail={"candidates": resolution.candidates if resolution else []},
            ))
            return result

        result.company = company
        result.stages.append(Stage(
            "resolve", ok=True,
            detail={
                "matched": company.display_name,
                "nse_symbol": company.nse_symbol,
                "bse_code": company.bse_code,
                "isin": company.isin,
                "method": resolution.method,
                "confidence": resolution.confidence,
            },
        ))

        symbol = (company.nse_symbol or "").strip()
        if not symbol:
            # Every downstream source is keyed by NSE symbol. A company that
            # resolved without one can still be reported as found, but nothing
            # can be researched against it.
            result.status = "resolved_without_symbol"
            result.message = (
                f"Matched {company.display_name}, but the exchange master gave no "
                "NSE symbol, so no filings could be retrieved."
            )
            result.stages.append(Stage(
                "symbol", ok=False, reason="no NSE symbol in the exchange master"
            ))
            return result

        # 2. What kind of entity is it? The schema, the tabs and the detectors
        #    all differ between a bank, an NBFC and an industrial company.
        entity = classify_entity(
            name=company.display_name,
            sector=company.sector or "",
            industry=company.industry or "",
        )
        result.entity_type = entity.entity_type.value
        result.stages.append(Stage(
            "classify", ok=bool(entity.reason) or entity.confidence > 0,
            detail={
                "entity_type": entity.entity_type.value,
                "confidence": entity.confidence,
                "signals": entity.signals,
            },
        ))

        # 3. Assemble the canonical dataset. Each collector adds what it can and
        #    records what it could not; none of them can empty the dataset.
        identity = self._identity(company, entity.entity_type)
        data = CanonicalCompanyData(identity=identity)
        self._add_resolution_source(data, company)

        if self._search_documents:
            self._collect_financials(data, symbol, months, result)
        else:
            result.stages.append(Stage(
                "filings", ok=False, reason="document search disabled for this run"
            ))

        # 4. Ownership is fetched independently of the financial statements and
        #    is often the most complete part of a run, because it comes from a
        #    structured disclosure rather than a scanned PDF.
        self._add_ownership(data, symbol, result)

        # 5. Market data is context, not evidence: a fallback provider, and its
        #    absence must never block a research run.
        self._add_market(data, symbol, result)

        result.data = data
        if not result.usable:
            result.status = "no_data"
            result.message = (
                f"Found {company.display_name}, but no financial statement, "
                "ownership pattern or market data could be retrieved for it."
            )
            return result

        # 6. Macro is context only. No official source is wired yet, so the
        #    strip is explicitly unavailable rather than filled with a plausible
        #    number that would be read as RBI's.
        macro = self._macro_strip(result)

        scope = _preferred_scope(data)
        result.dashboard = build_india_dashboard(
            data, scope=scope, macro=macro, is_fixture=False,
        )
        result.status = "ok"
        result.message = (
            f"Researched {company.display_name} "
            f"({entity.entity_type.value.title()}, {scope.title()})."
        )
        return result

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @staticmethod
    def _identity(company: Any, entity_type: str) -> CanonicalCompanyIdentity:
        return CanonicalCompanyIdentity(
            name=company.display_name,
            legal_name=company.legal_name or company.display_name,
            country=company.country or "IN",
            nse_symbol=company.nse_symbol or "",
            bse_code=company.bse_code or "",
            isin=company.isin or "",
            cin=company.cin or "",
            primary_exchange=company.primary_exchange or "",
            sector=company.sector or "",
            industry=company.industry or "",
            currency=company.currency or "INR",
            entity_type=entity_type,
            reporting_standard="IND_AS",
            description=company.display_name,
        )

    @staticmethod
    def _add_resolution_source(data: CanonicalCompanyData, company: Any) -> None:
        data.add_source(CanonicalSource(
            source_id=f"nse_master:{company.nse_symbol or company.isin}",
            source_name="NSE equity master",
            source_type="NSE_XBRL",
            trust_tier=TrustTier.OFFICIAL_STRUCTURED.value,
            document_type="LISTING_MASTER",
            document_title="NSE listed company master",
            url="https://www.nseindia.com/equities",
            retrieved_at=_now(),
            used_for=["identity"],
            status="OK",
            is_fixture=False,
        ))

    # ------------------------------------------------------------------
    # Filings
    # ------------------------------------------------------------------

    def _collect_financials(
        self,
        data: CanonicalCompanyData,
        symbol: str,
        months: int,
        result: IndiaResearchResult,
    ) -> None:
        """Discover filings, read them, and publish only validated statements."""
        try:
            registry = documents.discover(symbol, months_back=months)
        except Exception as exc:
            logger.warning("[india.adapter] discovery failed for %s: %s", symbol, exc)
            result.stages.append(Stage(
                "discover", ok=False, reason=f"filing discovery failed: {exc}"
            ))
            return

        candidates = self._financial_candidates(registry)
        if not candidates:
            result.stages.append(Stage(
                "discover", ok=False,
                reason="no financial results filing found in the window",
                detail={"months_back": months},
            ))
            return

        published = 0
        rejected_pages = 0
        for document in candidates:
            try:
                count, rejected = self._ingest_document(data, symbol, document, result)
            except Exception as exc:  # pragma: no cover - defensive per document
                logger.warning("[india.adapter] %s failed: %s", document.doc_id, exc)
                result.stages.append(Stage(
                    "parse", ok=False,
                    reason=f"{document.doc_id} could not be read: {exc}",
                ))
                continue
            published += count
            rejected_pages += rejected

        result.stages.append(Stage(
            "discover", ok=published > 0,
            reason="" if published else "no filing yielded a validated statement",
            detail={
                "filings_examined": len(candidates),
                "statements_published": published,
                "pages_withheld": rejected_pages,
            },
        ))

    #: Words that make a non-financial filing worth opening as a statement.
    #: ``promotable`` is deliberately broad — it hands the decision to the PDF
    #: stage — but each speculative candidate is a multi-megabyte download, so
    #: the budget is only spent on announcements that at least claim to contain
    #: results.
    _RESULT_HINTS = (
        "financial result", "financial statement", "audited financial",
        "unaudited", "results", "statement", "balance sheet",
        "profit and loss", "quarterly performance",
    )

    def _financial_candidates(self, registry: Any) -> list[Any]:
        """The filings worth parsing, newest first, classified ones first.

        Two sources, in strict priority order.

        ``latest_financials`` is what the exchange itself categorised as a
        results or audited-financials filing, so it goes first. ``promotable``
        catches the results statements that companies attach to board-meeting
        or "updates" filings instead of filing under a results category, and
        fills only the budget the classified documents leave over.

        The ordering matters more than it looks. Both sources are sorted by
        period, and a speculative "investor call" filing carries a more recent
        period than the last quarter's results, so merging them and sorting
        once let a press release outrank the actual statement and consume the
        whole budget. Nothing would then have been read, and the run would
        report a company that publishes no financials.
        """
        seen_urls: set[str] = set()
        classified: list[Any] = []
        speculative: list[Any] = []

        for document in registry.latest_financials(self.max_filings * 3):
            url = document.source_url or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            classified.append(document)

        for document in registry.promotable(limit=self.max_filings * 3):
            url = document.source_url or ""
            if not url or url in seen_urls:
                continue
            haystack = f"{document.title or ''} {document.category or ''}".lower()
            if not any(hint in haystack for hint in self._RESULT_HINTS):
                continue
            seen_urls.add(url)
            speculative.append(document)

        def recency(document_: Any) -> str:
            """What to sort a candidate by, worst case last.

            ``period_end`` is the subject of the filing, which is what a reader
            wants. A filing that states no period falls back to when it was
            filed, so it is still considered rather than dropped.
            """
            return str(
                getattr(document_, "period_end", "") or ""
                or getattr(document_, "filed_at", "") or ""
            )

        # Recency first, classification second. Putting every classified filing
        # ahead of every speculative one was wrong, and it was wrong in a way
        # only a live bank exposed: HDFC Bank's exchange feed classifies results
        # filings only up to December 2024, and files its current results as a
        # board-meeting attachment. Classified-first therefore ranked a
        # twenty-month-old statement above the most recent one, and the run
        # published last year's numbers as current. A results document from
        # last year is not a better answer than one from last month, whatever
        # the exchange called it.
        #
        # Classification only decides between filings of the same date, and it
        # decides in favour of the typed one, so the flag is negated for the
        # speculative documents before the descending sort.
        ranked = sorted(
            classified + speculative,
            key=lambda d: (recency(d), 0 if d in speculative else 1),
            reverse=True,
        )
        return ranked[: self.max_filings]

    def _ingest_document(
        self,
        data: CanonicalCompanyData,
        symbol: str,
        document: Any,
        result: IndiaResearchResult,
    ) -> tuple[int, int]:
        """Fetch, parse and validate one filing. Returns (pages, withheld)."""
        fetched = http_client.fetch(
            document.source_url,
            provider="nse_filing",
            kind="financials",
            accept=("application/pdf", "*/*"),
            max_bytes=25_000_000,
        )
        if not fetched.ok or not fetched.content:
            result.stages.append(Stage(
                "parse", ok=False,
                reason=f"{document.title or document.doc_id} was not retrievable",
            ))
            return 0, 0

        filing = pdf_tables.parse_pdf(
            fetched.content, max_pages=self.max_pages_per_filing
        )
        # A scan is reported before the results check, because a scan often
        # passes it: HDFC Bank's cover letter is born-digital and its text says
        # "financial results", while every statement page behind it is an image.
        #
        # It is only given up on once the optical pass has had its turn. A scan
        # whose statements were read is not a failure, and saying it "cannot be
        # read" about a page Finora has just read would be worse than silence.
        if filing.is_scanned and not filing.statement_pages:
            result.stages.append(Stage(
                "parse", ok=False,
                reason=(
                    f"{document.doc_id} is a scan of {filing.page_count} printed "
                    "page(s) with no text layer, and reading it optically "
                    "recovered no statement, so it cannot be read"
                ),
            ))
            return 0, 0
        if filing.is_scanned:
            result.stages.append(Stage(
                "parse", ok=True,
                reason=(
                    f"{document.doc_id} is a scan of {filing.page_count} printed "
                    f"page(s); {len(filing.ocr_pages)} page(s) were read optically "
                    "and the figures they carry are corroborated by the filing's "
                    "own arithmetic"
                ),
                detail={"ocr_pages": filing.ocr_pages},
            ))
        if not filing.is_results_document:
            result.stages.append(Stage(
                "parse", ok=False,
                reason=f"{document.doc_id} is not a results filing",
            ))
            return 0, 0

        source_id = f"nse_filing:{document.doc_id}"
        data.add_source(CanonicalSource(
            source_id=source_id,
            source_name="NSE corporate filing",
            source_type="NSE_FILING",
            trust_tier=TrustTier.OFFICIAL_FILING.value,
            document_type=document.kind.value if hasattr(document.kind, "value")
            else str(document.kind),
            document_title=document.title or "",
            period=document.period_end,
            published_date=document.filed_at,
            url=document.source_url,
            retrieved_at=_now(),
            used_for=["financials"],
            status="OK",
            is_fixture=False,
        ))

        period_end = document.period_end or filing.period_end
        audit = _audit_status(document)
        published = 0
        withheld = 0

        for page in filing.pages:
            if page.role not in _STATEMENT_ROLES:
                continue
            statement_type = _PAGE_ROLE_TO_STATEMENT.get(page.role)
            if statement_type is None:
                continue

            page_scope = _page_scope(page, filing)
            column = _current_column(page)
            if column is None:
                withheld += 1
                continue

            # A statement page without a resolvable period must not become the
            # canonical P&L merely because it is the only candidate. Its metrics
            # are published with no fiscal anchor, and the dashboard would read
            # them as current when they belong to an unrecognised period.
            if not period_end:
                withheld += 1
                result.stages.append(Stage(
                    "validate", ok=False,
                    reason=(
                        f"page {page.page_number} ({statement_type}) withheld: "
                        f"no resolvable period_end on the statement"
                    ),
                    detail={
                        "document": document.doc_id,
                        "scope": page_scope,
                    },
                ))
                continue

            values, provenance = self._read_page(page, column, filing)
            if not values:
                withheld += 1
                continue

            report = self._validate(values, statement_type, period_end, page_scope)
            # Release exactly what the validator vouched for. Gating this on
            # ``report.passed`` used to discard a page because one identity
            # failed, throwing away the metrics that had been corroborated by
            # the others. The validator already quarantines a statement whole
            # when nothing on it could be tested, so the quarantine boundary
            # belongs to it and not to this condition.
            released = apply_report(values, report)
            # The entity's own naming is applied to what survived, never to
            # what did not: an alias copies a figure the validator vouched for,
            # so it inherits that vouching and cannot carry a quarantined
            # figure into a published one.
            released, released_provenance = _apply_entity_conventions(
                released, provenance, result.entity_type
            )

            if not released:
                withheld += 1
                _record_rejection(result, document, page, statement_type, report)
                continue

            if not report.passed:
                # Published, but the shortfall stays visible on the dashboard
                # rather than disappearing into a thinner statement.
                result.stages.append(Stage(
                    "validate", ok=True,
                    reason=(
                        f"page {page.page_number} ({statement_type}) published in "
                        f"part: {len(released)} of {len(values)} metric(s) corroborated, "
                        f"{len(report.quarantined)} withheld"
                    ),
                    detail={
                        "document": document.doc_id,
                        "period": document.period_end,
                        "scope": page.scope,
                        "withheld": sorted(report.quarantined)[:12],
                    },
                ))

            statement = data.statements.setdefault(
                statement_type, CanonicalStatement(statement_type=statement_type)
            )

            # One reporting basis per period. Whichever basis is read first
            # wins unless a more preferred one turns up, in which case it
            # replaces it, so a period is never half group and half
            # standalone.
            incumbent = _outranked_periods(statement, period_end) if period_end else None
            if incumbent is not None and _scope_rank(incumbent) < _scope_rank(page_scope):
                withheld += 1
                result.stages.append(Stage(
                    "validate", ok=True,
                    reason=(
                        f"page {page.page_number} ({statement_type}) not used: "
                        f"{period_end} is already reported on the {incumbent} basis, "
                        f"which is preferred over {page_scope}"
                    ),
                    detail={
                        "document": document.doc_id,
                        "period": period_end,
                        "scope": page_scope,
                    },
                ))
                continue
            if period_end:
                _supersede(statement, period_end, page_scope)

            period_type, cumulative = _period_kind(column, statement_type)
            _record_metrics(
                statement, released, released_provenance, period_end, page_scope,
                audit, source_id, report, period_type, cumulative,
            )
            if period_end and period_end not in statement.periods:
                statement.periods.append(period_end)
            _add_period(
                data, period_end, document, audit, period_type, cumulative
            )
            published += 1

        return published, withheld

    def _read_page(
        self, page: Any, column: Any, filing: Any
    ) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
        """Map one statement page's current column onto canonical metrics.

        Returns the values and the per-metric provenance needed to build an
        auditable :class:`CanonicalMetric` later.
        """
        scale = filing.unit.scale if filing.unit else 1.0
        lines: list[ResolvedLine] = []
        provenance: dict[str, dict[str, Any]] = {}

        for row in page.rows:
            match = match_label(row.label)
            if match is None:
                continue
            cell = next(
                (c for c in row.cells if c.column == column.index and c.ok), None
            )
            if cell is None or cell.value is None:
                continue
            # A statement is filed in lakhs or crores, so its figures are scaled
            # to rupees. Earnings per share is not: a filing prints "12.38" for
            # a rupee amount of 12.38, and scaling it by the crore factor turned
            # a bank's EPS of 12.38 into 123,800,000 - which the validator then
            # correctly refused as impossible, taking the real figure with it.
            unit_type = _metric_unit_type(match.metric_id)
            scaled = (
                cell.value
                if unit_type in (UnitType.PER_SHARE.value, UnitType.RATIO.value,
                                 UnitType.PERCENT.value)
                else cell.value * scale
            )
            value = scaled
            lines.append(ResolvedLine(
                metric_id=match.metric_id,
                value=value,
                label=row.label,
                confidence=match.confidence,
                method=match.method,
                role=match.role,
                recovered=cell.recovered,
                scale=scale,
            ))
            provenance.setdefault(match.metric_id, {
                "label": row.label,
                "method": match.method,
                "confidence": match.confidence,
                "recovered": cell.recovered,
                "source_text": cell.source_text,
                "page": page.page_number,
            })

        chosen, _shadowed = resolve_metrics(lines)
        values = {metric_id: line.value for metric_id, line in chosen.items()}
        return values, provenance

    def _validate(
        self, values: dict[str, float], statement_type: str,
        period_end: str, scope: str,
    ) -> Any:
        if statement_type == "income_statement":
            return self._validator.validate_income_statement(
                values, period_label=period_end, scope=scope,
            )
        if statement_type == "balance_sheet":
            return self._validator.validate_balance_sheet(
                values, as_at=period_end, scope=scope,
            )
        # A cash flow statement is checked like any other. It used to be
        # accepted on having parsed at all, which meant a page read from the
        # wrong column published a full set of plausible-looking cash figures
        # that reconciled to nothing.
        return self._validator.validate_cash_flow(
            values, period_label=period_end, scope=scope,
        )

    # ------------------------------------------------------------------
    # Ownership, market, macro
    # ------------------------------------------------------------------

    def _add_ownership(
        self, data: CanonicalCompanyData, symbol: str, result: IndiaResearchResult
    ) -> None:
        try:
            feed = ownership_feed.fetch_ownership(
                symbol, xbrl_periods=min(self.ownership_quarters, 4),
            )
        except Exception as exc:
            logger.warning("[india.adapter] ownership failed for %s: %s", symbol, exc)
            result.stages.append(Stage(
                "ownership", ok=False, reason=f"shareholding retrieval failed: {exc}"
            ))
            return

        if not feed.available:
            result.stages.append(Stage(
                "ownership", ok=False,
                reason=feed.failures[0]["reason"] if feed.failures
                else "no shareholding pattern published",
            ))
            return

        rows: list[CanonicalOwnership] = feed.to_canonical()
        data.ownership.extend(rows)
        for record in feed.records:
            data.add_source(CanonicalSource(
                source_id=record.source_id,
                source_name="NSE shareholding pattern",
                source_type=SOURCE_SHAREHOLDING,
                trust_tier=TrustTier.OFFICIAL_DISCLOSURE.value,
                document_type="SHAREHOLDING",
                document_title=f"Shareholding pattern {record.as_of}",
                period=record.as_of,
                url=record.xbrl_url or "",
                retrieved_at=_now(),
                used_for=["ownership"],
                status="OK",
                is_fixture=False,
            ))
        for source in feed.sources:
            data.add_source(source)

        result.stages.append(Stage(
            "ownership", ok=True,
            detail={
                "quarters": len(rows),
                "latest_period": rows[-1].period if rows else "",
                "categories": feed.category_coverage,
            },
        ))

    def _add_market(
        self, data: CanonicalCompanyData, symbol: str, result: IndiaResearchResult
    ) -> None:
        try:
            snapshot = market_data_adapter.get_india_market_snapshot(symbol)
        except Exception as exc:
            logger.warning("[india.adapter] market data failed for %s: %s", symbol, exc)
            result.stages.append(Stage("market", ok=False, reason=str(exc)))
            return

        canonical = snapshot.to_canonical()
        if canonical is None or canonical.price is None:
            result.stages.append(Stage(
                "market", ok=False,
                reason=snapshot.reason or "no market price available",
            ))
            return

        data.market_data = canonical
        if canonical.source_id:
            data.add_source(CanonicalSource(
                source_id=canonical.source_id,
                source_name=canonical.source_name or "Market data",
                source_type="MARKET_DATA",
                trust_tier=TrustTier.FREE_MARKET.value,
                document_type="MARKET_QUOTE",
                document_title=f"{symbol} quote",
                period=canonical.price_date,
                retrieved_at=_now(),
                used_for=["valuation"],
                status=canonical.data_status,
                is_fixture=canonical.is_fixture,
            ))
        result.stages.append(Stage(
            "market", ok=True,
            detail={"price": canonical.price, "as_of": canonical.price_date},
        ))

    def _macro_strip(self, result: IndiaResearchResult) -> IndiaMacroStrip:
        """Macro context.

        No official RBI or exchange macro source is connected yet. Returning the
        unavailable strip keeps the dashboard honest and the company research
        complete; substituting a remembered yield would be the one thing in this
        pipeline that is indefensible.
        """
        result.stages.append(Stage(
            "macro", ok=False,
            reason="no official RBI/exchange macro source connected yet",
        ))
        return unavailable_macro_strip(
            "No official India macro source is connected. Company research is "
            "unaffected; only the macro context strip is unavailable."
        )

    # ------------------------------------------------------------------
    # Assisting functions
    # ------------------------------------------------------------------

    @staticmethod
    def _add_resolution_stage(company: Any) -> None:  # pragma: no cover
        """Reserved for a future non-exchange identity source."""


def _record_rejection(
    result: IndiaResearchResult, document: Any, page: Any,
    statement_type: str, report: Any,
) -> None:
    """Explain, on the dashboard, why a page the parser understood was withheld.

    Silence here reads as "the company published no balance sheet", which is a
    materially different claim from "the figures did not reconcile".
    """
    result.stages.append(Stage(
        "validate", ok=False,
        reason=(
            f"page {page.page_number} ({statement_type}) withheld: "
            + "; ".join(report.notes[:2] or ["failed its arithmetic identities"])
        ),
        detail={
            "document": document.doc_id,
            "period": document.period_end,
            "scope": page.scope,
            "checks_run": len(report.checks),
            "quarantined": sorted(report.quarantined)[:12],
        },
    ))


def _record_metrics(
    statement: CanonicalStatement,
    values: dict[str, float],
    provenance: dict[str, dict[str, Any]],
    period_end: str,
    scope: str,
    audit: str,
    source_id: str,
    report: Any,
    period_type: str = "UNSPECIFIED",
    cumulative: bool = False,
) -> None:
    for metric_id, value in values.items():
        info = provenance.get(metric_id, {})
        statement.add(CanonicalMetric(
            metric_id=metric_id,
            period=period_end,
            value=value,
            currency="INR",
            period_type=period_type,
            cumulative=cumulative,
            statement_scope=scope,
            audit_status=audit,
            status=MetricStatus.REPORTED.value,
            source_ids=[source_id],
            confidence=info.get("confidence", 0.5),
            reason=(
                f"read from '{info.get('label', metric_id)}' on page "
                f"{info.get('page', '?')} of the filing"
            ),
            display_name=metric_id,
            unit_type=_metric_unit_type(metric_id),
        ))
        if metric_id not in statement.line_items:
            statement.line_items.append(metric_id)


def _add_period(
    data: CanonicalCompanyData,
    period_end: str,
    document: Any,
    audit: str,
    kind: str = "UNSPECIFIED",
    cumulative: bool = False,
) -> None:
    if not period_end:
        return
    # A period is described by the most specific statement that reported it. The
    # income statement and the balance sheet are read from different pages and
    # can classify the same period differently, and "UNSPECIFIED" must never win
    # over a classification that was actually evidenced.
    ranks = {"UNSPECIFIED": 0, "POINT_IN_TIME": 1, "QUARTERLY": 2, "ANNUAL": 3}
    existing = next((p for p in data.periods if p.label == period_end), None)
    if existing is not None:
        if ranks.get(kind, 0) > ranks.get(existing.kind, 0):
            existing.kind = kind
            existing.cumulative = cumulative
        return
    end = _as_date(period_end)
    start = None
    if end is not None:
        # The Indian financial year runs 1 April to 31 March, so any month from
        # April onward sits in a year that began in April of that same year.
        if end.month >= 4:
            try:
                start = date(end.year, 4, 1)
            except ValueError:  # pragma: no cover
                start = None
        else:
            try:
                start = date(end.year - 1, 4, 1)
            except ValueError:  # pragma: no cover
                start = None
    data.periods.append(CanonicalPeriod(
        label=period_end,
        kind=kind,
        fiscal_year=_fiscal_year(period_end),
        start_date=start.isoformat() if start else "",
        end_date=end.isoformat() if end else period_end,
        cumulative=cumulative,
        audit_status=audit,
    ))


def _preferred_scope(data: CanonicalCompanyData) -> str:
    """Consolidated when the company published it, standalone otherwise.

    Group figures are the right default for research on a company: standalone
    excludes the subsidiaries that generate most of the revenue.
    """
    scopes = data.available_scopes()
    if Scope.CONSOLIDATED.value in scopes:
        return Scope.CONSOLIDATED.value
    if scopes:
        return scopes[0]
    return Scope.CONSOLIDATED.value


def _current_column(page: Any) -> Optional[Any]:
    for column in page.columns:
        if column.role == "CURRENT":
            return column
    return None


def _page_scope(page: Any, filing: Any) -> str:
    """The scope of a single page, defaulting to the document's own scope."""
    scope = (page.scope or "").strip().upper()
    if "STANDALONE" in scope:
        return Scope.STANDALONE.value
    if "CONSOLIDATED" in scope:
        return Scope.CONSOLIDATED.value
    document_scope = (filing.scope or "").strip().upper()
    if "STANDALONE" in document_scope:
        return Scope.STANDALONE.value
    return Scope.CONSOLIDATED.value


def _audit_status(document: Any) -> str:
    kind = getattr(document.kind, "value", str(document.kind)).upper()
    if "ANNUAL" in kind or "AUDIT" in kind:
        return AuditStatus.AUDITED.value
    return AuditStatus.UNAUDITED.value


def _period_kind(column: Any, statement_type: str) -> tuple[str, bool]:
    """Classify the column that was read, from its own header only.

    Returns ``(period_type, cumulative)`` and is deliberately reluctant. An
    Indian results P&L prints a short period and a cumulative one side by side,
    and the only thing that distinguishes them is the column header. When the
    header is OCR-damaged - which it usually is - the honest answer is that the
    duration is unknown, so ``UNSPECIFIED`` is returned and ``cumulative`` is
    False.

    Asserting ``cumulative=True`` for everything was a real defect, not a
    cosmetic one: it is a positive claim that these figures cover the year to
    date, and for a three-month column it is false. Worse, ``quarter == 4``
    does not rescue it. Reliance's audited FY2026 filing opens its P&L with the
    *fourth-quarter* three-month column (125,741 crore standalone) and puts the
    full year in a later one, so the fiscal quarter of the filing says nothing
    about the duration of the column that was read.

    Only the header can settle it, so only the header is allowed to.
    """
    if statement_type == "balance_sheet":
        return "POINT_IN_TIME", False
    header = str(getattr(column, "header_text", "") or "")
    if re.search(r"year\s+ended|annual|fy\s*\d{4}", header, re.I):
        return "ANNUAL", True
    if re.search(r"quarter|3\s*months|three\s*months", header, re.I):
        return "QUARTERLY", False
    return "UNSPECIFIED", False


def _fiscal_year(period_end: str) -> Optional[int]:
    """Indian fiscal year label for a period end.

    FY2026 runs 1 April 2025 to 31 March 2026, so a year that ends in March
    belongs to the year it ends in, and a year that ends in December belongs to
    the following one. Getting this backwards labels a March 2026 quarter as
    FY2027 and shifts every trend comparison by a year.
    """
    end = _as_date(period_end)
    if end is None:
        return None
    return end.year + 1 if end.month >= 4 else end.year


def _as_date(text: str) -> Optional[date]:
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


__all__ = [
    "IndiaAdapter",
    "IndiaResearchResult",
    "Stage",
    "SOURCE_SHAREHOLDING_XBRL",
    "SOURCE_TYPE_TIER",
]
