"""Live shareholding extraction for India listed companies.

Shareholding is a separate data model from financial metrics. It is not a
line item in a statement of accounts, it is a quarterly pattern filed under
SEBI's Regulation 31, and it carries categories a financial metric registry has
no concept of. It therefore has its own extractor and its own model, and feeds
the dashboard, the ownership forensics detectors and the evidence ledger
through :class:`~lib.core.canonical_models.CanonicalOwnership`.

Two official NSE sources are used, in order of cost:

1. ``corporate-share-holdings-master`` returns the whole promoter/public series
   for a symbol directly as JSON, one record per quarter. This alone gives a
   usable ownership history with a single request.
2. The per-quarter XBRL attachment linked from each record gives the
   dimensional category breakdown (promoter, FPI, mutual funds, insurance,
   banks, AIFs, and so on) that the flat master does not expose.

Neither source is a paid feed and neither needs credentials.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional

from lib.core.canonical_models import CanonicalOwnership, CanonicalSource
from lib.india import http_client
from lib.india.sources import (
    NSE_SHAREHOLDING_URL,
    SOURCE_SHAREHOLDING,
    SOURCE_SHAREHOLDING_XBRL,
)

logger = logging.getLogger("finora.india.ownership")


_PCT_RE = re.compile(r"-?\d+(?:\.\d+)?")

#: SEBI's shareholding taxonomy, mapped onto Finora's categories.
#:
#: The taxonomy is published by the exchange in the same shape for every
#: filer, so this mapping is universal rather than per-company. Two of the
#: entries are aggregates that the filing also breaks down, and taking both
#: would double count, so an aggregate is preferred and its components are only
#: summed when the aggregate is absent.
_MEMBER_MAP: dict[str, str] = {
    "ShareholdingOfPromoterAndPromoterGroup": "promoter",
    "InstitutionsForeign": "fii",
    "InstitutionsForeignPortfolioInvestorCategoryOne": "fii_component",
    "InstitutionsForeignPortfolioInvestorCategoryTwo": "fii_component",
    "OtherInstitutionsForeign": "fii_component",
    "InstitutionsDomestic": "dii_total",
    "PublicShareholding": "public_total",
    "SharesHeldByNonPromoterNonPublicShareholders": "non_promoter_non_public",
    "MutualFundsOrUTI": "mutual_fund",
    "InsuranceCompanies": "insurance",
    "Banks": "bank",
    "ProvidentFundsOrPensionFunds": "pension_fund",
    "AlternativeInvestmentFunds": "aif",
    "OtherFinancialInstitutions": "other_financial_inst",
    "NBFCsRegisteredWithRBI": "nbfc_institution",
    "NonInstitutions": "non_institution",
    "OtherNonInstitutions": "other_non_institution",
    "NonResidentIndians": "nri",
    "BodiesCorporate": "body_corporate",
    "IndividualsOrHinduUndividedFamily": "individual",
    "DirectorOrRelativesOfDirectors": "director",
    "DirectorsAndDirectorsRelatives": "director",
    "KeyManagerialPersonnel": "key_management",
    "RelativesOfPromotersOtherThanPromoterGroup": "promoter_relative",
    "ForeignDirectInvestment": "fdi",
    "ForeignNationals": "foreign_national",
    "CentralGovernmentOrPresidentOfIndia": "central_government",
    "StateGovernmentsOrGovernors": "state_government",
    "Governments": "government",
    "SovereignWealthFundsDomestic": "domestic_swf",
    "InvestorEducationAndProtectionFund": "iepf",
    "CustodianOrDRHolder": "custodian",
    "AssociateCompaniesOrSubsidiaries": "associate",
    "ShareholdingByCompaniesOrBodiesCorporateWhereCentralOrStateGovernmentIsPromoter": "state_promoted_corporate",
    "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh": "retail_small",
    "ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh": "individual_large",
    "ShareholdingPattern": "total",
}

#: Categories that roll up into DII for the dashboard, when the filing does not
#: disclose an explicit domestic-institutions total.
_DII_KEYS = frozenset({
    "mutual_fund", "insurance", "bank", "pension_fund", "aif",
    "other_financial_inst", "nbfc_institution", "domestic_swf",
})


def _member_to_category(member: str) -> str:
    """Map a taxonomy member's local name onto a Finora category.

    Lookup is exact after stripping the taxonomy's ``Member`` suffix. Prefix
    matching is deliberately avoided: ``InstitutionsForeign`` and
    ``InstitutionsForeignPortfolioInvestorCategoryOne`` share a prefix but are
    an aggregate and one of its components, and matching the prefix reported
    foreign institutional holding at 36.5% instead of 18.3% by counting the
    aggregate twice.
    """
    local = member.split(":")[-1].strip()
    if local.endswith("Member"):
        local = local[: -len("Member")]
    return _MEMBER_MAP.get(local, "")


def _pct(value: Any) -> Optional[float]:
    """Parse a percentage that may arrive as a float, a string, or as XBRL text.

    The flat master sends ``"50.48"``. The XBRL sends a decimal fraction with
    a ``scale`` attribute, so ``0.5048`` at scale 2 means 50.48. Both have to
    land in the same place or a promoter trend would be nonsense.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "NA", "N/A"}:
        return None
    match = _PCT_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# The flat master: promoter and public over time
