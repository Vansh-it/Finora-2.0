"""Deterministic financial calculation layer for chat.

The LLM is NEVER the source of arithmetic truth. This module computes
metrics from session financial data (or inline numbers extracted from the
question) and returns results with full provenance:

    {
      "metric": "operating_margin",
      "value": 4.64,
      "display": "4.64%",
      "formula": "operating_income / revenue",
      "inputs": {...},
      "period": "FY2025",
      "source_ids": [...],
      "status": "calculated" | "unavailable",
    }
"""

from __future__ import annotations

import re
from typing import Any, Optional


def _val(fact: Any) -> Optional[float]:
    if isinstance(fact, dict):
        fact = fact.get("value")
    if fact is None:
        return None
    try:
        return float(fact)
    except (TypeError, ValueError):
        return None


def _get_fact(stmts: dict, statement: str, key: str, period: str) -> Optional[dict]:
    fact = stmts.get(statement, {}).get(key)
    if not isinstance(fact, dict):
        return None
    if period and isinstance(fact.get(period), dict):
        return fact[period]
    if "value" in fact and fact.get("value") is not None:
        return fact
    return None


def _pct(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x * 100.0, 2)


def _display_pct(x: Optional[float]) -> str:
    return "N/A" if x is None else f"{x:.2f}%"


def _display_mult(x: Optional[float]) -> str:
    return "N/A" if x is None else f"{x:.2f}x"


def _display_usd(x: Optional[float]) -> str:
    if x is None:
        return "N/A"
    if abs(x) >= 1e9:
        return f"${x / 1e9:,.1f}B"
    if abs(x) >= 1e6:
        return f"${x / 1e6:,.1f}M"
    return f"${x:,.2f}"


def _result(metric: str, value: Optional[float], display: str, formula: str,
            inputs: dict, period: str, source_ids: list | None = None,
            note: str = "", value_type: str = "calculated") -> dict:
    return {
        "metric": metric,
        "value": value,
        "display": display,
        "formula": formula,
        "inputs": inputs,
        "period": period,
        "source_ids": source_ids or [],
        "note": note,
        "value_type": value_type,
        "status": "calculated" if value is not None else "unavailable",
    }


def _fmt_compact(x: Optional[float]) -> str:
    return _display_usd(x)


