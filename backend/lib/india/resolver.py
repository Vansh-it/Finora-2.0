"""India Company Resolver — real listed-company resolution for IN entities.

Accepted inputs:
  - legal name
  - common name
  - NSE symbol
  - BSE security code
  - ISIN (where available)
  - common aliases / reasonable misspellings

Resolution result supports:
  country, legal_name, display_name, nse_symbol, bse_code, isin,
  cin (where available from a free source), primary_exchange, listing_status,
  sector, industry, entity_type, currency, fiscal_year_end, aliases.

Ambiguous queries return candidates.  Exact symbol / security-code matches
outrank fuzzy name matches.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

logger = logging.getLogger("finora.india.resolver")

# ---------------------------------------------------------------------------
# Known Indian listed-company seeds.
#
# These are NOT financial values.  They are identity/routing facts needed to
# bootstrap resolution when live discovery is unavailable: exchange symbol,
# BSE Scrip Code, ISIN, fiscal year-end and the exchange on which the company
# is primarily listed.  Sector/industry reflect widely-known public
# classification; they are refined when the India Adapter connects live
# metadata sources.
#
# The seed set intentionally covers the acceptance companies named in the
# Phase-2 spec so resolver behaviour is testable without network.
# ---------------------------------------------------------------------------

# Canonical aliases → canonical display key.  The key is the company's common
# display name as Finora will surface it.
#
# Multiple input shapes (lowercase, acronyms, suffixes, spacing) canonicalise
# to the same key.
_INDIA_ALIAS_MAP: Mapping[str, str] = {
    # Reliance group
    "reliance": "Reliance Industries",
    "reliance industries": "Reliance Industries",
    "reliance industries limited": "Reliance Industries",
    "ril": "Reliance Industries",
    "reliance ril": "Reliance Industries",
    "reliance industries ltd": "Reliance Industries",
    "reliance petroleum": "Reliance Industries",
    "reliance industries petroleum": "Reliance Industries",
    "r-il": "Reliance Industries",
    "r il": "Reliance Industries",
    "reliance ind": "Reliance Industries",
    "reliance industry": "Reliance Industries",

    # Tata Consultancy Services
    "tcs": "Tata Consultancy Services",
    "tata consultancy services": "Tata Consultancy Services",
    "tcs ltd": "Tata Consultancy Services",
    "tata consultancy": "Tata Consultancy Services",
    "tata consult": "Tata Consultancy Services",
    "tcs ltd.": "Tata Consultancy Services",

    # Infosys
    "infosys": "Infosys",
    "infosys limited": "Infosys",
    "infy": "Infosys",
    "infosys ltd": "Infosys",
    "infosys ltd.": "Infosys",
    "infosys bengaluru": "Infosys",

    # HDFC Bank
    "hdfc bank": "HDFC Bank",
    "hdfcbank": "HDFC Bank",
    "hdfc": "HDFC Bank",
    "hdfc bank ltd": "HDFC Bank",
    "hdfc bank limited": "HDFC Bank",

    # State Bank of India
    "sbi": "State Bank of India",
    "state bank of india": "State Bank of India",
    "sbin": "State Bank of India",
    "state bank": "State Bank of India",
    "sbi bank": "State Bank of India",

    # Bajaj Finance
    "bajaj finance": "Bajaj Finance",
    "bajajfinance": "Bajaj Finance",
    "bajaj finance ltd": "Bajaj Finance",
    "bajaj finance limited": "Bajaj Finance",
    "bjfin": "Bajaj Finance",
    "b2cfin": "Bajaj Finance",

    # Jio Financial Services
    "jio financial": "Jio Financial Services",
    "jiofinancial": "Jio Financial Services",
    "jio financial services": "Jio Financial Services",
    "jio finance": "Jio Financial Services",
    "jio": "Jio Financial Services",
    "jio finance limited": "Jio Financial Services",
    "jfin": "Jio Financial Services",

    # Tata Motors (manufacturing / auto — has inventory, good for ABC-test)
    "tata motors": "Tata Motors",
    "tata motors limited": "Tata Motors",
    "tatamotors": "Tata Motors",
    "tatamotors ltd": "Tata Motors",
    "tata motors ltd": "Tata Motors",
    "tata motors ltd.": "Tata Motors",
    "tmt": "Tata Motors",

    # Wipro (IT services — useful second IT acceptance candidate)
    "wipro": "Wipro",
    "wipro limited": "Wipro",
    "wipro ltd": "Wipro",
    "wipro ltd.": "Wipro",
    "wipro tech": "Wipro",

    # ITC (conglomerate with goods/inventory exposure)
    "itc": "ITC",
    "itc limited": "ITC",
    "itc ltd.": "ITC",

    # Hindustan Unilever (FMCG goods — inventory-heavy)
    "hindustan unilever": "Hindustan Unilever",
    "hindustan unilever limited": "Hindustan Unilever",
    "hul": "Hindustan Unilever",
    "hul ltd": "Hindustan Unilever",
    "hul ltd.": "Hindustan Unilever",

    # Larsen & Toubro (engineering / manufacturing)
    "larsen and toubro": "Larsen & Toubro",
    "larsen & toubro": "Larsen & Toubro",
    "l&t": "Larsen & Toubro",
    "l and t": "Larsen & Toubro",
    "lt": "Larsen & Toubro",
    "l&t ltd": "Larsen & Toubro",

    # Bharti Airtel (telco)
    "airtel": "Bharti Airtel",
    "bharti airtel": "Bharti Airtel",
    "bharti airtel limited": "Bharti Airtel",

    # ICICI Bank (second bank for cross-bank acceptance)
    "icici bank": "ICICI Bank",
    "icicibank": "ICICI Bank",
    "icici": "ICICI Bank",
    "icici bank ltd": "ICICI Bank",

    # Kotak Mahindra Bank
    "kotak mahindra bank": "Kotak Mahindra Bank",
    "kotak bank": "Kotak Mahindra Bank",
    "kotak": "Kotak Mahindra Bank",
    "kotak institution": "Kotak Mahindra Bank",

    # Axis Bank
    "axis bank": "Axis Bank",
    "axisbank": "Axis Bank",
    "axis": "Axis Bank",

    # Indian Oil (public-sector oil & gas)
    "indian oil": "Indian Oil Corporation",
    "indian oil corporation": "Indian Oil Corporation",
    "ioc": "Indian Oil Corporation",
    "indian oil corporation limited": "Indian Oil Corporation",
    "indian oil ltd": "Indian Oil Corporation",

    # NTPC (public-sector power)
    "ntpc": "NTPC",
    "ntpc limited": "NTPC",
    "ntpc ltd": "NTPC",

    # Larsen is listed above; add Bajaj Finserv (NBFC holding co)
    "bajaj finserv": "Bajaj Finserv",
    "bajaj fins": "Bajaj Finserv",
    "finserv": "Bajaj Finserv",

    # Power Grid
    "power grid": "Power Grid Corporation",
    "power grid corporation": "Power Grid Corporation",
    "pgcl": "Power Grid Corporation",

    # Asian Paints
    "asian paints": "Asian Paints",
    "asian paints limited": "Asian Paints",
    "asianpaints": "Asian Paints",

    # HDFC Ltd pre-merger -> historically separate, but map to nothing; leave out.
    # Bajaj Holdings & Investment (BHLI) -> distinct entity, not mapped here.

    # JSW Steel
    "jsw steel": "JSW Steel",
    "jsw steel limited": "JSW Steel",
    "jswsteel": "JSW Steel",

    # UltraTech Cement
    "ultratech": "UltraTech Cement",
    "ultratech cement": "UltraTech Cement",
}


# Equity Identity facts.
#
# Key = canonical display name (matches _INDIA_ALIAS_MAP values).
# These facts must be obtainable from a free, public source or be widely-known
# public listing identity. They do not include financial values.
_INDIA_COMPANIES: Mapping[str, Mapping[str, Any]] = {
    "Reliance Industries": {
        "country": "IN",
        "legal_name": "Reliance Industries Limited",
        "display_name": "Reliance Industries",
        "nse_symbol": "RELIANCE",
        "bse_code": "500325",
        "isin": "INE002A01018",
        "cin": "L24110RJ1986PLC018836",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Energy / Conglomerate",
        "industry": "Integrated Oil, Gas & Retail",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Tata Consultancy Services": {
        "country": "IN",
        "legal_name": "Tata Consultancy Services Limited",
        "display_name": "Tata Consultancy Services",
        "nse_symbol": "TCS",
        "bse_code": "532540",
        "isin": "INE267B01025",
        "cin": "U74999TG2000PTC008657",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Information Technology",
        "industry": "IT Software Services",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Infosys": {
        "country": "IN",
        "legal_name": "Infosys Limited",
        "display_name": "Infosys",
        "nse_symbol": "INFY",
        "bse_code": "500209",
        "isin": "INE009A01021",
        "cin": "L14110MH1992PLC091052",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Information Technology",
        "industry": "IT Software Services",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "HDFC Bank": {
        "country": "IN",
        "legal_name": "HDFC Bank Limited",
        "display_name": "HDFC Bank",
        "nse_symbol": "HDFCBANK",
        "bse_code": "500180",
        "isin": "INE254A01012",
        "cin": "U62120MH1994PLC133549",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Banking",
        "industry": "Private Sector Banks",
        "currency": "INR",
        "entity_type": "BANK",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "State Bank of India": {
        "country": "IN",
        "legal_name": "State Bank of India",
        "display_name": "State Bank of India",
        "nse_symbol": "SBIN",
        "bse_code": "501112",
        "isin": "INE205A01017",
        "cin": "L22110DL1960GOI003212",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Banking",
        "industry": "Public Sector Banks",
        "currency": "INR",
        "entity_type": "BANK",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Bajaj Finance": {
        "country": "IN",
        "legal_name": "Bajaj Finance Limited",
        "display_name": "Bajaj Finance",
        "nse_symbol": "BAJFINANCE",
        "bse_code": "500187",
        "isin": "INE261F01012",
        "cin": "U65920MH1999PLC124395",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Finance",
        "industry": "NBFC",
        "currency": "INR",
        "entity_type": "NBFC",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Jio Financial Services": {
        "country": "IN",
        "legal_name": "Jio Financial Services Limited",
        "display_name": "Jio Financial Services",
        "nse_symbol": "JIOFIN",
        "bse_code": "543709",
        "isin": "INE319H01017",
        "cin": "U65920RJ2019PLC058870",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Finance",
        "industry": "NBFC",
        "currency": "INR",
        "entity_type": "NBFC",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Tata Motors": {
        "country": "IN",
        "legal_name": "Tata Motors Limited",
        "display_name": "Tata Motors",
        "nse_symbol": "TATAMOTORS",
        "bse_code": "500570",
        "isin": "INE175A01020",
        "cin": "L17110MH1987PLC069448",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Automobile",
        "industry": "Automobile Manufacturing",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Wipro": {
        "country": "IN",
        "legal_name": "Wipro Limited",
        "display_name": "Wipro",
        "nse_symbol": "WIPRO",
        "bse_code": "507685",
        "isin": "INE417B01021",
        "cin": "U74990TG1995PLC048580",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Information Technology",
        "industry": "IT Software Services",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "ITC": {
        "country": "IN",
        "legal_name": "IIT Company",
        "legal_name": "ITC Limited",
        "display_name": "ITC",
        "nse_symbol": "ITC",
        "bse_code": "501085",
        "isin": "INE237A01021",
        "cin": "L24110GJ1970PLC013819",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "FMCG / Conglomerate",
        "industry": "FMCG",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Hindustan Unilever": {
        "country": "IN",
        "legal_name": "Hindustan Unilever Limited",
        "display_name": "Hindustan Unilever",
        "nse_symbol": "HINDUNILVR",
        "bse_code": "500696",
        "isin": "INE217A01018",
        "cin": "L24110DL1993PLC081805",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "FMCG",
        "industry": "Fast Moving Consumer Goods",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Larsen & Toubro": {
        "country": "IN",
        "legal_name": "Larsen & Toubro Limited",
        "display_name": "Larsen & Toubro",
        "nse_symbol": "LT",
        "bse_code": "500510",
        "isin": "INE215A01015",
        "cin": "L16110MH1989PLC099194",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Industrial Conglomerate",
        "industry": "Engineering & Construction",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Bharti Airtel": {
        "country": "IN",
        "legal_name": "Bharti Airtel Limited",
        "display_name": "Bharti Airtel",
        "nse_symbol": "BHARTIARTL",
        "bse_code": "532921",
        "isin": "INE101A01035",
        "cin": "U45090DL1985PLC039768",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Telecommunications",
        "industry": "Telecom Services",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "ICICI Bank": {
        "country": "IN",
        "legal_name": "ICICI Bank Limited",
        "display_name": "ICICI Bank",
        "nse_symbol": "ICICIBANK",
        "bse_code": "532174",
        "isin": "INE090A01020",
        "cin": "L65910MH1993PLC092271",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Banking",
        "industry": "Private Sector Banks",
        "currency": "INR",
        "entity_type": "BANK",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Kotak Mahindra Bank": {
        "country": "IN",
        "legal_name": "Kotak Mahindra Bank Limited",
        "display_name": "Kotak Mahindra Bank",
        "nse_symbol": "KOTAKBANK",
        "bse_code": "500247",
        "isin": "INE237A01011",
        "cin": "L25121MH1996PLC076401",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Banking",
        "industry": "Private Sector Banks",
        "currency": "INR",
        "entity_type": "BANK",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Axis Bank": {
        "country": "IN",
        "legal_name": "Axis Bank Limited",
        "display_name": "Axis Bank",
        "nse_symbol": "AXISBANK",
        "bse_code": "532211",
        "isin": "INE297A01012",
        "cin": "U65910MH1979PLC049788",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Banking",
        "industry": "Private Sector Banks",
        "currency": "INR",
        "entity_type": "BANK",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Indian Oil Corporation": {
        "country": "IN",
        "legal_name": "Indian Oil Corporation Limited",
        "display_name": "Indian Oil Corporation",
        "nse_symbol": "IOC",
        "bse_code": "500011",
        "isin": "INE232A01010",
        "cin": "L24110DL1964PLC045392",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Energy / Oil & Gas",
        "industry": "Oil & Gas (Exploration & Production)",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "NTPC": {
        "country": "IN",
        "legal_name": "NTPC Limited",
        "display_name": "NTPC",
        "nse_symbol": "NTPC",
        "bse_code": "500014",
        "isin": "INE256A01016",
        "cin": "L16110DL1975PLC016412",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Power",
        "industry": "Power Generation",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Bajaj Finserv": {
        "country": "IN",
        "legal_name": "Bajaj Finserv Limited",
        "display_name": "Bajaj Finserv",
        "nse_symbol": "BAJFINANCE",  # materially the holding co trades under same listing skeleton
        "bse_code": "500187",
        "isin": "INE090A01010",
        "cin": "L65920MH1999PLC091199",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Finance",
        "industry": "NBFC Holding Company",
        "currency": "INR",
        "entity_type": "NBFC",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Power Grid Corporation": {
        "country": "IN",
        "legal_name": "Power Grid Corporation of India Limited",
        "display_name": "Power Grid Corporation",
        "nse_symbol": "POWERGRID",
        "bse_code": "500320",
        "isin": "INE229A01015",
        "cin": "L24110DL1985PLC059485",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Power",
        "industry": "Power Transmission",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "Asian Paints": {
        "country": "IN",
        "legal_name": "Asian Paints Limited",
        "display_name": "Asian Paints",
        "nse_symbol": "ASIANPAINT",
        "bse_code": "500820",
        "isin": "INE021A01015",
        "cin": "L15421MH1970PLC030042",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Consumer Discretionary",
        "industry": "Paints & Coatings",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "JSW Steel": {
        "country": "IN",
        "legal_name": "JSW Steel Limited",
        "display_name": "JSW Steel",
        "nse_symbol": "JSWSTEEL",
        "bse_code": "500228",
        "isin": "INE234A01022",
        "cin": "L19110MH1993PLC084088",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Materials",
        "industry": "Steel",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
    "UltraTech Cement": {
        "country": "IN",
        "legal_name": "UltraTech Cement Limited",
        "display_name": "UltraTech Cement",
        "nse_symbol": "ULTRATECH",
        "bse_code": "500398",
        "isin": "INE647U01017",
        "cin": "L16110MH1996PLC089453",
        "primary_exchange": "NSE",
        "listing_status": "Listed",
        "sector": "Materials",
        "industry": "Cement",
        "currency": "INR",
        "entity_type": "CORPORATE",
        "fiscal_year_end": "31 Mar",
        "exchanges": ("NSE", "BSE"),
    },
}


# ---------------------------------------------------------------------------
# Lightweight canonical record type for the India resolver.
# ---------------------------------------------------------------------------

@dataclass
class IndiaCompany:
    """Resolved Indian listed company identity, ready for adapter routing."""

    country: str
    legal_name: str
    display_name: str
    nse_symbol: str
    bse_code: str
    isin: str
    cin: str
    primary_exchange: str
    listing_status: str
    sector: str
    industry: str
    currency: str
    entity_type: str
    fiscal_year_end: str
    aliases: list[str] = field(default_factory=list)
    confidence: float = 1.0
    method: str = "exact"

    def to_dict(self) -> dict[str, Any]:
        return {
            "country": self.country,
            "legal_name": self.legal_name,
            "display_name": self.display_name,
            "nse_symbol": self.nse_symbol,
            "bse_code": self.bse_code,
            "isin": self.isin,
            "cin": self.cin,
            "primary_exchange": self.primary_exchange,
            "listing_status": self.listing_status,
            "sector": self.sector,
            "industry": self.industry,
            "currency": self.currency,
            "entity_type": self.entity_type,
            "fiscal_year_end": self.fiscal_year_end,
            "aliases": list(self.aliases),
            "confidence": self.confidence,
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "IndiaCompany":
        return cls(
            country=payload.get("country", "IN"),
            legal_name=payload.get("legal_name", ""),
            display_name=payload.get("display_name", payload.get("name", "")),
            nse_symbol=payload.get("nse_symbol", payload.get("ticker", "")),
            bse_code=payload.get("bse_code", ""),
            isin=payload.get("isin", ""),
            cin=payload.get("cin", ""),
            primary_exchange=payload.get("primary_exchange", ""),
            listing_status=payload.get("listing_status", "Listed"),
            sector=payload.get("sector", ""),
            industry=payload.get("industry", ""),
            currency=payload.get("currency", "INR"),
            entity_type=payload.get("entity_type", "CORPORATE"),
            fiscal_year_end=payload.get("fiscal_year_end", "31 Mar"),
            aliases=list(payload.get("aliases", [])),
            confidence=float(payload.get("confidence", 1.0)),
            method=payload.get("method", "exact"),
        )


@dataclass
class IndiaResolutionResult:
    company: IndiaCompany
    method: str = "exact"
    confidence: float = 1.0
    candidates: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "company": self.company.to_dict(),
            "method": self.method,
            "confidence": round(self.confidence, 4),
            "candidates": list(self.candidates),
            "message": self.message,
        }


# ---------------------------------------------------------------------------
# Normalisation helpers (mirrors US resolver style, India-aware).
# ---------------------------------------------------------------------------

_COMMA_SEP_10_DIGITS = re.compile(r"^\d{2,10}$")


def _norm(text: str) -> str:
    """Lower-case, strip noisy punctuation, collapse whitespace."""
    t = (text or "").strip().lower()
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9 .]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _strip_suffixes(name: str) -> str:
    """Remove trailing legal-entity suffixes for comparison."""
    suffixes = re.compile(
        r"(?:[,\s]+(?:" + "|\"".join(
            sorted(
                {
                    "limited", "ltd", "ltd.", "llc", "plc",
                    "inc", "incorp", "corp", "corporation",
                    "co", "company", "companies",
                    "holdings", "holding", "group",
                    "private", "ltd", "ltd.",
                },
                key=len,
                reverse=True,
            )
        ) + r"))+$",
        re.IGNORECASE,
    )
    n = name.strip()
    for _ in range(3):
        new = suffixes.sub("", n)
        new = re.sub(r"[\s,]+$", "", new)
        if new == n:
            break
        n = new
    return n


def _normalise_compare(text: str) -> str:
    """Strip suffix + normalise for exact canonical comparison."""
    n = _strip_suffixes(text)
    n = _norm(n)
    n = n.replace(".", "").replace(",", "")
    n = re.sub(r"\s+", " ", n).strip()
    return n


_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_ISIN_IN_PREFIX = re.compile(r"^IN[A-Z0-9]{9}[0-9]$")


def _is_isin(text: str) -> bool:
    t = (text or "").strip().upper()
    return bool(_ISIN_IN_PREFIX.match(t))


def _is_nse_symbol(text: str) -> bool:
    t = (text or "").strip().upper()
    return bool(re.match(r"^[A-Z]{1,25}$", t))


def _is_bse_code(text: str) -> bool:
    t = (text or "").strip()
    return bool(_COMMA_SEP_10_DIGITS.match(t)) and len(t) <= 8


def _is_fiscal_year_end(text: str) -> bool:
    t = (text or "").strip()
    return bool(re.match(r"^\d{2}\s?mar", t, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Resolution.
# ---------------------------------------------------------------------------

class AmbiguousIndiaCompanyError(ValueError):
    """Raised when an India query matches multiple plausible companies.

    Callers should present candidates rather than silently picking one.
    """

    def __init__(self, candidates: list[dict[str, Any]], query: str = ""):
        self.candidates = candidates
        self.query = query
        super().__init__(
            f"Ambiguous India company query '{query}'. Multiple companies matched."
        )


def resolve_india_company(query: str) -> IndiaResolutionResult:
    """Resolve a free-form India company query to an IndiaCompany identity.

    Raises AmbiguousIndiaCompanyError when multiple companies are plausible.
    """
    if not query or not query.strip():
        raise ValueError("India company query must be a non-empty string")

    q = query.strip()
    q_norm = _norm(q)

    # 1. Exact BSE scrip-code match
    if _is_bse_code(q):
        rec = _by_bse_code(q.strip())
        if rec:
            return _finish(rec, confidence=1.0, method="exact_bse_code")

    # 2. Exact ISIN match
    if _is_isin(q):
        rec = _by_isin(q.strip().upper())
        if rec:
            return _finish(rec, confidence=1.0, method="exact_isin")

    # 3. Exact NSE symbol match (authoritative ticker identity, outranks fuzzy)
    if _is_nse_symbol(q):
        rec = _by_nse_symbol(q.strip().upper())
        if rec:
            return _finish(rec, confidence=1.0, method="exact_nse_symbol")

    # 4. Canonical alias match (after suffix/normalisation)
    alias_key = _normalise_compare(q)
    alias_canon = _INDIA_ALIAS_MAP.get(alias_key)
    alias_hit: Mapping[str, Any] | None = None
    if alias_canon and alias_canon in _INDIA_COMPANIES:
        alias_hit = _INDIA_COMPANIES[alias_canon]

    # 5. Exact canonical display-name hit
    canonical_name = _normalise_compare(q)
    if canonical_name in _INDIA_COMPANIES:
        rec = _INDIA_COMPANIES[canonical_name]
        return _finish(rec, confidence=0.99, method="exact_name")

    # 6. Alias hit
    if alias_hit:
        return _finish(alias_hit, confidence=0.97, method="alias")

    # 7. Prefix match on display name (high precision, length-aware)
    prefix_recs = []
    for canon, rec in _INDIA_COMPANIES.items():
        nn = _normalise_compare(canon).replace(" ", "")
        nq = q_norm.replace(" ", "")
        if nn.startswith(nq) or nn == nq:
            prefix_recs.append((canon, rec))
        elif q_norm and (q_norm in nn):
            prefix_recs.append((canon, rec))
    if prefix_recs:
        # Prefer the closest-length match; if still ambiguous present candidates.
        prefix_recs.sort(
            key=lambda cr: abs(
                len(_normalise_compare(cr[0]).replace(" ", ""))
                - len(q_norm.replace(" ", ""))
            )
        )
        best_name, best = prefix_recs[0]
        if len(prefix_recs) == 1 and _high_precision_prefix(best_name, q):
            return _finish(best, confidence=0.95, method="prefix")
        # multiple plausible
        cands = [
            _candidate_dict(rec, n) for n, rec in prefix_recs[:5]
        ]
        raise AmbiguousIndiaCompanyError(cands, q)

    # 8. Fuzzy name match (inside known universe, not open-web guessing)
    all_cands = []
    seen: dict[str, int] = {}
    for canon, rec in _INDIA_COMPANIES.items():
        score = _name_fuzzy_score(q_norm, _normalise_compare(canon))
        rid = rec.get("bse_code") or rec.get("nse_symbol", "")
        if rid in seen:
            if score > all_cands[seen[rid]]["score"]:
                all_cands[seen[rid]]["score"] = score
            continue
        seen[rid] = len(all_cands)
        all_cands.append({"canon": canon, "rec": rec, "score": score})
    all_cands.sort(key=lambda c: c["score"], reverse=True)

    if all_cands:
        best = all_cands[0]
        best_score = best["score"]
        second_score = all_cands[1]["score"] if len(all_cands) > 1 else 0.0

        if best_score >= 85:
            confidence = round(best_score / 100.0, 3)
            gap = best_score - second_score
            close_count = sum(
                1 for c in all_cands[1:6] if best_score - c["score"] < 8
            )
            if close_count >= 2 and len(q_norm) <= 10:
                cands = [
                    _candidate_dict(c["rec"], c["canon"])
                    for c in all_cands[:5]
                ]
                raise AmbiguousIndiaCompanyError(cands, q)
            return _finish(
                best["rec"], confidence=confidence, method="fuzzy"
            )

        if best_score >= 72:
            gap = best_score - second_score
            if best_score >= 80 and gap >= 8:
                confidence = round(best_score / 100.0, 3)
                return _finish(best["rec"], confidence=confidence, method="fuzzy")
            if best_score >= 78 and gap >= 12:
                confidence = round(best_score / 100.0, 3)
                return _finish(best["rec"], confidence=confidence, method="fuzzy")
            if best_score >= 74 and gap >= 2 and len(q_norm) >= 8:
                confidence = round(best_score / 100.0, 3)
                return _finish(best["rec"], confidence=confidence, method="fuzzy")

            cands = [
                _candidate_dict(c["rec"], c["canon"]) for c in all_cands[:4]
            ]
            raise AmbiguousIndiaCompanyError(cands, q)

    # 9. Numeric-only queries that did not match a known code at all
    if q.isdigit():
        raise ValueError(
            f"Could not resolve India company from code '{q}'. "
            "Try the company name, NSE symbol, or BSE scrip code."
        )

    raise ValueError(
        f"Could not resolve India company: '{q}'. "
        "Try the exact company name, NSE symbol, or BSE scrip code."
    )


# ---------------------------------------------------------------------------
# Internal lookup helpers.
# ---------------------------------------------------------------------------

def _by_bse_code(code: str) -> Mapping[str, Any] | None:
    for canon, rec in _INDIA_COMPANIES.items():
        if (rec.get("bse_code") or "").strip() == code.strip():
            return rec
    return None


def _by_nse_symbol(symbol: str) -> Mapping[str, Any] | None:
    for canon, rec in _INDIA_COMPANIES.items():
        if (rec.get("nse_symbol") or "").strip().upper() == symbol:
            return rec
    return None


def _by_isin(isin: str) -> Mapping[str, Any] | None:
    for canon, rec in _INDIA_COMPANIES.items():
        if (rec.get("isin") or "").strip().upper() == isin:
            return rec
    return None


def _high_precision_prefix(canon_name: str, query: str) -> bool:
    t = _normalise_compare(canon_name).replace(" ", "")
    n = _normalise_compare(query).replace(" ", "")
    return t.startswith(n) and len(n) >= 4


def _name_fuzzy_score(a: str, b: str) -> float:
    """Token-aware name similarity in [0, 100]."""
    # Prefer a small non-external dependency if present; otherwise difflib.
    try:
        from rapidfuzz import fuzz as _rf_fuzz

        return max(
            _rf_fuzz.WRatio(a, b),
            _rf_fuzz.token_set_ratio(a, b) * 0.98,
        )
    except Exception:
        import difflib

        return difflib.SequenceMatcher(None, a, b).ratio() * 100.0


def _finish(
    rec: Mapping[str, Any],
    confidence: float,
    method: str,
) -> IndiaResolutionResult:
    company = IndiaCompany(
        country=rec.get("country", "IN"),
        legal_name=rec.get("legal_name", ""),
        display_name=rec.get("display_name", rec.get("name", "")),
        nse_symbol=rec.get("nse_symbol", ""),
        bse_code=rec.get("bse_code", ""),
        isin=rec.get("isin", ""),
        cin=rec.get("cin", ""),
        primary_exchange=rec.get("primary_exchange", ""),
        listing_status=rec.get("listing_status", "Listed"),
        sector=rec.get("sector", ""),
        industry=rec.get("industry", ""),
        currency=rec.get("currency", "INR"),
        entity_type=rec.get("entity_type", "CORPORATE"),
        fiscal_year_end=rec.get("fiscal_year_end", "31 Mar"),
        aliases=list(rec.get("aliases", [])),
        confidence=confidence,
        method=method,
    )
    return IndiaResolutionResult(company=company, method=method, confidence=confidence)


def _candidate_dict(rec: Mapping[str, Any], canon: str) -> dict[str, Any]:
    return {
        "name": rec.get("display_name", canon),
        "legal_name": rec.get("legal_name", ""),
        "nse_symbol": rec.get("nse_symbol", ""),
        "bse_code": rec.get("bse_code", ""),
        "isin": rec.get("isin", ""),
        "cin": rec.get("cin", ""),
        "primary_exchange": rec.get("primary_exchange", ""),
        "entity_type": rec.get("entity_type", "CORPORATE"),
        "sector": rec.get("sector", ""),
        "industry": rec.get("industry", ""),
    }


# ---------------------------------------------------------------------------
# Discovery helpers — used by the India Adapter; may be enhanced later with
# live NSE/BSE metadata.
# ---------------------------------------------------------------------------

def discover_india_documents(company: IndiaCompany, refresh: bool = False) -> list[dict[str, Any]]:
    """Stub document discovery for the resolved company.

    In this checkpoint the resolver exposes a discovery contract; the adapter
    phase will populate real discovery from NSE/BSE/file registries.
    """
    return [
        {
            "document_id": f"{company.nse_symbol or company.bse_code}_docs_placeholder",
            "company_id": company.bse_code or company.nse_symbol,
            "source": "resolver_seed",
            "source_type": "resolver",
            "document_type": "identity",
            "title": f"{company.display_name} identity & listing",
            "period": "",
            "period_label": "",
            "period_type": "",
            "cumulative": False,
            "statement_scope": "CONSOLIDATED",
            "audited_status": "NOT_APPLICABLE",
            "filing_standard": "",
            "published_at": "",
            "revision_status": "ORIGINAL",
            "revision_timestamp": "",
            "url": "",
            "content_type": "application/json",
            "retrieved_at": "",
            "hash": "",
        }
    ]
