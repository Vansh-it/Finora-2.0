"""Live Indian company resolution.

The Phase-1 resolver (``lib/india/resolver.py``) matches a hardcoded seed
table. This module resolves from live official sources first and falls back to
those seeds only when the network is unavailable, so production research never
depends on a baked-in company list (spec 6, 8, 129).

Resolution inputs accepted: legal name, common name, NSE symbol, BSE security
code, ISIN, aliases, reasonable misspellings.

Sources, in order:
  1. NSE equity master CSV (symbol, name, ISIN, series, listing date)
  2. BSE quote header API (security code, ISIN, industry, group) for symbols
     absent from the NSE master, and to attach a BSE scrip code

An ambiguous query returns candidates and never silently picks one (spec 7).
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from lib.india import http_client, sources
from lib.india.resolver import IndiaCompany, IndiaResolutionResult

logger = logging.getLogger("finora.india.live_resolver")

# ---------------------------------------------------------------------------
# Indian fiscal calendar helpers.
# ---------------------------------------------------------------------------
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
#: ~68% of Indian listed companies close their books on 31 March.
_FY_END_MARCH = "31-03"


def _parse_listing_date(raw: str) -> str:
    """Normalise NSE's ``06-OCT-2008`` to ISO ``2008-10-06``."""
    m = re.match(r"^(\d{1,2})-([A-Z]{3})-(\d{4})$", (raw or "").strip().upper())
    if not m:
        return ""
    day, mon, year = m.group(1), m.group(2), m.group(3)
    if mon not in _MONTHS:
        return ""
    return f"{year}-{_MONTHS[mon]:02d}-{int(day):02d}"


