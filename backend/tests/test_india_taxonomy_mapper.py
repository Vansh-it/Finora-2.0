"""Taxonomy mapper against real, OCR-damaged filing labels.

Every case here is a label taken from a real NSE results PDF, damaged exactly
as it arrived, or a deliberately confusable pair the mapper must refuse. The
cases exist to pin two things: a damaged label still resolves to the right
metric, and a line that is not a tracked metric resolves to nothing at all.
"""

from __future__ import annotations

import pytest

from lib.india.taxonomy_mapper import (
    FUZZY_FLOOR,
    coverage_report,
    map_rows,
    match_label,
    normalise_label,
)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_total_is_not_a_stopword():
    """"Total Income" and "Other Income" are different metrics."""
    assert normalise_label("Total Income") != normalise_label("Other Income")
    assert "total" in normalise_label("Total Income")


def test_stopwords_are_dropped():
    assert normalise_label("Total Expenses for the period") == \
        normalise_label("Total Expenses")


@pytest.mark.parametrize(
    "damaged, clean",
    [
        ("Olher Income", "Other Income"),
        ("Prollt After Tax", "Profit After Tax"),
        ("Com rehprehensive", "Comprehensive"),
        ("Value of Sales & Setvices", "Value of Sales Services"),
        ("CurrentTax", "Current Tax"),
        ("Excise Duly", "Excise Duty"),
    ],
)
def test_ocr_damage_folds_to_the_clean_form(damaged, clean):
    assert normalise_label(damaged) == normalise_label(clean)


# ---------------------------------------------------------------------------
# Measured labels from a real filing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label, metric_id",
    [
        ("Value of Sales & Setvices (Revenue)", "revenue"),
        ("Revenue from Operations", "revenue"),
        ("Olher Income", "other_income"),
        ("Total Income", "total_income"),
        ("Cost of Materials Consumed", "cost_of_materials"),
        ("Purchases of Stock-in-Trade", "purchases_stock_in_trade"),
        ("Employee Benefits Expense", "employee_benefits"),
        ("Finance Costs", "finance_costs"),
        ("Depreciation / Amortisation and Depletion Expense",
         "depreciation_amortisation"),
        ("Other Expenses", "other_expenses"),
        ("Total Expenses", "total_expenses"),
        ("Profit Before Tax", "pbt"),
        ("CurrentTax", "current_tax"),
        ("Deferred Tax", "deferred_tax"),
        ("Prollt After Tax", "net_profit"),
        ("Total Com rehensive Income for the Period", "comprehensive_income"),
        ("a) Basic (int)", "eps_basic"),
        ("b) Diluted (in t)", "eps_diluted"),
        ("Total Assets", "total_assets"),
        ("Paid-up Share Capital", "share_capital"),
        ("Cash and Cash Equivalents", "cash"),
    ],
)
def test_damaged_label_resolves_to_the_right_metric(label, metric_id):
    match = match_label(label)
    assert match is not None, f"{label!r} did not resolve"
    assert match.metric_id == metric_id


# ---------------------------------------------------------------------------
# Specificity: the ordering of the rule table is the mechanism
# ---------------------------------------------------------------------------


def test_comprehensive_total_beats_other_comprehensive():
    """A grand total must not be reported as its own component."""
    assert match_label("Total Comprehensive Income").metric_id == \
        "comprehensive_income"
    assert match_label("Other Comprehensive Income").metric_id == "oci"


def test_total_income_beats_other_income():
    assert match_label("Total Income").metric_id == "total_income"
    assert match_label("Other Income").metric_id == "other_income"


def test_pbt_is_not_net_profit():
    assert match_label("Profit Before Tax").metric_id == "pbt"
    assert match_label("Profit After Tax").metric_id == "net_profit"


def test_diluted_wins_over_basic_when_a_line_names_both():
    """Indian filings write both on one line; the specific reading must win."""
    assert match_label("Basic and Diluted EPS").metric_id == "eps_diluted"


def test_income_tax_is_the_total_tax_line():
    assert match_label("Income Tax").metric_id == "total_tax"


# ---------------------------------------------------------------------------
# Refusals: the mapper must decline rather than guess
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "Less: GST Recovered",           # netted off before revenue
        "Excise Duly",                   # no concept in the registry
        "a) Owners of the Company",      # an attribution, not a total
        "b) Non-Controlling Interest",
        "I Items Iha! will not be reclassified",
        "II",
        "Page I of",
        "Total",
        "",
        "   ",
    ],
)
def test_untracked_and_non_line_labels_are_refused(label):
    assert match_label(label) is None


def test_segment_rows_are_refused():
    """A segment figure is not the consolidated line of the same name."""
    assert match_label("Segment Results (EBITDA)") is None
    assert match_label("- Oil to Chemicals (O2C)") is None


def test_note_references_are_refused():
    assert match_label("Revenue from Operations (Note 5)") is None


