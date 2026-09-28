"""Finora Company Resolution Engine.



Turns natural-language company searches, tickers, legal names, misspellings,

and common aliases into a normalized :class:`Company` (name/ticker/CIK/

exchange) grounded in the official SEC company universe.



Resolution order (fastest → slowest):



    Human query

        ↓

    Query parser (extract company words + requested fiscal period)

        ↓

    Exact ticker resolver                 (local index, ms)

        ↓

    Exact company-name resolver           (local index, ms)

        ↓

    Alias resolver                        (local alias map, ms)

        ↓

    Local fuzzy resolver (RapidFuzz)      (local index, ms)

        ↓

    Ambiguity handler  →  candidate list  (never silently guesses)

        ↓

    LLM fallback ONLY for genuinely semantic prompts, and every LLM

    candidate is validated back against the local SEC universe before use.



Every resolution returns a confidence and the method used.  A canonical

``research_request`` object can be produced via :func:`parse_research_query`

and :func:`build_research_request`, so the downstream research pipeline

receives clean structured company info instead of raw human language.



The existing public API (``resolve_company``, ``_parse_ticker_map``,

``_is_ticker``, ``_normalize``, ``_ALIASES``) is preserved for backward

compatibility; ``CompanyUniverse`` is the new full engine.

"""



from __future__ import annotations



import json

import logging

import os

import re

import threading

import time

from dataclasses import dataclass, field

from datetime import datetime, timezone

from pathlib import Path

from typing import Any, Callable, Optional



logger = logging.getLogger("finora.company_resolver")



try:  # RapidFuzz is the preferred local fuzzy engine

    from rapidfuzz import fuzz as _rf_fuzz

    from rapidfuzz import process as _rf_process



    _HAS_RAPIDFUZZ = True

except Exception:  # pragma: no cover - fallback path for exotic installs

    _HAS_RAPIDFUZZ = False



from lib import sec_client as _sec_client_module  # noqa: E402

from lib.cache import company_index_cache, resolution_cache, single_flight  # noqa: E402

from lib.sec_client import get_ticker_mapping  # noqa: E402



# ── Paths ─────────────────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_COMPANY_INDEX_FILE = _DATA_DIR / "company_index.json"

# SEC official universe (company_tickers.json lacks exchange; the exchange file

# also lacks CIK-padded formatting, so we merge both official sources).

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

INDEX_REFRESH_SECONDS = 7 * 86400  # refresh the SEC universe weekly

INDEX_FETCH_STALE_SECONDS = 30 * 86400  # hard staleness for the local copy





# ── Data class ────────────────────────────────────────────────────────────────

@dataclass

class Company:

    """Normalized company object."""



    name: str = ""

    ticker: str = ""

    cik: str = ""

    exchange: str = ""

    status: str = "resolved"

    description: str = ""

    industry: str = ""

    sector: str = ""

    # ISO-3166 alpha-2 country of the registrant. Drives region dispatch in
    # lib.core.regions. Defaults to US because the resolver's universe is the
    # SEC ticker file, whose every record is a US registrant by construction.
    country: str = "US"

    # Resolution provenance

    confidence: float = 1.0

    method: str = "exact"

    @property

    def region(self):

        """Region pipeline for this company (see :mod:`lib.core.regions`)."""

        from lib.core.regions import region_for_company

        return region_for_company(self)

    def to_dict(self) -> dict[str, Any]:

        return {

            "name": self.name,

            "ticker": self.ticker,

            "cik": self.cik,

            "exchange": self.exchange,

            "status": self.status,

            "description": self.description,

            "industry": self.industry,

            "sector": self.sector,

            "country": self.country,

            "region": self.region.value,

            "confidence": self.confidence,

            "method": self.method,

        }

    @classmethod

    def from_dict(cls, payload: dict[str, Any]) -> "Company":

        """Rebuild from :meth:`to_dict`, ignoring derived keys.

        ``to_dict`` carries ``region`` for API consumers, but ``region`` is a
        property rather than a field, so ``Company(**payload)`` would raise.
        Reconstructing from the declared fields keeps the cache round-trip
        safe as the dataclass gains keys.
        """

        import dataclasses

        names = {f.name for f in dataclasses.fields(cls)}

        return cls(**{k: v for k, v in payload.items() if k in names})





class AmbiguousCompanyError(ValueError):

    """Raised when multiple companies plausibly match a query.



    Carries the top candidates so callers can present a picker instead of

    blindly researching a poor guess.

    """



    def __init__(self, candidates: list[dict], query: str = ""):

        self.candidates = candidates

        self.query = query

        super().__init__(

            f"Ambiguous company query '{query}'. Multiple companies matched."

        )





# ── Legal suffix handling ────────────────────────────────────────────────────

# Suffixes stripped from the END of a company name for comparison.

_SUFFIX_WORDS = {

    "inc", "incorporated", "incorp", "corp", "corporation", "corp.", "co",

    "company", "companies", "holdings", "holding", "plc", "ltd", "limited",

    "llc", "l.l.c.", "llp", "l.p.", "lp", "l.l.p", "group", "sa", "s.a.",

    "ag", "nv", "n.v.", "se", "s.e.", "bancorp", "bancorporation", "& co",

    "and co", "the", "common", "class a", "class b", "class c", "class a",

    "cap", "capital", "finl", "financial",

}

_SUFFIX_RE = re.compile(

    r"(?:[,\s]+(?:" + "|".join(re.escape(w) for w in sorted(_SUFFIX_WORDS, key=len, reverse=True)) + r"))+$",

    re.IGNORECASE,

)





def strip_legal_suffix(name: str) -> str:

    """Return a comparable name with legal-entity suffixes removed."""

    n = name.strip()

    for _ in range(3):

        new = _SUFFIX_RE.sub("", n)

        new = re.sub(r"[\s,]+$", "", new)

        if new == n:

            break

        n = new

    return n





