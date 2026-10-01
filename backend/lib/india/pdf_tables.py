"""Strict extraction of numbers from Indian results PDFs.

Why this module is shaped the way it is
---------------------------------------
Measured on a live Reliance quarterly filing (24 pages), the text layer shows:

* Labels and numbers sit on different x-bands, so a label is everything left of
  the first numeric column and a value is everything right of it.
* Labels are OCR-damaged: "Services" -> "Setvices", "Other" -> "Olher",
  "Profit" -> "Prollt". Matching must tolerate character noise.
* Digits are sometimes damaged too: ``1,175,9.19`` for 1,175,919, ``4;973``
  for 4,973, ``194,Q47`` for 194,047. A damaged cell is untrustworthy, so it
  is rejected rather than repaired.
* The header declares four period columns but only two carry numbers. A column
  with no numbers is missing data, never a value to be inferred.
* Only two of the four declared columns survive text extraction on some pages.

So the rules are:

1. Read words with coordinates; never rely on reading order.
2. Derive columns from the numbers that are actually present, then attach each
   column to the nearest declared period label.
3. Reject any cell whose characters are not a clean digit/group/decimal form.
   Parenthesised values are negatives, which is legitimate.
4. Match labels to concepts fuzzily, because the labels are damaged.
5. Publish only what survives, with an explicit rejection list. Where a filing
   contradicts itself, both the value and the contradiction are reported.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

logger = logging.getLogger("finora.india.pdf")


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
#: Characters that, appearing inside a numeric token, mean the text layer has
#: damaged a digit. Any of these rejects the cell.
_DAMAGE_CHARS = set("~!;:/\\|^\"'`{}[]<>*=?+_")

_NUMBER_RE = re.compile(r"^\(?\s*-?[0-9][0-9,\s]*(?:\.[0-9]+)?\s*\)?$")
_THOUSANDS_RE = re.compile(r"^\(.*\)$")


@dataclass
class NumberCell:
    """One parsed numeric cell, with the raw text it came from."""

    raw: str
    value: float
    x0: float
    x1: float
    column: int = -1
    rejected: str = ""
    #: True when the text layer damaged one leading glyph and the value was
    #: reconstructed from it. Recovered values are never published silently -
    #: the statement validator must corroborate them arithmetically.
    recovered: bool = False
    #: The text actually read from the PDF, kept beside the repaired value. A
    #: recovered cell is otherwise indistinguishable from a clean one in the
    #: audit trail: ``raw`` is the reconstructed token, so the evidence for the
    #: repair would be lost on serialisation.
    source_text: str = ""

    @property
    def ok(self) -> bool:
        return not self.rejected

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "value": self.value,
            "column": self.column,
            "x0": round(self.x0, 1),
            "x1": round(self.x1, 1),
            "rejected": self.rejected,
            "recovered": self.recovered,
            "source_text": self.source_text,
        }


def looks_numeric(token: str) -> bool:
    t = (token or "").strip()
    if not t:
        return False
    return bool(re.search(r"\d", t)) and (
        bool(re.fullmatch(r"[-()0-9,.\s]+", t)) or bool(_NUMBER_RE.match(t))
    )


#: Glyphs an OCR text layer routinely substitutes for a leading digit. The map is
#: deliberately one-directional and one-character wide: only a single leading
#: substitution is repaired, and only when the rest of the token is already a
#: clean grouped number. Anything wider stays rejected.
_OCR_LEADING_DIGIT = {
    "j": "1", "l": "1", "i": "1", "o": "0", "s": "5", "b": "6", "g": "6",
    "z": "2", "a": "4", "t": "7", "q": "9", "d": "0", "c": "0", "e": "8",
}

_DAMAGED_NUMBER_RE = re.compile(r"^([A-Za-z])([\d][\d,.]*)$")


def repair_ocr_separator(token: str) -> Optional[str]:
    """Repair a figure whose decimal point was read as a comma, or vice versa.

    Measured on a scanned results filing, the recogniser returned ``25108,30``
    for ``25108.30`` and ``62005,.98`` for ``62005.98``. Both are refused by
    :func:`parse_number` as ambiguous, so the profit before tax of a bank - the
    one figure a bank filing exists to report - would be dropped.

    Only two shapes are repaired, and both are unambiguous because there is
    exactly one way to read them:

    - a single separator with one or two digits after it, where the part before
      it holds five or more digits and is not valid Indian grouping, is a
      decimal point misread as a comma (``25108,30``);
    - a separator that is immediately followed by another separator and then
      exactly two digits is a duplicated separator (``62005,.98``).

    Anything else is left alone. A wrong repair is a plausible number, and a
    plausible number is worse than no number: it would be published.
    """
    t = (token or "").strip()
    if not t or not any(ch.isdigit() for ch in t):
        return None
    if t.count(".") == 1 and t.count(",") == 0:
        return None  # already the ordinary shape

    # A period is never a grouping mark, so where the recogniser produced two
    # adjacent separators - "62005,.98" - the period is the decimal point and
    # the comma is the one to drop.
    if t.count(".") == 1 and t.count(",") == 1:
        if not re.fullmatch(r"\d{1,},\.\d{2}", t):
            return None
        return t.replace(",", "")

    # "25108,30" for "25108.30". Indian grouping puts a separator every two
    # digits from the right, so a five-digit whole part cannot be grouped at
    # all and the separator can only have been a misread decimal point.
    swapped = re.fullmatch(r"(\d+),(\d{2})", t)
    if swapped and len(swapped.group(1)) >= 5:
        return f"{swapped.group(1)}.{swapped.group(2)}"
    return None


def recover_damaged_number(token: str) -> Optional[str]:
    """Reconstruct a number whose leading digit was OCR-damaged.

    Measured on a real results filing: ``J3,533`` for ``13,533``. The label
    classifier otherwise files the token as text and the figure is lost, so this
    narrow repair recovers it. Returns the candidate text, or ``None`` when the
    token is not a single-glyph-damaged number. Callers must mark the result
    ``recovered`` so downstream validation can require corroboration.
    """
    t = (token or "").strip()
    match = _DAMAGED_NUMBER_RE.match(t)
    if not match:
        return None
    glyph, rest = match.group(1), match.group(2)
    digit = _OCR_LEADING_DIGIT.get(glyph.lower())
    if digit is None:
        return None
    # A one- or two-character remainder is far more likely to be a label such as
    # "Q3" or "H1" than a truncated figure.
    digits = rest.replace(",", "").replace(".", "")
    if len(digits) < 3:
        return None
    candidate = digit + rest
    value, reason = parse_number(candidate)
    if reason:
        return None
    return candidate if value is not None else None


# Indian bank and NBFC results are often typeset with periods as the thousands
# separator while the same page also uses commas elsewhere, so a single filing
# prints "20,512.73" and "20.512.73" side by side. The dots are grouping marks,
# not decimals: in one Bajaj Finance statement the line items only reconcile if
# 20.512.73 is read as 20,512.73. This is only rewritten when the tail is one or
# two digits and the leading groups are all exactly three, so a real three-decimal
# quantity such as "20.512" is left alone and still rejected as ambiguous.
_DOT_GROUPED = re.compile(r"^(\d{1,3}(?:\.\d{3})+)\.(\d{1,2})$")


def _undo_dot_grouping(token: str) -> str:
    match = _DOT_GROUPED.match(token)
    if not match:
        return token
    return f"{match.group(1).replace('.', '')}.{match.group(2)}"


def parse_number(token: str) -> tuple[Optional[float], str]:
    """Strictly parse one numeric token. Returns ``(value, reject_reason)``.

    Rejects rather than repairs. ``(4,214)`` is a legitimate negative; ``4;973``
    is a damaged cell and is refused.
    """
    t = (token or "").strip()
    if not t:
        return None, "empty"
    if any(ch in _DAMAGE_CHARS for ch in t):
        return None, "damaged_characters"
    # A token that mixes digits with letters is a label fragment, not a number.
    if re.search(r"[A-Za-z]", t):
        return None, "contains_letters"

    negative = False
    if t.startswith("(") and t.endswith(")"):
        negative = True
        t = t[1:-1].strip()
    t = t.replace(" ", "")
    if t.startswith("-"):
        negative = not negative
        t = t[1:]
    t = t.rstrip(".")
    t = _undo_dot_grouping(t)
    if not t or not re.fullmatch(r"[0-9,]+(?:\.[0-9]+)?", t):
        return None, "not_a_number"

    body, _, frac = t.partition(".")
    if frac and not re.fullmatch(r"[0-9]{1,2}", frac):
        return None, "bad_decimal_places"
    if not any(ch.isdigit() for ch in body):
        return None, "no_integer_part"
    # Indian and western grouping are both fine, but a stray separator is not.
    if body.count(",") and not re.fullmatch(
        r"\d{1,3}(,\d{2,3})+|\d{1,2}(,\d{2})+,\d{3}|\d{1,3}(,\d{3})+", body
    ):
        return None, "bad_grouping"

    try:
        value = float(body.replace(",", "") + (("." + frac) if frac else ""))
    except ValueError:
        return None, "unparseable"
    if value != value or value in (float("inf"), float("-inf")):
        return None, "non_finite"
    return (-value if negative else value), ""


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
UNIT_MULTIPLIER = {
    "rupee": 1.0,
    "thousand": 1_000.0,
    "lakh": 100_000.0,
    "million": 1_000_000.0,
    "crore": 10_000_000.0,
    "billion": 1_000_000_000.0,
    "arab": 1_000_000_000.0,
}

# The rupee sign is mangled in these text layers ("if", "i!'", "~", "ff"), so the
# unit is detected from the word that follows, not from the symbol.
_UNIT_WORD_RE = re.compile(
    r"\b(thousands?|lakhs?|millions?|crores?|crore|billions?|arab|rupees?)\b", re.I
)


@dataclass
class Unit:
    scale: float
    name: str
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "scale": self.scale, "raw": self.raw}


def detect_unit(text: str) -> Unit:
    """Detect the statement's reporting unit. Defaults to rupees."""
    m = _UNIT_WORD_RE.search(text or "")
    if not m:
        return Unit(scale=1.0, name="rupee")
    word = m.group(1).lower().rstrip("s")
    if word in ("lakh",):
        word = "lakh"
    scale = UNIT_MULTIPLIER.get(word, 1.0)
    return Unit(scale=scale, name=word, raw=m.group(0))


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "sept": 9,
}
# 30th Jun'26 / 31st Mar'26 / 31-03-2026 / 30.06.2026 / June 30, 2026
# Ordinal suffixes are required: without them "30th" defeats a {3,9} letter run.
_PERIOD_PATTERNS = (
    re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s*[-/ ]?\s*([A-Za-z]{3,9})'?\s*(\d{2,4})"),
    re.compile(r"([A-Za-z]{3,9})'?\s*[-/ ]?\s*(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{2,4})"),
    re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})"),
)