# ---------------------------------------------------------------------------


@dataclass
class OwnershipRecord:
    """One quarter's shareholding pattern."""

    as_of: str
    promoter_pct: Optional[float] = None
    public_pct: Optional[float] = None
    categories: dict[str, float] = field(default_factory=dict)
    xbrl_url: str = ""
    record_id: str = ""
    source_id: str = ""
    #: The period the category breakdown actually came from. Normally equal to
    #: ``as_of``; differs only when the taxonomy and the summary table carry
    #: different period stamps, and is kept so the evidence trail is honest.
    category_period: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "promoter_pct": self.promoter_pct,
            "public_pct": self.public_pct,
            "categories": dict(self.categories),
            "category_period": self.category_period or self.as_of,
            "xbrl_url": self.xbrl_url,
            "record_id": self.record_id,
        }


@dataclass
class OwnershipResult:
    """Ownership history plus whatever went wrong, for the evidence ledger."""

    symbol: str
    records: list[OwnershipRecord] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    sources: list[CanonicalSource] = field(default_factory=list)
    #: Categories seen, so the dashboard can say what this company discloses.
    category_coverage: dict[str, int] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(self.records)

    @property
    def latest(self) -> Optional[OwnershipRecord]:
        return self.records[-1] if self.records else None

    def to_canonical(self) -> list[CanonicalOwnership]:
        """Convert to the canonical model, with period-over-period change.

        Change is computed here rather than left to the caller so the number in
        the dashboard, the number the forensics detector compares, and the
        number the AI quotes are the same number.
        """
        out: list[CanonicalOwnership] = []
        for index, record in enumerate(self.records):
            promoter_change_qoq = None
            promoter_change_yoy = None
            if record.promoter_pct is not None:
                if index >= 1 and self.records[index - 1].promoter_pct is not None:
                    promoter_change_qoq = round(
                        record.promoter_pct - self.records[index - 1].promoter_pct, 4
                    )
                if index >= 4 and self.records[index - 4].promoter_pct is not None:
                    promoter_change_yoy = round(
                        record.promoter_pct - self.records[index - 4].promoter_pct, 4
                    )

            # Prefer the filing's own domestic-institutions total. Summing the
            # components is a fallback for filers who disclose the parts and
            # not the aggregate.
            dii = record.categories.get("dii_total")
            if dii is None:
                dii = _sum_categories(record.categories, _DII_KEYS)
            fii = record.categories.get("fii")

            out.append(CanonicalOwnership(
                period=record.as_of,
                promoter_pct=record.promoter_pct,
                promoter_change_qoq=promoter_change_qoq,
                promoter_change_yoy=promoter_change_yoy,
                promoter_pledge_pct=record.categories.get("promoter_pledge"),
                fii_pct=fii,
                dii_pct=dii,
                mutual_fund_pct=record.categories.get("mutual_fund"),
                public_pct=record.public_pct,
                institutional_pct=_round_or_none(
                    None if fii is None and dii is None else (fii or 0.0) + (dii or 0.0)
                ),
                government_pct=record.categories.get("central_government"),
                source_ids=[record.source_id] if record.source_id else [],
            ))
        return out