def test_fuzzy_matches_stay_above_the_floor():
    """Anything the mapper accepted by similarity must clear the floor."""
    for label, match in map_rows([
        "Finance Costs", "CurrentTax", "Other Expenses", "Total Income",
    ]).items():
        if match.method == "FUZZY":
            assert match.confidence >= FUZZY_FLOOR


# ---------------------------------------------------------------------------
# Batch behaviour and coverage
# ---------------------------------------------------------------------------


def test_map_rows_keys_by_the_original_label():
    matches = map_rows(["Total Income", "Olher Income", "Total Income"])
    assert set(matches) == {"Total Income", "Olher Income"}
    assert matches["Olher Income"].metric_id == "other_income"


def test_map_rows_matches_prose_labels_unchanged():
    matches = map_rows(["Prollt After Tax"])
    assert "Prollt After Tax" in matches
    assert matches["Prollt After Tax"].matched_text == "profit after tax"


def test_coverage_report_is_explicit_about_shortfalls():
    report = coverage_report([
        "Value of Sales & Setvices (Revenue)", "Total Income", "Excise Duly",
    ])
    assert report["labels"] == 3
    assert report["matched"] == 2
    assert report["coverage"] == pytest.approx(0.667, abs=0.001)
    assert report["by_method"]["RULE"] == 2


def test_coverage_of_an_empty_statement_is_zero():
    report = coverage_report([])
    assert report["coverage"] == 0.0
    assert report["matched"] == 0


def test_every_matched_metric_exists_in_the_registry():
    """A rule must never point at a metric Finora does not define."""
    from lib.metrics.registry import get_registry
    for match in map_rows([
        "Total Income", "Prollt After Tax", "Total Assets", "Paid-up Share Capital",
        "Cash and Cash Equivalents", "a) Basic (int)", "b) Diluted (in t)",
        "Other Equity excluding Revaluation Reserve", "Income Tax",
        "Other Comprehensive Income",
    ]).values():
        assert get_registry().get(match.metric_id) is not None


# ---------------------------------------------------------------------------
# Bajaj Finance: an NBFC consolidated statement of profit and loss
# ---------------------------------------------------------------------------
def _metric_id(label):
    match = match_label(label)
    return match.metric_id if match else None


def test_a_profit_measure_that_mentions_exceptionals_is_not_an_exceptional_item():
    """Bajaj Finance published a phantom exceptional charge equal to its PBT.

    The line "Profit before exceptional items and tax" is a profit measure that
    happens to mention exceptionals; the exceptional item itself is nil. A bare
    "exceptional" rule resolved the profit line to exceptional_items, giving
    8,149 crore of exceptional charges against a printed 8,149 crore of profit
    before tax. The label is refused rather than resolved to anything.
    """
    assert _metric_id("Profit before exceptional items and tax") is None
    assert _metric_id("Profit before exceptional items and tax (1-2+3}") is None


def test_a_line_naming_the_exceptional_item_still_resolves():
    assert _metric_id("Total of exceptional items") == "exceptional_items"


def test_total_revenue_from_operations_is_revenue_not_total_income():
    """The aggregate is the operating revenue, so revenue must be able to hold it.

    A label resolves to exactly one metric, and the generic total rule claimed
    "Total revenue from operations" for total_income first. Revenue was then
    left holding whatever component line matched, and Bajaj Finance published
    revenue of 3.25 crore - "Sale of services" - while the statement printed
    total revenue from operations of 23,165.45 crore.
    """
    assert _metric_id("Total revenue from operations") == "revenue"
    assert _metric_id("Revenue from operations") == "revenue"
    assert _metric_id("Total income") == "total_income"
    assert _metric_id("Total revenue") == "total_income"


def test_only_the_aggregate_of_reserves_is_reserves_and_surplus():
    """A component reserve is not reserves and surplus.

    Bajaj Finance's P&L carries cash flow hedge and cost of hedging reserve
    lines inside other comprehensive income. Reading those as the balance
    sheet's reserves put a -10.60 crore hedging figure on the income statement.
    """
    assert _metric_id("Reserves and Surplus") == "reserves_surplus"
    assert _metric_id("Reserves") == "reserves_surplus"
    assert _metric_id("-Cash flow hedge reserve") is None
    assert _metric_id("-Cost of hedging reserve") is None
    assert _metric_id("General reserve") is None
    assert _metric_id("Capital Redemption Reserve Nil Nil") is None


@pytest.mark.parametrize(
    "label",
    [
        "Share of profit/(loss) from associates",
        "Share of profit from associate",
        "Share of loss in associates",
        "Share of the profit of an associate",
        "Profit on associates",
    ],
)
def test_a_share_of_associates_line_resolves(label):
    """It sits inside printed profit before tax without being income or cost."""
    assert _metric_id(label) == "share_of_associates"


def test_a_share_of_joint_ventures_is_not_a_share_of_associates():
    assert _metric_id("Share of profit from joint ventures") is None


def test_paid_up_share_capital_is_not_a_share_of_associates():
    assert _metric_id("Paid-up equity share capital") is None
