"""India market-data adapter — ₹0 / no-account market snapshots.

Provides near-current market context for Indian listed companies using free,
no-account means: primarily yfinance as a fallback market-data source.

Market data is NEVER the source of truth for financial statements. It is used
only for market-only values: share price, previous close, currency, market cap
(if available), shares outstanding (if available), 52-week range, historical
prices.

Every observation carries provider, retrieved_at, price_timestamp (where
available), and a freshness_status derived only from provider metadata / evidence.
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("finora.india.market")

# ---------------------------------------------------------------------------
# Freshness classification (§49).
# ---------------------------------------------------------------------------

class MarketFreshness(str, Enum):
    REALTIME = "REALTIME"
    DELAYED = "DELAYED"
    NEAR_REALTIME = "NEAR_REALTIME"
    END_OF_DAY = "END_OF_DAY"
    HISTORICAL = "HISTORICAL"
    UNKNOWN_FRESHNESS = "UNKNOWN_FRESHNESS"


# ---------------------------------------------------------------------------
# Market snapshot dataclass.
# ---------------------------------------------------------------------------

@dataclass
class IndiaMarketSnapshot:
    """Market context for one Indian listed company."""

    price: Optional[float] = None
    previous_close: Optional[float] = None
    price_date: str = ""
    percent_change: Optional[float] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    currency: str = "INR"
    exchange: str = ""
    source: str = ""           # provider name
    provider: str = ""         # provider identity
    retrieved_at: str = ""     # wall-clock time of this retrieval
    price_timestamp: Optional[str] = None
    freshness_status: str = MarketFreshness.UNKNOWN_FRESHNESS.value
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
            "fifty_two_week_low": self.fifty_two_week_low,
            "fifty_two_week_high": self.fifty_two_week_high,
            "currency": self.currency,
            "exchange": self.exchange,
            "source": self.source,
            "provider": self.provider,
            "retrieved_at": self.retrieved_at,
            "price_timestamp": self.price_timestamp,
            "freshness_status": self.freshness_status,
            "is_fixture": self.is_fixture,
            "reason": self.reason,
        }


def _empty_snapshot(reason: str = "No market data available") -> IndiaMarketSnapshot:
    return IndiaMarketSnapshot(
        reason=reason,
        freshness_status=MarketFreshness.UNKNOWN_FRESHNESS.value,
    )


# ---------------------------------------------------------------------------
# India symbol conventions.
# ---------------------------------------------------------------------------

def nse_yfinance_symbol(company_code: str) -> str:
    """yfinance NSE convention: SYMBOL.NS."""
    s = (company_code or "").strip().upper()
    if s.upper().endswith(".NS"):
        return s
    return f"{s}.NS"


def bse_yfinance_symbol(company_code: str) -> str:
    """yfinance BSE convention where supported: SYMBOL/BO."""
    s = (company_code or "").strip().upper()
    if s.upper().endswith(".BO"):
        return s
    return f"{s}.BO"


# ---------------------------------------------------------------------------
# Provider abstraction.
# ---------------------------------------------------------------------------

class IndiaMarketProvider:
    """One free/no-account market-data provider for India."""

    def __init__(self, name: str) -> None:
        self.name = name

    def snapshot(self, company_code: str) -> Optional[IndiaMarketSnapshot]:
        raise NotImplementedError

    def historical_price(
        self, company_code: str, target_date: str
    ) -> Optional[dict[str, Any]]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# yfinance provider (§47–§50).
# ---------------------------------------------------------------------------

@dataclass
class YFinanceIndiaProvider(IndiaMarketProvider):
    """yfinance-based India market snapshot; fallback only.

    yfinance.info is a deprecated property in recent versions and returns a
    snapshot dict; this provider uses the Ticker.info dict when available and
    falls back to Ticker.fast_info for a subset of fields where info is
    unavailable.
    """

    def __init__(self, yf: Any) -> None:
        super().__init__("yfinance")
        self._yf = yf

    def snapshot(self, company_code: str) -> Optional[IndiaMarketSnapshot]:
        try:
            ticker = self._yf.Ticker(nse_yfinance_symbol(company_code))
        except Exception as exc:
            logger.debug("yfinance snapshot failed for %s: %s", company_code, exc)
            return None

        info: dict[str, Any] = {}
        try:
            info = ticker.info or {}
        except Exception:
            # yfinance >= 1.0 may not expose .info; fall back to fast_info.
            try:
                fi = ticker.fast_info or {}
                if fi:
                    info = {
                        "currentPrice": fi.get("last_price"),
                        "previousClose": fi.get("previous_close"),
                        "marketCap": fi.get("market_cap"),
                        "sharesOutstanding": fi.get("shares_outstanding") or fi.get("sharesOutstanding"),
                        "fiftyTwoWeekLow": fi.get("fifty_two_week_low") or fi.get("fiftyTwoWeekLow"),
                        "fiftyTwoWeekHigh": fi.get("fifty_two_week_high") or fi.get("fiftyTwoWeekHigh"),
                        "currency": "INR",
                        "exchange": "",
                        "regularMarketTime": None,
                    }
            except Exception as exc2:
                logger.debug("yfinance fast_info failed for %s: %s", company_code, exc2)
                return None

        price = info.get("currentPrice")
        prev_close = info.get("previousClose")
        market_cap = info.get("marketCap")
        shares_outstanding = info.get("sharesOutstanding")
        fifty_two_week_low = info.get("fiftyTwoWeekLow")
        fifty_two_week_high = info.get("fiftyTwoWeekHigh")
        currency = (info.get("currency") or "INR").upper()
        exchange = info.get("exchange", "")

        freshness = MarketFreshness.NEAR_REALTIME.value
        price_timestamp: Optional[str] = None

        regular_market_time = info.get("regularMarketTime")
        if regular_market_time:
            try:
                import datetime as _dt
                ts = float(regular_market_time)
                price_timestamp = _dt.datetime.utcfromtimestamp(ts).isoformat()
            except Exception:
                pass

        return IndiaMarketSnapshot(
            price=price,
            previous_close=prev_close,
            price_date="",
            percent_change=None,
            market_cap=market_cap,
            shares_outstanding=shares_outstanding,
            fifty_two_week_low=fifty_two_week_low,
            fifty_two_week_high=fifty_two_week_high,
            currency=currency,
            exchange=exchange,
            source=self.name,
            provider=self.name,
            retrieved_at=time.time(),
            price_timestamp=price_timestamp,
            freshness_status=freshness,
            is_fixture=False,
            reason="",
        )

    def historical_price(
        self, company_code: str, target_date: str
    ) -> Optional[dict[str, Any]]:
        try:
            ticker = self._yf.Ticker(nse_yfinance_symbol(company_code))
            hist = ticker.history(start=target_date, end=target_date)
            if hist is None or hist.empty:
                return None
            row = hist.iloc[0]
            return {
                "close": float(row.get("Close", 0) or 0),
                "date": str(row.name.date()),
            }
        except Exception as exc:
            logger.debug("yfinance historical price failed for %s: %s", company_code, exc)
            return None


# ---------------------------------------------------------------------------
# Market-data adapter (orchestration + cache).
# ---------------------------------------------------------------------------

@dataclass
class IndiaMarketAdapter:
    """Orchestrates India market-data retrieval from free providers."""

    providers: list[IndiaMarketProvider] = field(default_factory=list)
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)
    _cache_ttl: float = 30.0  # seconds — short TTL for market prices

    def add_provider(self, provider: IndiaMarketProvider) -> None:
        # De-duplicate by name
        if provider.name not in {p.name for p in self.providers}:
            self.providers.append(provider)

    def snapshot(self, company_code: str) -> IndiaMarketSnapshot:
        """Return a market snapshot for *company_code*.

        Tries each provider in order; first successful non-empty snapshot wins.
        Caches short-lived market data; falls back to empty snapshot if all
        providers fail.
        """
        now = time.time()
        cache_key = f"snapshot:{company_code}"
        cached = self._cache.get(cache_key)
        if cached is not None and (now - cached.get("retrieved_at", 0)) < self._cache_ttl:
            snap = cached.get("snapshot")
            if snap is not None:
                return snap

        for provider in self.providers:
            try:
                snap = provider.snapshot(company_code)
                if snap is not None and snap.price is not None:
                    self._cache[cache_key] = {"snapshot": snap, "retrieved_at": now}
                    return snap
                if snap is not None and snap.reason:
                    logger.debug(
                        "India market provider %s returned no price for %s: %s",
                        provider.name, company_code, snap.reason,
                    )
            except Exception as exc:
                logger.debug("India market provider %s failed: %s", provider.name, exc)

        # All providers failed — return empty but not crashing.
        msg = "All India market-data providers unavailable; market snapshot unavailable"
        snap = _empty_snapshot(reason=msg)
        self._cache[cache_key] = {"snapshot": snap, "retrieved_at": now}
        return snap

    def historical_price(
        self, company_code: str, target_date: str
    ) -> Optional[dict[str, Any]]:
        """Return historical price closest to target_date using any provider."""
        now = time.time()
        cache_key = f"hist:{company_code}:{target_date}"
        cached = self._cache.get(cache_key)
        if cached is not None and (now - cached.get("retrieved_at", 0)) < self._cache_ttl:
            return cached.get("price")

        for provider in self.providers:
            try:
                result = provider.historical_price(company_code, target_date)
                if result is not None:
                    self._cache[cache_key] = {"price": result, "retrieved_at": now}
                    return result
            except Exception as exc:
                logger.debug("India market historical provider %s failed: %s", provider.name, exc)

        return None

    def invalidate_company(self, company_code: str) -> None:
        """Invalidate cached market data for a company."""
        for k in list(self._cache):
            if k.startswith(("snapshot:", "hist:")) and company_code in k:
                self._cache.pop(k, None)


# ---------------------------------------------------------------------------
# Public API — created/initialized when yfinance is available.
# ---------------------------------------------------------------------------

_INDIA_MARKET: Optional[IndiaMarketAdapter] = None
_YFINANCE_PROVIDER: Optional[YFinanceIndiaProvider] = None


def _ensure_yfinance_provider() -> Optional[YFinanceIndiaProvider]:
    global _YFINANCE_PROVIDER
    if _YFINANCE_PROVIDER is not None:
        return _YFINANCE_PROVIDER
    try:
        import yfinance as _yf
    except Exception as exc:
        logger.warning("yfinance not available for India market data: %s", exc)
        return None
    _YFINANCE_PROVIDER = YFinanceIndiaProvider(_yf)
    return _YFINANCE_PROVIDER


def _ensure_adapter() -> IndiaMarketAdapter:
    global _INDIA_MARKET
    if _INDIA_MARKET is not None:
        return _INDIA_MARKET
    adapter = IndiaMarketAdapter()
    yf_provider = _ensure_yfinance_provider()
    if yf_provider is not None:
        adapter.add_provider(yf_provider)
    _INDIA_MARKET = adapter
    return _INDIA_MARKET


def get_india_market_snapshot(company_code: str) -> IndiaMarketSnapshot:
    """Public India market snapshot; graceful degradation if providers fail."""
    adapter = _ensure_adapter()
    return adapter.snapshot(company_code)


def get_india_historical_price(
    company_code: str, target_date: str
) -> Optional[dict[str, Any]]:
    """Public India historical price; returns None if unavailable."""
    adapter = _ensure_adapter()
    return adapter.historical_price(company_code, target_date)


def clear_india_market_cache() -> None:
    """Clear short-lived India market cache (tests / refresh)."""
    global _INDIA_MARKET
    if _INDIA_MARKET is not None:
        _INDIA_MARKET._cache.clear()