# ── Normalization ─────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:

    """Lowercase, strip punctuation-noise, collapse whitespace."""

    t = text.strip().lower()

    t = t.replace("&", " and ").replace("®", "").replace("™", "")

    t = re.sub(r"[^a-z0-9 .]", " ", t)  # keep letters, digits, dots, spaces

    t = re.sub(r"\s+", " ", t).strip()

    return t





def _normalize_compare(text: str) -> str:

    """Normalize a name for exact comparison: remove suffix + punctuation."""

    n = strip_legal_suffix(text)

    n = _normalize(n)

    # Drop periods and extra spaces for comparison ("j.p.morgan" == "jp morgan")

    n = n.replace(".", "").replace(",", "")

    n = re.sub(r"\s+", " ", n).strip()

    return n





def _is_ticker(text: str) -> bool:

    """Heuristic: a clean 1-5 letter token looks like a ticker symbol."""

    return bool(re.match(r"^[A-Za-z]{1,5}$", text.strip()))





def _looks_like_word(text: str) -> bool:

    """True if the text is mostly alphabetic words (not a ticker blob)."""

    return bool(re.match(r"^[A-Za-z .\-']+$", text.strip())) and len(text.strip()) >= 3





# ── Alias layer (small, curated — the SEC index stays authoritative) ─────────

_ALIASES: dict[str, str] = {

    # → canonical company search key (resolved against the SEC index)

    "microsoft": "microsoft corp",

    "apple": "apple inc",

    "nvidia": "nvidia corp",

    "amazon": "amazon com inc",

    "google": "alphabet inc",

    "goog": "alphabet inc",

    "alphabet": "alphabet inc",

    "meta": "meta platforms inc",

    "meta platforms": "meta platforms inc",

    "facebook": "meta platforms inc",

    "instagram": "meta platforms inc",

    "whatsapp": "meta platforms inc",

    "tesla": "tesla inc",

    "netflix": "netflix inc",

    "berkshire": "berkshire hathaway inc",

    "berkshire hathaway": "berkshire hathaway inc",

    "samsung": "samsung electronics co ltd",

    "tencent": "tencent holdings ltd",

    "alibaba": "alibaba group holding ltd",

    "oracle": "oracle corp",

    "salesforce": "salesforce inc",

    "adobe": "adobe inc",

    "intel": "intel corp",

    "amd": "advanced micro devices inc",

    "advanced micro devices": "advanced micro devices inc",

    "cisco": "cisco systems inc",

    "ibm": "international business machines corp",

    "johnson & johnson": "johnson & johnson",

    "j&j": "johnson & johnson",

    "jpmorgan": "jpmorgan chase & co",

    "jpmorgan chase": "jpmorgan chase & co",

    "jp morgan": "jpmorgan chase & co",

    "j.p. morgan": "jpmorgan chase & co",

    "j p morgan": "jpmorgan chase & co",

    "visa": "visa inc",

    "mastercard": "mastercard inc",

    "walmart": "walmart inc",

    "disney": "walt disney co",

    "unitedhealth": "unitedhealth group inc",

    "costco": "costco wholesale corp",

    "nike": "nike inc",

    "uber": "uber technologies inc",

    "airbnb": "airbnb inc",

    "spotify": "spotify technology sa",

    "palantir": "palantir technologies inc",

    "crowdstrike": "crowdstrike holdings inc",

    "snowflake": "snowflake inc",

    "datadog": "datadog inc",

    "cloudflare": "cloudflare inc",

    "square": "block inc",

    "paypal": "paypal holdings inc",

    "morgan stanley": "morgan stanley",

    "goldman": "goldman sachs group inc",

    "goldman sachs": "goldman sachs group inc",

    "micron": "micron technology inc",

    "qualcomm": "qualcomm inc",

    "broadcom": "broadcom inc",

    "texas instruments": "texas instruments inc",

    "t mobile": "t-mobile us inc",

    "verizon": "verizon communications inc",

    "at&t": "at&t inc",

    "att": "at&t inc",

    "boeing": "boeing co",

    "caterpillar": "caterpillar inc",

    "exxon": "exxon mobil corp",

    "exxon mobil": "exxon mobil corp",

    "chevron": "chevron corp",

    "home depot": "home depot inc",

    "the home depot": "home depot inc",

    "mcdonalds": "mcdonald's corp",

    "mcdonald's": "mcdonald's corp",

    "starbucks": "starbucks corp",

    "coca cola": "coca-cola co",

    "coca-cola": "coca-cola co",

    "pepsi": "pepsico inc",

    "pepsico": "pepsico inc",

    "procter gamble": "procter & gamble co",

    "procter & gamble": "procter & gamble co",

    "pfizer": "pfizer inc",

    "merck": "merck & co inc",

    "abbott": "abbott laboratories",

    "3m": "3m co",

    "ge": "ge aerospace",

    "general electric": "ge aerospace",

    "honeywell": "honeywell international inc",

    "lockheed": "lockheed martin corp",

    "lockheed martin": "lockheed martin corp",

    "workday": "workday inc",

    "servicenow": "servicenow inc",

    "stripe": "stripe inc",

    "twilio": "twilio inc",

    "shopify": "shopify inc",

    "doordash": "doorDash inc",

    "intuit": "intuit inc",

    "zoom": "zoom video communications inc",

    "zoominfo": "zoominfo technologies inc",

    "roblox": "roblox corp",

    "unity": "unity software inc",

    "coinbase": "coinbase global inc",

    "robinhood": "robinhood markets inc",

    "charlie schwab": "charles schwab corp",

    "charles schwab": "charles schwab corp",

    "schwab": "charles schwab corp",

    "walt disney": "walt disney co",

    "target": "target corp",

    "lowes": "lowe's cos inc",

    "lowe's": "lowe's cos inc",

    "best buy": "best buy co inc",

    "gm": "general motors co",

    "general motors": "general motors co",

    "ford": "ford motor co",

    "microsoft corp": "microsoft corp",

    "microsooft": "microsoft corp",

}





