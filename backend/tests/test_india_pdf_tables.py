"""Strict PDF table extraction for Indian results filings.

Every case here was measured against a real NSE filing, not invented. The
reliability rules exist because the text layer of these PDFs damages both
labels and digits, so the extractor's job is to publish only what it can
prove and to say why it dropped the rest.
"""

from __future__ import annotations

import pytest

from lib.india.pdf_tables import (
    Column,
    detect_unit,
    looks_numeric,
    parse_number,
    parse_period_label,
    recover_damaged_number,
    _cluster_columns,
    _column_for,
    _mark_current_column,
    _qualify_role,
    _row_cells,
    PageAnalysis,
    Row,
)


# ---------------------------------------------------------------------------
# Number parsing: accept clean forms, refuse damaged ones
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("325,290", 325290.0),
        ("1,23,456", 123456.0),   # Indian grouping
        ("12,34,567.89", 1234567.89),
        ("(4,214)", -4214.0),      # accounting negative
        ("-1,234", -1234.0),
        ("0", 0.0),
        ("1,234.56", 1234.56),
        ("2,546", 2546.0),
    ],
)
def test_parse_number_accepts_clean_figures(raw, expected):
    value, reason = parse_number(raw)
    assert reason == "", f"{raw!r} should parse but was rejected: {reason}"
    assert value == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("1,175,9.19", "bad_grouping"),   # measured: a real damaged cell
        ("4;973", "damaged_characters"),   # measured
        ("2,20~,7~7", "damaged_characters"),  # measured
        ("!15,754", "damaged_characters"),    # measured
        ("171),121", "not_a_number"),     # measured: misplaced paren
        ("194,Q47", "contains_letters"),  # measured
        ("abc", "contains_letters"),
        ("1,2,34", "bad_grouping"),
        ("1.234", "bad_decimal_places"),
        ("", "empty"),
    ],
)
def test_parse_number_refuses_damaged_figures(raw, reason):
    value, got = parse_number(raw)
    assert value is None
    assert got == reason


def test_damaged_figure_is_refused_not_guessed():
    """A refused cell must carry no value at all, not a best guess."""
    value, _ = parse_number("1,175,9.19")
    assert value is None


# ---------------------------------------------------------------------------
# Leading-glyph recovery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("J3,533", "13,533"),   # measured on page 18 of a real filing
        ("l7,138", "17,138"),
        ("O1,204", "01,204"),
        ("S8,450", "58,450"),
    ],
)
def test_recover_damaged_number_fixes_one_leading_glyph(raw, expected):
    assert recover_damaged_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "Q3",         # a quarter label, not a figure
        "H1",
        "S1",
        "Other",      # ordinary words
        "FY24",
        "ICICI",
        "L17110MH1973PLC019786",  # a CIN
        "1,175,9.19",  # damage in the middle is not repairable
    ],
)
def test_recover_damaged_number_refuses_everything_else(raw):
    assert recover_damaged_number(raw) is None


def test_recovered_number_must_still_parse_cleanly():
    """Recovery may not bypass the grouping rules."""
    assert recover_damaged_number("J1,2,34") is None


# ---------------------------------------------------------------------------
# Units and periods
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, unit, multiplier",
    [
        ("~ in crore, exce er share data", "crore", 10_000_000),
        ("Rs. in lakhs", "lakh", 100_000),
        ("in million", "million", 1_000_000),
        ("Rs in thousands", "thousand", 1_000),   # plural form
        ("Rs in crores", "crore", 10_000_000),    # plural form
        ("Amount in 000", "rupee", 1),
        ("2,20,449 (in Rs. Crores)", "crore", 10_000_000),
    ],
)
def test_parse_unit(text, unit, multiplier):
    parsed = detect_unit(text)
    assert parsed.name == unit
    assert parsed.scale == multiplier


def test_share_data_footnote_does_not_change_unit():
    """Share counts in absolute units must not rescale the money."""
    assert detect_unit("in crore (except share data)").name == "crore"


def test_missing_unit_declaration_defaults_to_rupees():
    """Absence of a declaration is recorded as rupees, not guessed upward."""
    assert detect_unit("no unit stated here").name == "rupee"
    assert detect_unit("").scale == 1.0


@pytest.mark.parametrize(
    "text, expected",
    [
        ("30th Jun'26", "2026-06-30"),
        ("31st Mar'26", "2026-03-31"),
        ("31 Mar' 26", "2026-03-31"),
        ("31-03-2026", "2026-03-31"),
        ("30.06.2026", "2026-06-30"),
        ("June 30, 2026", "2026-06-30"),
        ("September 30th 2025", "2025-09-30"),
        ("3!J1l!Jun'25", None),   # measured: unrecoverable damage
        ("Year Ended", None),
        ("", None),
    ],
)
def test_parse_period_label(text, expected):
    assert parse_period_label(text) == expected