def _round_or_none(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 4)


def _sum_categories(categories: dict[str, float], keys: Iterable[str]) -> Optional[float]:
    present = [categories[k] for k in keys if k in categories]
    if not present:
        return None
    return round(sum(present), 4)


# ---------------------------------------------------------------------------
# The flat master fetch
# ---------------------------------------------------------------------------


def _parse_date(raw: Any) -> str:
    """SEBI dates arrive as ``30-JUN-2026``."""
    text = str(raw or "").strip().upper()
    if not text or text in {"-", "NA"}:
        return ""
    from datetime import datetime
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def fetch_shareholding_master(symbol: str) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    """Fetch the promoter/public series for one symbol.

    Returns ``(records, failure)``. A failure is a structured dict, never an
    exception, because a missing shareholding pattern must not stop research.
    """
    result = http_client.fetch(
        NSE_SHAREHOLDING_URL,
        provider="nse_shareholding",
        kind="ownership",
        params={"index": "equities", "symbol": symbol},
        max_bytes=8_000_000,
    )
    if not result.ok or not result.text:
        return [], result.failure or {
            "stage": "shareholding_master",
            "url": NSE_SHAREHOLDING_URL,
            "reason": "shareholding master returned no data",
        }
    try:
        payload = json.loads(result.text)
    except json.JSONDecodeError as exc:
        return [], {
            "stage": "shareholding_master",
            "url": NSE_SHAREHOLDING_URL,
            "reason": f"shareholding master response was not JSON: {exc}",
        }
    if not isinstance(payload, list):
        return [], {
            "stage": "shareholding_master",
            "url": NSE_SHAREHOLDING_URL,
            "reason": "shareholding master returned an unexpected shape",
        }
    return payload, None