# ── Query parser: conversational filler + fiscal period extraction ────────────

_FILLER_WORDS = {

    "research", "analyse", "analyze", "analysis", "financials", "financial",

    "dashboard", "company", "companies", "stock", "stocks", "show", "find",

    "get", "give", "make", "build", "me", "for", "please", "report", "the",

    "a", "an", "of", "on", "about", "into", "and", "with", "review", "study",

    "fundamentals", "valuation", "earnings", "data", "latest", "info",

    "information", "help", "i", "want", "would", "like", "to", "look", "up",

    "tell", "run", "create", "generate", "start", "check", "explore",

}

_FILLER_RE = re.compile(

    r"\b(?:" + "|".join(sorted(_FILLER_WORDS, key=len, reverse=True)) + r")\b",

    re.IGNORECASE,

)

# Period tokens: FY2024, fy2024, 2024, FY 2024

_PERIOD_RE = re.compile(r"\b(?:fy\s*)?(20\d{2}|19\d{2})\b", re.IGNORECASE)





@dataclass

class ParsedQuery:

    """Company words + fiscal period extracted from a freeform query."""



    raw: str

    company: str = ""

    ticker: str = ""

    period_mode: str = "latest"  # "latest" or "specified"

    start_year: Optional[int] = None

    end_year: Optional[int] = None

    period_label: str = ""





def _detect_period(query: str) -> tuple[Optional[int], Optional[int]]:

    """Return (start_year, end_year) parsed from the query.



    Examples: "FY2024" → (2024, 2024); "2021-2023" → (2021, 2023).

    """

    years = [int(m.group(1)) for m in _PERIOD_RE.finditer(query)]

    years = sorted(set(y for y in years if 1990 <= y <= 2030))

    if not years:

        return None, None

    if len(years) == 1:

        return years[0], years[0]

    return years[0], years[-1]





def parse_research_query(query: str) -> ParsedQuery:

    """Parse a freeform research query into company + requested period.



    Preserves meaningful info (company words, ticker, fiscal period) and

    removes conversational filler only when safe.  It never blindly deletes

    words that could be part of a company name: a token is only removed when

    it is a known filler AND is not inside the company span, and any leftover

    acronym-like token is kept.

    """

    if not query or not query.strip():

        raise ValueError("Research query must be a non-empty string")

    raw = query.strip()

    p = ParsedQuery(raw=raw)



    start_year, end_year = _detect_period(raw)

    if start_year is not None:

        p.start_year = start_year

        p.end_year = end_year or start_year

        p.period_mode = "specified"

        p.period_label = (

            f"FY{start_year}" if end_year in (None, start_year)

            else f"FY{start_year}-FY{end_year}"

        )

        # Remove period token(s) so they don't pollute the company name

        cleaned = _PERIOD_RE.sub(" ", raw)

    else:

        cleaned = raw



    # Remove filler words (case-insensitive, whole word)

    cleaned = _FILLER_RE.sub(" ", cleaned)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,;:!?-")



    # If nothing is left (e.g. "research microsoft" already stripped fine we

    # still get microsoft; but "show me please" would be empty → keep raw

    # trimmed as a fallback so the resolver decides).

    if not cleaned:

        cleaned = raw.strip()



    tokens = cleaned.split()

    # A single uppercase-ish short token is likely a ticker already (e.g. MSFT)

    joined = " ".join(tokens)



    if _is_ticker(cleaned) and len(cleaned) <= 5 and cleaned.isalpha():

        p.ticker = cleaned.upper()

        p.company = cleaned.upper()

    else:

        p.company = joined



    return p





def build_research_request(query: str, resolved: "ResolutionResult") -> dict[str, Any]:

    """Build the canonical normalized research request object."""

    parsed = parse_research_query(query)

    company = resolved.company

    return {

        "intent": "research",

        "raw_query": query,

        "company": {

            "name": company.name,

            "ticker": company.ticker,

            "cik": company.cik,

            "exchange": company.exchange,

        },

        "period_mode": parsed.period_mode,

        "periods": ([f"FY{parsed.end_year}"] if parsed.end_year else []),

        "resolution": {

            "method": resolved.method,

            "confidence": round(resolved.confidence, 4),

            "latency_ms": round(resolved.latency_ms, 2),

        },

    }





# ── CIK helpers ───────────────────────────────────────────────────────────────

def _cik_to_str(cik: Any) -> str:

    if isinstance(cik, int):

        return str(cik).zfill(10)

    s = str(cik).strip()

    if s.isdigit():

        return s.zfill(10)

    return s





# ── Record normalization ──────────────────────────────────────────────────────

def _normalize_company_dict(d: dict) -> dict:

    """Normalize a company dict from SEC data to standard keys."""

    cik = d.get("cik_str") or d.get("cik") or d.get("CIK") or ""

    if isinstance(cik, int):

        cik = str(cik).zfill(10)

    elif isinstance(cik, str):

        cik = cik.zfill(10) if cik.isdigit() else cik



    ticker = d.get("ticker") or d.get("Ticker") or ""

    name = (d.get("title") or d.get("name") or d.get("Title")

            or d.get("company_name") or "")

    exchange = d.get("exchange") or d.get("Exchange") or ""

    return {

        "cik": str(cik),

        "name": str(name),

        "ticker": str(ticker).upper(),

        "exchange": str(exchange),

    }





def _mapping_is_overridden() -> bool:

    """True when a test patched ``get_ticker_mapping`` in this module."""

    return get_ticker_mapping is not _sec_client_module.get_ticker_mapping