_ORDINAL_RE = re.compile(r"(?:st|nd|rd|th)\b", re.I)


def _month_from_token(token: str) -> int:
    """Month number from a month name of any length, else 0."""
    t = re.sub(r"[^A-Za-z]", "", (token or "")).lower()
    if not t:
        return 0
    if t.startswith("sept"):
        return 9
    for name, num in _MONTHS.items():
        if t == name or t.startswith(name) and len(t) <= len(name) + 2:
            return num
    return 0


def _normalise_year(year: int) -> int:
    if year < 100:
        return 2000 + year if year < 70 else 1900 + year
    return year


def parse_period_label(text: str) -> Optional[str]:
    """Turn a column header like ``30th Jun'26`` into ``2026-06-30``."""
    t = (text or "").strip()
    if not t:
        return None
    for pattern in _PERIOD_PATTERNS:
        for m in pattern.finditer(t):
            day = month = year = 0
            g1, g2, g3 = m.group(1), m.group(2), m.group(3)
            if g1.isdigit() and _month_from_token(g2):
                day, month, year = int(g1), _month_from_token(g2), _normalise_year(int(g3))
            elif g1.isdigit() and g2.isdigit() and g3.isdigit():
                # dd-mm-yyyy
                day, month, year = int(g1), int(g2), _normalise_year(int(g3))
                if month > 12:
                    day, month = month, day
            elif _month_from_token(g1) and g2.isdigit():
                month, day, year = _month_from_token(g1), int(g2), _normalise_year(int(g3))
            if not (day and month and year):
                continue
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            try:
                from datetime import date

                return date(year, month, day).isoformat()
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Row / page model
# ---------------------------------------------------------------------------
@dataclass
class Row:
    """One visual line: a label plus the numeric cells found on it."""

    top: float
    label: str
    cells: list[NumberCell] = field(default_factory=list)
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "raw": self.raw,
            "cells": [c.to_dict() for c in self.cells],
        }


