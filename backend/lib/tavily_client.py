"""Tavily Search API client.

Single place responsible for Tavily communication.
Handles API key loading, retries, caching, and rate-limiting.
Tavily free tier: 1000 searches/month, 50/day basic.
"""

from __future__ import annotations

import json
import os
import time
import hashlib
from typing import Any, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from dotenv import load_dotenv
from lib.netutil import apply_ipv4_first as _net_fix
from lib.cache import BoundedTTLCache
_net_fix()

from pathlib import Path

_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path, override=True)

# ── Configuration ─────────────────────────────────────────────────────────────
TAVILY_API_URL = "https://api.tavily.com/search"
REQUEST_TIMEOUT = 10  # seconds (was 20 — tightened for pipeline SLA)
MAX_RETRIES = 2  # was 3 — cap worst-case at ~10+20=30s
RETRY_BACKOFF = 1.5  # seconds, doubles each retry
MIN_REQUEST_INTERVAL = 0.5  # seconds between requests (free-tier courtesy)


def _get_api_key() -> str:
    """Read Tavily API key from environment. Raises if not configured."""
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "TAVILY_API_KEY not set. Add it to your .env file. "
            "Get a free key at https://tavily.com"
        )
    return key


# ── In-memory cache ──────────────────────────────────────────────────────────
_tavily_cache = BoundedTTLCache(maxsize=500, ttl=3600, name="tavily")
_last_request_time: float = 0.0

def clear_cache() -> None:
    """Drop all cached tavily responses -- useful for tests."""
    _tavily_cache.clear()
def _get_cached(key: str, ttl_seconds: float = 3600.0):
    """Return cached value or None."""
    return _tavily_cache.get(key)

def _set_cache(key: str, data):
    """Store value in cache."""
    _tavily_cache.set(key, data)


_search_count = 0  # module-level counter (must exist before first search)


def get_search_count() -> int:
    """Return number of Tavily searches performed since import/reset."""
    return _search_count


def reset_search_count() -> None:
    """Reset the search counter."""
    global _search_count
    _search_count = 0


# ── Rate limiting ─────────────────────────────────────────────────────────────
def _respect_rate_limit() -> None:
    """Ensure minimum interval between requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


# ── HTTP layer ────────────────────────────────────────────────────────────────
def tavily_search(
    query: str,
    *,
    max_results: int = 5,
    search_depth: str = "basic",
    include_answer: bool = False,
    timeout: int = REQUEST_TIMEOUT,
    cache_ttl: float = 3600.0,
) -> dict:
    """Perform a Tavily search with retries, caching, and rate limiting.

    Parameters
    ----------
    query : str
        Search query.
    max_results : int
        Maximum results to return (1-10).
    search_depth : str
        'basic' or 'advanced'. Basic is cheaper and faster.
    include_answer : bool
        Whether to include Tavily's AI-generated answer.
    timeout : int
        Request timeout in seconds.
    cache_ttl : float
        Cache time-to-live in seconds. Set to 0 to skip cache.

    Returns
    -------
    dict
        Tavily response with 'results', 'answer', etc.

    Raises
    ------
    RuntimeError
        If the request fails after all retries.
    ValueError
        If the response is invalid.
    """
    global _search_count

    # Check cache first
    if cache_ttl > 0:
        cached = _get_cached(query, cache_ttl)
        if cached is not None:
            return cached

    _respect_rate_limit()
    _search_count += 1

    api_key = _get_api_key()

    payload = json.dumps({
        "query": query,
        "max_results": min(max_results, 10),
        "search_depth": search_depth,
        "include_answer": include_answer,
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            req = Request(TAVILY_API_URL, data=payload, headers=headers, method="POST")
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                if cache_ttl > 0:
                    _set_cache(query, data)
                return data
        except HTTPError as exc:
            last_error = exc
            code = exc.code
            if code == 429:
                # Rate limited — back off
                wait = RETRY_BACKOFF * (2 ** attempt)
                time.sleep(wait)
            elif code >= 400 and code < 500:
                # Client error (non-retryable except 429)
                raise RuntimeError(f"Tavily HTTP {code}: {exc.reason}")
            else:
                # Server error — retry
                wait = RETRY_BACKOFF * (2 ** attempt)
                time.sleep(wait)
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            wait = RETRY_BACKOFF * (2 ** attempt)
            time.sleep(wait)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON from Tavily: {exc}")

    raise RuntimeError(
        f"Tavily request failed after {MAX_RETRIES} attempts: {last_error}"
    )
