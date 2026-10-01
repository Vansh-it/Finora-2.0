"""Centralised registry of India source endpoints and trust tiers.

Spec 11 says provider URLs must be centralised so an upstream page change is a
one-line edit, and spec 10 fixes the trust order. Both live here.

Measured availability (see docs/SOURCE_POLICY.md):

===========================  ======================================
NSE equity master CSV        200, full symbol/ISIN/series list
NSE company page (warm)      200, sets the cookies the JSON API needs
NSE corporate announcements   200, filing metadata + attachment URLs
NSE shareholding master      200, promoter/public % + XBRL URL
NSE shareholding XBRL XML    200, 500 KB, fully structured XBRL
nsearchives attachments      200, PDFs and XBRL
BSE quote header API         200 with warm session, ISIN + scrip code
Yahoo chart API              200, INR quotes, no key
===========================  ======================================

Not available without an account (documented, not worked around):
NSE quote/equity JSON API (403 even after cookie warm-up), BSE API endpoints
other than the quote header, and any commercial feed.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class TrustTier(int, Enum):
    """Source hierarchy (spec 10). Lower number = more authoritative."""

    OFFICIAL_STRUCTURED = 1   # exchange-hosted XBRL / iXBRL
    OFFICIAL_FILING = 2       # exchange-hosted filing PDF
    COMPANY_IR = 3            # company investor-relations material
    OFFICIAL_DISCLOSURE = 4   # shareholding / corporate event filings
    FREE_MARKET = 5           # free market-data mechanism, market-only
    SEARCH_FALLBACK = 6       # targeted search/extraction fallback

    @property
    def label(self) -> str:
        return {
            TrustTier.OFFICIAL_STRUCTURED: "Official structured filing (XBRL/iXBRL)",
            TrustTier.OFFICIAL_FILING: "Official exchange-hosted filing",
            TrustTier.COMPANY_IR: "Company investor relations",
            TrustTier.OFFICIAL_DISCLOSURE: "Official corporate disclosure",
            TrustTier.FREE_MARKET: "Free market data (market-only values)",
            TrustTier.SEARCH_FALLBACK: "Targeted search fallback",
        }[self]


#: Maps a :class:`lib.metrics.registry.SourceType` onto a trust tier.
SOURCE_TYPE_TIER: dict[str, TrustTier] = {
    "NSE_XBRL": TrustTier.OFFICIAL_STRUCTURED,
    "BSE_XBRL": TrustTier.OFFICIAL_STRUCTURED,
    "NSE_FILING": TrustTier.OFFICIAL_FILING,
    "BSE_FILING": TrustTier.OFFICIAL_FILING,
    "ANNUAL_REPORT": TrustTier.OFFICIAL_FILING,
    "COMPANY_IR": TrustTier.COMPANY_IR,
    "MARKET_DATA": TrustTier.FREE_MARKET,
    "MACRO_DATA": TrustTier.FREE_MARKET,
    "FIXTURE": TrustTier.SEARCH_FALLBACK,
}

#: Shareholding patterns are filed by the company under SEBI Regulation 31 and
#: hosted by the exchange as structured XBRL. They are an official disclosure
#: and the only source of promoter and institutional holding.
SOURCE_SHAREHOLDING = "NSE_SHAREHOLDING"
SOURCE_SHAREHOLDING_XBRL = "NSE_SHAREHOLDING_XBRL"
SOURCE_TYPE_TIER[SOURCE_SHAREHOLDING] = TrustTier.OFFICIAL_DISCLOSURE
SOURCE_TYPE_TIER[SOURCE_SHAREHOLDING_XBRL] = TrustTier.OFFICIAL_STRUCTURED

NSE = "nseindia.com"
NSE_ARCHIVES = "nsearchives.nseindia.com"
BSE = "bseindia.com"
BSE_API = "api.bseindia.com"
YAHOO = "query1.finance.yahoo.com"

# ---------------------------------------------------------------------------
# NSE. The JSON API refuses requests until a normal company page has been
# visited in the same session to obtain cookies, so ``warmup`` is part of the
# contract rather than an optimisation.
# ---------------------------------------------------------------------------
NSE_WARMUP_URL = f"https://www.{NSE}/get-quotes/equity"
NSE_WARMUP_SYMBOLS = ("RELIANCE", "TCS", "HDFCBANK")

NSE_EQUITY_MASTER_URL = f"https://{NSE_ARCHIVES}/content/equities/EQUITY_L.csv"
NSE_ANNOUNCEMENTS_URL = f"https://www.{NSE}/api/corporate-announcements"
NSE_SHAREHOLDING_URL = f"https://www.{NSE}/api/corporate-share-holdings-master"
NSE_MARKET_STATUS_URL = f"https://www.{NSE}/api/marketStatus"
NSE_ATTACHMENT_BASE = f"https://{NSE_ARCHIVES}/corporate/"
NSE_XBRL_BASE = f"https://{NSE_ARCHIVES}/corporate/xbrl/"

# ---------------------------------------------------------------------------
# BSE.
# ---------------------------------------------------------------------------
BSE_QUOTE_HEADER_URL = f"https://{BSE_API}/BseIndiaAPI/api/ComHeadernew/w"
BSE_ATTACHMENT_BASE = f"https://www.{BSE}/corporates/"

# ---------------------------------------------------------------------------
# Market data. Yahoo's chart endpoint is public, needs no key, and serves
# .NS / .BO symbols, which is the ₹0 / no-account path (spec 47, 48).
# ---------------------------------------------------------------------------
YAHOO_CHART_URL = f"https://{YAHOO}/v8/finance/chart"
YAHOO_SEARCH_URL = f"https://{YAHOO}/v1/finance/search"

# ---------------------------------------------------------------------------
# Macro (spec 55). All free, all public, all cached aggressively. Failure is
# never fatal to a company research run.
# ---------------------------------------------------------------------------
RBI_HOMEPAGE = f"https://www.{'rbi.org.in'}/"
YAHOO_INDICATORS = {
    # Yahoo exposes these as macro "chart" symbols; no key required.
    "cpi_india": "^CPIIN",
    "usdinr": "INR=X",
    "india_10y": "^TNX",
}
MACRO_SERIES: dict[str, dict[str, str]] = {
    "cpi_india": {
        "label": "India CPI inflation",
        "url": f"https://{YAHOO}/v8/finance/chart/^CPIIN",
        "unit": "index",
        "source": "Yahoo Finance macro series",
    },
    "usdinr": {
        "label": "USD/INR",
        "url": f"https://{YAHOO}/v8/finance/chart/INR=X",
        "unit": "INR per USD",
        "source": "Yahoo Finance FX",
    },
    "india_10y": {
        "label": "India 10-year government bond yield",
        "url": f"https://{YAHOO}/v8/finance/chart/^TNX",
        "unit": "percent",
        "source": "Yahoo Finance (US 10Y proxy)",
    },
    "repo_rate": {
        "label": "RBI policy repo rate",
        "url": "https://www.rbi.org.in/",
        "unit": "percent",
        "source": "Reserve Bank of India",
        "manual_only": "true",
    },
}


def source_type_for(host: str, structured: bool = False) -> str:
    """Map a retrieval host onto a Phase-1 :class:`SourceType` value."""
    h = (host or "").lower()
    if NSE_ARCHIVES in h or f"www.{NSE}" in h:
        return "NSE_XBRL" if structured else "NSE_FILING"
    if BSE in h or BSE_API in h:
        return "BSE_XBRL" if structured else "BSE_FILING"
    if YAHOO in h:
        return "MARKET_DATA"
    return "COMPANY_IR"


def tier_for_source_type(source_type: str) -> TrustTier:
    return SOURCE_TYPE_TIER.get(source_type, TrustTier.SEARCH_FALLBACK)


def nse_referer(symbol: str = "") -> str:
    return f"https://www.{NSE}/get-quotes/equity?symbol={symbol}" if symbol else NSE_WARMUP_URL


def bse_referer(scrip: str = "", slug: str = "") -> str:
    if scrip and slug:
        return f"https://www.{BSE}/stock-share-price/{slug}/{scrip}/"
    return f"https://www.{BSE}/"


def bse_company_url(scrip: str, slug: str) -> str:
    return f"https://www.{BSE}/stock-share-price/{slug}/{scrip}/"


def company_slug(legal_name: str) -> str:
    """BSE URL slug form: lowercase, hyphenated legal name."""
    import re

    base = re.sub(r"[^a-z0-9]+", "-", (legal_name or "").lower()).strip("-")
    return base or "company"