@dataclass
class Column:
    index: int
    centre: float
    x0: float
    x1: float
    header_text: str = ""
    period_end: str = ""
    #: "PERIOD" for a dated column, "DURATION" for Year Ended / Quarter Ended
    #: without a date, "UNLABELLED" when nothing in the header matched.
    kind: str = "UNLABELLED"
    cell_count: int = 0
    #: "CURRENT" for the leftmost data column, which by universal convention in
    #: Indian results filings is the period the filing is about. Other columns
    #: stay "UNATTRIBUTED" unless their header parsed, because the headers in
    #: these PDFs are routinely OCR-damaged and a mislabelled column is worse
    #: than an unnamed one.
    role: str = "UNATTRIBUTED"
    #: True when the column holds more than one figure for the same line item,
    #: which means two periods were clustered together. Such a column is never
    #: publishable: reading "the first value" would substitute a comparative
    #: for the current period, and every arithmetic check would still pass.
    ambiguous: bool = False
    ambiguous_rows: int = 0

    @property
    def is_publishable(self) -> bool:
        return (bool(self.period_end) or self.role == "CURRENT") and not self.ambiguous

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "centre": round(self.centre, 1),
            "header_text": self.header_text,
            "period_end": self.period_end,
            "kind": self.kind,
            "role": self.role,
            "cell_count": self.cell_count,
            "ambiguous": self.ambiguous,
            "ambiguous_rows": self.ambiguous_rows,
        }


@dataclass
class PageAnalysis:
    page_number: int
    scope: str = ""
    unit: Unit = field(default_factory=lambda: Unit(scale=1.0, name="rupee"))
    role: str = "OTHER"
    columns: list[Column] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    #: Characters recovered from the page. Zero means the page is an image.
    char_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page_number,
            "scope": self.scope,
            "unit": self.unit.to_dict(),
            "role": self.role,
            "columns": [c.to_dict() for c in self.columns],
            "row_count": len(self.rows),
            "char_count": self.char_count,
            "rejected": self.rejected,
        }


#: Roles a page can play in a results filing.
#: P_AND_L requires a meaningful income-statement anchor — a page is not a P&L
#: merely because its title area contains a stray "results" substring. Balance-sheet
#: pages that mention "deposits" or "advances" must not be promoted to P_AND_L by a
#: weak title match, so the P_AND_L pattern is anchored on structural line-item names.
#: When the title is ambiguous but the page body carries strong P&L row anchors, the
#: page is promoted to P_AND_L from its row content rather than its title.
_ROLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("P_AND_L", re.compile(
        r"statement of (unaudited )?(consolidated |stand ?alone )?profit and loss"
        r"|financial results for the (quarter|year)"
        r"|statement of profit and loss"
        r"|statement of (comprehensive )?income"
        r"|income statement", re.I)),
    ("BALANCE_SHEET", re.compile(
        r"balance sheet as at|statement of financial position"
        r"|statement of assets and liabilities", re.I)),
    ("CASH_FLOW", re.compile(
        r"statement of cash flow|cash flow statement"
        r"|statement of changes in financial position", re.I)),
    ("SEGMENT", re.compile(r"segment (information|results|revenue)", re.I)),
    ("RATIOS", re.compile(r"formulae for computation of ratios", re.I)),
    ("CHANGES_IN_EQUITY", re.compile(
        r"statement of changes in (equity|shareholders)", re.I)),
    ("BORROWINGS", re.compile(r"statement of borrowings|borrowings", re.I)),
    ("SEGMENT_ASSETS", re.compile(r"segment assets|segment liabilities", re.I)),
)

#: Row-level anchors that identify an income statement even when the page title
#: is ambiguous or missing. A page whose rows carry these line items is a P&L,
#: regardless of what its header says.
_P_AND_L_ROW_ANCHORS = re.compile(
r"\b(total income|interest earned|interest expended|"
r"profit before tax|net profit|operating expenses|"
r"other income|total expense|finance cost|"
r"employee benefit|depreciation|"
r"net interest income|preliminary expenses)\b", re.I)


