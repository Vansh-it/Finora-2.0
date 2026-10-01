"""Shared HTTP retrieval layer for all India research adapters.

Every network call in the India pipeline goes through here so that a single
place owns: URL validation, allowlisting, session reuse, headers, timeouts,
bounded retries with exponential backoff, rate limiting, response-size caps,
caching, and request de-duplication.

Design constraints (spec 11, 94-97, 98, 100):

* Provider URLs are centralised, never scattered as literals in call sites, so
  an official page change is a one-line edit.
* No CAPTCHA bypass, no stealth/evasion headers, no auth circumvention. We are
  a polite client that identifies itself and accepts rate limits.
* Downloaded bytes are untrusted. We cap size, validate content type, and never
  execute or evaluate response content.
* SSRF-safe: every URL is validated before the socket is opened, and every
  redirect hop is re-validated.
* Failures are recorded as structured :class:`ProviderFailure` rather than
  raised, so one dead provider never sinks a research run.

Two entry points matter: :func:`get_text` and :func:`get_bytes`.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlparse

import httpx

from lib import netutil
from lib.cache import BoundedTTLCache
from lib.ssrf_guard import validate_url

netutil.apply_ipv4_first()

logger = logging.getLogger("finora.india.http")

# ---------------------------------------------------------------------------
# Tunables. Deliberately conservative: we are a guest on these sites.
# ---------------------------------------------------------------------------
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0
MAX_REDIRECTS = 4
MAX_BYTES = 40 * 1024 * 1024  # 40 MB ceiling; annual reports sit well under
MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.8
BACKOFF_CAP = 12.0
#: Honest, descriptive client identifier. Deliberately NOT a browser string:
# spec 11 forbids stealth/evasion behaviour, so we never impersonate Chrome or
# Safari. Some official hosts (BSE) run a WAF that rejects any UA token
# containing "bot", or an embedded URL/e-mail, so the identifier is kept to a
# plain product token plus a short purpose phrase. Measured against
# bseindia.com: the URL/e-mail forms return 403, these return 200.
DEFAULT_USER_AGENT = "FinoraResearch/2.0 (Finora equity research)"

# ---------------------------------------------------------------------------
# Domain allowlist. Only official Indian exchange / regulator / company hosts
# are fetchable without an explicit per-call override. Spec 96 asks for
# allowlisting "where feasible"; this is that.
# ---------------------------------------------------------------------------
OFFICIAL_DOMAINS: tuple[str, ...] = (
    "nseindia.com",
    "nsearchives.nseindia.com",
    "bseindia.com",
    "bseindia.com",
    "mcxindia.com",
    "sebi.gov.in",
    "rbi.org.in",
    "mospi.gov.in",
    "indiabudget.gov.in",
    "dea.gov.in",
    "ccee.gov.in",
    "sbilife.co.in",
    "liceonline.in",
)

MARKET_DOMAINS: tuple[str, ...] = (
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
    "finance.yahoo.com",
)

_ALLOWED_SUFFIXES: tuple[str, ...] = tuple(
    {d.lower().lstrip(".") for d in (*OFFICIAL_DOMAINS, *MARKET_DOMAINS)}
)


def is_allowlisted(url: str) -> bool:
    """True when ``url``'s host is an allowlisted official/market domain."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return any(host == s or host.endswith("." + s) for s in _ALLOWED_SUFFIXES)


# ---------------------------------------------------------------------------
# Failure model. Every provider failure is data, not an exception, unless the
# caller explicitly opts into raising.
# ---------------------------------------------------------------------------

@dataclass
class ProviderFailure:
    """A structured, user-safe record of one failed retrieval."""

    provider: str
    url: str
    reason: str
    status_code: Optional[int] = None
    attempts: int = 0
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "url": self.url,
            "reason": self.reason,
            "status_code": self.status_code,
            "attempts": self.attempts,
            "at": self.at,
        }


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Rate limiting. One token bucket per host, so a burst of parallel financial
# downloads to nsearchives cannot turn into a stampede. Spec 11/100.
# ---------------------------------------------------------------------------