# ---------------------------------------------------------------------------
# Column geometry
# ---------------------------------------------------------------------------


def test_cluster_columns_groups_right_aligned_figures():
    """Measured: a two-column P&L produced 61 phantom columns before this."""
    cells = []
    for top in (100.0, 115.0, 130.0):
        cells.append((top, 380.0, 400.0, "1,000", False))
        cells.append((top, 460.0, 480.0, "2,000", False))
    columns = _cluster_columns([(c[0], c[1], c[2], c[3]) for c in cells], 24.0)
    assert len(columns) == 2
    assert all(c.cell_count == 3 for c in columns)


def test_mark_current_column_skips_phantom_column():
    """A stray page-number column must not be treated as the period column."""
    cells = [(0.0, 0.0, 0.0, "", False)]
    columns = _cluster_columns(
        [(100.0, 10.0, 20.0, "7", False)]                       # page number
        + [(200.0 + i, 380.0, 400.0, "1,000", False) for i in range(10)]
        + [(200.0 + i, 460.0, 480.0, "2,000", False) for i in range(9)],
        24.0,
    )
    del cells
    _mark_current_column(columns)
    current = [c for c in columns if c.role == "CURRENT"]
    assert len(current) == 1
    assert current[0].cell_count == 10
    assert current[0].index == 1


def test_column_for_uses_right_edge():
    columns = [Column(index=0, centre=100.0, x0=80.0, x1=120.0),
               Column(index=1, centre=200.0, x0=180.0, x1=220.0)]
    assert _column_for(215.0, columns) == 1
    assert _column_for(118.0, columns) == 0
    assert _column_for(999.0, []) == -1


# ---------------------------------------------------------------------------
# Row assembly
# ---------------------------------------------------------------------------


def test_row_cells_merges_fragments_sharing_a_column():
    """Measured: '13,398' arrived as two words, '13' and '398'."""
    result = _row_cells(
        [
            (10.0, 380.0, 400.0, "31,134", False),
            (10.0, 460.0, 472.0, "13", False),
            (10.0, 480.0, 500.0, "398", False),
        ],
        [Column(index=0, centre=390.0, x0=370.0, x1=400.0),
         Column(index=1, centre=470.0, x0=450.0, x1=500.0)],
        9, "Total Comprehensive Income",
    )
    assert result["rejections"] == []
    values = {c.column: c.value for c in result["cells"]}
    assert values == {0: 31134.0, 1: 13398.0}


def test_row_cells_refuses_a_merge_that_would_not_parse():
    """Joining fragments must never invent a figure.

    ``1,2,34`` and ``567`` concatenate to ``1,2,34567``, which is not a legal
    grouped number. The merge is refused, so the damaged fragment stays
    rejected and the clean fragment is kept on its own rather than combined
    into a figure that was never printed.
    """
    result = _row_cells(
        [(10.0, 460.0, 472.0, "1,2,34", False),
         (10.0, 480.0, 500.0, "567", False)],
        [Column(index=0, centre=470.0, x0=450.0, x1=500.0)],
        9, "Revenue",
    )
    by_raw = {c.raw: c for c in result["cells"]}
    assert set(by_raw) == {"1,2,34", "567"}
    assert by_raw["1,2,34"].ok is False
    assert by_raw["567"].value == 567.0
    assert len(result["rejections"]) == 1


def test_row_cells_marks_recovered_values():
    """Recovery happens upstream in ``analyse_page``; the flag is carried here."""
    result = _row_cells(
        [(10.0, 380.0, 400.0, "13,533", True)],
        [Column(index=0, centre=390.0, x0=370.0, x1=400.0)],
        18, "Other Equity",
    )
    cell = result["cells"][0]
    assert cell.raw == "13,533"
    assert cell.value == 13533.0
    assert cell.recovered is True


def test_row_cells_does_not_flag_a_clean_value_as_recovered():
    result = _row_cells(
        [(10.0, 380.0, 400.0, "13,533", False)],
        [Column(index=0, centre=390.0, x0=370.0, x1=400.0)],
        18, "Other Equity",
    )
    assert result["cells"][0].recovered is False


def test_recovered_cell_still_counts_as_accepted():
    result = _row_cells(
        [(10.0, 380.0, 400.0, "13,533", True)],
        [Column(index=0, centre=390.0, x0=370.0, x1=400.0)],
        18, "Other Equity",
    )
    assert result["cells"][0].ok is True


def test_merged_fragments_inherit_recovery_flag():
    result = _row_cells(
        [(10.0, 460.0, 472.0, "13", False), (10.0, 480.0, 500.0, "398", True)],
        [Column(index=0, centre=470.0, x0=450.0, x1=500.0)],
        9, "Revenue",
    )
    assert result["cells"][0].recovered is True


# ---------------------------------------------------------------------------
# Statement-page qualification
# ---------------------------------------------------------------------------


