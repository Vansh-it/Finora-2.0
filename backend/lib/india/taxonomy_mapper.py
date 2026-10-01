"""Map damaged PDF line-item labels onto canonical Finora metrics.

The problem this solves is specific. An Indian results filing states its profit
and loss in a house style that is not Finora's, and the PDF text layer damages
the label while doing it. One real filing rendered "Value of Sales & Setvices
(Revenue)", "Olher Income", "Prollt After Tax" and "Total Com rehprehensive
Income". An exact-match mapper finds none of those, so the extractor would
publish a statement of damages instead of a statement of accounts.

The approach is a two-stage match with an explicit confidence, because the
correct behaviour on an ambiguous line is to publish nothing:

1. An ordered rule table of distinctive tokens, most specific first. Order is
   load-bearing: "Other Comprehensive Income" must reach ``oci`` before the
   general comprehensive-income rule, and "Total Income" must beat "Other
   Income".
2. A normalised fuzzy fallback for OCR noise, accepted only above a similarity
   floor.

Every match reports how it was reached, so the audit trail can distinguish a
certain mapping from a fuzzy one.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional

from lib.metrics.registry import get_registry

logger = logging.getLogger("finora.india.taxonomy_mapper")


# ---------------------------------------------------------------------------
# Label normalisation
# ---------------------------------------------------------------------------

#: Words carrying no meaning for matching. Dropping them stops "Total Expenses
#: for the period" from failing to match "Total Expenses".
#:
#: "total" is deliberately NOT a stopword. It is load-bearing: "Total Income"
#: and "Other Income" are different metrics, and stripping it left both
#: normalising to "income", which cost the mapper every subtotal line.
_STOPWORDS = frozenset({
    "the", "a", "an", "for", "of", "to", "in", "on", "at", "as", "by",
    "and", "or", "with", "per", "during", "period", "year", "quarter",
    "ended", "closing", "note", "notes", "particulars", "figures", "rs",
    "inr", "amount", "amounts",
})

#: Canonical spellings applied before comparison. OCR consistently turns these
#: into each other and Indian filings use several variants of each. Multi-word
#: phrases collapse to a single token so a later split cannot lose them, and
#: the text layer writes many of them unspaced, so each pattern tolerates that.
_CANONICAL_WORDS: tuple[tuple[str, str], ...] = (
    (r"\bsetvices\b|\bservces\b|\bservices?\b", "service"),
    (r"\bolher\b|\bother\b", "other"),
    (r"\bprollt\b|\bprolit\b|\bpr0fit\b|\bproflt\b|\bproft\b", "profit"),
    # "Com rehprehensive" in the measured filing: the word was split, and the
    # damage is not a single-glyph substitution ("reh" + "p" + "hensive"), so
    # the pattern tolerates both a split and arbitrary damage inside the word.
    (r"\bcom\s*re\w*ensive\b|\bcomprehensive\b", "comprehensive"),
    (r"\bexclse\b|\bexcise\b", "excise"),
    # "Duly" is the measured OCR damage of "Duty" (l for y).
    (r"\bdul(?:y|v)\b", "duty"),
    (r"\bdepreciatlon\b|\bdepreciation\b", "depreciation"),
    (r"\bamortisatlon\b|\bamortisation\b|\bamortization\b", "amortisation"),
    (r"\bemploye\b|\bemployee\b", "employee"),
    (r"\bflnance\b|\bfinance\b", "finance"),
    (r"\blnterest\b|\binterest\b", "interest"),
    (r"\btax\b", "tax"),
    (r"\bmaterlals\b|\bmaterials\b", "material"),
    (r"\bconsumed\b|\bconsumption\b", "consumed"),
    (r"\binventor(?:y|ies)\b", "inventory"),
    (r"\bchanges?\b", "change"),
    (r"\brevenue\b", "revenue"),
    (r"\bexpenses?\b|\bexpenditure\b", "expense"),
    (r"\bincome\b", "income"),
    (r"\boperations?\b", "operation"),
    (r"\bequity\b", "equity"),
    (r"\bshareholders?\b|\bshare.?holders?\b", "shareholder"),
    (r"\bborrowings?\b", "borrowing"),
    (r"\bcapital\b", "capital"),
    (r"\bdebt\b", "debt"),
    (r"\bcash\b", "cash"),
    (r"\bassets?\b", "asset"),
    (r"\bliabilities?\b", "liability"),
    (r"\bpayables?\b", "payable"),
    (r"\breceivables?\b", "receivable"),
    (r"\bcurrent\b", "current"),
    (r"\bnon.?current\b", "noncurrent"),
    (r"\bcost\b", "cost"),
    (r"\bdividend\b", "dividend"),
    (r"\bpaid\b", "paid"),
    (r"\braised\b", "raised"),
    (r"\brepaid\b", "repaid"),
    (r"\bdeferred\b", "deferred"),
    (r"\bexceptional\b|\bexception\b", "exceptional"),
    (r"\bweighted\b", "weighted"),
    (r"\bshares?\b", "share"),
    (r"\bbasic\b", "basic"),
    (r"\bdiluted\b", "diluted"),
    (r"\baverage\b", "average"),
    (r"\brupees?\b|\binr\b", "rupee"),
    (r"\bface\b|\bvalue\b", "value"),
    # --- multi-word phrases -> one token --------------------------------
    (r"\bowners?\s+of\s+(?:the\s+)?company\b", "owner"),
    (r"\bnon\s+controlling\b", "noncontrolling"),
    (r"\bcontrolling\s+interest\b", "noncontrolling"),
    (r"\bassociates?\s+(?:and|&)\s+joint\s+ventures?\b", "associatejointventure"),
    # The phrase rules must precede the single-word rules that would otherwise
    # consume the first word: "materials" -> "material" left the text as
    # "costmaterials", which no rule matched.
    (r"\bcost\s+of\s+material", "costmaterial"),
    (r"\bstock[\s-]?in[\s-]?trade\b", "stockintrade"),
    (r"\bmaterlals\b|\bmaterials\b", "material"),
    (r"\bpurchases\b|\bpurchase\b", "purchase"),
    (r"\bcash\s+and\s+cash\s+equivalents?\b", "cashandcashequivalent"),
    (r"\bpaid[\s-]?up\s+share\s+capital\b", "sharecapital"),
    (r"\breserves?\s*(?:and|&)\s*surplus\b", "reservessurplus"),
    (r"\bcurrent\s*tax\b", "currenttax"),
    (r"\bemployee\s+benefits?\b", "employeebenefit"),
    (r"\bdepreciation\s*/\s*amortisation\b", "depreciationamortisation"),
    (r"\bprofit\s+and\s+loss\b", "profitloss"),
    (r"\bfree\s+cash\s+flow\b", "freecashflow"),
    (r"\bnet\s+(?:increase|decrease|change)\b", "netchange"),
    # The three activity subtotals and the two cash balances are what make a
    # cash flow statement testable. Without them the statement has no identity
    # to check and the whole page has to be withheld.
    (r"\boperating\s+activities\b", "operatingactivity"),
    (r"\binvesting\s+activities\b", "investingactivity"),
    (r"\bfinancing\s+activities\b", "financingactivity"),
    (r"\bbeginning\s+of\s+(?:the\s+)?(?:period|year)\b", "openingcash"),
    (r"\bclosing\s+of\s+(?:the\s+)?(?:period|year)\b|\bend\s+of\s+(?:the\s+)?(?:period|year)\b", "closingcash"),
)


def normalise_label(label: str) -> str:
    """Reduce a filing label to comparable tokens.

    Deliberately lossy, in a documented way. This only ever sees text labels,
    so Indian digit grouping is irrelevant here.
    """
    text = (label or "").lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^a-z0-9\s()./&-]", " ", text)
    for pattern, replacement in _CANONICAL_WORDS:
        text = re.sub(pattern, replacement, text)
    tokens = []
    for token in re.split(r"\s+", text):
        token = token.strip("()./&-")
        if not token or token in _STOPWORDS:
            continue
        tokens.append(token)
    return " ".join(tokens)


# ---------------------------------------------------------------------------
# Rule table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelRule:
    """One canonical metric and the labels that identify it."""

    metric_id: str
    pattern: re.Pattern[str]
    #: Confidence this rule earns. A rule naming a multi-word concept is a
    #: certain match; a rule resting on one short common token is only
    #: probable, because damage elsewhere in the line could have hidden a
    #: qualifier.
    confidence: float = 0.99
    #: A role marks a label whose figure is not the canonical value of the
    #: metric it resolves to. "Value of Sales" is gross of GST, while
    #: "Revenue from Operations" is not, and the registry has one concept
    #: where an Indian statement of accounts prints two lines.
    role: str = ""


#: Ordered most-specific first. Ordering is the whole mechanism: a line reading
#: "Total Comprehensive Income for the Period" must resolve to
#: ``comprehensive_income`` and not to ``total_income``, and "Profit Before Tax"
#: must not resolve to ``net_profit``.
_RULES: tuple[LabelRule, ...] = (
    # --- totals that contain other totals --------------------------------
    LabelRule("comprehensive_income", re.compile(r"\btotal\s+comprehensive\b")),
    LabelRule("oci", re.compile(r"\bother\s+comprehensive\b")),
    LabelRule("comprehensive_income", re.compile(r"\bcomprehensive\s+income\b")),
    LabelRule("total_tax", re.compile(r"\btotal\s+tax\b")),
    # "Income Tax" heads the total tax line in an Indian statement of
    # accounts; there is no "Total" on it.
    LabelRule("total_tax", re.compile(r"\bincome\s+tax\b")),
    # A bank prints one tax line, headed "Tax Expense", with no "Total" on it.
    LabelRule("total_tax", re.compile(r"\btax\s+expense\b")),
    # "Total revenue from operations" is the operating revenue itself, named as
    # a total because the line sits under a revenue heading. The generic total
    # rule above would claim it for total_income, and since a label resolves to
    # one metric, revenue was then left holding a component line: Bajaj Finance
    # published revenue of 3.25 crore, "Sale of services", while the statement
    # printed total revenue from operations of 23,165.45 crore. The lookahead
    # hands the label to revenue, where the "revenue from operation" rule below
    # claims it. "Total income" still resolves to total_income.
    LabelRule("revenue", re.compile(r"\btotal\s+revenue\s+from\s+operation")),
    LabelRule("total_income", re.compile(r"\btotal\s+revenue\b(?!\s+from\s+operation)")),
    LabelRule("total_income", re.compile(r"\btotal\s+income\b")),
    LabelRule("total_expenses", re.compile(r"\btotal\s+operating\s+expense\b")),
    LabelRule("total_expenses", re.compile(r"\btotal\s+expense\b")),
    LabelRule("ebitda", re.compile(r"\bebitda\b")),
    LabelRule("ebit", re.compile(r"\bebit\b")),
    # --- profit lines, most specific first --------------------------------
    LabelRule("net_profit", re.compile(r"\bprofit\s+after\s+tax\b")),
    LabelRule("net_profit", re.compile(r"\bprofit\s+for\s+the\s+period\b")),
    # "Net Profit for the period" and "Net Profit from ordinary activities
    # after tax" are both what a bank calls profit after tax, and both are lost
    # to the rules above: the pattern is written in the words the label prints,
    # but it is matched against the *normalised* label, where "for the period"
    # has been stripped as stopwords. "net profit" is what survives, and it
    # means the same thing in both lines.
    LabelRule("net_profit", re.compile(r"\bnet\s+profit\b")),
    LabelRule("net_profit", re.compile(r"\bpat\b")),
    LabelRule("pbt", re.compile(r"\bprofit\s+before\s+tax\b")),
    # "Profit from ordinary activities before tax" is the same line with the
    # qualifier in the middle, which the adjacent pattern above cannot see. The
    # trailing guard requires no further "tax" after the one it matched, so a
    # line that goes on to name a different tax - "profit before exceptional
    # items and tax" - is not claimed, and is refused outright besides.
    LabelRule("pbt", re.compile(r"\bprofit\b.*\bbefore\s+tax\b(?!.*\btax\b)")),
    LabelRule("pbt", re.compile(r"\bpbt\b")),
    # Matched against the normalised label, where "of" and "from" are stopwords
    # and the printed "Share of profit/(loss) from associates" arrives as
    # "share profit/(loss from associates". A line naming both a share and an
    # associate is that line; nothing else in a statement of accounts does.
    LabelRule("share_of_associates",
              re.compile(r"\bshare\b.*\bassociates?\b|\bprofit\b.*\bassociates?\b")),
    # A bank prints provisions between total expenditure and profit before tax,
    # and says so: HDFC Bank's own line reads "Total Expenditure (excluding
    # provisions and contingencies)". The provision is therefore inside the
    # printed profit before tax without being inside total expenses, which is
    # what lets the P&L identity close.
    #
    # "other than tax" is kept in the pattern on purpose. A bank prints its
    # provision and its tax on the same page, and the tax line is the one that
    # must not be captured here.
    LabelRule("provisions",
              re.compile(r"(?<!before\s)\bprovisions?\b(?!.*\bfor\s+tax\b)"
                         r"|\bimpairment\s+on\s+financial\s+assets?\b")),
    LabelRule("exceptional_items", re.compile(r"\bexceptional\b")),
    LabelRule("current_tax", re.compile(r"\bcurrenttax\b")),
    LabelRule("deferred_tax", re.compile(r"\bdeferred\s+tax\b")),
    # --- income lines ------------------------------------------------------
    # A bank heads its lending spread with two lines and nothing else, and
    # they are the inputs net interest income is built from.
    #
    # "Interestexpended" arrives from an image with the spaces missing, so the
    # de-spaced spelling is matched as its own word. "Interest eamed" is the
    # recogniser's reading of "earned", measured on HDFC Bank's scanned
    # quarter: the two spellings are both accepted, and no looser pattern is,
    # because a component line like "Interest / discount on advances" shares
    # the word and must not be claimed as the total.
    LabelRule("interest_earned",
              re.compile(r"\binterest\s+ea(?:rned|med)\b")),
    LabelRule("interest_expended", re.compile(r"\binterestexpended\b")),
    LabelRule("other_income", re.compile(r"\bother\s+income\b")),
    LabelRule("revenue", re.compile(r"\brevenue\s+from\s+operation")),
    # Gross of GST. An Indian statement of accounts usually prints this line
    # *and* the net revenue line, and they differ by the GST collected on
    # behalf of the government, which is not the company's income. The
    # registry has one revenue concept, so this resolves to ``revenue`` at
    # reduced confidence and loses to the net line on the same page. It is
    # kept as a fallback for the many companies that print only the gross.
    LabelRule("revenue", re.compile(r"\bvalue\s+of\s+sales?\b"),
              confidence=0.70, role="GROSS"),
    LabelRule("revenue", re.compile(r"\bincome\s+from\s+operation")),
    LabelRule("revenue", re.compile(r"\bsales?\b|\brevenue\b"),
              confidence=0.90, role="UNCERTAIN"),
    LabelRule("cost_of_materials", re.compile(r"\bcostmaterial\b")),
    LabelRule("purchases_stock_in_trade", re.compile(r"\bpurchase\s+stockintrade\b")),
    LabelRule("changes_in_inventories", re.compile(r"\bchange\s+in\s+inventory")),
    LabelRule("employee_benefits", re.compile(r"\bemployeebenefit\b")),
    LabelRule("finance_costs", re.compile(r"\bfinance\s+costs?\b")),
    LabelRule("finance_costs", re.compile(r"\bfinance\s+charge\b")),
    LabelRule("depreciation_amortisation",
              re.compile(r"\bdepreciationamortisation\b|\bdepreciation\b|"
                         r"\bamortisation\b|\bamortization\b")),
    LabelRule("other_expenses", re.compile(r"\bother\s+expense\b")),
    # A bank prints "Operating expenses" as the running cost line that sits
    # between interest expended and total expenditure. The total-expenses rule
    # above claims "Total operating expenses" and is listed first, so this
    # matches only the line that is not a total.
    LabelRule("operating_expenses", re.compile(r"\boperating\s+expense\b")),
    # --- per-share ---------------------------------------------------------
    # Diluted first: Indian filings name both on one line, and the more
    # specific reading has to win.
    LabelRule("eps_diluted", re.compile(r"\bdiluted\b")),
    LabelRule("eps_basic", re.compile(r"\bbasic\b")),
    # --- balance sheet -----------------------------------------------------
    LabelRule("total_assets", re.compile(r"\btotal\s+asset\b")),
    LabelRule("share_capital", re.compile(r"\bsharecapital\b")),
    LabelRule("cash", re.compile(r"\bcashandcashequivalent\b")),
    LabelRule("total_equity", re.compile(r"\btotal\s+equity\b")),
    LabelRule("equity", re.compile(r"\bother\s+equity\b|\bowners?\s+equity\b")),
    # Only the aggregate counts. A singular "reserve" is a component - general,
    # capital, debenture redemption, cash flow hedge, cost of hedging - and those
    # are not reserves and surplus. Bajaj Finance's P&L carries hedge-reserve
    # lines inside other comprehensive income, and reading them as the balance
    # sheet's reserves put a -10.60 crore hedging figure on the income statement.
    LabelRule("reserves_surplus", re.compile(r"\breservessurplus\b|\breserves\b")),
    # --- cash flow ---------------------------------------------------------
    LabelRule("free_cash_flow", re.compile(r"\bfreecashflow\b")),
    LabelRule("operating_cash_flow", re.compile(r"\bcash\s+flow\s+from\s+operation")),
    LabelRule("operating_cash_flow", re.compile(r"\boperating\s+activities\b")),
    LabelRule("capex", re.compile(r"\bpurchase\s+of\s+(?:fixed|property|plant)\b")),
    LabelRule("capex", re.compile(r"\bcapital\s+expenditure\b")),
    LabelRule("dividends_paid", re.compile(r"\bdividend.*\bpaid\b")),
    LabelRule("net_change_in_cash", re.compile(r"\bnetchange\b.*\bcash\b")),
    LabelRule("operating_cash_flow", re.compile(r"\boperatingactivity\b")),
    LabelRule("investing_cash_flow", re.compile(r"\binvestingactivity\b")),
    LabelRule("financing_cash_flow", re.compile(r"\bfinancingactivity\b")),
    LabelRule("opening_cash", re.compile(r"\bopeningcash\b")),
    LabelRule("closing_cash", re.compile(r"\bclosingcash\b")),
)

#: Labels that look like a line item but are not one. Publishing a subtotal
#: twice, or treating a note reference as a figure, is worse than omitting the
#: row. Segment tables are excluded because a segment's figures do not
#: aggregate to the consolidated line of the same name.
_EXCLUDE = re.compile(
    # A note *heading* starts the label; a note *cited* by a line item does not.
    # Matching "note" anywhere refused real statement lines, and the ones it
    # refused include the two figures a bank's profit after tax is proved by:
    # HDFC Bank prints "Tax Expense (Refer note 14)" and "Provisions (other than
    # tax) and Contingencies (Refer note 8)". Dropping them left the P&L with no
    # tax and no provision, so no identity could close.
    #
    # A bare "(Note 5)" *closing* the label is the other case: there the
    # parenthetical is the whole claim — the row is a pointer at a note, met in
    # summaries and note listings where the figure beside it is not this
    # statement's own line. "(Refer note N)" opens with its qualifier, so it is
    # kept while "(Note N)" is refused.
    r"^\(?note\b|\(notes?\b[^)]*\)$|\bsee\s+note\b|\bpage\b|\bwww\.|"
    r"\bour\s+subsidiar|\bsegment\b|\bjoint\s+venture\b|"
    r"\bface\s+value\b|\brs\.?\s*in\b|"
    # "Profit before exceptional items and tax" is a profit measure that happens
    # to mention exceptionals, not the amount of the exceptional item. On Bajaj
    # Finance's consolidated P&L it read 8,149 crore against "Exceptional items",
    # which is nil, publishing a phantom exceptional charge equal to profit
    # before tax. The line is refused rather than resolved to anything.
    r"\bprofit\s+before\s+exceptional\b",
)


@dataclass(frozen=True)
class LabelMatch:
    """A resolved line-item label, with the evidence for the match."""

    metric_id: str
    confidence: float
    method: str          # RULE | FUZZY
    matched_text: str
    rule_index: int = -1
    #: Empty for a canonical figure, otherwise GROSS or UNCERTAIN. See
    #: ``resolve_metrics``: when one statement prints two lines for the same
    #: metric, this is what decides which is the real value.
    role: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "confidence": round(self.confidence, 3),
            "method": self.method,
            "matched_text": self.matched_text,
            "role": self.role,
        }


#: Below this similarity a fuzzy match is a guess, not a mapping, and is
#: refused. Measured against real damaged labels, surviving matches sit above
#: 0.80 while "Other Expenses" against "Other Income" scores ~0.55 and is
#: correctly rejected.
FUZZY_FLOOR = 0.80

#: Above this a fuzzy match is reported as near-certain.
FUZZY_STRONG = 0.92


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _fuzzy_candidates() -> list[tuple[str, str]]:
    """Labels a fuzzy match may compare against, drawn from the rule table."""
    out: list[tuple[str, str]] = []
    for rule in _RULES:
        words = set(re.findall(r"[a-z]+", rule.pattern.pattern))
        words -= {"b", "s", "and", "or", "the", "a", "of"}
        if not words:
            continue
        out.append((rule.metric_id, " ".join(sorted(words))))
    return out


_FUZZY_CANDIDATES = _fuzzy_candidates()


def _known_metric(metric_id: str) -> bool:
    try:
        get_registry().get(metric_id)
    except Exception:
        return False
    return True


def match_label(label: str) -> Optional[LabelMatch]:
    """Resolve one filing label to a canonical metric, or ``None``.

    Returning ``None`` is normal and expected: most rows of a results filing
    are not metrics Finora tracks, and refusing them is correct. A rule may not
    point at a metric the registry does not define.
    """
    text = (label or "").strip()
    if not text or _EXCLUDE.search(text.lower()):
        return None

    norm = normalise_label(text)
    if not norm:
        return None

    for index, rule in enumerate(_RULES):
        if not rule.pattern.search(norm):
            continue
        if not _known_metric(rule.metric_id):
            logger.debug(
                "[india.mapper] %r matched a rule for unknown metric %s; refused",
                text, rule.metric_id,
            )
            return None
        return LabelMatch(
            metric_id=rule.metric_id,
            confidence=rule.confidence,
            method="RULE",
            matched_text=norm,
            rule_index=index,
            role=rule.role,
        )

    best_metric = ""
    best_score = 0.0
    for metric_id, candidate in _FUZZY_CANDIDATES:
        score = _similarity(norm, candidate)
        if score > best_score:
            best_metric, best_score = metric_id, score
    if best_score >= FUZZY_FLOOR and _known_metric(best_metric):
        return LabelMatch(
            metric_id=best_metric,
            confidence=0.93 if best_score >= FUZZY_STRONG else min(0.95, best_score),
            method="FUZZY",
            matched_text=norm,
        )
    return None


def map_rows(labels: Iterable[str]) -> dict[str, LabelMatch]:
    """Resolve a batch of labels, keyed by the original label text.

    Duplicate labels in one statement are normal, so the mapping is keyed by
    label and the caller applies it per column.
    """
    out: dict[str, LabelMatch] = {}
    for label in labels:
        text = (label or "").strip()
        if text in out:
            continue
        match = match_label(text)
        if match is not None:
            out[text] = match
    return out


@dataclass
class ResolvedLine:
    """One label, its canonical metric, and the value read for one period."""

    metric_id: str
    value: float
    label: str
    confidence: float
    method: str
    role: str = ""
    recovered: bool = False
    scale: float = 1.0

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "value": self.value,
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "method": self.method,
            "role": self.role,
            "recovered": self.recovered,
        }


#: Role ranking when two rows resolve to the same metric. Lower wins.
_ROLE_RANK = {"": 0, "UNCERTAIN": 1, "GROSS": 2}


def resolve_metrics(
    candidates: Iterable[ResolvedLine],
) -> tuple[dict[str, ResolvedLine], list[dict[str, object]]]:
    """Pick one line per metric when a statement prints several.

    An Indian statement of accounts routinely prints more than one line that
    means the same thing: "Value of Sales" and "Revenue from Operations" are
    both revenue, differing by GST. Measured on the Reliance consolidated P&L,
    both matched ``revenue`` at equal confidence, and the published value was
    therefore decided by the order the rows happened to come back in. Reorder
    the table and the company would report 8% more revenue.

    Selection is by role and then confidence, never by position, so the same
    filing always yields the same value. Losing lines are returned rather than
    dropped, because a shadowed gross figure is the explanation for a
    reconciliation the reader may want to check by hand.

    A line that is a reconstruction from damaged text never displaces a clean
    line: the repair is a hypothesis and should lose to a reading.
    """
    chosen: dict[str, ResolvedLine] = {}
    shadowed: list[dict[str, object]] = []

    for line in candidates:
        incumbent = chosen.get(line.metric_id)
        if incumbent is None:
            chosen[line.metric_id] = line
            continue

        def rank(item: ResolvedLine) -> tuple[int, float, int]:
            return (
                _ROLE_RANK.get(item.role, 0),
                item.confidence,
                0 if not item.recovered else 1,
            )

        if rank(line) < rank(incumbent):
            winner, loser = line, incumbent
        else:
            winner, loser = incumbent, line
        chosen[line.metric_id] = winner
        shadowed.append({
            "metric_id": loser.metric_id,
            "label": loser.label,
            "value": loser.value,
            "reason": (
                f"a {winner.role or 'canonical'} line on the same statement "
                f"({winner.label}) carries this metric"
            ),
        })

    return chosen, shadowed


def coverage_report(labels: Iterable[str]) -> dict[str, object]:
    """Summarise how much of a statement the mapper can read.

    Reported so a low coverage figure is visible to the caller rather than
    silently producing a half-empty statement.
    """
    labels = [label for label in labels if (label or "").strip()]
    matches = map_rows(labels)
    methods: dict[str, int] = {}
    for match in matches.values():
        methods[match.method] = methods.get(match.method, 0) + 1
    return {
        "labels": len(labels),
        "matched": len(matches),
        "coverage": round(len(matches) / len(labels), 3) if labels else 0.0,
        "by_method": methods,
    }