def _attribute_headers(
    columns: list[Any], header_words: list[dict[str, Any]]
) -> None:
    """Give each column the heading that sits above it.

    A heading belongs to the column it is centred over, so the comparison is
    between centres. Matching on a column's trailing edge instead - which is
    what this did - puts a date on the wrong side of a wide, ragged figure: a
    period heading lands whichever column happens to be nearest, and on a
    scanned page, where the figures sit at slightly different indents, that is
    regularly the neighbouring column.

    The distance allowed is a fraction of the spacing the columns themselves
    establish, not a fixed tolerance. Half a column is the most a heading can
    drift and still describe the column beneath it, and a group heading such as
    "Quarter ended" that spans two columns falls between them and is kept by
    both, which is exactly what it says.
    """
    if not columns or not header_words:
        return

    centres = sorted(c.centre for c in columns)
    gaps = [b - a for a, b in zip(centres, centres[1:]) if b > a]
    if gaps:
        typical = sorted(gaps)[len(gaps) // 2]
    else:
        typical = max(columns[0].x1 - columns[0].x0, 1.0)
    reach = typical * 0.75

    for word in header_words:
        middle = (word["x0"] + word["x1"]) / 2.0
        nearest = min(columns, key=lambda c: abs(c.centre - middle))
        if abs(nearest.centre - middle) > reach:
            continue
        existing = nearest.header_text
        nearest.header_text = f"{existing} {word['text']}".strip() if existing else word["text"]

    for column in columns:
        column.header_text = re.sub(r"\s+", " ", column.header_text).strip()
        period = parse_period_label(column.header_text)
        if period:
            column.period_end = period
            column.kind = "PERIOD"
        elif re.search(r"year ended|quarter ended|period ended", column.header_text, re.I):
            column.kind = "DURATION"


#: Fraction of the page, measured from the top, that a page's own title lives
#: in. Used to decide what a page *is* before trusting a mention further down.
_ROLE_TITLE_FRACTION = 0.22

#: A text layer puts every character of a line on one baseline, so a row can be
#: gathered within a fraction of a line height. Recognition does not: each box is
#: detected independently and the boxes of one printed row came back up to 9px
#: apart at a 2.5x render, which is more than the text tolerance and enough to
#: drop a column from a row it belongs to. The tolerance is widened for read
#: pages by this factor - still well under the 21px pitch of the rows
#: themselves, so two rows cannot be joined.
OCR_ROW_TOLERANCE_FACTOR = 1.6


def _matches(pattern: re.Pattern[str], text: str, flat_text: str) -> bool:
    """Match a pattern against page text, tolerating words that lost their spaces.

    A born-digital text layer spaces its words, so the pattern is tried as
    written. Only when that fails is the comparison repeated with the spaces
    removed from both sides, which is what lets a heading read from an image be
    recognised as the statement it names.
    """
    if pattern.search(text):
        return True
    flat_pattern = re.compile(re.sub(r"\s+", "", pattern.pattern), pattern.flags)
    return bool(flat_text and flat_pattern.search(flat_text))

_SCOPE_PATTERNS = (
    ("CONSOLIDATED", re.compile(r"consolidated", re.I)),
    ("STANDALONE", re.compile(r"stand ?alone", re.I)),
)


def _row_tolerance(page_height: float) -> float:
    """Vertical tolerance for grouping words into a visual line.

    Roughly a third of a typical 10pt line height, scaled to the page.
    """
    return max(2.0, page_height * 0.0035)


def _column_gap_threshold(page_width: float) -> float:
    """Horizontal gap that separates two numeric columns.

    Indian results tables are right-aligned, so numbers in one column share a
    right edge and differ in x0 by their digit count. Measured on a Reliance
    quarterly P&L, the within-column right-edge spread is under 6px while
    adjacent columns are 70-90px apart. A 24px split threshold therefore
    separates columns reliably; the earlier fixed 7px tolerance produced 61
    phantom columns on a 2-column page.
    """
    return max(12.0, page_width * 0.04)


def _cluster_columns(
    cells: list[tuple[float, float, float, str]], threshold: float
) -> list[Column]:
    """Group right-aligned numbers into columns by right edge."""
    if not cells:
        return []
    ordered = sorted(cells, key=lambda c: c[2])  # by x1
    clusters: list[list[tuple[float, float, float, str]]] = [[ordered[0]]]
    for cell in ordered[1:]:
        if cell[2] - clusters[-1][-1][2] > threshold:
            clusters.append([cell])
        else:
            clusters[-1].append(cell)

    columns: list[Column] = []
    for index, cluster in enumerate(clusters):
        x1s = [c[2] for c in cluster]
        x0s = [c[1] for c in cluster]
        columns.append(
            Column(
                index=index,
                centre=sum(x1s) / len(x1s),
                x0=min(x0s),
                x1=max(x1s),
                cell_count=len(cluster),
            )
        )
    return columns


def _column_for(x1: float, columns: list[Column]) -> int:
    """Nearest column by right edge, so right-aligned figures stay together."""
    if not columns:
        return -1
    return min(range(len(columns)), key=lambda i: abs(columns[i].x1 - x1))


def _row_cells(
    band_cells: list[tuple[float, float, float, str, bool]],
    columns: list[Column],
    page_number: int,
    label: str,
) -> dict[str, Any]:
    """Parse one row's numbers, merging fragments that share a column.

    A PDF text layer can split one figure across two words - measured:
    ``13,398`` came out as ``13`` and ``398`` in the same column. Since a column
    holds exactly one value per row, two tokens landing in the same column are
    fragments of a single number, not two numbers. The merge is accepted only
    when the concatenation parses as a clean number; otherwise both fragments
    are kept and reported, because silently joining them would invent a figure.
    """
    grouped: dict[int, list[tuple[float, float, float, str, bool]]] = {}
    for cell in sorted(band_cells, key=lambda c: c[1]):
        grouped.setdefault(_column_for(cell[2], columns), []).append(cell)

    cells: list[NumberCell] = []
    rejections: list[dict[str, Any]] = []
    for column_index in sorted(grouped):
        group = grouped[column_index]
        if len(group) > 1:
            merged = "".join(c[3] for c in group)
            value, reason = parse_number(merged)
            if not reason and value is not None:
                cells.append(
                    NumberCell(
                        raw=merged, value=value, x0=group[0][1], x1=group[-1][2],
                        column=column_index, recovered=any(c[4] for c in group),
                        # The fragments as printed, so a reader can see which
                        # part was damaged and which was reassembled.
                        source_text=merged,
                    )
                )
                continue
        for _, x0, x1, raw, was_recovered in group:
            value, reason = parse_number(raw)
            cells.append(
                NumberCell(
                    raw=raw, value=value or 0.0, x0=x0, x1=x1, column=column_index,
                    rejected=reason, recovered=was_recovered and not reason,
                    source_text=raw,
                )
            )
            if reason:
                rejections.append({"raw": raw, "reason": reason})
    cells.sort(key=lambda c: c.column)
    return {"cells": cells, "rejections": rejections}


def _mark_ambiguous_columns(
    columns: list[Column], rows: list[Row]
) -> list[dict[str, Any]]:
    """Flag columns that hold more than one figure for most of the same rows.

    A column should hold exactly one number per row. When it routinely holds
    two, two genuinely different columns were clustered together, because
    right-edge clustering links neighbouring columns whenever the digit-width
    spread inside a column bridges the gap between them.

    Measured on a Reliance quarterly P&L, that put the current quarter and the
    prior-year comparative in one column. Reading "the first value in the
    current column" then published a comparative as the current quarter, and
    because a quarter's own figures are internally consistent, every
    arithmetic identity passed. Nothing downstream could have caught it.

    The test is deliberately a *ratio*, not a count. An isolated row carrying
    two figures is a footnote or a two-part line item, not two periods, and
    withholding a page for it would cost a quarter that is in fact perfectly
    readable. Two merged columns affect essentially every line item they
    contain, so the fraction of that column's populated rows is what
    separates the two cases. An ambiguous column is never publishable.
    """
    notes: list[dict[str, Any]] = []
    for column in columns:
        populated = [row for row in rows if any(c.column == column.index for c in row.cells)]
        if not populated:
            continue
        clashing: list[Row] = []
        for row in populated:
            values = [
                c for c in row.cells
                if c.column == column.index and c.ok and c.value is not None
            ]
            if len(values) > 1:
                clashing.append(row)
        if not clashing or len(clashing) < _MIN_AMBIGUOUS_ROWS:
            continue
        if len(clashing) / len(populated) < _AMBIGUOUS_COLUMN_RATIO:
            continue
        column.ambiguous = True
        column.ambiguous_rows = len(clashing)
        notes.append({
            "raw": f"column {column.index}: {len(clashing)} of {len(populated)} rows hold two figures",
            "reason": (
                f"column {column.index} merged two periods: "
                + "; ".join(
                    ", ".join(c.raw for c in row.cells if c.column == column.index)
                    for row in clashing[:3]
                )
            ),
        })
    return notes


def _is_note_reference_column(rows: Optional[list[Row]], index: int) -> bool:
    """True when a column holds footnote numbers rather than money.

    Bank and NBFC statements carry a leftmost column of ascending footnote
    references next to the caption - Bajaj Finance's consolidated P&L runs
    1, 2, 3, 7, 9, 11, 12, 13 down the page. Those numbers are dense enough to
    clear the 20% of the busiest column, and sitting furthest left they win the
    "leftmost data column" rule, so the period column was never reached and
    every line of the statement went unread.

    The signature is narrow on purpose: distinct integers in 1..999 that
    strictly increase as the page descends. Money never climbs monotonically
    down a statement, so anything matching this is a reference list, and
    anything not matching it is left to the ordinary column tests.
    """
    values: list[int] = []
    for row in rows or []:
        for cell in row.cells:
            if cell.column != index or cell.rejected or cell.value is None:
                continue
            value = cell.value
            if value != int(value) or not (1 <= value <= 999):
                return False
            values.append(int(value))
    if len(values) < _MIN_NOTE_REFERENCE_ROWS:
        return False
    return all(b > a for a, b in zip(values, values[1:]))


def _mark_current_column(columns: list[Column], rows: Optional[list[Row]] = None) -> None:
    """Mark the period column the filing is about.

    Indian results tables put the period being reported in the first data
    column, followed by the prior-year period. That is a format convention, not
    a guess about the data, so it is safe to rely on - but it fixes exactly one
    candidate, the leftmost data column, and this function must not reach past
    it to a later one.

    Reaching past it was a real defect. On Reliance's audited FY2026 P&L the
    leftmost data column is a merged cluster, so it was correctly rejected as
    ambiguous; the scan then continued and marked the *next* qualifying column
    CURRENT, which is the prior year. That published FY2025 revenue of 980,136
    crore as FY2026. The figures reconcile internally - every identity passes,
    because a whole year of real data balances - so no validator could have
    caught it, and a full year of wrong history looked entirely healthy.

    So when the leftmost data column is ambiguous or missing, the page yields
    no current period at all. A missing year is recoverable; a wrong one is
    indistinguishable from the truth downstream.

    Page headers and footers contribute one-cell phantom columns (a page
    number, a stray year), so a column counts as data only if it holds a
    meaningful share of the figures on the page.
    """
    if not columns:
        return
    busiest = max(c.cell_count for c in columns)
    if busiest < _MIN_COLUMN_CELLS:
        return
    threshold = max(_MIN_COLUMN_CELLS, int(busiest * 0.2))
    for column in columns:
        if column.cell_count < threshold:
            continue
        # A footnote list is definitively not the reported period, so it is
        # stepped over rather than treated as an ambiguous page.
        if _is_note_reference_column(rows, column.index):
            logger.debug(
                "[india.pdf] column %d holds footnote references; stepping past it",
                column.index,
            )
            continue
        if column.ambiguous:
            logger.debug(
                "[india.pdf] leftmost data column %d is ambiguous; yielding no current period",
                column.index,
            )
            return
        column.role = "CURRENT"
        return


# ---------------------------------------------------------------------------
# Page extraction
# ---------------------------------------------------------------------------
def analyse_page(page: Any, page_number: int) -> PageAnalysis:
    """Extract labelled rows and numeric columns from one PDF page."""
    try:
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception as exc:  # pragma: no cover - pdfplumber edge cases
        logger.warning("[india.pdf] page %d word extraction failed: %s", page_number, exc)
        return PageAnalysis(page_number=page_number)

    return _analyse_words(
        words,
        width=float(page.width or 595.0),
        height=float(page.height or 842.0),
        page_number=page_number,
    )


def _analyse_words(
    words: list[dict[str, Any]],
    *,
    width: float,
    height: float,
    page_number: int,
    row_tolerance: Optional[float] = None,
) -> PageAnalysis:
    """Analyse a page from positioned words, however those words were read.

    The text layer and the OCR fallback produce the same shape - a list of
    ``{"text", "x0", "x1", "top", "bottom"}`` boxes - so everything that decides
    a page's role, its columns and its rows lives here and neither reader has a
    private path through the logic that decides what is published.
    """
    analysis = PageAnalysis(page_number=page_number)

    # Characters actually recovered from the page. Rows and columns are not a
    # text measure: a cover letter or an auditor's report has neither, and an
    # image-only scan and a paragraph of prose are not the same thing.
    analysis.char_count = sum(len(w["text"]) for w in words)

    if not words:
        return analysis

    full_text = " ".join(w["text"] for w in sorted(words, key=lambda w: (w["top"], w["x0"])))
    # Recognition of a bold heading loses the spaces inside it: the title of a
    # scanned results page arrives as "UNAUDITEDSTANDALONEFINANCIALRESULTSFOR
    # THEQUARTER", and no role pattern can match that. The de-spaced form is
    # built once here and used as a fallback, so a heading is still recognised
    # while the text that becomes a row label keeps its original spelling.
    flat_text = re.sub(r"\s+", "", full_text)

    # A page is told what it is by its own title. Searching the whole page lets
    # a passing mention of "financial results" in a footnote or a running header
    # claim a balance sheet for a profit and loss account, so the title region
    # is searched first and the rest of the page is the fallback. A statement
    # names itself at the top; that is not an accident of these filings.
    title_text = " ".join(
        w["text"] for w in sorted(
            (w for w in words if w["top"] <= _ROLE_TITLE_FRACTION * height),
            key=lambda w: (w["top"], w["x0"]),
        )
    )
    flat_title = re.sub(r"\s+", "", title_text)

    # ``role`` starts as OTHER, which is truthy, so the fallback below has to
    # test for a *matched* role rather than for any role. Testing truthiness
    # ended the loop after the title region on every page whose title named
    # nothing, and the whole-page fallback — the pass the cover letter needs —
    # never ran. The letter then stayed OTHER instead of matching "financial
    # results for the quarter" and being structurally downgraded to TEXT.
    for corpus, flat_corpus in ((title_text, flat_title), (full_text, flat_text)):
        if not corpus.strip():
            continue
        for role, pattern in _ROLE_PATTERNS:
            if _matches(pattern, corpus, flat_corpus):
                analysis.role = role
                break
        if analysis.role != "OTHER":
            break

    for scope, pattern in _SCOPE_PATTERNS:
        if _matches(pattern, full_text, flat_text):
            analysis.scope = scope
            break

    analysis.unit = detect_unit(full_text[:1200])

    # --- cluster words into visual lines --------------------------------
    tol = row_tolerance if row_tolerance else _row_tolerance(height)
    bands: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda w: w["top"]):
        if bands and abs(word["top"] - bands[-1][0]["top"]) <= tol:
            bands[-1].append(word)
        else:
            bands.append([word])
    bands.sort(key=lambda b: b[0]["top"])

    # --- find the header band: the region holding period labels ----------
    header_words: list[dict[str, Any]] = []
    for band in bands[:14]:
        text = " ".join(w["text"] for w in band)
        if re.search(r"(quarter|year|period|ended|as at|particulars)", text, re.I) or \
           parse_period_label(text):
            header_words.extend(band)
        if re.search(r"\b(income|expenses|particulars)\b", text, re.I) and header_words:
            break
    # The gate is the *bottom* of the header, not its top. The period headings
    # above a results table are themselves numeric - "30.06.2026" is a date and
    # reads as a number - and gating on the top of the header let the column
    # headings form columns of their own, one phantom column per heading. Gating
    # on the bottom keeps a heading where it belongs: as the label of a column.
    body_top = max((w["bottom"] for w in header_words), default=0.0)

    # --- numeric cells ---------------------------------------------------
    # Only cells below the header count. This drops the address blocks, phone
    # numbers and CIN digits that otherwise pollute the column model (measured:
    # page 1 contributed 22 phantom columns before the header gate).
    body_cells: list[tuple[float, float, float, str, bool]] = []
    for band in bands:
        top = band[0]["top"]
        if top < body_top - tol:
            continue
        for word in band:
            text = word["text"]
            # Repair is tried first, not only on tokens that look like text. A
            # figure whose decimal point was read as a comma still looks like a
            # number to the shape test, so repairing only the failures left
            # "62005,.98" unrepaired and the cell rejected.
            repaired = repair_ocr_separator(text) or recover_damaged_number(text)
            if repaired:
                body_cells.append((top, word["x0"], word["x1"], repaired, True))
            elif looks_numeric(text):
                body_cells.append((top, word["x0"], word["x1"], text, False))

    if not body_cells:
        return analysis

    analysis.columns = _cluster_columns(
        [(c[0], c[1], c[2], c[3]) for c in body_cells], _column_gap_threshold(width)
    )

    # --- attach header text / period to each column ----------------------
    _attribute_headers(analysis.columns, header_words)

    # --- build rows ------------------------------------------------------
    for band in bands:
        band_top = band[0]["top"]
        if band_top < body_top - tol:
            continue
        band_cells = [c for c in body_cells if abs(c[0] - band_top) <= tol]
        if not band_cells:
            continue
        numeric_x1 = {c[1] for c in band_cells}
        parts = sorted(
            (
                w for w in band
                if not looks_numeric(w["text"])
                and not recover_damaged_number(w["text"])
                and w["x1"] not in numeric_x1
            ),
            key=lambda w: w["x0"],
        )
        label = re.sub(r"\s+", " ", " ".join(w["text"] for w in parts)).strip()
        row_cells = _row_cells(band_cells, analysis.columns, page_number, label)
        analysis.rejected.extend(
            {"page": page_number, "raw": c["raw"], "reason": c["reason"], "label": label}
            for c in row_cells["rejections"]
        )
        analysis.rows.append(
            Row(
                top=band_top, label=label, cells=row_cells["cells"],
                raw=" ".join(w["text"] for w in sorted(band, key=lambda w: w["x0"])),
            )
        )

        # Row-content evidence: a page whose title is ambiguous but whose body rows
        # carry strong income-statement anchors is a P&L, regardless of what the
        # title matched. This rescues consolidated Bank P&L pages whose title does
        # not name the statement but whose rows name "Total Income", "Interest
        # Earned", "Interest Expended", "Profit Before Tax", and similar.
        if analysis.role == "OTHER" and analysis.rows:
            body_text = " ".join(
                r.label for r in analysis.rows if r.label
            )
            if _P_AND_L_ROW_ANCHORS.search(body_text):
                analysis.role = "P_AND_L"

    # Ambiguity can only be judged once the rows exist, and it must be judged
    # before the current column is chosen.
    analysis.rejected.extend(
        {"page": page_number, **note}
        for note in _mark_ambiguous_columns(analysis.columns, analysis.rows)
    )
    _mark_current_column(analysis.columns, analysis.rows)

    logger.debug(
        "[india.pdf] page %d role=%s scope=%s unit=%s cols=%d rows=%d rejected=%d",
        page_number, analysis.role, analysis.scope, analysis.unit.name,
        len(analysis.columns), len(analysis.rows), len(analysis.rejected),
    )
    _qualify_role(analysis)
    return analysis