def _statement_rows(count: int, magnitude: float = 100000.0):
    return [
        Row(top=float(i), label=f"Line item {i}",
            cells=[type("C", (), {"ok": True, "value": magnitude})()])
        for i in range(count)
    ]


def _cover_letter_rows():
    """Measured page 1 of a real filing: postal codes, years, phone fragments."""
    return [
        Row(top=float(i), label=label,
            cells=[type("C", (), {"ok": True, "value": value})()])
        for i, (label, value) in enumerate([
            ("Mumbai Bandra (East), Mumbai", 400.0),
            ("Scrip Code: Trading Symbol: RELIANCE", 500325.0),
            ("Phone #: +91-22-3555", 2268.0),
            ("L-1840 Luxembourg Singapore", 68804.0),
            ("June", 2026.0),
        ])
    ]


def test_cover_letter_is_not_a_statement():
    analysis = PageAnalysis(page_number=1, role="P_AND_L", scope="CONSOLIDATED")
    analysis.rows = _cover_letter_rows()
    analysis.columns = [Column(index=0, centre=157.0, x0=145.0, x1=170.0, cell_count=6)]
    _qualify_role(analysis)
    assert analysis.role == "TEXT"


def test_real_statement_page_qualifies():
    analysis = PageAnalysis(page_number=9, role="P_AND_L", scope="CONSOLIDATED")
    analysis.rows = _statement_rows(32)
    analysis.columns = [
        Column(index=0, centre=410.0, x0=390.0, x1=430.0, cell_count=36),
        Column(index=1, centre=490.0, x0=470.0, x1=510.0, cell_count=33),
    ]
    _qualify_role(analysis)
    assert analysis.role == "P_AND_L"


def test_thin_page_is_not_a_statement():
    """Too few label-plus-number rows to be a statement, however many columns."""
    analysis = PageAnalysis(page_number=1, role="P_AND_L", scope="CONSOLIDATED")
    analysis.rows = _statement_rows(5)
    analysis.columns = [
        Column(index=0, centre=410.0, x0=390.0, x1=430.0, cell_count=36),
        Column(index=1, centre=490.0, x0=470.0, x1=510.0, cell_count=33),
    ]
    _qualify_role(analysis)
    assert analysis.role == "TEXT"


def test_single_data_column_is_not_a_statement():
    """Ratios and one-figure notes have a single column; statements do not."""
    analysis = PageAnalysis(page_number=1, role="P_AND_L", scope="CONSOLIDATED")
    analysis.rows = _statement_rows(30)
    analysis.columns = [
        Column(index=0, centre=410.0, x0=390.0, x1=430.0, cell_count=36),
        Column(index=1, centre=490.0, x0=470.0, x1=510.0, cell_count=3),
    ]
    _qualify_role(analysis)
    assert analysis.role == "TEXT"


def test_segment_pages_are_left_alone():
    """The qualification test targets statements, not segment tables."""
    analysis = PageAnalysis(page_number=13, role="SEGMENT", scope="CONSOLIDATED")
    analysis.rows = _cover_letter_rows()
    _qualify_role(analysis)
    assert analysis.role == "SEGMENT"


def test_looks_numeric_rejects_ordinary_words():
    assert looks_numeric("325,290") is True
    assert looks_numeric("(4,214)") is True
    assert looks_numeric("Other") is False
    assert looks_numeric("") is False


# ---------------------------------------------------------------------------
# Indian grouping: periods as thousands separators
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20.512.73", 20512.73),
        ("81.982.38", 81982.38),
        ("2.378.69", 2378.69),
        ("1.234.56", 1234.56),
        ("20.512.7", 20512.7),
    ],
)
def test_periods_are_read_as_thousands_separators(raw, expected):
    """Bajaj Finance prints "20.512.73" on a page that also prints "23,165.45".

    Indian bank and NBFC results are typeset with periods as the thousands
    separator in some cells and commas in others on the same line. The line
    items only reconcile if 20.512.73 is 20,512.73: interest income 20,512.73
    plus fees 2,378.69 plus 94.40 plus 3.25 plus 34.39 plus 141.99 is exactly
    the printed total revenue from operations of 23,165.45. Refusing the token
    lost most of the statement.
    """
    value, reason = parse_number(raw)
    assert reason == "", reason
    assert value == pytest.approx(expected)


def test_a_genuine_three_decimal_value_is_not_read_as_grouping():
    """"20.512" is a real quantity, not a grouped 20,512, so it stays refused."""
    value, reason = parse_number("20.512")
    assert value is None
    assert reason == "bad_decimal_places"


def test_dot_grouping_does_not_disturb_ordinary_separators():
    for raw, expected in (("23,165.45", 23165.45), ("2,05,132.73", 205132.73),
                          ("(374.27)", -374.27), ("1,993.44", 1993.44)):
        value, reason = parse_number(raw)
        assert reason == "", (raw, reason)
        assert value == pytest.approx(expected)