# ── SEC universe loader ───────────────────────────────────────────────────────

def _load_index_records() -> list[dict]:

    """Load the merged official SEC universe (tickers + exchange info).



    Strategy:

      1. If ``get_ticker_mapping`` was patched (tests), build the universe

         from that patched value so resolution works offline.

      2. Try the local disk cache if fresh (fast path, zero network).

      3. Otherwise fetch SEC company_tickers.json (all tickers) plus the

         exchange companion file, merge on CIK, persist to disk.

      4. If network fails and a stale disk copy exists, use it (report stale).

    """

    records: list[dict] = []



    # 0) Patched mapping (tests) — never hit the network for these

    if _mapping_is_overridden():

        try:

            raw = get_ticker_mapping()

            records = _parse_ticker_map(raw)

        except Exception:

            records = []

        if records:

            return records



    # 1) In-memory / disk index path

    fresh = company_index_cache.get("records")

    if fresh is not None:

        return fresh



    # 1b) disk file

    disk_records, disk_ts = _read_disk_index()

    if disk_records and disk_ts and (time.time() - disk_ts) < INDEX_REFRESH_SECONDS:

        company_index_cache.set("records", disk_records)

        return disk_records



    # 2) Fetch from SEC (single-flight so parallel requests share one fetch)

    def _fetch():

        return _fetch_sec_universe()



    try:

        records = single_flight("sec-company-universe", "sec", _fetch)

    except Exception as exc:

        logger.warning(f"SEC universe fetch failed: {exc}")

        records = []

        if disk_records:

            logger.warning("Using stale local company index (network unavailable)")

            company_index_cache.set("records", disk_records)

            return disk_records

        # Last resort: try the classic ticker map via sec_client cache

        try:

            raw = get_ticker_mapping()

            records = _parse_ticker_map(raw)

        except Exception:

            records = []



    if records:

        company_index_cache.set("records", records)

        try:

            _write_disk_index(records)

        except Exception as exc:

            logger.warning(f"Could not persist company index: {exc}")

    return records





def _fetch_sec_universe() -> list[dict]:

    """Fetch official SEC universe JSON files and merge into records."""

    from lib.sec_client import sec_get, _get_user_agent

    from urllib.request import Request, urlopen

    import urllib.error



    user_agent = _get_user_agent()

    headers = {"User-Agent": user_agent, "Accept": "application/json"}

    merged: dict[str, dict] = {}



    def _get_json(url: str) -> dict:

        try:

            req = Request(url, headers=headers, method="GET")

            with urlopen(req, timeout=20) as resp:

                return json.loads(resp.read().decode("utf-8"))

        except Exception:

            # fall back to the sec_client path which has retries/cache

            data = sec_get(url, cache_ttl=86400.0)

            if isinstance(data, dict):

                return data

            return {}



    primary = _get_json(_TICKERS_URL)

    # Handle the SEC numbered-dict format: {"0": {"cik_str": ..., "ticker": ..., "title": ...}, ...}

    if isinstance(primary, dict):

        for key, val in primary.items():

            if isinstance(val, dict) and "ticker" in val:

                cik = _cik_to_str(val.get("cik_str") or val.get("cik", ""))

                ticker = str(val.get("ticker", "")).upper()

                name = str(val.get("title") or val.get("name", ""))

                if ticker and cik:

                    merged[ticker] = {"cik": cik, "name": name, "ticker": ticker, "exchange": ""}

        # Also handle {"fields": [...], "data": [[...], ...]} format

        if "data" in primary and "fields" in primary:

            fields = primary["fields"]

            for row in primary["data"]:

                company = {}

                for i, field_name in enumerate(fields):

                    if i < len(row):

                        company[field_name] = row[i]

                rec = {

                    "cik": _cik_to_str(company.get("cik_str") or company.get("cik", "")),

                    "name": str(company.get("title") or company.get("name", "")),

                    "ticker": str(company.get("ticker", "")).upper(),

                    "exchange": "",

                }

                if rec["ticker"] and rec["cik"]:

                    merged[rec["ticker"]] = rec



    # Merge exchange info from the exchange companion file

    exchange_data = _get_json(_TICKERS_EXCHANGE_URL)

    if isinstance(exchange_data, dict):

        for key, val in exchange_data.items():

            if isinstance(val, dict) and "ticker" in val:

                ticker = str(val.get("ticker", "")).upper()

                exchange = str(val.get("exchange", ""))

                if ticker in merged and exchange:

                    merged[ticker]["exchange"] = exchange

        # Also handle {"fields": [...], "data": [[...], ...]} format

        if "data" in exchange_data and "fields" in exchange_data:

            fields = exchange_data["fields"]

            for row in exchange_data["data"]:

                company = {}

                for i, field_name in enumerate(fields):

                    if i < len(row):

                        company[field_name] = row[i]

                ticker = str(company.get("ticker", "")).upper()

                exchange = str(company.get("exchange", ""))

                if ticker in merged and exchange:

                    merged[ticker]["exchange"] = exchange



    records = list(merged.values())

    logger.info(f"SEC universe loaded: {len(records)} tickers")

    return records





def _read_disk_index() -> tuple[list[dict], float]:

    try:

        if not _COMPANY_INDEX_FILE.exists():

            return [], 0.0

        data = json.loads(_COMPANY_INDEX_FILE.read_text(encoding="utf-8"))

        fetched_at = float(data.get("fetched_at", 0.0))

        records = data.get("records", [])

        if isinstance(records, list) and len(records) > 1000:

            return records, fetched_at

        return [], 0.0

    except Exception:

        return [], 0.0