#: A page only counts as a statement when it looks like a table of figures, not
#: a cover letter that happens to say "financial results". Measured: page 1 of
#: the Reliance filing is a letter to the exchanges with 9 label-plus-number
#: rows (postal codes, phone fragments, years) against 32 on the real P&L.
#: Every threshold here is company-size independent. A magnitude threshold was
#: tried and removed: it cannot separate a real figure (a 2,026-crore column is
#: legitimate) from a postal code without risking false downgrades on smaller
#: companies, so it was discarded rather than left in as decoration.
_MIN_STATEMENT_ROWS = 10
_MIN_STATEMENT_ACCEPTED_CELLS = 12
_MIN_DATA_COLUMNS = 2
_MIN_COLUMN_CELLS = 5

#: Fraction of a column's populated rows that must hold two figures before the
#: column is treated as two merged periods and withheld. Measured: the Reliance
#: Q3 FY2026 P&L page puts the current and prior quarter in one column on 15 of
#: 18 populated rows (0.83, withheld), while a correct page shows two figures on
#: 2 of 30 rows (0.07, an isolated two-part line, kept).
_AMBIGUOUS_COLUMN_RATIO = 0.4
#: Below this many clashing rows the ratio is not evidence of anything, so the
#: column is left alone.
_MIN_AMBIGUOUS_ROWS = 3
_MIN_NOTE_REFERENCE_ROWS = 5


