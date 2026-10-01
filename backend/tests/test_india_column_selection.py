"""Choosing which column of a results table the filing is reporting.

A results PDF prints the period being reported, the prior-year period, and often
a cumulative column, side by side. Reading the wrong one is the most damaging
mistake this pipeline can make, because a comparative period is a complete,
internally consistent set of figures: every arithmetic identity holds, the
numbers are real, and only the label is wrong. Nothing downstream can detect
it, so the choice has to be made correctly here or not published at all.

Each test below is a defect that actually occurred, measured on live Reliance
filings.
"""

from __future__ import annotations

import pytest

from lib.india.adapter import _fiscal_year, _period_kind
from lib.india.pdf_tables import (
    Column,
    _mark_current_column,
    _mark_ambiguous_columns,
    NumberCell,
    Row,
)


def _col(index: int, x1: float, count: int) -> Column:
    return Column(
        index=index, centre=x1, x0=x1 - 30.0, x1=x1, cell_count=count
    )


def _row(column: int, *values: str) -> Row:
    """One row carrying one value per column, as ``_row_cells`` would produce."""
    return Row(
        top=0.0,
        label="Revenue from Operations",
        cells=[
            NumberCell(raw=v, value=float(v.replace(",", "")), x0=0.0,
                       x1=1.0, column=c)
            for c, v in ((column, values[0]),)
        ],
    )


def _two_value_row(column: int, first: str, second: str) -> Row:
    return Row(
        top=0.0,
        label="Revenue from Operations",
        cells=[
            NumberCell(raw=first, value=float(first.replace(",", "")),
                       x0=300.0, x1=340.0, column=column),
            NumberCell(raw=second, value=float(second.replace(",", "")),
                       x0=360.0, x1=400.0, column=column),
        ],
    )


# ---------------------------------------------------------------------------
# The prior-year substitution
# ---------------------------------------------------------------------------
def test_ambiguous_first_column_does_not_fall_through_to_the_prior_year():
    """A rejected first column must not promote the next one into its place.

    Reliance's audited FY2026 P&L opens with a column whose right edges chain
    two periods into one cluster, so it is rejected as ambiguous. The scan then
    used to continue and mark the *following* column current - which is the
    prior year. That published FY2025 revenue of 980,136 crore as FY2026.

    The figures reconciled perfectly, because a whole real year balances like
    any other. The only defence is to publish nothing from the page.
    """
    columns = [
        _col(0, 100.0, 1),      # stray page number
        _col(1, 120.0, 2),      # header text
        _col(2, 421.0, 69),     # merged: two periods, 39 rows, 69 figures
        _col(3, 481.0, 13),
        _col(4, 512.0, 1),
        _col(5, 541.0, 32),     # prior year, fully populated
    ]
    columns[2].ambiguous = True
    columns[2].ambiguous_rows = 30

    _mark_current_column(columns)

    assert not any(c.role == "CURRENT" for c in columns), (
        "a page whose reported column is unreadable must yield no current "
        "period, not the prior year's"
    )


def test_the_leftmost_data_column_is_the_one_taken():
    """With no ambiguity, the first data column is the reported period."""
    columns = [
        _col(0, 101.0, 3),      # phantom from the page header
        _col(1, 232.0, 2),      # phantom
        _col(2, 280.0, 31),     # reported quarter
        _col(3, 337.0, 32),     # prior quarter
        _col(4, 423.0, 39),     # half year
        _col(5, 567.0, 33),     # audited year
    ]
    _mark_current_column(columns)
    assert [c.index for c in columns if c.role == "CURRENT"] == [2]


# ---------------------------------------------------------------------------
# Distinguishing a merged period column from an ordinary two-part row
# ---------------------------------------------------------------------------
def test_a_column_holding_two_figures_on_every_row_is_ambiguous():
    """The measured Q3 FY2026 shape: two figures on nearly every line item."""
    column = _col(0, 421.0, 36)
    rows = [_two_value_row(0, f"{100 + i},000", f"{200 + i},000") for i in range(18)]

    notes = _mark_ambiguous_columns([column], rows)

    assert column.ambiguous is True
    assert column.ambiguous_rows == 18
    assert column.is_publishable is False
    assert notes and "merged two periods" in notes[0]["reason"]


def test_an_isolated_two_figure_row_is_not_treated_as_two_periods():
    """Two figures on one row are a footnote or a two-part line item.

    A correct Reliance page has exactly this: a two-part line among thirty
    otherwise clean rows. Withholding the page for it would cost a quarter that
    reads perfectly well, so the test has to be a ratio, not a count.
    """
    column = _col(0, 280.0, 31)
    rows = [_two_value_row(0, f"{100 + i},000", f"{200 + i},000") for i in range(2)]
    rows += [Row(top=float(i), label="Other", cells=[
        NumberCell(raw=f"{i},000", value=float(i), x0=0.0, x1=1.0, column=0)
    ]) for i in range(28)]

    _mark_ambiguous_columns([column], rows)
    _mark_current_column([column])

    assert column.ambiguous is False
    assert column.role == "CURRENT", (
        "an isolated two-figure row must not cost the page its period"
    )


def test_phantom_columns_do_not_become_the_current_column():
    """Header and footer artefacts are not data columns."""
    columns = [_col(0, 101.0, 3), _col(1, 232.0, 2)]
    _mark_current_column(columns)
    assert not any(c.role == "CURRENT" for c in columns)