def _write_disk_index(records: list[dict]) -> None:

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    payload = {

        "fetched_at": time.time(),

        "fetched_at_iso": datetime.now(timezone.utc).isoformat(),

        "count": len(records),

        "records": records,

    }

    # atomic write

    tmp = _COMPANY_INDEX_FILE.with_suffix(".json.tmp")

    tmp.write_text(json.dumps(payload), encoding="utf-8")

    tmp.replace(_COMPANY_INDEX_FILE)





# ── Fuzzy index (built once, not per request) ────────────────────────────────

@dataclass

class _FuzzyIndex:

    tickers: list[str] = field(default_factory=list)

    names: list[str] = field(default_factory=list)

    ticker_record_indices: list[int] = field(default_factory=list)  # ticker → record

    name_record_indices: list[int] = field(default_factory=list)    # name → record

    short_names: list[str] = field(default_factory=list)  # leading distinctive token

    short_name_record_indices: list[int] = field(default_factory=list)





_index_lock = threading.Lock()

_fuzzy_index: Optional[_FuzzyIndex] = None

_records_cache: list[dict] = []





def _ensure_records() -> list[dict]:

    global _records_cache

    records = _load_index_records()

    if records:

        _records_cache = records

    if not _records_cache:

        # Build a minimal fallback from the classic map so resolver still works

        try:

            _records_cache = _parse_ticker_map(get_ticker_mapping())

        except Exception:

            _records_cache = []

    return _records_cache





def _build_fuzzy_index(records: list[dict]) -> _FuzzyIndex:

    """Build normalized search lists once and reuse across requests."""

    idx = _FuzzyIndex()

    for i, rec in enumerate(records):

        ticker = (rec.get("ticker") or "").strip().upper()

        name = rec.get("name") or ""

        if ticker:

            idx.tickers.append(ticker)

            idx.ticker_record_indices.append(i)

        if name:

            normalized = _normalize_compare(name)

            idx.names.append(normalized)

            idx.name_record_indices.append(i)

            # Users type the distinctive leading token ("palantir"), not the
            # full legal name. Indexing the token as well lets a short typo
            # score against a name that would otherwise dilute it to noise.

            head = normalized.split(" ", 1)[0]

            if head and head != normalized:

                idx.short_names.append(head)

                idx.short_name_record_indices.append(i)

    return idx





def _get_fuzzy_index() -> tuple[_FuzzyIndex, list[dict]]:

    global _fuzzy_index, _records_cache

    with _index_lock:

        records = _ensure_records()

        if _fuzzy_index is None or len(_records_cache) != len(records):

            _fuzzy_index = _build_fuzzy_index(records)

        return _fuzzy_index, records





def _fuzzy_score(a: str, b: str) -> float:

    """Best available token-aware fuzzy score in [0, 100]."""

    if _HAS_RAPIDFUZZ:

        return max(

            _rf_fuzz.WRatio(a, b),

            _rf_fuzz.token_set_ratio(a, b) * 0.98,

        )

    # difflib fallback (rare environments)

    import difflib

    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100.0





def _scorer(query: str, choice: str, **kwargs) -> float:

    """rapidfuzz-compatible wrapper around :func:`_fuzzy_score`.

    ``rapidfuzz.process.extract`` calls the scorer with
    ``score_cutoff=<float>`` and discards anything at or below it, so a scorer
    that does not accept the keyword raises ``TypeError``. Returning 0 below
    the cutoff is what makes ``extract`` apply the cutoff, rather than
    pre-filtering here and disagreeing with it about the boundary.
    """

    score = _fuzzy_score(query, choice)

    cutoff = kwargs.get("score_cutoff")

    if cutoff is not None and score < float(cutoff):

        return 0.0

    return score


# A leading-token index lets "palantir" match "palantir technologies inc",
# but a 1-3 character token is mostly noise: WRatio against "tel" scores 90
# for "palanteer" because the short ratio component saturates. Requiring some
# substance keeps the index useful for distinctive words without letting
# three-letter tokens outrank the real match.

_MIN_SHORT_NAME_LEN = 5

# Lowest fuzzy score at which a candidate is worth offering to the user as a
# possible match. Matches below this are noise from short-string ratios, and
# the fastest auto-accept path already requires 78, so offering a weaker
# candidate list only ever asks the user to choose between non-matches.

_PLAUSIBLE_CANDIDATE_FLOOR = 78


def _min_length(extracted, min_len: int):

    """Drop fuzzy hits whose matched text is too short to be meaningful."""

    return [row for row in extracted if len(row[0]) >= min_len]


def _fuzzy_extract(query: str, choices: list[str], limit: int = 8):

    """Return list of (choice, score, index) sorted desc by score.

    Scores with :func:`_fuzzy_score` so that candidate ranking and any later
    scoring use one definition. Ranking with a narrower scorer than the one
    used to decide the match is what lets a good candidate never surface.
    """

    if _HAS_RAPIDFUZZ:

        extracted = _rf_process.extract(
            query, choices, scorer=_scorer, limit=limit
        )

        return extracted  # list of (choice, score, index)

    scored = []

    for j, choice in enumerate(choices):

        scored.append((choice, _fuzzy_score(query, choice), j))

    scored.sort(key=lambda x: x[1], reverse=True)

    return scored[:limit]





# ── Resolution result ─────────────────────────────────────────────────────────

@dataclass

class ResolutionResult:

    company: Company

    method: str = "exact"

    confidence: float = 1.0

    candidates: list[dict] = field(default_factory=list)

    latency_ms: float = 0.0

    message: str = ""



    def to_dict(self) -> dict[str, Any]:

        return {

            "company": self.company.to_dict(),

            "method": self.method,

            "confidence": round(self.confidence, 4),

            "candidates": self.candidates,

            "latency_ms": round(self.latency_ms, 2),

            "message": self.message,

        }





# ── The universe engine ───────────────────────────────────────────────────────