def _qualify_role(analysis: PageAnalysis) -> None:
    """Downgrade a statement role to TEXT when the page is not a table."""
    if analysis.role not in ("P_AND_L", "BALANCE_SHEET", "CASH_FLOW",
                             "CHANGES_IN_EQUITY", "BORROWINGS"):
        return
    rows_with_data = [
        r for r in analysis.rows
        if r.label and any(c.ok for c in r.cells)
    ]
    accepted = sum(1 for r in analysis.rows for c in r.cells if c.ok)
    data_columns = [c for c in analysis.columns if c.cell_count >= _MIN_COLUMN_CELLS]
    if (
        len(rows_with_data) < _MIN_STATEMENT_ROWS
        or accepted < _MIN_STATEMENT_ACCEPTED_CELLS
        or len(data_columns) < _MIN_DATA_COLUMNS
    ):
        analysis.role = "TEXT"


# ---------------------------------------------------------------------------
# Whole-document analysis
# ---------------------------------------------------------------------------
@dataclass
class ParsedFiling:
    """Everything one PDF yielded, including what it refused to yield."""

    page_count: int = 0
    scope: str = ""
    unit: Unit = field(default_factory=lambda: Unit(scale=1.0, name="rupee"))
    is_results_document: bool = False
    #: The document is a scan of printed pages, not born-digital text. HDFC Bank
    #: posts its results that way: the cover letter carries text and every
    #: statement page is a single image, so there is nothing to read at all.
    #: Reporting that plainly is the difference between a filing Finora cannot
    #: read and a filing Finora looked at wrongly.
    is_scanned: bool = False
    #: Pages of a scanned filing that were read optically, by page number. Empty
    #: for a filing with a text layer, because nothing was read from an image.
    ocr_pages: list[int] = field(default_factory=list)
    period_end: str = ""
    period_end_source: str = "NONE"
    symbol: str = ""
    scrip_code: str = ""
    cin: str = ""
    company_name: str = ""
    pages: list[PageAnalysis] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    @property
    def statement_pages(self) -> list[PageAnalysis]:
        return [p for p in self.pages if p.role in ("P_AND_L", "BALANCE_SHEET", "CASH_FLOW")]

    def quality(self) -> dict[str, Any]:
        total = sum(len(p.rejected) for p in self.pages)
        return {
            "page_count": self.page_count,
            "statement_pages": len(self.statement_pages),
            "rejected_cells": total,
            "rows_extracted": sum(len(p.rows) for p in self.pages),
            "is_results_document": self.is_results_document,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.quality(),
            "scope": self.scope,
            "unit": self.unit.to_dict(),
            "period_end": self.period_end,
            "period_end_source": self.period_end_source,
            "symbol": self.symbol,
            "scrip_code": self.scrip_code,
            "cin": self.cin,
            "company_name": self.company_name,
            "pages": [p.to_dict() for p in self.pages],
            "rejected": self.rejected[:200],
        }