def calculate_from_session(session, question: str) -> list[dict]:
    """Compute every metric the question asks for, from session data.

    Deterministic — no LLM, no network. Returns [] when the session has
    no financial data.
    """
    out: list[dict] = []
    if session is None:
        return out

    stmts = session.financial_statements or {}
    valuation = (session.valuation_metrics or {}).get("valuation_metrics", {})
    market = getattr(session, "market_data", None) or {}
    periods = stmts.get("periods", [])
    target = None

    m = re.search(r"\bfy\s?(\d{4})\b", question, re.IGNORECASE)
    if m:
        target = f"FY{m.group(1)}"
    if not target:
        target = periods[-1] if periods else ""

    low = question.lower()
    src_ids = _session_source_ids(session)

    def income(key: str, period: str = "") -> Optional[float]:
        return _val(_get_fact(stmts, "income_statement", key, period or target))

    def bs(key: str, period: str = "") -> Optional[float]:
        return _val(_get_fact(stmts, "balance_sheet", key, period or target))

    def cf(key: str, period: str = "") -> Optional[float]:
        return _val(_get_fact(stmts, "cash_flow", key, period or target))

    def add(name: str, value: Optional[float], display: str, formula: str,
            inputs: dict, value_type: str = "calculated") -> None:
        out.append(_result(name, value, display, formula, inputs, target,
                           src_ids, value_type=value_type))

    # ── Margins ──
    def _margin(name: str, numer: Optional[float], denom: Optional[float]) -> None:
        if numer is None or not denom:
            add(name, None, "N/A", f"{name} = numerator / revenue",
                {}, note="Required inputs unavailable")
            return
        v = _pct(numer / denom)
        add(name, v, _display_pct(v), f"{name} = numerator / revenue * 100",
            {"numerator": numer, "revenue": denom})

    wants = _requested(question)

    if "revenue" in wants or "all" in wants:
        v = income("revenue")
        add("revenue", v, _fmt_compact(v), "reported value", {"source": "SEC XBRL"},
            value_type="reported")

    if {"gross_margin", "all"} & wants:
        _margin("gross_margin", income("gross_profit"), income("revenue"))

    if {"operating_margin", "all"} & wants:
        _margin("operating_margin", income("operating_income"), income("revenue"))

    if {"net_margin", "all"} & wants:
        _margin("net_margin", income("net_income"), income("revenue"))

    if {"ebitda_margin", "all"} & wants:
        ebitda = income("ebitda") or _sum(income("operating_income"),
                                          _val(_get_fact(stmts, "additional", "d_and_a", target)))
        _margin("ebitda_margin", ebitda, income("revenue"))

    # ── FCF ──
    if {"free_cash_flow", "fcf_margin", "all"} & wants:
        ocf = cf("operating_cash_flow")
        capex = cf("capital_expenditure")
        fcf = None
        if ocf is not None and capex is not None:
            fcf = ocf + capex if capex < 0 else ocf - capex
        if "free_cash_flow" in wants or "all" in wants:
            add("free_cash_flow", fcf, _fmt_compact(fcf),
                "FCF = operating_cash_flow + capex (capex reported negative)",
                {"operating_cash_flow": ocf, "capex": capex})
        if {"fcf_margin", "all"} & wants:
            fv = _pct(fcf / income("revenue")) if fcf is not None and income("revenue") else None
            add("fcf_margin", fv, _display_pct(fv), "fcf_margin = FCF / revenue * 100",
                {"fcf": fcf, "revenue": income("revenue")})

    # ── Returns ──
    if {"roe", "all"} & wants:
        ni, eq = income("net_income"), bs("shareholders_equity")
        v = _pct(ni / eq) if ni is not None and eq else None
        add("roe", v, _display_pct(v), "ROE = net_income / shareholders_equity * 100",
            {"net_income": ni, "equity": eq})

    if {"roa", "all"} & wants:
        ni, ta = income("net_income"), bs("total_assets")
        v = _pct(ni / ta) if ni is not None and ta else None
        add("roa", v, _display_pct(v), "ROA = net_income / total_assets * 100",
            {"net_income": ni, "total_assets": ta})

    if {"roic", "all"} & wants:
        oi, ta, cash = income("operating_income"), bs("total_assets"), bs("cash_and_equivalents")
        eq, debt = bs("shareholders_equity"), bs("total_debt")
        v = None
        if oi is not None and ta is not None:
            ic = ta - (cash or 0.0)
            if ic > 0:
                v = _pct(oi / ic)
        add("roic", v, _display_pct(v), "ROIC = operating_income / (total_assets - cash)",
            {"operating_income": oi, "total_assets": ta, "cash": cash,
             "equity": eq, "debt": debt},
            note="simplified ROIC approximation" if v is not None else "")

    if {"roce", "all"} & wants:
        oi, ta, cl = income("operating_income"), bs("total_assets"), bs("current_liabilities")
        v = None
        if oi is not None and ta is not None and cl is not None:
            ce = ta - cl
            if ce > 0:
                v = _pct(oi / ce)
        add("roce", v, _display_pct(v), "ROCE = operating_income / (total_assets - current_liabilities)",
            {"operating_income": oi, "total_assets": ta, "current_liabilities": cl})

    # ── Liquidity ──
    if {"current_ratio", "all"} & wants:
        ca, cl = bs("current_assets"), bs("current_liabilities")
        v = round(ca / cl, 3) if ca is not None and cl else None
        add("current_ratio", v, _display_mult(v), "current_ratio = current_assets / current_liabilities",
            {"current_assets": ca, "current_liabilities": cl})

    if {"quick_ratio", "all"} & wants:
        ca, inv, cl = bs("current_assets"), bs("inventory"), bs("current_liabilities")
        v = round((ca - inv) / cl, 3) if ca is not None and inv is not None and cl else None
        add("quick_ratio", v, _display_mult(v), "quick_ratio = (current_assets - inventory) / current_liabilities",
            {"current_assets": ca, "inventory": inv, "current_liabilities": cl})

    # ── Leverage ──
    if {"debt_to_equity", "all"} & wants:
        d, e = bs("total_debt"), bs("shareholders_equity")
        v = round(d / e, 3) if d is not None and e else None
        add("debt_to_equity", v, _display_mult(v), "debt_to_equity = total_debt / shareholders_equity",
            {"total_debt": d, "shareholders_equity": e})

    # ── Growth (YoY) ──
    if len(periods) >= 2 and ({"revenue_growth", "all"} & wants or _is_growth_q(low)):
        cur, prev = target, periods[-2] if periods[-2] != target else periods[-3] if len(periods) >= 3 else None
        if prev:
            for key, name in (("revenue", "revenue_growth"),
                              ("net_income", "net_income_growth"),
                              ("diluted_eps", "eps_growth"),
                              ("operating_income", "operating_income_growth")):
                a, b = income(key, cur), income(key, prev)
                g = _pct((a - b) / abs(b)) if a is not None and b not in (None, 0) else None
                add(name, g, _display_pct(g), f"{name} = (current - previous) / |previous| * 100",
                    {f"{key}_{cur}": a, f"{key}_{prev}": b})

    # ── Valuation multiples from valuation engine (preferred — already computed) ──
    for vmid in ("pe_ratio", "ps_ratio", "pb_ratio", "ev_to_revenue",
                 "ev_to_ebitda", "market_cap", "share_price", "enterprise_value"):
        if vmid not in wants and "all" not in wants:
            continue
        m2 = valuation.get(vmid)
        if isinstance(m2, dict) and m2.get("status") == "calculated" and m2.get("value") is not None:
            out.append({
                "metric": vmid,
                "value": m2.get("value"),
                "display": m2.get("display_value", ""),
                "formula": m2.get("formula", ""),
                "inputs": {i.get("name", ""): i.get("value") for i in (m2.get("inputs") or []) if isinstance(i, dict)},
                "period": m2.get("period", target),
                "source_ids": src_ids,
                "note": "from valuation engine" + (f", price as of {m2.get('market_data_date', '')}" if m2.get("market_data_date") else ""),
                "value_type": m2.get("price_type", "calculated"),
                "status": "calculated",
            })
        elif vmid in wants and "all" not in wants:
            out.append(_result(vmid, None, "N/A", "", {}, target, src_ids,
                               note="Not available — market data may be missing"))

    # ── Market cap from live market data if available ──
    if ({"market_cap", "share_price", "all"} & wants and market.get("price") is not None
            and not any(r["metric"] == "market_cap" and r["value"] is not None for r in out)):
        shares = market.get("shares_outstanding") or _val(
            _get_fact(stmts, "additional", "shares_outstanding", target))
        if shares:
            mc = float(market["price"]) * float(shares)
            add("market_cap", mc, _fmt_compact(mc),
                "market_cap = price * shares_outstanding",
                {"price": market["price"], "shares_outstanding": shares},
                value_type="current market value")

    return out


