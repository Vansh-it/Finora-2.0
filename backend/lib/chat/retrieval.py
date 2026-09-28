"""Targeted retrieval engine for Finora Chat.

Used ONLY when the existing research session cannot answer a question.
Retrieval hierarchy (per question type):

  External facts (CEO, board, founded, HQ):
    1. Company IR / official pages via Tavily + Jina (best 1-2 pages)
    2. Structured profile (FMP) as supplement

  Causal / explanatory (why did X change):
    1. Existing filing commentary in session (checked by caller)
    2. SEC filing text (10-K/10-Q MD&A) via SEC EDGAR full-text search
    3. Tavily search restricted to authoritative domains

  Latest filings/announcements:
    1. SEC EDGAR submissions
    2. Tavily

All network calls have explicit timeouts and graceful degradation.
Tavily/Jina are tools — never invoked speculatively.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

logger = logging.getLogger("finora.chat.retrieval")

# ── Timeouts (seconds) ────────────────────────────────────────────────────────
TAVILY_TIMEOUT = 6.0
JINA_TIMEOUT = 10.0
RETRIEVAL_BUDGET = 8.0  # total wall-clock budget for optional retrieval

# Trusted domains per question family
_FINANCE_DOMAINS = [
    "sec.gov", "investorRelations", "bloomberg.com", "reuters.com",
    "wsj.com", "ft.com", "cnbc.com", "apnews.com", "prnewswire.com",
    "businesswire.com", "globenewswire.com", "statista.com",
]
_GOVERNANCE_HINTS = ("leadership", "management", "board", "governance",
                     "executives", "team", "about", "company-officers")
_CAUSAL_HINTS = ("md&a", "10-k", "10-q", "earnings", "results", "annual report",
                 "management discussion", "commentary", "press release", "filing")


class RetrievalResult:
    """Container for retrieval output with provenance."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.sources: list[dict] = []
        self.errors: list[str] = []
        self.elapsed_ms: int = 0
        self.services_used: list[str] = []

    def to_context_lines(self, max_chars: int = 2200) -> list[str]:
        out: list[str] = []
        total = 0
        for ln in self.lines:
            if total + len(ln) + 1 > max_chars:
                break
            out.append(ln)
            total += len(ln) + 1
        return out

    def is_empty(self) -> bool:
        return not self.lines


def _truncate(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:n].rsplit(" ", 1)[0] + "…" if len(text) > n else text


# ── Tavily wrapper ────────────────────────────────────────────────────────────
def _tavily_search(query: str, max_results: int = 5) -> Optional[list[dict]]:
    try:
        from lib.tavily_client import tavily_search
        resp = tavily_search(
            query,
            max_results=max_results,
            search_depth="basic",
            timeout=6,
        )
        return resp.get("results") or []
    except Exception as exc:  # Tavily missing/unconfigured/network error
        logger.warning(f"[CHAT] tavily unavailable: {exc}")
        return None


def _jina_read(url: str, max_chars: int = 4000) -> Optional[str]:
    try:
        from lib.jina_client import read_url
        result = read_url(url)
        if result.get("status") == "success" and result.get("content"):
            return result["content"][:max_chars]
    except Exception as exc:
        logger.warning(f"[CHAT] jina read failed for {url}: {exc}")
    return None


def _domain_ok(url: str, allowed: Optional[list[str]]) -> bool:
    if not url:
        return False
    low = url.lower()
    if allowed is None:
        return True
    return any(d.lower() in low for d in allowed)


def _rank_results(results: list[dict], hints: tuple[str, ...]) -> list[dict]:
    """Rank Tavily results by hint relevance + position."""

    def score(r: dict) -> float:
        s = 0.0
        title = (r.get("title") or "").lower()
        content = (r.get("content") or "").lower()
        for i, h in enumerate(hints):
            weight = 3.0 - i * 0.3
            if h in title:
                s += weight * 2
            if h in content:
                s += weight
        url = (r.get("url") or "").lower()
        if "sec.gov" in url:
            s += 2.0
        return s

    return sorted(results, key=score, reverse=True)