_RESULTS_RE = re.compile(
    r"(financial results?|financial statements?)\s*(for|as at)?", re.I
)
_SUBJECT_RE = re.compile(
    r"sub\s*:\s*(.{0,220}?)(?:kindly|please|this is|sincerely|yours)", re.I | re.S
)
_SYMBOL_RE = re.compile(r"trading symbol\s*[:\s]\s*([A-Za-z0-9&.\-]{1,15})", re.I)
_SCRIP_RE = re.compile(r"scrip code\s*[:\s]\s*(\d{6})", re.I)
_CIN_RE = re.compile(r"\bCIN\s*[:\-]?\s*([LUP]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6})", re.I)
_COMPANY_RE = re.compile(r"^([A-Z][A-Za-z0-9 &\-.]{4,70}(?:Limited|Ltd\.?))", re.M)


def _identity_from_text(text: str, filing: ParsedFiling) -> None:
    m = _SYMBOL_RE.search(text)
    if m and not filing.symbol:
        filing.symbol = m.group(1).upper()
    m = _SCRIP_RE.search(text)
    if m and not filing.scrip_code:
        filing.scrip_code = m.group(1)
    m = _CIN_RE.search(text)
    if m and not filing.cin:
        filing.cin = m.group(1).upper()
    if not filing.company_name:
        m = _COMPANY_RE.search(text)
        if m:
            filing.company_name = re.sub(r"\s+", " ", m.group(1)).strip()


