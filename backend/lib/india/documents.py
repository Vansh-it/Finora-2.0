"""Document discovery and the filing registry.

What actually exists for free, measured against live NSE (see
``docs/SOURCE_POLICY.md``):

* ``/api/corporate-announcements`` returns every exchange filing with the
  subject line, the attachment PDF URL, category, and timestamp. This is the
  document index. It needs a cookie handshake first (see
  :func:`lib.india.http_client`).
* The ``hasXbrl`` flag on announcements is **not** trustworthy: it is set on
  records whose only attachment is a PDF newspaper clipping, and constructed
  ``/corporate/xbrl/{SYM}_{dt}_WEB.xml`` URLs return 404. So it is recorded
  as metadata and never used to decide whether structured data exists.
* Shareholding XBRL *is* genuinely structured and addressable, and is handled
  by :mod:`lib.india.ownership`.
* Financial statements therefore arrive as PDFs. Parsing quality is addressed
  in :mod:`lib.india.pdf_tables`, with rejection rather than guessing.

The registry is the single place that knows which document is the current
revision of a filing, so downstream stages never have to re-derive that.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Iterable, Optional

from lib.india import http_client, sources

logger = logging.getLogger("finora.india.documents")


class DocumentKind(str, Enum):
    """What a filing is, for the purpose of metric extraction."""

    ANNUAL_REPORT = "ANNUAL_REPORT"
    QUARTERLY_RESULT = "QUARTERLY_RESULT"
    ANNUAL_RESULT = "ANNUAL_RESULT"
    AUDITED_FINANCIALS = "AUDITED_FINANCIALS"
    SHAREHOLDING = "SHAREHOLDING"
    INSIDER_TRADING = "INSIDER_TRADING"
    BOARD_MEETING = "BOARD_MEETING"
    AGM = "AGM"
    DIVIDEND = "DIVIDEND"
    FUNDRAISING = "FUNDRAISING"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    CREDIT_RATING = "CREDIT_RATING"
    REGULATORY = "REGULATORY"
    PRESS_RELEASE = "PRESS_RELEASE"
    OTHER = "OTHER"

    @property
    def is_financial(self) -> bool:
        return self in {
            DocumentKind.ANNUAL_REPORT,
            DocumentKind.QUARTERLY_RESULT,
            DocumentKind.ANNUAL_RESULT,
            DocumentKind.AUDITED_FINANCIALS,
        }

    @property
    def is_annual(self) -> bool:
        """A full reporting period rather than a slice of one."""
        return self in {
            DocumentKind.ANNUAL_REPORT,
            DocumentKind.ANNUAL_RESULT,
        }

    @property
    def is_period_document(self) -> bool:
        """A kind for which a fiscal quarter is a meaningful attribute.

        Quarterly and annual results describe a slice of a fiscal year. A
        shareholding pattern, an AGM notice or a credit rating does not, and
        stamping a quarter onto those would invent one.
        """
        return self.is_financial


# Documents that merely *discuss* results. These match the financial keyword
# rules but are not statements, so they are demoted before any other rule runs.
# Measured example: Reliance's
# "kavinavora_19072026180618_SE_Transcript.pdf" is an analyst-call transcript
# whose text says "unaudited financial results (Consolidated and Standalone)",
# and was being classified as AUDITED_FINANCIALS before this list existed.
_COMMENTARY_TEXT = re.compile(
    r"transcript|press release|newspaper|media|presentation|slide deck|"
    r"audio|video|webcast|analyst|investor meet|con\.?\s*call|"
    r"letter to (shareholders|stock exchang)|clippings|advertisement|"
    r"copy of newspaper|news verification|open house|intimation of (the )?date",
    re.I,
)
_COMMENTARY_FILENAME = re.compile(
    r"transcript|_MR[_.]|media[_.]?release|press[_.]?release|presentation|"
    r"newspaper|_PR[_.]|advert|clippings|intimation|notice|letter|"
    r"_AGM[_.]|-AGM[_.]|AGM\.pdf|Proxy|NoticeOfMeeting|ResultsAnnouncement",
    re.I,
)
# NSE itself labels the results announcement with these categories.
_RESULTS_CATEGORIES = re.compile(
    r"outcome of board meeting|board meeting|financial results|results|"
    r"audited|annual report|integrated",
    re.I,
)

# Ordered rules: first match wins, so the more specific patterns come first.
# Each entry is (kind, pattern).
#
# Order matters twice over. Period-specific rules come before the bare
# ``audited`` rule so that a filing is named for the period it reports rather
# than for its assurance level - audit status is carried separately by the
# taxonomy, and mixing the two produced "AUDITED_FINANCIALS" for every
# quarterly results announcement. And ``audited`` is guarded with a negative
# lookbehind because "unaudited" literally contains it.
_RULES: tuple[tuple[DocumentKind, str], ...] = (
    (DocumentKind.QUARTERLY_RESULT,
     r"(?:un)?(?:audited)?\s*(?:consolidated\s+|stand\s?alone\s+)*"
     r"financial\s+results?\s+(?:for|of)\s+the\s+quarter"),
    (DocumentKind.ANNUAL_RESULT,
     r"annual\s+(?:results|financial)|financial\s+results?\s+for\s+the\s+year|"
     r"results?\s+for\s+the\s+(?:financial\s+)?year"),
    (DocumentKind.QUARTERLY_RESULT, r"quarterly\s+(?:results|financial)"),
    # Unaudited results with no stated period. SEBI requires an audit only for
    # annual and half-year statements, so an unaudited results announcement is a
    # quarterly one. This rule is also what stops the bare form from falling
    # through to OTHER once the audit wording is correctly excluded.
    (DocumentKind.QUARTERLY_RESULT,
     r"un[-\s_]?audited\s+(?:consolidated\s+|stand\s?alone\s+)*"
     r"(?:financial\s+)?results?"),
    (DocumentKind.AUDITED_FINANCIALS,
     r"(?<!\bun)(?<!\bun-)(?<!\bun_)(?<!\bun )audited\s+"
     r"(?:consolidated\s+|stand\s?alone\s+)*"
     r"(?:condensed\s+)?(?:financial\s+)?(?:results|statements)"),
    (DocumentKind.ANNUAL_REPORT, r"annual report"),
    (DocumentKind.ANNUAL_REPORT, r"integrated report|integrated annual report"),
    (DocumentKind.ANNUAL_REPORT, r"integrated filing"),
    (DocumentKind.SHAREHOLDING,
     r"shareholding (pattern|as on)|statement of shareholding|shareholding pattern"),
    (DocumentKind.SHAREHOLDING, r"\bshp\b|shareholding"),
    (DocumentKind.INSIDER_TRADING, r"insider trading|regulation of insider"),
    (DocumentKind.AGM, r"annual general meeting|\bagm\b|shareholders meeting"),
    (DocumentKind.DIVIDEND, r"dividend|record date"),
    (DocumentKind.FUNDRAISING,
     r"rights issue|bonus issue|issue of (shares|securities)|qip|follow.on offer|"
     r"preferential issue|gdr|\badrs\b|convertible|warrant|fund raising|fundraising|"
     r"debt securities|bond issue|commercial paper|securitis|allotment of securities"),
    (DocumentKind.CORPORATE_ACTION,
     r"acquisition|merger|amalgamation|demerger|demutualis|stake (acquisition| sale)|"
     r"disposal|divestit|restructur|name change|scheme of arrangement"),
    (DocumentKind.CREDIT_RATING, r"credit rating|rating (action|agency|revision)"),
    (DocumentKind.BOARD_MEETING, r"outcome of board meeting|board meeting"),
    (DocumentKind.REGULATORY,
     r"sebi|regulatory|penalty|show cause|inspection|nos|surveillance|"
     r"trading window|compliance|certificate under|disclosure under"),
    (DocumentKind.PRESS_RELEASE, r"press release|newspaper|presentation|media"),
)

_COMPILED: tuple[tuple[DocumentKind, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pat, re.I)) for kind, pat in _RULES
)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_FY_RE = re.compile(r"financial year\s*(\d{4})[-/ ](\d{2})", re.I)
_YEAR_PAIR_RE = re.compile(r"\b(\d{2,4})\s*[-–/]\s*(\d{2,4})\b")
_QUARTER_RE = re.compile(r"quarter\s*(?:ended)?\s*(?:on)?\s*([0-3]{1,2})\s*", re.I)
_QUARTER_NUM_RE = re.compile(r"\bq([1-4])\s*fy\s*(\d{2,4})", re.I)
#: A bare "Q3" with no fiscal year attached. Indian filings use this constantly
#: ("Q3 FY27 results", "Q1 PAT"), and without it the quarter silently fell back
#: to the period-end month, which reported the wrong quarter.
_BARE_QUARTER_RE = re.compile(r"\bq([1-4])\b(?!\s*fy)", re.I)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def parse_nse_timestamp(raw: Any) -> str:
    """``'25-Sep-2026 22:49:03'`` -> ISO ``'2026-09-25T22:49:03'``."""
    text = (raw or "").strip()
    if not text:
        return ""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return ""


def _parse_size(raw: str) -> int:
    m = re.match(r"^\s*([\d.,]+)\s*(bytes|kb|mb|gb)?\s*$", (raw or "").lower())
    if not m:
        return 0
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return 0
    unit = m.group(2) or "bytes"
    mult = {"bytes": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3}[unit]
    return int(value * mult)


def fiscal_year_of(when: date) -> int:
    """Indian FY label: Apr 2026 - Mar 2027 is FY2026."""
    return when.year + 1 if when.month >= 4 else when.year


def _fiscal_year_from_text(text: str, filed: Optional[date]) -> Optional[int]:
    m = _FY_RE.search(text or "")
    if m:
        start = int(m.group(1))
        return start + 1 if start % 100 < 50 else start + 1
    q = _QUARTER_NUM_RE.search(text or "")
    if q and filed:
        return int(q.group(2)) + (1 if len(q.group(2)) == 2 else 0)
    return fiscal_year_of(filed) if filed else None


def detect_period_end(text: str) -> str:
    """Pull an explicit period end out of filing prose.

    Indian filings say "quarter ended June 30, 2026" or "for the year ended
    31st March, 2026". Returns ISO date or ``""``.
    """
    t = text or ""
    m = re.search(
        r"(?:quarter|year|period)\s+ended\s+(?:on\s+)?([0-3]{1,2})(?:st|nd|rd|th)?\s+"
        r"([A-Za-z]{3,9}),?\s*(\d{4})",
        t, re.I,
    )
    if m:
        day = int(m.group(1))
        mon = _MONTHS.get(m.group(2)[:3].lower())
        if mon and 1 <= day <= 31:
            try:
                return date(int(m.group(3)), mon, day).isoformat()
            except ValueError:
                return ""
    m = re.search(
        r"([0-3]{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9}),?\s*(\d{4})", t, re.I
    )
    if m:
        day = int(m.group(1))
        mon = _MONTHS.get(m.group(2)[:3].lower())
        if mon and 1 <= day <= 31:
            try:
                return date(int(m.group(3)), mon, day).isoformat()
            except ValueError:
                return ""
    # Month-first is the other common order and was not handled: filings and
    # results PDFs both write "June 30, 2026" as readily as "30th June, 2026".
    m = re.search(
        r"([A-Za-z]{3,9})\.?\s+([0-3]{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", t, re.I
    )
    if m:
        mon = _MONTHS.get(m.group(1)[:3].lower())
        day = int(m.group(2))
        if mon and 1 <= day <= 31:
            try:
                return date(int(m.group(3)), mon, day).isoformat()
            except ValueError:
                return ""
    return ""


def explicit_quarter(text: str) -> Optional[int]:
    """Quarter stated in the wording, or ``None`` if the text does not say.

    Kept separate from the period-end derivation because the two disagree in a
    way that matters: "for the year ended December 31, 2024" derives Q3 from
    the month, but an annual filing is not a third quarter.
    """
    t = text or ""
    m = _QUARTER_RE.search(t)
    if m and m.group(1) in "1234":
        return int(m.group(1))
    m = _QUARTER_NUM_RE.search(t)
    if m:
        return int(m.group(1))
    m = _BARE_QUARTER_RE.search(t)
    if m:
        return int(m.group(1))
    return None


def detect_quarter(text: str, period_end: str) -> Optional[int]:
    """Quarter from the wording, falling back to the period-end month."""
    stated = explicit_quarter(text)
    if stated is not None:
        return stated
    if period_end:
        month = int(period_end[5:7])
        return {3: 4, 6: 1, 9: 2, 12: 3}.get(month)
    return None


def detect_scope(text: str) -> str:
    """Consolidated vs standalone. NSE filings list both in one PDF."""
    t = (text or "").lower()
    has_consolidated = "consolidated" in t
    has_standalone = "standalone" in t or "stand alone" in t
    if has_consolidated and not has_standalone:
        return "CONSOLIDATED"
    if has_standalone and not has_consolidated:
        return "STANDALONE"
    return "BOTH"


#: Indian listed companies file results within 30-45 days of quarter end, and
#: annual results within 60 days of 31 March. So a result filing whose prose
#: omits the period almost always describes the quarter that just closed.
#: Maps a filing month to ``(month, day, year_offset)`` of that period end.
_QUARTER_END_BY_FILING_MONTH: dict[int, tuple[int, int, int]] = {
    1: (12, 31, -1),   # Jan/Feb  -> Q3 ended 31 Dec of the previous year
    2: (12, 31, -1),
    3: (3, 31, 0),     # Mar-Jun  -> year ended 31 Mar of the same year
    4: (3, 31, 0),
    5: (3, 31, 0),
    6: (3, 31, 0),
    7: (6, 30, 0),     # Jul-Sep  -> Q1 ended 30 Jun
    8: (6, 30, 0),
    9: (6, 30, 0),
    10: (9, 30, 0),    # Oct-Dec  -> Q2 ended 30 Sep
    11: (9, 30, 0),
    12: (9, 30, 0),
}


def infer_period_end(filed: date, kind: "DocumentKind") -> str:
    """Best-effort period end for a result filing with no explicit date.

    Recorded as inferred, never as verified: the PDF parser confirms or
    overrides it, and the value is only used when nothing better exists.
    """
    entry = _QUARTER_END_BY_FILING_MONTH.get(filed.month)
    if not entry:
        return ""
    month, day, year_offset = entry
    try:
        return date(filed.year + year_offset, month, day).isoformat()
    except ValueError:
        return ""


def fiscal_year_for_period(period_end: str) -> Optional[int]:
    """FY label from a period end: Apr-Dec is FY of the ending year, Jan-Mar the prior.

    A year ended 31 March 2026 is FY2026; a quarter ended 30 June 2026 is FY2027.
    """
    try:
        d = date.fromisoformat(period_end)
    except (TypeError, ValueError):
        return None
    return d.year + 1 if d.month >= 4 else d.year


def classify(category: str, text: str, filename: str = "") -> DocumentKind:
    """Map an NSE announcement onto a :class:`DocumentKind`.

    Order matters: commentary (transcripts, media releases, AGM notices) is
    excluded first, because those documents quote result figures in prose and
    would otherwise be mistaken for statements.
    """
    name = (filename or "").rsplit("/", 1)[-1]
    haystack = f"{category or ''} {text or ''}"

    if _COMMENTARY_TEXT.search(haystack) or _COMMENTARY_FILENAME.search(name):
        # An AGM notice that happens to mention the annual report is still an
        # AGM notice.
        if not _RESULTS_CATEGORIES.search(category or ""):
            return DocumentKind.PRESS_RELEASE
        # Otherwise fall through: e.g. "Outcome of Board Meeting" filings are
        # the actual results and must not be demoted by a stray "notice" word.

    for kind, pattern in _COMPILED:
        if pattern.search(haystack):
            return kind
    return DocumentKind.OTHER


# ---------------------------------------------------------------------------
# Filing record
# ---------------------------------------------------------------------------
@dataclass
class FilingDocument:
    """One discovered filing, normalised."""

    doc_id: str
    kind: DocumentKind
    category: str
    title: str
    source: str
    source_url: str
    filed_at: str = ""
    period_end: str = ""
    #: "EXPLICIT" when the filing prose named the period, "INFERRED" when it
    #: came from the standard filing-lag pattern, "NONE" when unknown.
    period_end_source: str = "NONE"
    #: Set by the PDF parser once the document's own header confirms the period.
    period_end_verified: bool = False
    fiscal_year: Optional[int] = None
    quarter: Optional[int] = None
    scope: str = "BOTH"
    size_bytes: int = 0
    has_xbrl_flag: bool = False
    xbrl_url: str = ""
    revision: int = 1
    revision_of: str = ""
    #: Original announcement classification when the PDF contents overrode it.
    reclassified_from: str = ""
    is_current: bool = True
    seq_id: str = ""

    @property
    def is_pdf(self) -> bool:
        return self.source_url.lower().endswith(".pdf")

    @property
    def period_key(self) -> str:
        """Identity of the *period* a filing covers, for revision grouping."""
        if self.period_end:
            return f"{self.kind.value}:{self.period_end}"
        if self.fiscal_year:
            q = f"Q{self.quarter}" if self.quarter else "FY"
            return f"{self.kind.value}:FY{self.fiscal_year}-{q}"
        return f"{self.kind.value}:{self.filed_at[:10]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "kind": self.kind.value,
            "category": self.category,
            "title": self.title,
            "source": self.source,
            "source_url": self.source_url,
            "filed_at": self.filed_at,
            "period_end": self.period_end,
            "period_end_source": self.period_end_source,
            "period_end_verified": self.period_end_verified,
            "fiscal_year": self.fiscal_year,
            "quarter": self.quarter,
            "scope": self.scope,
            "size_bytes": self.size_bytes,
            "has_xbrl_flag": self.has_xbrl_flag,
            "xbrl_url": self.xbrl_url,
            "revision": self.revision,
            "revision_of": self.revision_of,
            "reclassified_from": self.reclassified_from,
            "is_current": self.is_current,
            "is_financial": self.kind.is_financial,
            "is_pdf": self.is_pdf,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
@dataclass
class IndiaDocumentRegistry:
    """Every discovered filing for one company, with revisions resolved."""

    symbol: str
    documents: list[FilingDocument] = field(default_factory=list)
    company_name: str = ""
    industry: str = ""
    isin_from_source: str = ""
    failures: list[dict[str, Any]] = field(default_factory=list)
    coverage_start: str = ""
    coverage_end: str = ""

    def by_kind(self, *kinds: DocumentKind) -> list[FilingDocument]:
        wanted = set(kinds)
        return [d for d in self.documents if d.kind in wanted and d.is_current]

    def current(self, kind: DocumentKind) -> list[FilingDocument]:
        return self.by_kind(kind)

    def financial_documents(self) -> list[FilingDocument]:
        return self.by_kind(
            DocumentKind.ANNUAL_REPORT,
            DocumentKind.QUARTERLY_RESULT,
            DocumentKind.ANNUAL_RESULT,
            DocumentKind.AUDITED_FINANCIALS,
        )

    def latest_financials(self, n: int = 8) -> list[FilingDocument]:
        """Most recent financial filings, newest first."""
        docs = sorted(
            self.financial_documents(),
            key=lambda d: (d.filed_at or "", d.period_end or ""),
            reverse=True,
        )
        return docs[:n]

    def promotable(self, limit: int = 12) -> list[FilingDocument]:
        """Non-financial filings that are still worth opening as PDFs.

        Many companies post results under a neutral category such as "Outcome
        of Board Meeting" or "Updates" with the results statement as the
        attachment. The announcement text alone cannot tell, so these documents
        are offered to the PDF stage, which decides from the document's own
        header. Everything here is large enough to plausibly be a statement.
        """
        out: list[FilingDocument] = []
        for doc in self.documents:
            if not doc.is_current or doc.kind.is_financial:
                continue
            if doc.kind in {
                DocumentKind.BOARD_MEETING,
                DocumentKind.OTHER,
                DocumentKind.PRESS_RELEASE,
                DocumentKind.AGM,
            } and doc.size_bytes >= 60_000:
                out.append(doc)
        out.sort(key=lambda d: (d.filed_at or ""), reverse=True)
        return out[:limit]

    def promote(self, doc: FilingDocument, kind: DocumentKind,
                period_end: str = "") -> FilingDocument:
        """Re-classify a document after its own contents proved it mislabelled.

        The announcement category and the attachment frequently disagree, and
        the attachment wins because it is the primary document. The original
        classification is kept in :attr:`reclassified_from` for audit.
        """
        if not doc.reclassified_from:
            doc.reclassified_from = doc.kind.value
        doc.kind = kind
        if period_end and period_end != doc.period_end:
            doc.period_end = period_end
            doc.period_end_source = "EXPLICIT"
            doc.period_end_verified = True
            doc.fiscal_year = fiscal_year_for_period(period_end) or doc.fiscal_year
            doc.quarter = detect_quarter("", period_end) or doc.quarter
        return doc

    def periods_with_financials(self) -> list[str]:
        seen: dict[str, None] = {}
        for d in self.financial_documents():
            key = d.period_end or (f"FY{d.fiscal_year}" if d.fiscal_year else "")
            if key:
                seen[key] = None
        return sorted(seen)

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for d in self.documents:
            counts[d.kind.value] = counts.get(d.kind.value, 0) + 1
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "industry": self.industry,
            "isin_from_source": self.isin_from_source,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "document_count": len(self.documents),
            "counts_by_kind": counts,
            "current_counts": {
                k: sum(1 for d in self.documents if d.kind.value == k and d.is_current)
                for k in counts
            },
            "periods_with_financials": self.periods_with_financials(),
            "failures": list(self.failures),
            "documents": [d.to_dict() for d in self.documents],
        }


# ---------------------------------------------------------------------------
# Fetching announcements
# ---------------------------------------------------------------------------
def _warm_session(symbol: str) -> None:
    """NSE refuses JSON API calls until a normal page has set cookies."""
    http_client.counted_fetch(
        sources.NSE_WARMUP_URL,
        provider="nse_warmup",
        kind="events",
        params={"symbol": symbol} if symbol else None,
        headers={"Referer": sources.nse_referer(symbol)},
        accept=("text/html", "text/plain", "*/*"),
        max_bytes=3 * 1024 * 1024,
    )


def fetch_announcements(
    symbol: str,
    from_date: date,
    to_date: date,
    index: str = "equities",
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    """Fetch raw NSE announcements. Returns ``(records, failure)``."""
    _warm_session(symbol)
    res = http_client.counted_fetch(
        sources.NSE_ANNOUNCEMENTS_URL,
        provider="nse_announcements",
        kind="events",
        params={
            "index": index,
            "symbol": symbol,
            "from_date": from_date.strftime("%d-%m-%Y"),
            "to_date": to_date.strftime("%d-%m-%Y"),
        },
        headers={
            "Referer": sources.nse_referer(symbol),
            "Accept": "application/json,text/plain,*/*",
        },
        accept=("application/json", "text/plain", "*/*"),
        max_bytes=24 * 1024 * 1024,
    )
    if not res.ok:
        return [], (res.failure.to_dict() if res.failure else {"reason": "unknown"})
    import json

    try:
        payload = json.loads(res.text)
    except ValueError as exc:
        return [], {"provider": "nse_announcements", "reason": f"bad_json: {exc}"}
    if not isinstance(payload, list):
        return [], {"provider": "nse_announcements", "reason": "unexpected_payload_shape"}
    return [r for r in payload if isinstance(r, dict)], None


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------
def _doc_from_record(record: dict[str, Any], symbol: str) -> Optional[FilingDocument]:
    url = (record.get("attchmntFile") or "").strip()
    if not url:
        return None
    if not url.lower().startswith("http"):
        return None

    category = (record.get("desc") or "").strip()
    text = (record.get("attchmntText") or "").strip()
    filed_at = parse_nse_timestamp(record.get("an_dt") or record.get("sort_date"))
    filed_date = filed_at[:10] or None
    try:
        filed = date.fromisoformat(filed_date) if filed_date else None
    except ValueError:
        filed = None

    kind = classify(category, text, url)
    period_end = detect_period_end(text)
    period_source = "EXPLICIT" if period_end else "NONE"
    if not period_end and kind.is_financial and filed:
        # NSE's attchmntText is not a reliable period source, so fall back to
        # the standard filing-lag rule and label the result as inferred.
        inferred = infer_period_end(filed, kind)
        if inferred:
            period_end, period_source = inferred, "INFERRED"
    # A quarter is only an attribute of a period document, and for an annual
    # filing only an explicitly stated one is believable: deriving it from the
    # period-end month stamped an annual report covering December 2024 as "Q3".
    if not kind.is_period_document:
        quarter = None
    else:
        quarter = explicit_quarter(text)
        if quarter is None and kind.is_annual:
            # A full year running to the March year end is Q4 by convention.
            quarter = 4 if period_end.endswith("-03-31") else None
        elif quarter is None and period_end:
            month = int(period_end[5:7]) if len(period_end) >= 7 else 0
            quarter = {3: 4, 6: 1, 9: 2, 12: 3}.get(month)
    # The FY label must follow the period the numbers cover, not the date they
    # were filed. A year ended 31 March 2026 is FY2026 even though it is filed
    # in April 2026.
    fy = fiscal_year_for_period(period_end) or _fiscal_year_from_text(text, filed)
    seq = str(record.get("seq_id") or "").strip()
    doc_id = f"{symbol}:{seq or record.get('dt') or url.rsplit('/', 1)[-1]}"

    return FilingDocument(
        doc_id=doc_id,
        kind=kind,
        category=category,
        title=(text[:300] or category or url.rsplit("/", 1)[-1]),
        source=sources.source_type_for("nseindia.com"),
        source_url=url,
        filed_at=filed_at,
        period_end=period_end,
        period_end_source=period_source,
        fiscal_year=fy,
        quarter=quarter,
        scope=detect_scope(text),
        size_bytes=_parse_size(record.get("attFileSize") or record.get("fileSize") or ""),
        # Recorded only. Measured: this flag is set on filings whose only
        # attachment is a newspaper PDF, so it is never a parse strategy input.
        has_xbrl_flag=bool(record.get("hasXbrl")),
        seq_id=seq,
    )


def _resolve_revisions(documents: list[FilingDocument]) -> list[FilingDocument]:
    """Mark superseded filings.

    NSE does not publish a revision field, so revisions are detected the way
    an analyst would: same kind and same period, filed more than once. The
    newest filing for a period is current; earlier ones are kept for audit with
    ``is_current=False``.
    """
    groups: dict[str, list[FilingDocument]] = {}
    for d in documents:
        groups.setdefault(d.period_key, []).append(d)

    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda d: (d.filed_at or "", d.doc_id))
        for index, doc in enumerate(members, start=1):
            doc.revision = index
            doc.is_current = index == len(members)
            if index > 1:
                doc.revision_of = members[0].doc_id
    return documents


def discover(
    symbol: str,
    months_back: int = 30,
    today: Optional[date] = None,
    kinds: Optional[Iterable[DocumentKind]] = None,
) -> IndiaDocumentRegistry:
    """Discover filings for a company and return a resolved registry.

    ``months_back`` bounds the NSE query, which is a single call for the whole
    window; older history can be requested by widening it.
    """
    end = today or date.today()
    start = end - timedelta(days=int(months_back * 30.44))
    registry = IndiaDocumentRegistry(
        symbol=symbol,
        coverage_start=start.isoformat(),
        coverage_end=end.isoformat(),
    )

    records, failure = fetch_announcements(symbol, start, end)
    if failure:
        logger.warning("[india.docs] announcements failed for %s: %s", symbol, failure)
        registry.failures.append(failure)
        return registry

    wanted = set(kinds) if kinds else None
    seen: set[str] = set()
    for record in records:
        doc = _doc_from_record(record, symbol)
        if doc is None or doc.doc_id in seen:
            continue
        if wanted and doc.kind not in wanted:
            continue
        seen.add(doc.doc_id)
        if record.get("sm_name") and not registry.company_name:
            registry.company_name = str(record["sm_name"])
        if record.get("smIndustry") and not registry.industry:
            registry.industry = str(record["smIndustry"])
        if record.get("sm_isin") and not registry.isin_from_source:
            registry.isin_from_source = str(record["sm_isin"]).upper()
        registry.documents.append(doc)

    registry.documents.sort(key=lambda d: (d.filed_at or ""), reverse=True)
    _resolve_revisions(registry.documents)
    logger.info(
        "[india.docs] %s: %d filings (%d current financial) over %s..%s",
        symbol, len(registry.documents), len(registry.financial_documents()),
        registry.coverage_start, registry.coverage_end,
    )
    return registry