# ---------------------------------------------------------------------------
# Fiscal year labelling
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "period_end,expected",
    [
        ("2026-03-31", 2026),   # year ended in March belongs to that year
        ("2026-06-30", 2027),   # June onward belongs to the following FY
        ("2025-12-31", 2026),
        ("2025-09-30", 2026),
        ("2025-04-01", 2026),
    ],
)
def test_fiscal_year_follows_the_april_to_march_year(period_end, expected):
    assert _fiscal_year(period_end) == expected


def test_fiscal_year_of_an_unparseable_date_is_unknown():
    assert _fiscal_year("not a date") is None


# ---------------------------------------------------------------------------
# Period duration is only claimed when the header supports it
# ---------------------------------------------------------------------------
def test_a_damaged_header_does_not_become_a_cumulative_claim():
    """An unreadable header means the duration is unknown, not annual.

    Marking every statement ``cumulative=True`` asserted that the figures
    cover the year to date, which is false for a three-month column. Nothing in
    the header survived to contradict it, so the claim has to be withheld too.
    """
    column = Column(index=0, centre=280.0, x0=250.0, x1=280.0,
                    header_text="FOR RESULTS", cell_count=31)
    assert _period_kind(column, "income_statement") == ("UNSPECIFIED", False)


def test_a_quarter_header_is_recognised():
    column = Column(index=0, centre=280.0, x0=250.0, x1=280.0,
                    header_text="ENDED QUARTER Ended", cell_count=31)
    assert _period_kind(column, "income_statement") == ("QUARTERLY", False)


def test_a_year_ended_header_is_the_only_cumulative_claim():
    column = Column(index=0, centre=280.0, x0=250.0, x1=280.0,
                    header_text="Year ended 31st March, 2026", cell_count=31)
    assert _period_kind(column, "income_statement") == ("ANNUAL", True)


def test_a_balance_sheet_is_a_point_in_time_and_never_cumulative():
    """A balance sheet is a snapshot, so a cumulative flag is meaningless."""
    column = Column(index=0, centre=280.0, x0=250.0, x1=280.0,
                    header_text="As at 31st March", cell_count=40)
    assert _period_kind(column, "balance_sheet") == ("POINT_IN_TIME", False)


def test_the_filing_quarter_does_not_decide_the_column_duration():
    """A Q4 filing's first column is the three-month column, not the year.

    Reliance's FY2026 annual filing opens its standalone P&L with the Q4
    three-month column (125,741 crore) and puts the full year in a later one, so
    inferring the duration from the filing's fiscal quarter would have labelled
    a quarter's figures as a year's.
    """
    column = Column(index=0, centre=323.0, x0=300.0, x1=323.0,
                    header_text="Ended Quarter", cell_count=29)
    period_type, cumulative = _period_kind(column, "income_statement")
    assert (period_type, cumulative) != ("ANNUAL", True)


# ---------------------------------------------------------------------------
# Footnote reference columns are not the current period
# ---------------------------------------------------------------------------
def _note_column_rows() -> list[Row]:
    """Bajaj Finance's consolidated P&L: a footnote list, then four periods."""
    notes = [1, 2, 3, 7, 9, 11, 12, 13]
    rows: list[Row] = []
    for index, note in enumerate(notes):
        rows.append(Row(
            top=float(index),
            label=f"Line item {note}",
            cells=[NumberCell(raw=str(note), value=float(note), x0=54.0,
                             x1=62.0, column=0)],
        ))
    for column in (1, 2, 3, 4):
        for index in range(30):
            rows.append(Row(
                top=float(index),
                label=f"Line item {index}",
                cells=[NumberCell(raw="1,000.00", value=1000.0,
                                  x0=300.0 + column * 10.0,
                                  x1=320.0 + column * 10.0, column=column)],
            ))
    return rows


def test_a_footnote_list_is_stepped_over_to_reach_the_period():
    """The leftmost column is note references, so the period column is next.

    Bank and NBFC statements print an ascending list of footnote numbers beside
    the caption. Those numbers are dense enough to clear the share-of-busiest
    test and sit furthest left, so they were being marked as the current period.
    Bajaj Finance's consolidated P&L ran 1, 2, 3, 7, 9, 11, 12, 13 down the
    page, and every line of the statement went unread as a result.
    """
    rows = _note_column_rows()
    columns = [
        Column(index=0, centre=58.0, x0=54.0, x1=62.0, cell_count=8),
        Column(index=1, centre=340.0, x0=310.0, x1=370.0, cell_count=30),
        Column(index=2, centre=350.0, x0=320.0, x1=380.0, cell_count=30),
        Column(index=3, centre=360.0, x0=330.0, x1=390.0, cell_count=30),
        Column(index=4, centre=370.0, x0=340.0, x1=400.0, cell_count=30),
    ]
    _mark_current_column(columns, rows)
    marked = [c.index for c in columns if c.role == "CURRENT"]
    assert marked == [1]


def test_a_rising_run_of_small_integers_in_a_data_column_is_still_a_period():
    """Only a footnote list is stepped over, not a column of real figures.

    The rule must stay narrow: money climbs monotonically down a statement
    essentially never, but a column that only passes because its figures happen
    to be small integers is still the period being reported.
    """
    rows = [
        Row(top=float(i), label=f"Line {i}",
            cells=[NumberCell(raw=str(v), value=float(v), x0=300.0, x1=340.0,
                              column=0)])
        for i, v in enumerate((5.5, 12.25, 40.0, 99.75, 123.5), start=1)
    ]
    columns = [Column(index=0, centre=320.0, x0=300.0, x1=340.0, cell_count=5)]
    _mark_current_column(columns, rows)
    assert [c.index for c in columns if c.role == "CURRENT"] == [0]