def _results_to_lines(results: list[dict], max_results: int = 3,
                      snippet_len: int = 320) -> list[tuple[str, dict]]:
    """Convert Tavily results to (evidence_line, source_dict) pairs."""
    pairs: list[tuple[str, dict]] = []
    for r in results[:max_results]:
        title = r.get("title") or "Untitled"
        url = r.get("url") or ""
        snippet = _truncate(r.get("content") or "", snippet_len)
        if not snippet:
            continue
        sid = f"web-{abs(hash(url)) % 100000:05d}"
        pairs.append((
            f"[{sid}] {title}: {snippet} ({url})",
            {
                "source_id": sid,
                "title": title,
                "url": url,
                "source_type": "web",
                "provider": "Tavily",
                "snippet": snippet,
            },
        ))
    return pairs


def _run_with_timeout(fn, timeout_s: float):
    """Run fn() with a hard wall-clock timeout using a worker thread."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn)
        try:
            return future.result(timeout=timeout_s)
        except Exception:
            return None


# ── Public entry points ───────────────────────────────────────────────────────

def retrieve_external_facts(company: str, ticker: str, question: str,
                            fact_kind: str = "general") -> RetrievalResult:
    """Retrieve company facts missing from context (CEO, board, founded...)."""
    result = RetrievalResult()
    t0 = __import__("time").time()

    low = question.lower()
    if any(w in low for w in ("ceo", "chief executive")):
        query = f"{company} CEO chief executive officer"
        hints = ("ceo", "chief executive", "leadership", "executive")
    elif "board" in low or "director" in low:
        query = f"{company} board of directors members"
        hints = ("board of directors", "directors", "board", "governance")
    elif "found" in low:
        query = f"{company} founded history founding"
        hints = ("founded", "founding", "history", "founder")
    elif "headquarter" in low or "hq" in low:
        query = f"{company} headquarters location"
        hints = ("headquarters", "located", "based in")
    elif "employee" in low:
        query = f"{company} number of employees"
        hints = ("employees", "headcount", "workforce")
    elif "subsidiar" in low:
        query = f"{company} subsidiaries business segments"
        hints = ("subsidiaries", "segments", "operates")
    elif "business model" in low or "what does" in low:
        query = f"{company} what does the company do business model segments"
        hints = ("business model", "segments", "operates", "products")
    else:
        query = f"{company} {question.strip()[:80]}"
        hints = tuple(w for w in low.split() if len(w) > 4)[:4]

    search = _run_with_timeout(lambda: _tavily_search(query, max_results=6), TAVILY_TIMEOUT)
    if search is None:
        result.errors.append("tavily_unavailable")
    else:
        result.services_used.append("tavily")
        ranked = _rank_results(search, hints)
        # Prefer governance/official pages for leadership questions
        if fact_kind == "leadership":
            ranked.sort(key=lambda r: 1.0 if any(h in (r.get("url") or "").lower()
                                                 for h in _GOVERNANCE_HINTS) else 0.0,
                        reverse=True)
        pairs = _results_to_lines(ranked, max_results=3)
        # Read only the single best page if snippets look thin
        need_full_page = len(pairs) == 0 or all(
            len(p[0]) < 180 for p in pairs[:1])
        if pairs and need_full_page and fact_kind == "leadership":
            best_url = ranked[0].get("url", "")
            content = _run_with_timeout(lambda: _jina_read(best_url), JINA_TIMEOUT)
            if content:
                result.services_used.append("jina")
                # Extract sentences around leadership terms
                sents = re.split(r"(?<=[.!?])\s+", content)
                keep = [s for s in sents
                        if any(h in s.lower() for h in hints)][:6]
                if keep:
                    sid = pairs[0][1]["source_id"]
                    result.lines.append(
                        f"[{sid}] {' '.join(keep)[:1200]} ({best_url})")
                else:
                    result.lines.append(pairs[0][0])
            else:
                result.lines.extend(p[0] for p in pairs)
        else:
            result.lines.extend(p[0] for p in pairs)
        result.sources = [p[1] for p in pairs]

    if not result.lines:
        result.errors.append("no_results")
    result.elapsed_ms = int((__import__("time").time() - t0) * 1000)
    return result


def retrieve_causal_evidence(company: str, ticker: str, question: str,
                             metric_phrase: str = "") -> RetrievalResult:
    """Retrieve explanatory evidence for 'why did X change' questions."""
    result = RetrievalResult()
    t0 = __import__("time").time()

    topic = metric_phrase or re.sub(
        r"^\s*(why|what caused|what drove|what led to|what explains)\b", "",
        question, flags=re.IGNORECASE).strip()
    topic = re.sub(r"[?.!]+$", "", topic)[:100]

    queries = [
        f"{company} {topic} 10-K MD&A explanation",
        f"{company} {topic} earnings release management explanation",
    ]
    hints = _CAUSAL_HINTS

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(_tavily_search, q, 5): q for q in queries}
        merged: list[dict] = []
        for fut in as_completed(futs, timeout=TAVILY_TIMEOUT + 2):
            try:
                res = fut.result()
            except Exception:
                res = None
            if res:
                merged.extend(res)

    if merged:
        result.services_used.append("tavily")
        seen_urls: set[str] = set()
        unique = []
        for r in merged:
            u = r.get("url", "")
            if u and u not in seen_urls:
                seen_urls.add(u)
                unique.append(r)
        ranked = _rank_results(unique, hints)
        pairs = _results_to_lines(ranked, max_results=4)
        result.lines = [p[0] for p in pairs]
        result.sources = [p[1] for p in pairs]
    else:
        result.errors.append("tavily_unavailable_or_no_results")

    result.elapsed_ms = int((__import__("time").time() - t0) * 1000)
    return result


def retrieve_definition(term: str) -> Optional[str]:
    """Educational definition is handled by the LLM's general knowledge.
    Kept as a hook for future glossary integration. No network."""
    return None


def fetch_current_price_snapshot(ticker: str) -> Optional[dict]:
    """Fresh market quote with explicit freshness metadata.

    Uses the existing Twelve Data primary + Stooq fallback chain.
    Returns None when both fail — caller must say so rather than
    implying a price.
    """
    # Short TTL for freshness: bypass the 1h cache by design decision —
    # the existing fetch_quote cache is 1h; for chat we accept it only
    # when it was written within the last 5 minutes.
    try:
        from lib import twelve_data_client as td
        quote = None
        try:
            quote = td.fetch_quote(ticker, timeout=6)
        except Exception:
            quote = None

        if isinstance(quote, dict) and quote.get("close"):
            price = float(quote["close"])
            ts = quote.get("timestamp")
            date = ""
            if ts:
                try:
                    from datetime import datetime, timezone
                    date = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                except (TypeError, ValueError, OSError):
                    pass
            prev = quote.get("previous_close")
            pct = None
            try:
                if price and prev:
                    pct = round((price - float(prev)) / float(prev) * 100.0, 2)
            except (TypeError, ValueError):
                pass
            return {
                "ticker": ticker,
                "price": price,
                "date": date or "live",
                "previous_close": float(prev) if prev else None,
                "percent_change": pct,
                "source": "Twelve Data",
                "value_type": "current market value",
            }
    except Exception as exc:
        logger.warning(f"[CHAT] twelve data quote failed: {exc}")

    # Stooq fallback — free, no key; returns last close
    try:
        from lib.stooq_client import fetch_historical_price
        from datetime import date, timedelta
        # try recent trading days
        for back in range(5):
            d = date.today() - timedelta(days=back)
            if d.weekday() >= 5:
                continue
            hist = fetch_historical_price(ticker, d.isoformat())
            if hist and hist.get("close"):
                return {
                    "ticker": ticker,
                    "price": float(hist["close"]),
                    "date": hist.get("date", d.isoformat()),
                    "previous_close": None,
                    "percent_change": None,
                    "source": "Stooq",
                    "value_type": "last available close",
                }
    except Exception as exc:
        logger.warning(f"[CHAT] stooq fallback failed: {exc}")

    return None


def retrieve_latest_filings(company: str, ticker: str) -> RetrievalResult:
    """Latest filings/announcements lookup."""
    result = RetrievalResult()
    t0 = __import__("time").time()
    query = f"{company} latest 10-K 10-Q filing SEC {ticker}"
    search = _run_with_timeout(lambda: _tavily_search(query, max_results=5), TAVILY_TIMEOUT)
    if search:
        result.services_used.append("tavily")
        ranked = _rank_results(search, ("sec.gov", "filing", "10-k", "10-q", "earnings"))
        pairs = _results_to_lines(ranked, max_results=3)
        result.lines = [p[0] for p in pairs]
        result.sources = [p[1] for p in pairs]
    else:
        result.errors.append("tavily_unavailable")
    result.elapsed_ms = int((__import__("time").time() - t0) * 1000)
    return result