#: Statement pages rarely sit at the very front of a filing, and a filing can be
#: thirty pages of notes before the first statement. This is the number of
#: image pages read, counted from the front, and it is a cost bound rather than
#: an assumption about where the statements are: every page read is analysed by
#: the same rules as a text page, so reading too few loses data and reading more
#: costs time but cannot introduce a different kind of error.
_MAX_OCR_PAGES = 14


def parse_pdf(payload: bytes, max_pages: int = 60, max_ocr_pages: int = _MAX_OCR_PAGES) -> ParsedFiling:
    """Analyse a results PDF. Never raises on a malformed document."""
    filing = ParsedFiling()
    if not payload:
        return filing
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - dependency is declared
        logger.error("[india.pdf] pdfplumber is not installed")
        return filing

    try:
        pdf = pdfplumber.open(io.BytesIO(payload))
    except Exception as exc:
        logger.warning("[india.pdf] cannot open document: %s", exc)
        filing.rejected.append({"reason": f"unopenable_pdf: {type(exc).__name__}"})
        return filing

    try:
        with pdf:
            filing.page_count = len(pdf.pages)
            header_text: list[str] = []
            for index, page in enumerate(pdf.pages[:max_pages], start=1):
                analysis = analyse_page(page, index)
                filing.pages.append(analysis)
                filing.rejected.extend(analysis.rejected)
                if index <= 2:
                    try:
                        header_text.append(page.extract_text() or "")
                    except Exception:
                        pass

            head = "\n".join(header_text)
            _identity_from_text(head, filing)

            if _RESULTS_RE.search(head) or any(
                p.role in ("P_AND_L", "BALANCE_SHEET", "CASH_FLOW") for p in filing.pages
            ):
                filing.is_results_document = True

            # A page that yielded no characters is an image. When most of the
            # document is like that and no statement page was recognised, the
            # filing is a scan. The test is on characters rather than rows,
            # because a cover letter and an auditor's report have no table
            # either, and neither of them is unreadable.
            textless = sum(1 for p in filing.pages if not p.char_count)
            filing.is_scanned = bool(
                filing.pages
                and not any(
                    p.role in ("P_AND_L", "BALANCE_SHEET", "CASH_FLOW")
                    for p in filing.pages
                )
                and textless * 2 > len(filing.pages)
            )

            # A scan is read optically. This happens here, after the text layer
            # has been given its chance, so a filing with a text layer never pays
            # for OCR - and a scan that OCR cannot improve is still reported as
            # a scan, not as an empty result.
            if filing.is_scanned:
                _apply_ocr(payload, filing, max_ocr_pages=max_ocr_pages)

            # Scope: the dominant scope across statement pages wins.
            scopes: dict[str, int] = {}
            for p in filing.statement_pages:
                if p.scope:
                    scopes[p.scope] = scopes.get(p.scope, 0) + 1
            filing.scope = max(scopes, key=lambda k: scopes[k]) if scopes else ""
            if not filing.scope and "consolidated" in head.lower():
                filing.scope = "CONSOLIDATED"

            units = [p.unit for p in filing.statement_pages if p.unit.name != "rupee"]
            filing.unit = units[0] if units else detect_unit(head[:1200])

            filing.period_end, filing.period_end_source = _resolve_period(head, filing)
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    return filing


def _apply_ocr(payload: bytes, filing: ParsedFiling, *, max_ocr_pages: int) -> None:
    """Read the image pages of a scanned filing and re-analyse them.

    Each page is replaced by the analysis of what was recognised on it, so a
    scanned filing reaches the validator through exactly the same path a born-
    digital one does and is subject to exactly the same identities. A page that
    yields nothing stays empty, which is how a text page that cannot be read
    already behaves.
    """
    from . import ocr

    if not ocr.available():
        filing.rejected.append({
            "reason": "scanned_pdf_without_ocr",
            "detail": (
                "the filing is a scan and no OCR backend is installed, so its "
                "statements cannot be read"
            ),
        })
        logger.warning("[india.pdf] scanned filing, but no OCR backend is available")
        return

    targets = [
        p.page_number for p in filing.pages
        if not p.char_count and p.page_number <= max_ocr_pages
    ]
    if not targets:
        return

    logger.info(
        "[india.pdf] reading %d image page(s) of a scanned filing", len(targets)
    )
    recognised = ocr.read_document_pages(payload, targets)
    if not recognised:
        filing.rejected.append({
            "reason": "ocr_read_nothing",
            "detail": "the image pages were read but no text was recognised",
        })
        return

    by_number = {p.page_number: p for p in filing.pages}
    for number, (words, width, height) in recognised.items():
        page = by_number.get(number)
        if page is None:
            continue
        filing.pages[filing.pages.index(page)] = _analyse_words(
            words, width=width, height=height, page_number=number,
            row_tolerance=(
                _row_tolerance(height) * OCR_ROW_TOLERANCE_FACTOR
            ),
        )
        filing.ocr_pages.append(number)
    filing.ocr_pages.sort()

    filing.rejected.extend(
        {
            "raw": f"page {number}",
            "reason": "image page read optically; figures still require corroboration",
        }
        for number in sorted(recognised)
    )

    if not filing.is_results_document and any(
        p.role in ("P_AND_L", "BALANCE_SHEET", "CASH_FLOW") for p in filing.pages
    ):
        filing.is_results_document = True


def _resolve_period(head: str, filing: ParsedFiling) -> tuple[str, str]:
    """Period end for the document, from the subject line then the page titles."""
    subject = _SUBJECT_RE.search(head)
    candidates = [subject.group(1)] if subject else []
    candidates.append(head)
    from lib.india import documents as docmod

    for text in candidates:
        explicit = docmod.detect_period_end(text)
        if explicit:
            return explicit, "EXPLICIT"

    for page in filing.pages:
        for column in page.columns:
            if column.period_end:
                return column.period_end, "PAGE_COLUMN"
    return "", "NONE"