def _records_from_master(symbol: str, rows: list[dict[str, Any]]) -> list[OwnershipRecord]:
    """Build the quarterly series from the flat master.

    Newest last, because every downstream trend compares against the previous
    element and a reversed list would turn a promoter reduction into a rise.
    """
    seen: set[str] = set()
    out: list[OwnershipRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        as_of = _parse_date(row.get("date"))
        if not as_of or as_of in seen:
            continue
        seen.add(as_of)
        record_id = str(row.get("recordId") or "")
        out.append(OwnershipRecord(
            as_of=as_of,
            promoter_pct=_pct(row.get("pr_and_prgrp")),
            public_pct=_pct(row.get("public_val")),
            xbrl_url=str(row.get("xbrl") or ""),
            record_id=record_id,
            source_id=f"nse_shp_master:{record_id}" if record_id else "",
        ))
    out.sort(key=lambda r: r.as_of)
    return out


# ---------------------------------------------------------------------------
# The dimensional XBRL
# ---------------------------------------------------------------------------

_XBRL_NS = "{http://www.xbrl.org/2003/instance}"
_XBRLDI_NS = "{http://xbrl.org/2006/xbrldi}"


def parse_shareholding_xbrl(payload: bytes) -> dict[str, dict[str, float]]:
    """Extract the category breakdown from a shareholding XBRL attachment.

    Returns ``{iso_date: {category: percent}}``.

    The date key is essential. One attachment covers every quarter the filer
    has reported in that taxonomy, so summing across it inflates every
    category by the number of periods: FII read 36.54% instead of 18.33%
    because five quarters of the same holding were added together.

    The document is a dimensional fact set: every fact carries a
    ``contextRef``, and the context names both the shareholder category on the
    ``CategoryOfShareholdersAxis`` dimension and the instant it applies to. The
    categories are SEBI's, not the company's, so the same parser handles every
    filer.
    """
    try:
        from lxml import etree
    except ImportError:  # pragma: no cover - dependency is declared
        return {}

    try:
        parser = etree.XMLParser(
            resolve_entities=False, no_network=True, recover=False, huge_tree=False
        )
        root = etree.fromstring(payload, parser=parser)
    except Exception as exc:
        logger.warning("[india.ownership] shareholding XBRL unparseable: %s", exc)
        return {}

    contexts: dict[str, tuple[str, dict[str, str]]] = {}
    for context in root.findall(f".//{_XBRL_NS}context"):
        dims: dict[str, str] = {}
        for member in context.iter(f"{_XBRLDI_NS}explicitMember"):
            dimension = str(member.get("dimension") or "").split("}")[-1]
            dims[dimension] = (member.text or "").strip()
        instant_node = context.find(f"{_XBRL_NS}period/{_XBRL_NS}instant")
        instant = (instant_node.text or "").strip() if instant_node is not None else ""
        contexts[context.get("id") or ""] = (instant, dims)

    by_date: dict[str, dict[str, float]] = {}
    for element in root.iter():
        tag = element.tag
        if not isinstance(tag, str) or not tag.endswith("PercentageOfTotalVotingRights"):
            continue
        text = (element.text or "").strip()
        if not text:
            continue
        try:
            value = float(text)
        except ValueError:
            continue

        # The shareholding taxonomy states voting rights as a decimal fraction:
        # 0.4962 is 49.62%. An explicit ``scale`` attribute, where the filer
        # supplies one, is honoured first. Leaving this unconverted made every
        # institutional holding read as 0.2% instead of 20%.
        scale = element.get("scale")
        if scale is not None:
            try:
                value *= 10 ** int(scale)
            except ValueError:
                pass
        elif abs(value) <= 1.0:
            value *= 100.0

        instant, dims = contexts.get(element.get("contextRef") or "", ("", {}))
        if not instant:
            continue
        member = ""
        for dimension, value_text in dims.items():
            if "CategoryOfShareholders" in dimension:
                member = value_text
                break
        if not member:
            continue
        category = _member_to_category(member)
        if not category:
            continue
        bucket = by_date.setdefault(_iso_date(instant), {})
        # A category can appear more than once at one date (a filer may split a
        # category across contexts). Sum rather than overwrite, or the first
        # holder would stand in for the whole group.
        bucket[category] = round(bucket.get(category, 0.0) + value, 4)

    return {date_key: _collapse_aggregates(vals) for date_key, vals in by_date.items()}


def _iso_date(text: str) -> str:
    raw = str(text or "").strip()
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return raw
    return _parse_date(raw)


def _collapse_aggregates(categories: dict[str, float]) -> dict[str, float]:
    """Resolve the taxonomy's aggregate members against their components.

    A filing normally reports ``InstitutionsForeign`` *and* the three
    sub-members that make it up. Summing all four would report foreign
    institutional holding at roughly twice its true value, so the aggregate
    wins and the components are only added when no aggregate is present.

    ``retail`` is derived rather than read, because SEBI's "non-institutions"
    member is wider than retail: it contains bodies corporate and trusts, so
    taking it as retail overstated retail holding by roughly 7 points. The
    public total less the two institutional totals is the exact residual.
    """
    out = dict(categories)
    components = out.pop("fii_component", None)
    if "fii" not in out and components:
        out["fii"] = round(components, 4)

    if "dii_total" not in out:
        dii = _sum_categories(out, _DII_KEYS)
        if dii is not None:
            out["dii_total"] = dii

    public_total = out.get("public_total")
    fii = out.get("fii")
    dii_total = out.get("dii_total")
    if public_total is not None and fii is not None and dii_total is not None:
        out["retail"] = round(public_total - fii - dii_total, 4)

    return out


def _pick_period(
    by_date: dict[str, dict[str, float]], as_of: str
) -> tuple[str, dict[str, float]]:
    """Choose the quarter in an attachment that belongs to one record.

    An exact match is the normal case. When a filer stamps the summary table
    and the taxonomy a day or two apart, the nearest prior period within one
    quarter is used, because a shareholding pattern cannot change that fast and
    a neighbouring quarter is the only defensible fallback. Picking a later
    quarter would leak future data into an earlier record.
    """
    if as_of in by_date:
        return as_of, by_date[as_of]

    dates = sorted(d for d in by_date if d)
    if not dates:
        return "", {}

    try:
        target = date.fromisoformat(as_of)
    except ValueError:
        return dates[-1], by_date[dates[-1]]

    prior = [d for d in dates if d <= as_of]
    if not prior:
        return "", {}
    chosen = prior[-1]
    try:
        gap_days = (target - date.fromisoformat(chosen)).days
    except ValueError:
        return chosen, by_date[chosen]
    if gap_days > 100:
        return "", {}
    return chosen, by_date[chosen]


def _enrich_with_xbrl(
    records: list[OwnershipRecord],
    failures: list[dict[str, Any]],
    limit: int = 4,
) -> None:
    """Fill in the category breakdown for the most recent quarters.

    Bounded to the newest few periods: the category split is what the
    dashboard and the ownership detectors need, they are reported in
    descending prominence in every filing, and each attachment is about half a
    megabyte.

    Each attachment carries every quarter the filer has reported under that
    taxonomy, so it is parsed once and cached, and only the requested period is
    taken from it.
    """
    parsed: dict[str, dict[str, dict[str, float]]] = {}

    for record in reversed(records[-limit:]):
        if not record.xbrl_url or record.categories:
            continue
        url = record.xbrl_url
        if url not in parsed:
            result = http_client.fetch(
                url,
                provider="nse_shareholding_xbrl",
                kind="ownership",
                accept=("application/xml", "text/xml", "*/*"),
                max_bytes=12_000_000,
            )
            if not result.ok or not result.content:
                parsed[url] = {}
                failures.append({
                    "stage": "shareholding_xbrl",
                    "url": url,
                    "as_of": record.as_of,
                    "reason": "shareholding XBRL attachment unavailable",
                })
            else:
                parsed[url] = parse_shareholding_xbrl(result.content)

        by_date = parsed[url]
        if not by_date:
            if not any(f["stage"] == "shareholding_xbrl" and f["url"] == url
                       for f in failures):
                failures.append({
                    "stage": "shareholding_xbrl",
                    "url": url,
                    "as_of": record.as_of,
                    "reason": "no dimensional category facts found",
                })
            continue

        period, categories = _pick_period(by_date, record.as_of)
        if not categories:
            failures.append({
                "stage": "shareholding_xbrl",
                "url": url,
                "as_of": record.as_of,
                "reason": "attachment has no category facts for this period",
            })
            continue
        record.categories = dict(categories)
        record.source_id = record.source_id or ""
        if period and period != record.as_of:
            record.category_period = period


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def fetch_ownership(
    symbol: str,
    *,
    include_xbrl: bool = True,
    xbrl_periods: int = 4,
    retrieved_at: str = "",
) -> OwnershipResult:
    """Retrieve the full shareholding history for one NSE symbol.

    Always returns a result. An exchange that is down produces a result with
    ``available`` false and a recorded failure, so the dashboard can say
    "shareholding unavailable" instead of the research run failing.
    """
    result = OwnershipResult(symbol=symbol)
    if not symbol:
        result.failures.append({
            "stage": "ownership",
            "reason": "no NSE symbol to request shareholding for",
        })
        return result

    rows, failure = fetch_shareholding_master(symbol)
    if failure:
        result.failures.append(failure)
        return result

    result.records = _records_from_master(symbol, rows)
    if not result.records:
        result.failures.append({
            "stage": "shareholding_master",
            "reason": f"no shareholding pattern published for {symbol}",
        })
        return result

    if include_xbrl:
        _enrich_with_xbrl(result.records, result.failures, limit=xbrl_periods)

    for category in sorted({k for r in result.records for k in r.categories}):
        result.category_coverage[category] = sum(
            1 for r in result.records if category in r.categories
        )

    for record in result.records:
        if not record.source_id:
            continue
        result.sources.append(CanonicalSource(
            source_id=record.source_id,
            source_name=f"NSE shareholding pattern as at {record.as_of}",
            source_type=SOURCE_SHAREHOLDING,
            trust_tier="PRIMARY",
            document_type="SHAREHOLDING_PATTERN",
            document_title=f"Shareholding pattern - {record.as_of}",
            period=record.as_of,
            url=record.xbrl_url or NSE_SHAREHOLDING_URL,
            retrieved_at=retrieved_at,
            used_for="Promoter, public and institutional holding",
        ))

    return result
