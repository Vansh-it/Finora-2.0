"""Context sufficiency engine.

Determines whether the current Finora research session can answer a
question, and builds a COMPACT evidence pack — only the fields relevant
to the question, never the entire dashboard JSON.

Design:
  - Never dump the whole session into the LLM.
  - Every value keeps its period label and source metadata.
  - Deterministic: no LLM calls, no network.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# ── Metric keyword → session metric IDs ──────────────────────────────────────
_METRIC_SYNONYMS: dict[str, list[str]] = {
    "revenue": ["revenue", "revenue_growth", "revenue_cagr", "revenue_growth"],
    "sales": ["revenue", "revenue_growth"],
    "net income": ["net_income", "net_income_growth", "net_margin", "net_income_cagr"],
    "profit": ["net_income", "net_margin", "gross_profit"],
    "operating income": ["operating_income", "operating_margin", "operating_income_growth"],
    "ebit": ["operating_income", "operating_margin"],
    "operating profit": ["operating_income", "operating_margin"],
    "gross profit": ["gross_profit", "gross_margin"],
    "ebitda": ["ebitda", "ebitda_margin", "ev_to_ebitda", "debt_to_ebitda"],
    "eps": ["diluted_eps", "eps_growth", "eps_cagr"],
    "earnings per share": ["diluted_eps", "eps_growth"],
    "free cash flow": ["free_cash_flow", "fcf_margin", "fcf_growth"],
    "fcf": ["free_cash_flow", "fcf_margin", "fcf_growth"],
    "cash flow": ["operating_cash_flow", "free_cash_flow", "cash_conversion"],
    "operating cash flow": ["operating_cash_flow", "ocf_growth", "cash_conversion"],
    "margin": ["gross_margin", "operating_margin", "net_margin", "ebitda_margin", "fcf_margin"],
    "gross margin": ["gross_margin"],
    "operating margin": ["operating_margin"],
    "net margin": ["net_margin"],
    "profitability": ["gross_margin", "operating_margin", "net_margin", "roe", "roa", "roic"],
    "roe": ["roe"],
    "return on equity": ["roe"],
    "roa": ["roa"],
    "return on assets": ["roa"],
    "roic": ["roic"],
    "roce": ["roce"],
    "debt": ["debt_to_equity", "debt_to_ebitda", "interest_coverage", "total_liabilities"],
    "debt to equity": ["debt_to_equity"],
    "leverage": ["debt_to_equity", "debt_to_ebitda", "interest_coverage"],
    "liquidity": ["current_ratio", "quick_ratio"],
    "current ratio": ["current_ratio"],
    "quick ratio": ["quick_ratio"],
    "pe": ["pe_ratio"],
    "p/e": ["pe_ratio"],
    "valuation": ["share_price", "market_cap", "pe_ratio", "ps_ratio", "pb_ratio",
                  "ev_to_revenue", "ev_to_ebitda", "enterprise_value"],
    "market cap": ["market_cap", "enterprise_value"],
    "enterprise value": ["enterprise_value", "ev_to_revenue", "ev_to_ebitda"],
    "share price": ["share_price"],
    "stock price": ["share_price"],
    "shares outstanding": ["shares_outstanding", "market_cap"],
    "dividend": ["dividend_yield", "payout_ratio"],
    "assets": ["total_assets", "roa", "asset_turnover"],
    "liabilities": ["total_liabilities", "debt_to_equity"],
    "equity": ["shareholders_equity", "roe", "debt_to_equity"],
    "inventory": ["inventory", "days_inventory_outstanding"],
    "receivables": ["receivables", "days_sales_outstanding"],
    "risk": ["piotroski", "altman", "beneish"],
    "red flags": ["red_flags"],
    "piotroski": ["piotroski"],
    "altman": ["altman"],
    "beneish": ["beneish"],
    "capex": ["capital_expenditure", "free_cash_flow"],
    "working capital": ["working_capital", "current_ratio", "quick_ratio"],
}

# Statement items resolvable directly from financial statements
_STATEMENT_KEYS = {
    "revenue": "revenue", "sales": "revenue",
    "net income": "net_income", "net profit": "net_income",
    "operating income": "operating_income", "operating profit": "operating_income",
    "ebit": "operating_income",
    "gross profit": "gross_profit", "gross income": "gross_profit",
    "diluted eps": "diluted_eps", "eps": "diluted_eps",
    "earnings per share": "diluted_eps",
    "total assets": "total_assets", "total liabilities": "total_liabilities",
    "shareholders equity": "shareholders_equity",
    "stockholders equity": "shareholders_equity",
    "operating cash flow": "operating_cash_flow", "ocf": "operating_cash_flow",
    "capital expenditure": "capital_expenditure", "capex": "capital_expenditure",
    "cost of revenue": "cost_of_revenue", "cost of goods sold": "cost_of_revenue",
    "r&d": "research_and_development", "research and development": "research_and_development",
    "sg&a": "sga_expense", "selling general": "sga_expense",
    "inventory": "inventory", "receivables": "receivables", "payables": "payables",
    "goodwill": "goodwill", "shares outstanding": "shares_outstanding",
    "cash": "cash_and_equivalents", "debt": "total_debt",
}

_PERIOD_PAT = re.compile(
    r"\b(fy\s?(\d{4})|fiscal (year )?(\d{4})|q([1-4])\s?(\d{4})|q([1-4])\b|(19|20)(\d{2}))\b",
    re.IGNORECASE,
)


def _fmt_value(val: Any) -> str:
    """Format a raw value compactly for the LLM."""
    if val is None:
        return "N/A"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return str(val)
    if abs(f) >= 1e9:
        return f"${f / 1e9:,.1f}B"
    if abs(f) >= 1e6:
        return f"${f / 1e6:,.1f}M"
    if abs(f) < 1000 and abs(f) >= 1:
        return f"{f:,.2f}"
    return f"{f:,.4g}"


def _get_fact_value(stmts: dict, statement: str, key: str, period: str) -> Optional[dict]:
    """Return fact dict {value, ...} for a statement key + period."""
    fact = stmts.get(statement, {}).get(key)
    if not isinstance(fact, dict):
        return None
    if period and isinstance(fact.get(period), dict):
        inner = fact[period]
        return {"value": inner.get("value"), "period": period}
    if "value" in fact and fact.get("value") is not None:
        return {"value": fact["value"], "period": fact.get("period", period)}
    return None


def detect_requested_period(message: str) -> Optional[str]:
    """Extract an FY period mention from the question, if any."""
    m = re.search(r"\b(fy\s?(\d{4}))\b", message, re.IGNORECASE)
    if m:
        return f"FY{m.group(2)}"
    m = re.search(r"\b(?:fiscal (?:year )?|in )((19|20)\d{2})\b", message, re.IGNORECASE)
    if m:
        return f"FY{m.group(1)}"
    return None


def collect_requested_metrics(message: str) -> list[str]:
    """Map the question to canonical metric names we can look up."""
    low = message.lower()
    found: list[str] = []
    for phrase in sorted(_METRIC_SYNONYMS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(phrase) + r"\b", low):
            for canonical in _METRIC_SYNONYMS[phrase]:
                if canonical not in found:
                    found.append(canonical)
    return found[:12]


def build_evidence_pack(session, message: str, max_chars: int = 3500) -> dict:
    """Build a compact evidence pack for the question from the session.

    Returns:
        {
          "sufficient": bool,
          "lines": [str...],        # compact evidence lines for the LLM
          "metrics_found": [...],   # canonical metric IDs resolved
          "requested_period": str,
          "latest_period": str,
          "source_ids": [...],      # relevant source IDs for citation
          "has_price": bool,
          "price": {...} or None,   # last known market data (NOT live)
          "commentary": [...],      # filing commentary relevant to "why" questions
        }
    """
    pack: dict = {
        "sufficient": False,
        "lines": [],
        "metrics_found": [],
        "requested_period": detect_requested_period(message),
        "latest_period": "",
        "source_ids": [],
        "has_price": False,
        "price": None,
        "commentary": [],
    }
    if session is None:
        return pack

    meta = session.company_meta or {}
    stmts = session.financial_statements or {}
    metrics = session.calculated_metrics or {}
    valuation = session.valuation_metrics or {}
    market = getattr(session, "market_data", None) or {}
    summary = session.executive_summary or {}
    forensic = session.forensic_scores or {}
    red_flags = getattr(session, "red_flags", None) or []
    verification = session.verification_results or {}

    periods: list[str] = stmts.get("periods", []) or []
    latest = periods[-1] if periods else ""
    pack["latest_period"] = latest

    company_name = meta.get("name") or getattr(session, "company", "")
    ticker = meta.get("ticker", "")
    lines: list[str] = [f"Company: {company_name} ({ticker})"]
    if periods:
        lines.append(f"Periods available: {', '.join(periods)}")

    wanted = collect_requested_metrics(message)
    target_period = pack["requested_period"] or latest

    # ── 1. Statement facts ──
    low = message.lower()
    emitted: set[str] = set()
    for phrase, key in _STATEMENT_KEYS.items():
        if not re.search(r"\b" + re.escape(phrase) + r"\b", low):
            continue
        if key in emitted:
            continue
        for stmt_name in ("income_statement", "balance_sheet", "cash_flow", "additional"):
            fact = _get_fact_value(stmts, stmt_name, key, target_period)
            if fact and fact.get("value") is not None:
                lines.append(f"{key} ({fact['period']}): {_fmt_value(fact['value'])}")
                emitted.add(key)
                pack["metrics_found"].append(key)
                break

    # ── 2. Calculated metrics ──
    annual = metrics.get("annual_metrics", {})
    per_period = annual.get(target_period) or annual.get(latest) or {}
    for mid in wanted:
        if mid in emitted or mid not in per_period:
            continue
        m = per_period.get(mid)
        if isinstance(m, dict) and m.get("status") == "calculated" and m.get("value") is not None:
            lines.append(
                f"{mid} ({m.get('period', target_period)}): {m.get('display_value', _fmt_value(m.get('value')))}"
                + (f" | Formula: {m.get('formula', '')}" if m.get("formula") else "")
            )
            emitted.add(mid)
            pack["metrics_found"].append(mid)

    # Growth metrics for period comparisons
    growth = metrics.get("growth_metrics", {})
    for label, group in growth.items():
        for mid in wanted:
            if mid in emitted:
                continue
            m = group.get(mid)
            if isinstance(m, dict) and m.get("status") == "calculated" and m.get("value") is not None:
                lines.append(f"{mid} ({label}): {m.get('display_value', '')}")
                emitted.add(mid)
                pack["metrics_found"].append(f"{mid}@{label}")

    # Comparative / trend / causal questions need multi-period visibility
    is_comparative = ("why" in low or "change" in low or "decline" in low
                      or "decrease" in low or "increase" in low or "grew" in low
                      or "fell" in low or "compare" in low or "improved" in low
                      or "deteriorated" in low or "deteriorating" in low
                      or "improving" in low or "trend" in low or "over time" in low
                      or "better or worse" in low or "history" in low)
    if is_comparative:
        prev = periods[-2] if len(periods) >= 2 else ""
        if prev:
            for phrase, key in _STATEMENT_KEYS.items():
                # Period-scoped tag: the latest value may already be emitted
                # under the bare key, but prior periods must still appear.
                if f"{key}@{prev}" in emitted:
                    continue
                if not re.search(r"\b" + re.escape(phrase) + r"\b", low):
                    continue
                fact = _get_fact_value(stmts, "income_statement", key, prev) \
                    or _get_fact_value(stmts, "cash_flow", key, prev)
                if fact and fact.get("value") is not None:
                    lines.append(f"{key} ({fact['period']}): {_fmt_value(fact['value'])}")
                    emitted.add(f"{key}@{fact['period']}")
        # Calculated metrics (margins, ROE, ...) across ALL available periods
        # so trend questions can be answered without prior-period guessing.
        for p in periods[:-1]:
            per_p = annual.get(p) or {}
            for mid in wanted:
                tag = f"{mid}@{p}"
                if tag in emitted:
                    continue
                m = per_p.get(mid)
                if isinstance(m, dict) and m.get("status") == "calculated" and m.get("value") is not None:
                    lines.append(f"{mid} ({m.get('period', p)}): {m.get('display_value', _fmt_value(m.get('value')))}")
                    emitted.add(tag)
                    pack["metrics_found"].append(tag)

    # ── 3. Valuation / market data ──
    val_metrics = valuation.get("valuation_metrics", {})
    for vmid in wanted:
        if vmid in emitted:
            continue
        m = val_metrics.get(vmid)
        if isinstance(m, dict) and m.get("status") == "calculated" and m.get("value") is not None:
            price_type = m.get("price_type", "")
            asof = m.get("market_data_date", "")
            suffix = f" (as of {asof})" if asof else ""
            if price_type:
                suffix += f" [{price_type}]"
            lines.append(f"{vmid}: {m.get('display_value', '')}{suffix}")
            emitted.add(vmid)
            pack["metrics_found"].append(vmid)

    if market.get("price") is not None and ("price" in low or "market cap" in low
                                            or "trading" in low or "share" in low):
        lines.append(
            f"last_known_price ({market.get('price_date', 'unknown date')}): "
            f"${market['price']}"
        )
        pack["has_price"] = True
        pack["price"] = {
            "price": market.get("price"),
            "date": market.get("price_date", ""),
            "source": market.get("source", ""),
        }

    # ── 4. Executive summary / commentary (for interpretation & causal) ──
    is_why = "why" in low or "what caused" in low or "explain" in low
    is_interpret = any(w in low for w in ("what does", "tell", "mean", "indicate",
                                          "improving", "deteriorating", "concern"))
    if is_why or is_interpret:
        if summary.get("executive_overview"):
            lines.append(f"Analyst overview: {summary['executive_overview'][:400]}")
        for h in (summary.get("highlights") or [])[:4]:
            title = h.get("title", "")
            text = h.get("text", "")[:200]
            if text:
                lines.append(f"Highlight — {title}: {text}")
        commentary = verification.get("management_commentary") or []
        for c in commentary[:5]:
            if isinstance(c, dict):
                txt = (c.get("text") or "")[:250]
                if txt:
                    src = c.get("source_id", "")
                    lines.append(f"Filing commentary [{src}]: {txt}")
                    if src:
                        pack["source_ids"].append(src)
                    pack["commentary"].append(c)
        if summary.get("management_commentary_summary"):
            lines.append(f"Management commentary summary: {summary['management_commentary_summary'][:300]}")

    # ── 5. Forensic / red flags when risk is discussed ──
    if any(w in low for w in ("risk", "flag", "fraud", "score", "healthy", "quality")):
        p = forensic.get("piotroski") or {}
        a = forensic.get("altman") or {}
        b = forensic.get("beneish") or {}
        if isinstance(p, dict) and p.get("score") is not None:
            lines.append(f"Piotroski F-Score: {p.get('score')}/9 ({p.get('status', '')})")
        if isinstance(a, dict) and a.get("score") is not None:
            lines.append(f"Altman Z-Score: {a.get('score')} ({a.get('status', '')})")
        if isinstance(b, dict) and b.get("score") is not None:
            lines.append(f"Beneish M-Score: {b.get('score')} ({b.get('status', '')})")
        for rf in red_flags[:5]:
            if isinstance(rf, dict):
                lines.append(f"Red flag [{rf.get('severity', 'medium')}]: {rf.get('headline', '')[:150]}")

    # ── 6. Source registry (IDs for citation) ──
    registry = session.source_registry or {}
    for src in (registry.get("sources") or [])[:6]:
        sid = src.get("source_id", "")
        if sid:
            pack["source_ids"].append(sid)
            title = src.get("title", "")
            url = src.get("url", "")
            stype = src.get("source_type", "")
            period = src.get("period", "")
            lines.append(f"Source [{sid}]: {title} ({stype}, {period})" + (f" {url}" if url else ""))

    pack["lines"] = lines
    # Truncate to a char budget so prompts stay small
    out: list[str] = []
    total = 0
    for ln in lines:
        if total + len(ln) + 1 > max_chars:
            break
        out.append(ln)
        total += len(ln) + 1
    pack["lines"] = out

    # Sufficiency: we have the company + at least one data line beyond headers
    pack["sufficient"] = bool(company_name) and len(out) >= 2
    return pack


def pack_to_context_text(pack: dict) -> str:
    """Render an evidence pack as LLM-ready context text."""
    return "\n".join(pack.get("lines", []))