_CALC_TRIGGER = re.compile(
    r"\b(calculate|compute|what('s| is) the (operating|gross|net|fcf|free cash) ?(margin|ratio)|"
    r"margin|ratio|p/e|pe ratio|ev/ebitda|ev/revenue|roic|roe|roa|debt to equity|"
    r"current ratio|quick ratio|market cap|growth rate|cagr)\b",
    re.IGNORECASE,
)


def _requested(question: str) -> set[str]:
    low = question.lower()
    wants: set[str] = set()
    table = [
        (r"operating margin", "operating_margin"),
        (r"gross margin", "gross_margin"),
        (r"net (margin|profit margin)", "net_margin"),
        (r"ebitda margin", "ebitda_margin"),
        (r"fcf margin|free cash flow margin", "fcf_margin"),
        (r"free cash flow|\bfcf\b", "free_cash_flow"),
        (r"\broe\b|return on equity", "roe"),
        (r"\broa\b|return on assets", "roa"),
        (r"\broic\b", "roic"),
        (r"\broce\b", "roce"),
        (r"current ratio", "current_ratio"),
        (r"quick ratio", "quick_ratio"),
        (r"debt.to.equity", "debt_to_equity"),
        (r"\bp/?e\b|pe ratio|price.to.earnings", "pe_ratio"),
        (r"\bp/?s\b|price.to.sales", "ps_ratio"),
        (r"\bp/?b\b|price.to.book", "pb_ratio"),
        (r"ev/?revenue|ev\/sales", "ev_to_revenue"),
        (r"ev/?ebitda", "ev_to_ebitda"),
        (r"market cap", "market_cap"),
        (r"share price|stock price", "share_price"),
        (r"enterprise value", "enterprise_value"),
        (r"revenue growth|revenue (rise|increase|decline|fall|drop)", "revenue_growth"),
        (r"eps growth", "eps_growth"),
        (r"net income growth", "net_income_growth"),
        (r"operating income (growth|change|decline|decrease)", "operating_income_growth"),
        (r"\brevenue\b|\bsales\b", "revenue"),
    ]
    for pat, name in table:
        if re.search(pat, low):
            wants.add(name)
    if not wants and _CALC_TRIGGER.search(low):
        wants.add("all")
    return wants


def _is_growth_q(low: str) -> bool:
    return any(w in low for w in ("growth", "grew", "decline", "decrease", "increase",
                                  "fell", "dropped", "compare", "change"))


def _sum(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a + b


def _session_source_ids(session) -> list[str]:
    registry = session.source_registry or {}
    ids = []
    for src in (registry.get("sources") or [])[:6]:
        sid = src.get("source_id", "")
        if sid:
            ids.append(sid)
    return ids


def calculate_percentage_change(old: float, new: float) -> Optional[float]:
    """Percentage change helper, deterministic."""
    if old == 0:
        return None
    return round((new - old) / abs(old) * 100.0, 2)


def calculations_to_text(calcs: list[dict]) -> str:
    """Render calculation results as compact LLM evidence lines."""
    lines: list[str] = []
    for c in calcs:
        if c.get("status") != "calculated":
            lines.append(f"{c['metric']}: UNAVAILABLE — {c.get('note', 'inputs missing')}")
            continue
        ln = f"{c['metric']} ({c.get('period', '')}): {c.get('display', '')}"
        if c.get("formula"):
            ln += f" | Formula: {c['formula']}"
        ins = c.get("inputs") or {}
        if ins:
            ins_str = ", ".join(f"{k}={_fmt_compact(v) if isinstance(v, (int, float)) and abs(v) > 1e6 else v}"
                                for k, v in list(ins.items())[:4])
            ln += f" | Inputs: {ins_str}"
        if c.get("value_type") and c["value_type"] not in ("calculated", "reported"):
            ln += f" [{c['value_type']}]"
        lines.append(ln)
    return "\n".join(lines)