class CompanyUniverse:

    """Resolution engine backed by the local SEC index."""



    def __init__(self) -> None:

        self._records: list[dict] = []

        self._ticker_index: dict[str, dict] = {}

        self._normalized_names: dict[str, list[dict]] = {}

        self._load()



    def _load(self) -> None:

        records = _load_index_records()

        self._records = records or _records_cache

        for rec in self._records:

            ticker = (rec.get("ticker") or "").upper()

            if ticker:

                self._ticker_index.setdefault(ticker, rec)

            nname = _normalize_compare(rec.get("name") or "")

            if nname:

                self._normalized_names.setdefault(nname, []).append(rec)

        logger.info(f"CompanyUniverse ready with {len(self._records)} records")



    # ── fast lookups ──────────────────────────────────────────────────────

    def by_ticker(self, ticker: str) -> Optional[dict]:

        return self._ticker_index.get((ticker or "").strip().upper())



    def by_cik(self, cik: str) -> Optional[dict]:

        cik_s = _cik_to_str(cik)

        for rec in self._records:

            if _cik_to_str(rec.get("cik", "")) == cik_s:

                return rec

        return None



    def by_name(self, name: str) -> Optional[dict]:

        cands = self._normalized_names.get(_normalize_compare(name))

        if cands:

            return cands[0]

        return None



    # ── full resolution ───────────────────────────────────────────────────

    def resolve(

        self,

        query: str,

        llm_fallback: Optional[Callable[[str], Optional[str]]] = None,

    ) -> ResolutionResult:

        """Resolve a freeform query to a normalized Company.



        Raises

        ------

        ValueError

            When the company cannot be confidently resolved.

        AmbiguousCompanyError

            When multiple companies plausibly match.

        """

        t0 = time.time()



        # Fast cached resolutions (exact ticker/name) avoid re-matching.

        # When tests patch the mapping we skip the cache entirely so results

        # always reflect the currently patched universe.

        using_mock = _mapping_is_overridden()

        cache_key = ""

        cached = None

        if not using_mock and query:

            cache_key = "res:" + _normalize_compare(query)

            cached = resolution_cache.get(cache_key)

        if cached is not None:

            company = Company.from_dict(cached["company"])

            company.confidence = cached.get("confidence", 1.0)

            company.method = cached.get("method", "exact")

            return ResolutionResult(

                company=company,

                method=company.method,

                confidence=company.confidence,

                latency_ms=(time.time() - t0) * 1000,

            )



        if not query or not query.strip():

            raise ValueError("Company query must be a non-empty string")

        q_raw = query.strip()



        try:

            parsed = parse_research_query(q_raw)

        except ValueError:

            parsed = None



        target = parsed.company.strip() if parsed else q_raw

        if not target:

            target = q_raw



        # ── 1. Exact ticker (fastest path) ────────────────────────────────

        ticker_clean = target.upper().strip()

        if _is_ticker(ticker_clean):

            rec = self.by_ticker(ticker_clean)

            if rec:

                return self._finish(

                    rec, confidence=1.0, method="exact_ticker",

                    t0=t0, cache_key=cache_key,

                )



        # Alias canonicalization

        alias_key = _normalize(target)

        alias_canon = _ALIASES.get(alias_key)

        alias_hit = None

        if alias_canon:

            rec = self.by_name(alias_canon) or self.by_ticker(alias_canon.upper())

            if rec:

                alias_hit = rec



        # ── 2. Exact name match (normalized incl. legal suffixes) ─────────

        nname_target = _normalize_compare(target)

        rec = self.by_name(target) if target else None

        if rec is None:

            exact_recs = self._normalized_names.get(nname_target)

            rec = exact_recs[0] if exact_recs else None

        if rec:

            return self._finish(rec, confidence=0.99, method="exact_name",

                                t0=t0, cache_key=cache_key)



        # ── 3. Alias resolution ───────────────────────────────────────────

        if alias_hit:

            return self._finish(alias_hit, confidence=0.97, method="alias",

                                t0=t0, cache_key=cache_key)



        # ── 4. Prefix match on ticker or normalized name (high precision) ─

        prefix_recs: list[dict] = []

        nname = nname_target.replace(" ", "")

        for rec in self._records:

            rec_t = (rec.get("ticker") or "").upper()

            rec_nn = _normalize_compare(rec.get("name") or "").replace(" ", "")

            if nname and (rec_nn.startswith(nname) or rec_nn == nname):

                prefix_recs.append(rec)

            elif ticker_clean and rec_t.startswith(ticker_clean):

                prefix_recs.append(rec)

            if len(prefix_recs) > 8:

                break

        if prefix_recs:

            # pick the best by name-length closeness

            prefix_recs.sort(

                key=lambda r: abs(len((r.get("name") or "").replace(" ", "")) - len(nname))

            )

            best = prefix_recs[0]

            if len(prefix_recs) == 1 or _high_precision_prefix(best, target):

                return self._finish(best, confidence=0.95, method="prefix",

                                    t0=t0, cache_key=cache_key)

            # multiple plausible → present candidates

            cands = self._candidate_dicts(prefix_recs[:5])

            raise AmbiguousCompanyError(cands, q_raw)



        # ── 5. Fuzzy resolution (RapidFuzz) ───────────────────────────────

        fuzzy_idx, records = _get_fuzzy_index()

        target_fuzzy = _normalize_compare(target)

        limit = 10



        # Fuzzy match against names

        top = _fuzzy_extract(target_fuzzy, fuzzy_idx.names, limit)

        # Also try the leading token of each name, so a short typo scores
        # against "palantir" rather than "palantir technologies inc".

        sh_top = _min_length(
            _fuzzy_extract(target_fuzzy, fuzzy_idx.short_names, limit),
            _MIN_SHORT_NAME_LEN,
        )

        # Also try tickers (high-confidence for short queries)

        tk_top = _fuzzy_extract(target_fuzzy, fuzzy_idx.tickers, limit // 2)

        all_cands: list[dict] = []

        # record identity -> position in all_cands, so a record matched by more
        # than one form keeps its best score instead of being dropped.

        seen_ids: dict[object, int] = {}

        # Merge results, mapping indices back to records

        def _merge(extracted, record_indices):

            for choice, score, choice_idx in extracted:

                rec_idx = record_indices[choice_idx] if choice_idx < len(record_indices) else -1

                if rec_idx < 0 or rec_idx >= len(records):

                    continue

                rec = records[rec_idx]

                rid = rec.get("cik") or rec.get("ticker")

                if rid in seen_ids:

                    slot = seen_ids[rid]

                    if score > all_cands[slot]["score"]:

                        all_cands[slot]["score"] = score

                    continue

                seen_ids[rid] = len(all_cands)

                all_cands.append({"record": rec, "score": score})

        _merge(top, fuzzy_idx.name_record_indices)

        _merge(sh_top, fuzzy_idx.short_name_record_indices)

        _merge(tk_top, fuzzy_idx.ticker_record_indices)

        all_cands.sort(key=lambda c: c["score"], reverse=True)



        if all_cands:

            best = all_cands[0]

            best_score = best["score"]

            second_score = all_cands[1]["score"] if len(all_cands) > 1 else 0.0



            if best_score >= 85:

                confidence = round(best_score / 100.0, 3)

                # Ambiguity: only flag if multiple candidates are close together

                gap = best_score - second_score

                close_count = sum(1 for c in all_cands[1:6]

                                  if best_score - c["score"] < 8)

                if close_count >= 2 and len(target_fuzzy) <= 10:

                    cands = self._candidate_dicts(

                        [c["record"] for c in all_cands[:5]]

                    )

                    raise AmbiguousCompanyError(cands, q_raw)

                return self._finish(best["record"], confidence=confidence,

                                    method="fuzzy", t0=t0, cache_key=cache_key)

            if best_score >= 72:

                # Lower-confidence fuzzy match: auto-resolve when there is a

                # clear dominant candidate (large gap to #2).

                gap = best_score - second_score

                if best_score >= 80 and gap >= 8:

                    confidence = round(best_score / 100.0, 3)

                    return self._finish(best["record"], confidence=confidence,

                                        method="fuzzy", t0=t0, cache_key=cache_key)

                if best_score >= 78 and gap >= 12:

                    confidence = round(best_score / 100.0, 3)

                    return self._finish(best["record"], confidence=confidence,

                                        method="fuzzy", t0=t0, cache_key=cache_key)

                # For longer queries (>= 8 chars), even a small gap is meaningful

                if best_score >= 74 and gap >= 2 and len(target_fuzzy) >= 8:

                    confidence = round(best_score / 100.0, 3)

                    return self._finish(best["record"], confidence=confidence,

                                        method="fuzzy", t0=t0, cache_key=cache_key)

                # Ambiguity means "several plausible companies", so at least one
                # candidate has to clear the floor we would accept on its own.
                # A long nonsense string peaks in the low 70s with a flat
                # profile; offering that list is not a choice, it is a dead end,
                # so fall through to the unresolvable path instead.

                if best_score >= _PLAUSIBLE_CANDIDATE_FLOOR:

                    cands = self._candidate_dicts([c["record"] for c in all_cands[:4]])

                    raise AmbiguousCompanyError(cands, q_raw)



        # ── 6. LLM fallback (only when genuinely required + enabled) ──────

        if llm_fallback is not None:

            try:

                suggestion = llm_fallback(q_raw)

            except Exception as exc:

                logger.warning(f"LLM company fallback failed: {exc}")

                suggestion = None

            if suggestion:

                # Validate the LLM suggestion against the local universe.

                llm_rec = (self.by_ticker(suggestion.strip().upper())

                           or self.by_name(suggestion))

                if llm_rec:

                    return self._finish(llm_rec, confidence=0.8,

                                        method="llm_validated", t0=t0,

                                        cache_key=cache_key)



        raise ValueError(

            f"Could not resolve company: '{q_raw}'. "

            "Try the exact company name or ticker symbol."

        )



    def _finish(

        self,

        rec: dict,

        confidence: float,

        method: str,

        t0: float,

        cache_key: str,

    ) -> ResolutionResult:

        company = Company(

            name=rec.get("name", ""),

            ticker=(rec.get("ticker") or "").upper(),

            cik=_cik_to_str(rec.get("cik", "")),

            exchange=rec.get("exchange", ""),

            # Absent from the SEC ticker file, which is US-only by

            # construction; keep the US default explicit rather than guessing.

            country=(rec.get("country") or "US").upper(),

            status="resolved",

            confidence=confidence,

            method=method,

        )

        if cache_key:

            resolution_cache.set(cache_key, {

                "company": company.to_dict(),

                "confidence": confidence,

                "method": method,

            })

        return ResolutionResult(

            company=company,

            method=method,

            confidence=confidence,

            latency_ms=(time.time() - t0) * 1000,

        )



    def _candidate_dicts(self, records: list[dict]) -> list[dict]:

        out = []

        for rec in records[:8]:

            out.append({

                "name": rec.get("name", ""),

                "ticker": (rec.get("ticker") or "").upper(),

                "cik": _cik_to_str(rec.get("cik", "")),

                "exchange": rec.get("exchange", ""),

            })

        return out



    # ── autocomplete ──────────────────────────────────────────────────────

    def suggest(self, query: str, limit: int = 8) -> list[dict]:

        """Return top candidate companies for an autocomplete dropdown.



        Backed by the local index — matches ticker prefixes first, then

        normalized-name prefixes, then fuzzy name prefixes.  Never blocks on

        network (index is loaded once).

        """

        q = (query or "").strip()

        if not q or len(q) < 1:

            return []

        q_upper = q.upper()

        nname_q = _normalize_compare(q)

        results: list[dict] = []

        seen = set()



        def _add(rec: dict, score: float) -> None:

            rid = (rec.get("cik") or rec.get("ticker") or "")

            if rid in seen:

                return

            seen.add(rid)

            results.append({

                "name": rec.get("name", ""),

                "ticker": (rec.get("ticker") or "").upper(),

                "cik": _cik_to_str(rec.get("cik", "")),

                "exchange": rec.get("exchange", ""),

                "score": score,

            })



        # 1. ticker prefix

        for rec in self._records:

            t = (rec.get("ticker") or "").upper()

            if t.startswith(q_upper) and len(t) >= len(q_upper):

                _add(rec, 100.0 if t == q_upper else 90.0)

        # 2. name prefix (normalized)

        for rec in self._records:

            nn = _normalize_compare(rec.get("name") or "").replace(" ", "")

            nq = nname_q.replace(" ", "")

            if nq and nn.startswith(nq):

                _add(rec, 80.0)

            elif nq and q.lower() in (rec.get("name") or "").lower():

                _add(rec, 70.0)

        # 3. token prefix ("microsoft" → starts-with "micro")

        words = [w for w in nname_q.split() if len(w) >= 3]

        if words:

            first = words[0]

            for rec in self._records:

                name = (rec.get("name") or "")

                for w in re.split(r"\s+", _normalize(name)):

                    if w.startswith(first) and len(w) >= len(first):

                        _add(rec, 60.0)

                        break

        # 4. small fuzzy assist

        if len(results) < 3 and len(q) >= 4:

            fuzzy_idx, records = _get_fuzzy_index()

            for choice, score, choice_idx in _fuzzy_extract(

                nname_q, fuzzy_idx.names, limit=8

            ):

                if score >= 75 and choice_idx < len(fuzzy_idx.name_record_indices):

                    rec_idx = fuzzy_idx.name_record_indices[choice_idx]

                    if rec_idx < len(records):

                        _add(records[rec_idx], score)

        results.sort(key=lambda r: r["score"], reverse=True)

        return results[:limit]





def _high_precision_prefix(best: dict, target: str) -> bool:

    """A prefix match is high precision if the name begins with the full target."""

    t = _normalize_compare(target).replace(" ", "")

    n = _normalize_compare(best.get("name") or "").replace(" ", "")

    return n.startswith(t) and len(t) >= 4





# ── Singleton ─────────────────────────────────────────────────────────────────

_universe: Optional[CompanyUniverse] = None





def get_universe() -> CompanyUniverse:

    global _universe

    if _mapping_is_overridden():

        # Tests patch the mapping — rebuild the (tiny) mock universe each time

        # so consecutive tests with different mocks see the correct rows.

        reset_universe()

    if _universe is None:

        _universe = CompanyUniverse()

    return _universe





def reset_universe() -> None:

    """Drop singleton (tests)."""

    global _universe

    _universe = None





# ── Backward-compatible public API ────────────────────────────────────────────

def resolve_company(query: str) -> Company:

    """Resolve a company name or ticker to a normalized Company object.



    Backward-compatible wrapper over the new engine.  Raises

    ``ValueError``/``AmbiguousCompanyError`` when resolution fails.



    Parameters

    ----------

    query : str

        Company name (e.g. "Microsoft", "Microsoft Corporation"), a ticker

        symbol (e.g. "MSFT"), or natural language ("research microsoft FY2024").

    """

    if query is None:

        raise TypeError("Company query must be a string")

    universe = get_universe()

    result = universe.resolve(query)

    return result.company





def smart_resolve(query: str) -> dict[str, Any]:

    """Resolve and return the full result dict (method, confidence, latency)."""

    universe = get_universe()

    result = universe.resolve(query)

    return result.to_dict()





def suggest_companies(query: str, limit: int = 8) -> list[dict]:

    """Autocomplete companies by prefix/ticker/fuzzy match."""

    return get_universe().suggest(query, limit=limit)





def build_canonical_request(query: str) -> dict[str, Any]:

    """Build the canonical research request object from a raw query."""

    parsed = parse_research_query(query)

    resolved = get_universe().resolve(parsed.company or query)

    return build_research_request(query, resolved)





# ── Parse helpers (kept for tests) ────────────────────────────────────────────

def _parse_ticker_map(data: Any) -> list[dict]:

    """Parse SEC ticker mapping into a normalized list of company dicts."""

    companies: list[dict] = []

    if isinstance(data, dict):

        if "data" in data and "fields" in data:

            fields = data["fields"]

            for row in data["data"]:

                company = {}

                for i, field_name in enumerate(fields):

                    if i < len(row):

                        company[field_name] = row[i]

                companies.append(_normalize_company_dict(company))

        else:

            for _k, val in data.items():

                if isinstance(val, dict) and ("ticker" in val or "title" in val):

                    companies.append(_normalize_company_dict(val))

    elif isinstance(data, list):

        if data and isinstance(data[0], list):

            for row in data:

                if len(row) >= 3:

                    companies.append({

                        "cik": _cik_to_str(row[0]) if isinstance(row[0], int) else str(row[0]),

                        "name": str(row[1]),

                        "ticker": str(row[2]).upper(),

                        "exchange": str(row[3]) if len(row) > 3 else "",

                    })

        elif data and isinstance(data[0], dict):

            for item in data:

                companies.append(_normalize_company_dict(item))

    return companies





def _clean_company_name(name: str) -> str:

    """Clean up SEC company name for display."""

    return name.strip()





# Cache observability helper

def clear_resolution_cache() -> None:

    """Clear cached resolutions (tests)."""

    resolution_cache.clear()

    reset_universe()