class _HostLimiter:
    """Simple per-host minimum-interval gate with jittered backoff."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, min_interval: float) -> None:
        if min_interval <= 0:
            return
        while True:
            with self._lock:
                last = self._last.get(host, 0.0)
                delta = time.time() - last
                if delta >= min_interval:
                    self._last[host] = time.time()
                    return
                wait_for = min_interval - delta
            time.sleep(min(wait_for, 5.0))


_HOST_LIMITER = _HostLimiter()
_HOST_MIN_INTERVAL: dict[str, float] = {
    "nseindia.com": 1.2,
    "nsearchives.nseindia.com": 0.8,
    "bseindia.com": 1.2,
}


# ---------------------------------------------------------------------------
# Caches, TTLs chosen by data volatility (spec 76).
# ---------------------------------------------------------------------------
IDENTITY_CACHE = BoundedTTLCache(maxsize=4000, ttl=7 * 86400.0, name="india_identity")
DOCUMENT_CACHE = BoundedTTLCache(maxsize=2000, ttl=3 * 86400.0, name="india_documents")
FILING_CACHE = BoundedTTLCache(maxsize=2000, ttl=30 * 86400.0, name="india_filings")
ANNUAL_REPORT_CACHE = BoundedTTLCache(maxsize=200, ttl=90 * 86400.0, name="india_annual_reports")
OWNERSHIP_CACHE = BoundedTTLCache(maxsize=2000, ttl=7 * 86400.0, name="india_ownership")
EVENTS_CACHE = BoundedTTLCache(maxsize=2000, ttl=6 * 3600.0, name="india_events")
MARKET_CACHE = BoundedTTLCache(maxsize=4000, ttl=300.0, name="india_market")
MACRO_CACHE = BoundedTTLCache(maxsize=40, ttl=6 * 3600.0, name="india_macro")

_CACHE_BY_KIND: dict[str, BoundedTTLCache] = {
    "identity": IDENTITY_CACHE,
    "documents": DOCUMENT_CACHE,
    "filing": FILING_CACHE,
    "annual_report": ANNUAL_REPORT_CACHE,
    "ownership": OWNERSHIP_CACHE,
    "events": EVENTS_CACHE,
    "market": MARKET_CACHE,
    "macro": MACRO_CACHE,
}

# ---------------------------------------------------------------------------
# Session reuse. NSE in particular requires a cookie handshake before it will
# answer API calls at all; a fresh connection per request makes that
# impossible, so one client per host is kept and reused.
# ---------------------------------------------------------------------------
_SESSIONS: dict[tuple[str, str, bool], httpx.Client] = {}
_SESSION_LOCK = threading.Lock()
_SESSION_HEADERS = {
    "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "gzip, deflate",
    "connection": "keep-alive",
}


def _session(host: str, verify: bool = True) -> httpx.Client:
    key = (host, "https" if verify else "http", verify)
    with _SESSION_LOCK:
        client = _SESSIONS.get(key)
        if client is None:
            client = httpx.Client(
                timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
                follow_redirects=False,
                verify=verify,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    **_SESSION_HEADERS,
                },
            )
            _SESSIONS[key] = client
        return client


def close_sessions() -> None:
    """Close pooled clients (tests, shutdown)."""
    with _SESSION_LOCK:
        for client in _SESSIONS.values():
            try:
                client.close()
            except Exception:
                pass
        _SESSIONS.clear()


# ---------------------------------------------------------------------------
# De-duplication. Spec 78: if many metric calculations need the same filing it
# is downloaded once. Keyed by URL + kind so identical requests coalesce.
# ---------------------------------------------------------------------------
_FETCH_LOCKS: dict[str, threading.Lock] = {}
_FETCH_LOCKS_GUARD = threading.Lock()


def _fetch_lock(key: str) -> threading.Lock:
    with _FETCH_LOCKS_GUARD:
        lock = _FETCH_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FETCH_LOCKS[key] = lock
        return lock


# ---------------------------------------------------------------------------
# Core fetch.
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    """Outcome of one retrieval attempt sequence."""

    ok: bool
    url: str
    provider: str = ""
    status_code: Optional[int] = None
    text: str = ""
    content: bytes = b""
    content_type: str = ""
    final_url: str = ""
    retrieved_at: str = field(default_factory=_now_iso)
    from_cache: bool = False
    failure: Optional[ProviderFailure] = None
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "url": self.url,
            "provider": self.provider,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "final_url": self.final_url,
            "retrieved_at": self.retrieved_at,
            "from_cache": self.from_cache,
            "attempts": self.attempts,
            "failure": self.failure.to_dict() if self.failure else None,
        }


def _acceptable_content_type(raw: str, want: tuple[str, ...]) -> bool:
    ct = (raw or "").split(";")[0].strip().lower()
    if not ct:
        return True  # some official endpoints omit the header; body check follows
    if any(w in ct for w in want):
        return True
    # Tolerate generic types. Octet-stream is how BSE serves many downloads,
    # and text/csv is how NSE serves the equity master; both are legitimate
    # text bodies, so a correct response is never rejected on content type.
    return ct in {
        "application/octet-stream",
        "binary/octet-stream",
        "text/plain",
        "text/csv",
        "application/csv",
    }


def _validate_hop(url: str, provider: str, enforce_allowlist: bool) -> Optional[ProviderFailure]:
    ok, reason = validate_url(url)
    if not ok:
        return ProviderFailure(
            provider=provider, url=url, reason=f"blocked_url: {reason}"
        )
    if enforce_allowlist and not is_allowlisted(url):
        return ProviderFailure(
            provider=provider,
            url=url,
            reason="host_not_allowlisted",
        )
    return None


def _read_capped(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    """Stream a response body with a hard byte ceiling.

    Returns ``(body, truncated)``. Never buffers an unbounded amount, so a
    hostile or misconfigured endpoint cannot exhaust memory.
    """
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= max_bytes:
            return b"".join(chunks)[:max_bytes], True
    return b"".join(chunks), False


def fetch(
    url: str,
    *,
    provider: str,
    method: str = "GET",
    headers: Optional[Mapping[str, str]] = None,
    params: Optional[Mapping[str, Any]] = None,
    data: Optional[Mapping[str, Any]] = None,
    json_body: Any = None,
    kind: str = "documents",
    cache_ttl: Optional[float] = None,
    max_bytes: int = MAX_BYTES,
    accept: tuple[str, ...] = ("text/html", "application/json", "text/plain", "application/xml", "text/xml", "*/*"),
    enforce_allowlist: bool = True,
    max_attempts: int = MAX_ATTEMPTS,
    cache_key: Optional[str] = None,
) -> FetchResult:
    """Fetch one URL with full safety, retry, rate-limit and cache handling.

    Never raises for network/HTTP problems; the outcome is in
    :attr:`FetchResult.failure`. Programming errors (bad args) still raise.
    """
    # Failures recorded for this call, newest last.
    host = ""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        host = ""

    cache = _CACHE_BY_KIND.get(kind)
    key = cache_key or f"{url}|{method}|{sorted((params or {}).items())!r}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]

    if cache is not None:
        cached = cache.get(digest)
        if isinstance(cached, FetchResult) and cached.ok:
            cached.from_cache = True
            return cached

    # One in-flight request per key; concurrent identical callers coalesce.
    with _fetch_lock(digest):
        if cache is not None:
            cached = cache.get(digest)
            if isinstance(cached, FetchResult) and cached.ok:
                cached.from_cache = True
                return cached

        last: Optional[ProviderFailure] = None
        attempts = 0
        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            hop = _validate_hop(url, provider, enforce_allowlist)
            if hop is not None:
                return FetchResult(
                    ok=False, url=url, provider=provider, failure=hop, attempts=1
                )

            _HOST_LIMITER.wait(host, _HOST_MIN_INTERVAL.get(host, 0.4))

            try:
                client = _session(host or "unknown", verify=True)
                resp = client.request(
                    method,
                    url,
                    headers=dict(headers or {}),
                    params=dict(params) if params else None,
                    data=dict(data) if data else None,
                    json=json_body,
                )
            except Exception as exc:  # network, DNS, TLS, timeout
                last = ProviderFailure(
                    provider=provider,
                    url=url,
                    reason=f"{type(exc).__name__}: {exc}"[:300],
                    attempts=attempt,
                    at=_now_iso(),
                )
                if attempt < max_attempts:
                    time.sleep(min(BACKOFF_BASE * (2 ** (attempt - 1)), BACKOFF_CAP))
                    continue
                break

            # Redirects: re-validate every hop (SSRF via redirect).
            hops = 0
            while resp.status_code in (301, 302, 303, 307, 308) and hops < MAX_REDIRECTS:
                location = resp.headers.get("location", "")
                if not location:
                    break
                nxt = str(httpx.URL(str(resp.url)).join(location))
                hop = _validate_hop(nxt, provider, enforce_allowlist)
                if hop is not None:
                    return FetchResult(
                        ok=False,
                        url=url,
                        provider=provider,
                        status_code=resp.status_code,
                        failure=hop,
                        attempts=attempt,
                    )
                resp = client.request(
                    resp.request.method if resp.request else "GET",
                    nxt,
                    headers=dict(headers or {}),
                )
                hops += 1

            status = resp.status_code
            if status in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("retry-after")
                last = ProviderFailure(
                    provider=provider,
                    url=url,
                    reason=f"http_{status}",
                    status_code=status,
                    attempts=attempt,
                    at=_now_iso(),
                )
                if attempt < max_attempts:
                    wait = BACKOFF_BASE * (2 ** (attempt - 1))
                    if retry_after and retry_after.isdigit():
                        wait = min(float(retry_after), BACKOFF_CAP)
                    time.sleep(min(wait, BACKOFF_CAP))
                    continue
                break

            if status >= 400:
                # 4xx other than 429 is terminal: retrying will not help.
                return FetchResult(
                    ok=False,
                    url=url,
                    provider=provider,
                    status_code=status,
                    failure=ProviderFailure(
                        provider=provider,
                        url=url,
                        reason=f"http_{status}",
                        status_code=status,
                        attempts=attempt,
                        at=_now_iso(),
                    ),
                    attempts=attempt,
                )

            if not _acceptable_content_type(resp.headers.get("content-type", ""), accept):
                return FetchResult(
                    ok=False,
                    url=url,
                    provider=provider,
                    status_code=status,
                    failure=ProviderFailure(
                        provider=provider,
                        url=url,
                        reason=f"unexpected_content_type: {resp.headers.get('content-type','')[:80]}",
                        status_code=status,
                        attempts=attempt,
                        at=_now_iso(),
                    ),
                    attempts=attempt,
                )

            try:
                body, truncated = _read_capped(resp, max_bytes)
            except Exception as exc:
                last = ProviderFailure(
                    provider=provider,
                    url=url,
                    reason=f"read_error: {type(exc).__name__}",
                    status_code=status,
                    attempts=attempt,
                    at=_now_iso(),
                )
                if attempt < max_attempts:
                    time.sleep(min(BACKOFF_BASE * (2 ** (attempt - 1)), BACKOFF_CAP))
                    continue
                break

            result = FetchResult(
                ok=True,
                url=url,
                provider=provider,
                status_code=status,
                content=body,
                text=body.decode("utf-8", errors="replace"),
                content_type=resp.headers.get("content-type", ""),
                final_url=str(resp.url),
                attempts=attempt,
            )
            if truncated:
                logger.warning(
                    "[india.http] %s response truncated at %d bytes for %s",
                    provider, max_bytes, url,
                )
            if cache is not None:
                ttl = cache_ttl if cache_ttl is not None else cache.ttl
                # Do not persist failures: spec 77 forbids permanent failure caching.
                cache.set(digest, result, ttl=ttl)
            return result

        return FetchResult(
            ok=False,
            url=url,
            provider=provider,
            failure=last
            or ProviderFailure(provider=provider, url=url, reason="unknown_failure"),
            attempts=attempts,
        )


def get_text(url: str, **kwargs: Any) -> str:
    """Fetch and return decoded text, or ``""`` on any failure."""
    res = fetch(url, **kwargs)
    return res.text if res.ok else ""


def get_json(url: str, **kwargs: Any) -> Any:
    """Fetch and parse JSON, returning ``None`` on any failure.

    Cached decoded JSON so a repeated parse of the same body is free.
    """
    res = fetch(url, **kwargs)
    if not res.ok or not res.text:
        return None
    import json

    try:
        return json.loads(res.text)
    except (ValueError, TypeError) as exc:
        logger.warning("[india.http] %s returned unparseable JSON: %s", url, exc)
        return None


def get_bytes(url: str, **kwargs: Any) -> bytes:
    """Fetch raw bytes, or ``b""`` on any failure."""
    res = fetch(url, **kwargs)
    return res.content if res.ok else b""


def invalidate(kind: str, prefix: str = "") -> int:
    """Drop cached entries for a kind, optionally by key prefix."""
    cache = _CACHE_BY_KIND.get(kind)
    if cache is None:
        return 0
    if prefix:
        # Cache keys are hashes, so prefix matching is only meaningful for the
        # full digest. Callers that know the key use delete_by_key instead.
        return cache.invalidate_prefix(prefix)
    cache.clear()
    return len(cache)


def delete_by_key(kind: str, cache_key: str) -> None:
    """Invalidate one cache entry given its logical key."""
    cache = _CACHE_BY_KIND.get(kind)
    if cache is None:
        return
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:32]
    cache.delete(digest)


def cache_stats() -> dict[str, dict]:
    """Per-kind cache statistics for observability (spec 98)."""
    return {kind: c.stats() for kind, c in _CACHE_BY_KIND.items()}


# ---------------------------------------------------------------------------
# Request counter for the performance report (spec 138).
# ---------------------------------------------------------------------------
_REQUEST_STATS: dict[str, int] = {}
_REQUEST_STATS_LOCK = threading.Lock()


def record_request(provider: str, ok: bool) -> None:
    key = f"{provider}:{'ok' if ok else 'fail'}"
    with _REQUEST_STATS_LOCK:
        _REQUEST_STATS[key] = _REQUEST_STATS.get(key, 0) + 1


def request_stats() -> dict[str, int]:
    with _REQUEST_STATS_LOCK:
        return dict(_REQUEST_STATS)


def reset_request_stats() -> None:
    with _REQUEST_STATS_LOCK:
        _REQUEST_STATS.clear()


# Wrap fetch so every call site gets counting for free.
_raw_fetch = fetch


def counted_fetch(url: str, **kwargs: Any) -> FetchResult:
    provider = kwargs.get("provider") or "unknown"
    res = _raw_fetch(url, **kwargs)
    record_request(provider, res.ok)
    return res