# ---------------------------------------------------------------------------
# Query normalisation
# ---------------------------------------------------------------------------
_SUFFIXES = (
    "limited", "ltd", "ltd.", "private limited", "pvt ltd", "pvt. ltd.",
    "corporation", "corp", "corp.", "company", "co", "co.", "india",
    "industries", "financial services", "limited.", "l p", "s a",
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def strip_legal_suffixes(name: str) -> str:
    """Drop trailing legal-form words so 'Infosys Limited' == 'Infosys'."""
    parts = normalise(name).split()
    changed = True
    while changed and parts:
        changed = False
        for suf in _SUFFIXES:
            token = suf.strip()
            if parts and parts[-1] == token and len(parts) > 1:
                parts = parts[:-1]
                changed = True
                break
    return " ".join(parts)


def query_variants(query: str) -> list[str]:
    """Every normalised spelling we will try to match, most specific first."""
    raw = (query or "").strip()
    n = normalise(raw)
    stripped = strip_legal_suffixes(raw)
    out: list[str] = []

    def add(v: str) -> None:
        if v and v not in out:
            out.append(v)

    # The raw symbol if it looks like one (uppercase, short, alnum).
    if re.fullmatch(r"[A-Za-z0-9&.\-]{1,15}", raw) and any(c.isupper() for c in raw):
        add(raw.upper())
    add(n)
    add(stripped)
    # Space-free comparison key catches 'HDFCBank' vs 'HDFC Bank'.
    add(stripped.replace(" ", ""))
    return out


def is_isin(text: str) -> bool:
    """True when ``text`` has ISIN shape (``IN`` + 10 alphanumerics).

    Deliberately a shape test, not a check-digit test: a wrong check-digit
    implementation would reject valid queries, which is a worse failure than
    accepting a well-formed ISIN that simply is not in the master. The master
    lookup below is the real authority on whether the ISIN exists.
    """
    return bool(re.fullmatch(r"IN[0-9A-Z]{10}", (text or "").strip().upper()))


def is_bse_code(text: str) -> bool:
    t = (text or "").strip()
    return bool(re.fullmatch(r"[0-9]{6}", t))


def looks_like_nse_symbol(text: str) -> bool:
    t = (text or "").strip()
    return bool(re.fullmatch(r"[A-Z][A-Z0-9&]{0,14}", t.upper()))


# ---------------------------------------------------------------------------
# NSE equity master
# ---------------------------------------------------------------------------
@dataclass
class _NseRow:
    symbol: str
    name: str
    series: str
    isin: str
    listing_date: str
    face_value: str = ""

    @property
    def is_equity(self) -> bool:
        # EQ = equity. Skip ETFs, warrants, debt and SME-series duplicates.
        return self.series.strip().upper() == "EQ"


def _fetch_nse_master() -> list[_NseRow]:
    """Download and parse the NSE listed-equity master.

    The CSV is ~180 KB and only changes when NSE adds or delists a symbol, so
    it is cached for a week by :mod:`lib.india.http_client`.
    """
    res = http_client.counted_fetch(
        sources.NSE_EQUITY_MASTER_URL,
        provider="nse_master",
        kind="identity",
        accept=("text/csv", "text/plain", "application/csv", "*/*"),
        max_bytes=8 * 1024 * 1024,
    )
    if not res.ok:
        logger.warning("[india.resolver] NSE equity master unavailable: %s",
                       res.failure.reason if res.failure else "unknown")
        return []
    try:
        text = res.text
    except Exception as exc:
        logger.warning("[india.resolver] NSE master decode failed: %s", exc)
        return []

    # The published header carries spaces after some commas
    # ("SYMBOL,NAME OF COMPANY, SERIES, ..."), so keys are stripped.
    reader = csv.DictReader(
        io.StringIO(text.lstrip("\ufeff")),
        skipinitialspace=True,
    )
    if not reader.fieldnames:
        logger.warning("[india.resolver] NSE master had no header row")
        return []
    header = {(h or "").strip().upper(): h for h in reader.fieldnames}

    def cell(raw: Mapping[str, Any], key: str) -> str:
        actual = header.get(key)
        if actual is None:
            return ""
        value = raw.get(actual)
        return ("" if value is None else str(value)).strip()

    rows: list[_NseRow] = []
    for raw in reader:
        symbol = cell(raw, "SYMBOL").upper()
        if not symbol:
            continue
        rows.append(
            _NseRow(
                symbol=symbol,
                name=cell(raw, "NAME OF COMPANY"),
                series=cell(raw, "SERIES"),
                isin=cell(raw, "ISIN NUMBER").upper(),
                listing_date=_parse_listing_date(cell(raw, "DATE OF LISTING")),
                face_value=cell(raw, "FACE VALUE"),
            )
        )
    logger.info("[india.resolver] NSE master rows: %d (equity=%d)",
                len(rows), sum(1 for r in rows if r.is_equity))
    return rows


@dataclass
class _Master:
    rows: list[_NseRow]
    by_symbol: dict[str, _NseRow] = field(default_factory=dict)
    by_isin: dict[str, _NseRow] = field(default_factory=dict)
    by_name: dict[str, list[_NseRow]] = field(default_factory=dict)
    by_name_compact: dict[str, list[_NseRow]] = field(default_factory=dict)
    available: bool = False

    @classmethod
    def build(cls) -> "_Master":
        rows = _fetch_nse_master()
        m = cls(rows=rows, available=bool(rows))
        for r in rows:
            m.by_symbol.setdefault(r.symbol, r)
            if r.isin:
                m.by_isin.setdefault(r.isin, r)
            nk = strip_legal_suffixes(r.name)
            if nk:
                m.by_name.setdefault(nk, []).append(r)
                m.by_name_compact.setdefault(nk.replace(" ", ""), []).append(r)
        return m


_MASTER: Optional[_Master] = None


def get_master(refresh: bool = False) -> _Master:
    global _MASTER
    if _MASTER is None or refresh:
        _MASTER = _Master.build()
    return _MASTER


# ---------------------------------------------------------------------------
# BSE lookup (adds security code / industry to a resolved company)
# ---------------------------------------------------------------------------
def _bse_lookup(scrip_code: str) -> dict[str, Any]:
    """Fetch BSE header data for a security code. Never raises."""
    res = http_client.counted_fetch(
        sources.BSE_QUOTE_HEADER_URL,
        provider="bse_quote",
        kind="identity",
        params={"quotetype": "EQ", "scripcode": scrip_code, "seriesid": ""},
        headers={"Referer": sources.bse_referer()},
        accept=("application/json", "text/plain", "*/*"),
    )
    if not res.ok or not res.text:
        return {}
    import json

    try:
        payload = json.loads(res.text)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _seed_by_isin() -> dict[str, dict[str, Any]]:
    """Seed identity records indexed by ISIN.

    Used only to backfill identity fields the live master does not publish
    (BSE scrip code, CIN, sector, industry, entity type). These are identity
    facts, not financial values, and every backfilled field is reported in
    :attr:`IndiaCompany.seed_fields` so a reviewer can see what was joined.
    """
    global _SEED_BY_ISIN
    if _SEED_BY_ISIN is not None:
        return _SEED_BY_ISIN
    from lib.india import resolver as seed_resolver

    out: dict[str, dict[str, Any]] = {}
    for seed in (getattr(seed_resolver, "_INDIA_COMPANIES", {}) or {}).values():
        rec = seed.to_dict() if hasattr(seed, "to_dict") else dict(seed)
        isin = str(rec.get("isin") or "").strip().upper()
        if isin:
            out.setdefault(isin, rec)
    _SEED_BY_ISIN = out
    return out


def _enrich_with_bse(company: IndiaCompany) -> IndiaCompany:
    """Attach BSE scrip code and industry when we can confirm the company."""
    if not company.bse_code:
        # BSE codes are not derivable from ISIN, so only enrich when a seed
        # record already supplies one. Guessing a code would be fabrication.
        return company
    payload = _bse_lookup(company.bse_code)
    if not payload:
        return company
    isin = (payload.get("ISIN") or "").strip().upper()
    if isin and company.isin and isin != company.isin:
        # Different company on that code: refuse to merge the two records.
        logger.warning(
            "[india.resolver] BSE code %s maps to ISIN %s but %s has %s; ignoring",
            company.bse_code, isin, company.display_name, company.isin,
        )
        return company
    if isin and not company.isin:
        company.isin = isin
        company.seed_fields.append("isin")
    if not company.sector:
        industry = (payload.get("Industry") or "").strip()
        if industry:
            company.sector = industry
            company.seed_fields.append("sector")
    return company


_SEED_BY_ISIN: Optional[dict[str, dict[str, Any]]] = None


def _backfill_identity(company: IndiaCompany) -> IndiaCompany:
    """Fill identity-only gaps from the seed table, joined on ISIN.

    An ISIN is exchange-assigned and globally unique, so a match is a reliable
    identity join. Financial values are never taken from here.
    """
    if not company.isin:
        return company
    record = _seed_by_isin().get(company.isin.upper())
    if not record:
        return company
    for field_name, value in (
        ("bse_code", record.get("bse_code")),
        ("cin", record.get("cin")),
        ("sector", record.get("sector")),
        ("industry", record.get("industry")),
        ("entity_type", record.get("entity_type")),
        ("listing_status", record.get("listing_status")),
    ):
        if value and not getattr(company, field_name, ""):
            setattr(company, field_name, value)
            company.seed_fields.append(field_name)
    for alias in record.get("aliases") or ():
        if alias and alias not in company.aliases:
            company.aliases.append(alias)
            company.seed_fields.append("aliases")
    return company


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
@dataclass
class _Match:
    row: _NseRow
    confidence: float
    method: str


def _score_name(query: str, candidate: str) -> float:
    """Similarity in [0, 1]. Exact > prefix > token-overlap > subsequence."""
    q = strip_legal_suffixes(query)
    c = strip_legal_suffixes(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    qc, cc = q.replace(" ", ""), c.replace(" ", "")
    if qc == cc:
        return 0.97
    if qc and cc and (qc.startswith(cc) or cc.startswith(qc)):
        # 'reliance' vs 'reliance industries'
        return 0.88
    qt, ct = set(q.split()), set(c.split())
    if qt and ct:
        overlap = len(qt & ct) / max(len(qt), len(ct))
        if overlap >= 0.99:
            return 0.95
        if overlap >= 0.6:
            return 0.6 + 0.25 * overlap
    # Character-level ratio, cheap and dependency-free.
    try:
        from difflib import SequenceMatcher

        r = SequenceMatcher(None, q, c).ratio()
        if r >= 0.86:
            return 0.5 + 0.3 * r
    except Exception:
        pass
    return 0.0


def _match(query: str) -> list[_Match]:
    master = get_master()
    if not master.rows:
        return []
    q = (query or "").strip()
    matches: dict[str, _Match] = {}

    def offer(row: _NseRow, conf: float, method: str) -> None:
        prev = matches.get(row.symbol)
        if prev is None or conf > prev.confidence:
            matches[row.symbol] = _Match(row=row, confidence=conf, method=method)

    # 1. ISIN
    if is_isin(q):
        row = master.by_isin.get(q.upper())
        if row:
            offer(row, 1.0, "isin")

    # 2. BSE security code. The NSE master carries no BSE scrip code, so this
    #    only resolves for companies the Phase-1 seed table already knows.
    #    Deriving a code from an ISIN would be a guess, so we do not.
    if is_bse_code(q):
        for row in _scrip_code_map().get(q, ()):
            offer(row, 1.0, "bse_code")

    # 3. Exact NSE symbol
    up = q.upper()
    if up in master.by_symbol:
        row = master.by_symbol[up]
        # A bare symbol is an explicit user instruction; outrank any name match.
        offer(row, 0.99, "nse_symbol")

    # 4. Name matching
    for variant in query_variants(q):
        for bucket in (master.by_name.get(variant), master.by_name_compact.get(variant.replace(" ", ""))):
            for row in bucket or ():
                offer(row, _score_name(q, row.name), "name")

    # 5. Fuzzy sweep when nothing strong matched
    if not any(m.confidence >= 0.9 for m in matches.values()):
        scored: list[tuple[float, _NseRow]] = []
        for row in master.by_symbol.values():
            s = _score_name(q, row.name)
            if s >= 0.82:
                scored.append((s, row))
        scored.sort(key=lambda t: -t[0])
        for s, row in scored[:12]:
            offer(row, s, "fuzzy")

    ranked = [m for m in matches.values() if m.confidence >= 0.5]
    ranked.sort(key=lambda m: (-m.confidence, m.row.symbol))
    return ranked


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _to_company(match: _Match) -> IndiaCompany:
    row = match.row
    return IndiaCompany(
        country="IN",
        display_name=row.name or row.symbol,
        legal_name=row.name or row.symbol,
        nse_symbol=row.symbol,
        bse_code="",
        isin=row.isin,
        cin="",
        primary_exchange="NSE",
        listing_status="LISTED",
        sector="",
        industry="",
        entity_type="",
        currency="INR",
        # Indian fiscal years overwhelmingly close on 31 March. A non-March
        # year-end is refined later from the filings themselves.
        fiscal_year_end="31 Mar",
        aliases=[row.symbol] if row.symbol else [],
        confidence=round(match.confidence, 3),
        method=match.method,
        listing_date=row.listing_date,
        resolution_confidence=round(match.confidence, 3),
        resolution_method=match.method,
    )


def _seed_fallback(query: str) -> IndiaResolutionResult:
    """Fall back to the Phase-1 seed table when live discovery is unavailable."""
    from lib.india import resolver as seed_resolver

    try:
        return seed_resolver.resolve_india_company(query)
    except Exception as exc:
        raise ValueError(
            f"No Indian company matched {query!r} (live discovery and seed fallback both failed: {exc})"
        ) from exc


_SCRIP_CODES: Optional[dict[str, list[str]]] = None


def _scrip_code_map() -> dict[str, list[str]]:
    """BSE scrip code -> NSE symbols, using the seed table plus a name match.

    BSE does not publish a free scrip-code list that survives rate limiting, so
    live BSE-code resolution is best-effort. Anything not in the seed table is
    reported as unresolved rather than guessed.
    """
    global _SCRIP_CODES
    if _SCRIP_CODES is not None:
        return _SCRIP_CODES
    from lib.india import resolver as seed_resolver

    seeds = getattr(seed_resolver, "_INDIA_COMPANIES", {}) or {}
    rows: list[str] = []
    mapping: dict[str, list[str]] = {}
    for key, seed in seeds.items():
        seed = seed.to_dict() if hasattr(seed, "to_dict") else dict(seed)
        code = str(seed.get("bse_code") or "").strip()
        symbol = str(seed.get("nse_symbol") or "").strip().upper()
        if code and symbol:
            mapping.setdefault(code, []).append(symbol)

    master = get_master()
    out: dict[str, list[_NseRow]] = {}
    for code, symbols in mapping.items():
        found = [master.by_symbol[s] for s in symbols if s in master.by_symbol]
        if found:
            out[code] = found
    _SCRIP_CODES = out
    return out


def resolve(query: str, refresh: bool = False) -> IndiaResolutionResult:
    """Resolve an Indian listed company from live official sources.

    Falls back to the Phase-1 seed table only when the live sources are
    unreachable, and reports ``source`` accordingly so the caller (and the
    dashboard) can be honest about where identity came from.
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("Empty company query")

    master = get_master(refresh=refresh)
    if not master.available:
        logger.info("[india.resolver] live master unavailable; using seed fallback")
        result = _seed_fallback(q)
        result.source = "SEED_FALLBACK"
        return result

    matches = _match(q)
    if not matches:
        # No live match. Before failing, ask the seed table: it may know a
        # company that is delisted from the current NSE master.
        try:
            result = _seed_fallback(q)
            result.source = "SEED_FALLBACK"
            return result
        except Exception:
            raise ValueError(
                f"No Indian listed company matched {q!r}. "
                "Check the NSE symbol, BSE scrip code, or company name."
            ) from None

    best = matches[0]
    # Ambiguity: a second candidate within a hair of the best is a real
    # question, not a detail. Spec 7 forbids silently choosing.
    runner_up = next(
        (m for m in matches[1:] if best.confidence - m.confidence < 0.04
         and m.confidence >= 0.5),
        None,
    )
    if runner_up is not None:
        return IndiaResolutionResult(
            status="AMBIGUOUS",
            query=q,
            candidates=[
                {
                    "display_name": m.row.name,
                    "nse_symbol": m.row.symbol,
                    "isin": m.row.isin,
                    "primary_exchange": "NSE",
                    "currency": "INR",
                    "confidence": round(m.confidence, 3),
                    "match_method": m.method,
                }
                for m in matches[:6]
            ],
        )

    company = _to_company(best)
    company = _backfill_identity(company)
    company = _enrich_with_bse(company)
    if company.bse_code and "bse_code" not in company.seed_fields:
        company.seed_fields.append("bse_code")
    return IndiaResolutionResult(
        status="RESOLVED",
        query=q,
        company=company,
        confidence=company.resolution_confidence,
        method=company.resolution_method,
        candidates=[
            {
                "display_name": m.row.name,
                "nse_symbol": m.row.symbol,
                "isin": m.row.isin,
                "confidence": round(m.confidence, 3),
            }
            for m in matches[:6]
        ],
        source="LIVE_NSE_MASTER",
    )


def invalidate(refresh: bool = True) -> None:
    """Drop cached identity data so the next resolution refetches."""
    global _MASTER
    _MASTER = None
    http_client.invalidate("identity")


def search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Free-text company search for autocomplete."""
    master = get_master()
    if not master.rows:
        return []
    q = strip_legal_suffixes(query)
    if not q:
        return []
    out: list[tuple[float, _NseRow]] = []
    for row in master.by_symbol.values():
        s = _score_name(q, row.name)
        # A symbol-prefix hit is a strong signal, e.g. "hdfc" -> HDFCBANK.
        if s > 0 and row.symbol.lower().startswith(q.replace(" ", "")):
            s = max(s, 0.9)
        if s >= 0.55:
            out.append((s, row))
    out.sort(key=lambda t: (-t[0], t[1].symbol))
    return [
        {
            "display_name": r.name,
            "nse_symbol": r.symbol,
            "isin": r.isin,
            "country": "IN",
            "currency": "INR",
            "score": round(s, 3),
        }
        for s, r in out[:limit]
    ]
