"""Fast deterministic chat query router.

Classifies a user question into one of nine categories (A–I) using pure
Python heuristics — no LLM call, no network. Targets sub-millisecond
decisions so the shortest correct answer path can be chosen.

Categories
----------
A  GREETING / CONVERSATIONAL   → immediate simple LLM response, no research
B  DEFINITION / EDUCATIONAL    → general financial knowledge, no external
C  CONTEXT FACT LOOKUP         → existing session context only
D  CALCULATION                 → deterministic Python calculator
E  INTERPRETATION              → context + calculator + LLM explanation
F  EXPLANATORY / CAUSAL        → existing evidence first, targeted retrieval
G  EXTERNAL FACT LOOKUP        → targeted authoritative lookup
H  CURRENT / TIME-SENSITIVE    → fresh market-data path
I  DEEP RESEARCH               → deeper retrieval + synthesis
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Route constants ───────────────────────────────────────────────────────────
ROUTE_GREETING = "greeting"          # A
ROUTE_DEFINITION = "definition"      # B
ROUTE_CONTEXT_LOOKUP = "context_lookup"    # C
ROUTE_CALCULATION = "calculation"    # D
ROUTE_INTERPRETATION = "interpretation"    # E
ROUTE_CAUSAL = "causal"              # F
ROUTE_EXTERNAL_LOOKUP = "external_lookup"  # G
ROUTE_CURRENT_DATA = "current_data"  # H
ROUTE_DEEP_RESEARCH = "deep_research"      # I
ROUTE_GENERAL = "general"            # fallback (chat without session)

_ALL_ROUTES = {
    ROUTE_GREETING, ROUTE_DEFINITION, ROUTE_CONTEXT_LOOKUP,
    ROUTE_CALCULATION, ROUTE_INTERPRETATION, ROUTE_CAUSAL,
    ROUTE_EXTERNAL_LOOKUP, ROUTE_CURRENT_DATA, ROUTE_DEEP_RESEARCH,
    ROUTE_GENERAL,
}


@dataclass
class RouteDecision:
    route: str
    confidence: float = 0.5
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"route": self.route, "confidence": round(self.confidence, 2),
                "signals": self.signals}


# ── Pattern tables ────────────────────────────────────────────────────────────
_GREETING_RE = re.compile(
    r"^\s*(hi|hey|hello|yo|sup|thanks|thank you|thx|good (morning|afternoon|evening)"
    r"|how are you|who are you|what can you do|what do you do|help)\b[\s!.?]*$",
    re.IGNORECASE,
)

# Definition: "what is EPS" / "explain EBITDA" / "what does operating margin mean"
_DEFINITION_STARTERS = ("what is ", "what are ", "what does ", "explain ", "define ",
                        "meaning of ", "tell me what ", "how does ... work")
_DEFINITION_CONCEPTS = [
    "eps", "ebitda", "ebit", "operating margin", "gross margin", "net margin",
    "net profit margin", "free cash flow", "fcf", "roe", "roa", "roic", "roce",
    "p/e", "pe ratio", "ev/ebitda", "ev/revenue", "debt to equity",
    "current ratio", "quick ratio", "working capital", "cagr", "market cap",
    "enterprise value", "book value", "dividend yield", "revenue", "turnover",
    "leverage", "liquidity", "amortization", "depreciation", "goodwill",
    "operating income", "net income", "gross profit", "cash flow",
    "balance sheet", "income statement", "10-k", "10-q", "diluted", "buyback",
    "shares outstanding", "interest coverage", "asset turnover", "dso", "dpo",
]

# Time-sensitive signals
_CURRENT_RE = re.compile(
    r"\b(right now|today|current(ly)?|this (week|month|quarter|year)|latest|"
    r"as of|at the moment|live|real[- ]time|yesterday|last (close|price))\b",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(
    r"\b(share price|stock price|price of .{0,30}(stock|shares)|market cap|"
    r"valuation today|trading at|stock doing|performing today|price target)\b",
    re.IGNORECASE,
)

# Calculation request: explicit ask to compute
_CALC_REQUEST_RE = re.compile(
    r"\b(calculate|compute|work out|what('s| is) the (value|number) of|"
    r"how (do|would) (you|i) calculate|show (me )?(the )?(math|calculation|work))\b",
    re.IGNORECASE,
)

# Known metric vocabulary (used for calc vs interpretation disambiguation)
_METRIC_WORDS = [
    "margin", "ratio", "growth", "cagr", "return on", "roe", "roa", "roic",
    "roce", "p/e", "pe ratio", "ev/ebitda", "ev/revenue", "debt to equity",
    "debt-to-equity", "current ratio", "quick ratio", "fcf", "free cash flow",
    "operating margin", "gross margin", "net margin", "ebitda margin",
    "interest coverage", "asset turnover", "market cap", "enterprise value",
    "eps", "revenue per share", "book value", "working capital",
]

# "What is the P/E?" — a fact question about a derived metric. With a session this
# is a deterministic calculation, not a definition (spec §5).
_CALC_WHAT_IS_RE = re.compile(
    r"^\s*what('s| is| was)\s+(the\s+)?("
    r"p/e|pe ratio|ev/ebitda|ev/revenue|ev/sales|market cap|enterprise value|"
    r"[a-z]{0,24}(margin|ratio)s?|roe|roa|roic|roce|cagr|free cash flow margin|fcf margin"
    r")\b",
    re.IGNORECASE,
)

# Concepts that stay educational even when a session exists ("What is EPS?" =
# what does it MEAN, not "give me Tesla's EPS") — spec category B.
_CONCEPT_ONLY_RE = re.compile(
    r"\b(eps|earnings per share|diluted eps|ebitda|ebit|diluted|buyback|"
    r"10-k|10-q|goodwill|cagr|amortization|depreciation)\b",
    re.IGNORECASE,
)

# Causal question: why / what caused / what drove
_CAUSAL_RE = re.compile(
    r"^\s*(why|what caused|what drove|what led to|what explains|"
    r"how come|what('s| is) the reason)\b",
    re.IGNORECASE,
)

# External fact lookup: leadership, history, description
_EXTERNAL_FACT_RE = re.compile(
    r"\b(ceo|cfo|coo|cto|chairman|chief .{1,20} officer|board (members|of directors|director)"
    r"|directors|leadership|management team|executive team|founder|founded|founding|"
    r"headquarters|headquartered|employees|full[- ]time employees|subsidiar(y|ies)|"
    r"business model|what does .{0,40} (do|sell|make)|segments|operates in|"
    r"history of|company profile)\b",
    re.IGNORECASE,
)

# Deep research signals
_DEEP_RE = re.compile(
    r"\b(analyz(e|ing)|deep dive|compare .{0,60}(across|over|with|vs)|"
    r"last (three|3|few|several) years|over the years|trend(s)? over|"
    r"biggest risks|risk factors|full(y)? (analysis|assessment|breakdown)|"
    r"investment (case|thesis)|valuation analysis|pros and cons)\b",
    re.IGNORECASE,
)

# Interpretation: "what does X tell us/mean/indicate/suggest"
_INTERPRET_RE = re.compile(
    r"\b(what does .{1,60}(tell|say|mean|indicate|suggest|imply|signal)|"
    r"tell(s)? (me |us )?about|is .{1,40}(improving|deteriorating|getting better|getting worse)"
    r"|healthy|concerning|worrying|should i be concerned|how (is|are) .{1,40}doing)\b",
    re.IGNORECASE,
)

# Metric mention helper
_METRIC_RE = re.compile(
    r"\b(" + "|".join(re.escape(m) for m in _METRIC_WORDS) + r")\b",
    re.IGNORECASE,
)

# Financial-statement item vocabulary (context lookup)
_STATEMENT_ITEMS = [
    "revenue", "sales", "net income", "net profit", "operating income",
    "operating profit", "ebit", "gross profit", "gross income", "ebitda",
    "eps", "earnings per share", "diluted eps", "operating cash flow", "ocf",
    "capex", "capital expenditure", "free cash flow", "cash flow",
    "total assets", "total liabilities", "shareholders equity", "stockholders equity",
    "debt", "cash", "inventory", "receivables", "payables", "goodwill",
    "shares outstanding", "expenses", "cost of revenue", "cost of goods sold",
    "r&d", "research and development", "sg&a", "selling general",
]

_STATEMENT_ITEM_RE = re.compile(
    r"\b(" + "|".join(re.escape(i) for i in _STATEMENT_ITEMS) + r")\b",
    re.IGNORECASE,
)

_PERIOD_RE = re.compile(
    r"\b(fy\s?\d{4}|fiscal (year )?\d{4}|q[1-4]\s?\d{4}|q[1-4]\b|quarter|"
    r"last year|previous year|prior year|ttm|trailing|annual|monthly|"
    r"(19|20)\d{2})\b",
    re.IGNORECASE,
)


def route_query(message: str, has_session: bool = False) -> RouteDecision:
    """Classify a chat message into a route. Pure function, no I/O."""
    msg = (message or "").strip()
    low = msg.lower()
    signals: list[str] = []
    if not msg:
        return RouteDecision(ROUTE_GREETING, 0.9, ["empty"])

    # ── A. Greeting / conversational (exact-ish match) ──
    if _GREETING_RE.match(msg):
        return RouteDecision(ROUTE_GREETING, 0.95, ["greeting_pattern"])

    has_session_sig = bool(has_session)
    if has_session_sig:
        signals.append("has_session")

    # Pre-compute interpretation signal (needed by the D2 metric-calc gate)
    is_interpretive = bool(re.search(
        r"\b(tell|say|indicate|suggest|imply|signal|mean)\b.{0,30}\b(us|me|you|about this|for this)\b",
        low)) or "tell us" in low or "tell me about the" in low

    # ── H. Current / time-sensitive (price/current-data focus wins early) ──
    price_mentioned = bool(_PRICE_RE.search(msg))
    time_mentioned = bool(_CURRENT_RE.search(msg))
    if price_mentioned and (time_mentioned or _PRICE_RE.search(msg).group(0).lower() in (
            "share price", "stock price", "market cap", "trading at")):
        signals.append("price+time")
        return RouteDecision(ROUTE_CURRENT_DATA, 0.92, signals)
    if price_mentioned:
        signals.append("price")
        return RouteDecision(ROUTE_CURRENT_DATA, 0.85, signals)

    # ── D. Explicit calculation request ──
    if _CALC_REQUEST_RE.search(msg):
        signals.append("calc_request")
        return RouteDecision(ROUTE_CALCULATION, 0.9, signals)

    # ── D2. What-is questions about derived metrics → calculation (spec §5) ──
    # "What is the P/E?" / "What is operating margin?" with a session:
    # compute from context instead of reciting a textbook definition.
    if has_session and not is_interpretive and _CALC_WHAT_IS_RE.match(msg):
        signals.append("metric_calc")
        return RouteDecision(ROUTE_CALCULATION, 0.8, signals)

    # ── B. Definition / educational ──
    # "What is EPS?" — short question about a concept, no company possessive.
    # Exclude interpretation phrasings ("what does X tell/say/mean for US").
    is_question = low.startswith(("what is", "what are", "what does", "explain", "define"))
    mentions_concept = any(c in low for c in _DEFINITION_CONCEPTS)
    mentions_company = bool(re.search(
        r"\b(tesla|apple|microsoft|nvidia|amazon|alphabet|google|meta|netflix|"
        r"this company|the company|their|its|company)\b", low))
    if (is_question and mentions_concept and not is_interpretive and not mentions_company
            and len(low.split()) <= 8):
        # Bare statement-item questions with a session are fact lookups, not
        # definitions ("What is net income?" ≈ "What is Tesla's net income?") —
        # spec category C. Concept-only terms (EPS, EBITDA…) stay definitions.
        if has_session and _STATEMENT_ITEM_RE.search(low) and not _CONCEPT_ONLY_RE.search(low):
            pass  # fall through to context lookup below
        else:
            return RouteDecision(ROUTE_DEFINITION, 0.88, ["concept_definition"])

    # ── F. Causal — check before generic interpretation ──
    if _CAUSAL_RE.match(msg):
        signals.append("why_question")
        # "Why" about a concept (not company) stays definition-adjacent
        if not has_session and not _STATEMENT_ITEM_RE.search(msg):
            return RouteDecision(ROUTE_DEFINITION, 0.6, signals + ["no_context"])
        return RouteDecision(ROUTE_CAUSAL, 0.9, signals)

    # ── I. Deep research ──
    if _DEEP_RE.search(msg) and len(msg.split()) >= 6:
        signals.append("deep_research")
        return RouteDecision(ROUTE_DEEP_RESEARCH, 0.8, signals)

    # ── G. External fact lookup ──
    if _EXTERNAL_FACT_RE.search(msg):
        signals.append("external_fact")
        return RouteDecision(ROUTE_EXTERNAL_LOOKUP, 0.85, signals)

    # ── E. Interpretation ──
    if _INTERPRET_RE.search(msg):
        signals.append("interpretation")
        return RouteDecision(ROUTE_INTERPRETATION, 0.85, signals)

    # ── C. Context fact lookup ──
    if has_session and (_STATEMENT_ITEM_RE.search(msg) or _METRIC_RE.search(msg)):
        signals.append("statement_or_metric")
        return RouteDecision(ROUTE_CONTEXT_LOOKUP, 0.85, signals)

    # ── Fallback: session questions without explicit statement terms ──
    if has_session and len(msg.split()) >= 3:
        return RouteDecision(ROUTE_CONTEXT_LOOKUP, 0.5, signals + ["session_default"])
    if is_question and mentions_concept:
        return RouteDecision(ROUTE_DEFINITION, 0.7, ["concept_fallback"])
    return RouteDecision(ROUTE_GENERAL, 0.4, ["fallback"])
