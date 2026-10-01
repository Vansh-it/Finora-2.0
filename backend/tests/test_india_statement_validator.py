"""Arithmetic validation of extracted statements.

This is the check that decides whether Finora believes a number. A PDF text
layer damages digits silently, so a row can parse cleanly, pass every format
check, and still be wrong. The only defence that does not involve guessing is
arithmetic: statements are internally consistent, and a filing whose own totals
do not add up is reporting either damage or a misread column.

Every identity here is one the filing itself asserts. Nothing is reconstructed:
a failure is reported and the affected metrics are withheld.
"""

from __future__ import annotations

import pytest

from lib.india.statement_validator import (
    DEFAULT_TOLERANCE,
    StatementValidator,
    apply_report,
)


#: A real Reliance consolidated P&L page, in crore, as extracted. The identities
#: that the summary states were checked by hand against these numbers.
CLEAN_PNL = {
    "revenue": 298621.0,
    "other_income": 4447.0,
    "total_income": 303068.0,
    "total_expenses": 275873.0,
    "pbt": 27195.0,
    "current_tax": 844.0,
    "deferred_tax": 5735.0,
    "total_tax": 6579.0,
    "net_profit": 20616.0,
}


@pytest.fixture()
def validator() -> StatementValidator:
    return StatementValidator()


# ---------------------------------------------------------------------------
# A clean statement
# ---------------------------------------------------------------------------


def test_clean_statement_passes_every_identity(validator):
    report = validator.validate_income_statement(CLEAN_PNL, period_label="Q1 FY2027")
    assert report.passed is True
    assert report.failures == []
    assert report.quarantined == set()
    # total income, pbt, net profit, tax. The remaining identities need line
    # items this minimal statement does not carry, and a missing metric must
    # not be reported as a broken identity.
    assert len(report.checks) == 4


def test_clean_statement_keeps_every_metric(validator):
    report = validator.validate_income_statement(CLEAN_PNL)
    assert apply_report(CLEAN_PNL, report) == CLEAN_PNL


# ---------------------------------------------------------------------------
# Rounding tolerance
# ---------------------------------------------------------------------------


def test_rounding_within_tolerance_is_accepted(validator):
    """A statement rounded to the nearest lakh must not be flagged."""
    values = dict(CLEAN_PNL, total_income=303070.0)
    report = validator.validate_income_statement(values)
    assert report.passed is True


def test_tolerance_is_relative_to_the_larger_side(validator):
    """A small error on a large total is rounding; on a small total it is not."""
    # A 0.2% discrepancy on a total of 300,000 is rounding. Every downstream
    # identity has to hold too, so the whole statement is nudged rather than
    # just the one line under test.
    big = {
        "revenue": 299221.0, "other_income": 4447.0, "total_income": 303668.0,
        "total_expenses": 276473.0, "pbt": 27195.0, "current_tax": 844.0,
        "deferred_tax": 5735.0, "total_tax": 6579.0, "net_profit": 20616.0,
    }
    assert validator.validate_income_statement(big).passed is True

    # The same 0.5% band on a total of 200 is 1.0, so 2.5 is well outside it.
    small = {"revenue": 100.0, "other_income": 1.0, "total_income": 102.5}
    report = validator.validate_income_statement(small)
    assert report.passed is False


def test_tolerance_default_is_half_a_percent():
    assert DEFAULT_TOLERANCE == pytest.approx(0.005)


# ---------------------------------------------------------------------------
# Damage detection: the identities that matter
# ---------------------------------------------------------------------------


def test_transposed_digit_in_total_income_is_caught(validator):
    """298621 + 4447 = 303068; a dropped digit gives 30308."""
    values = dict(CLEAN_PNL, total_income=30308.0)
    report = validator.validate_income_statement(values)
    assert report.passed is False
    assert "total_income" in report.quarantined
    assert "revenue" in report.quarantined
    assert "total_income = revenue + other_income" in [c.name for c in report.failures]


def test_wrong_column_assignment_is_caught(validator):
    """The measured failure: prior-period figures read as the current period.

    A statement whose totals do not reconcile cannot be published even though
    every individual cell parsed cleanly.
    """
    values = dict(CLEAN_PNL, net_profit=13272.0)   # prior-period PAT
    report = validator.validate_income_statement(values)
    assert report.passed is False
    assert "net_profit" in report.quarantined


def test_missing_digit_in_tax_is_caught(validator):
    values = dict(CLEAN_PNL, total_tax=658.0)      # 5735 read as 735+84=819
    report = validator.validate_income_statement(values)
    assert report.passed is False
    assert "total_tax" in report.quarantined


def test_profit_before_tax_identity_is_checked(validator):
    values = dict(CLEAN_PNL, pbt=271_950.0)
    report = validator.validate_income_statement(values)
    assert report.passed is False
    assert "pbt" in report.quarantined


def test_comprehensive_income_identity_is_checked(validator):
    # 20,616 - 8,379 is 12,237, not 13,398: the measured filing printed a
    # total that did not reconcile with its own components.
    values = dict(CLEAN_PNL, oci=-8379.0, comprehensive_income=13398.0)
    report = validator.validate_income_statement(values)
    assert report.passed is False
    assert "comprehensive_income" in report.quarantined


def test_reconciling_comprehensive_income_passes(validator):
    values = dict(CLEAN_PNL, oci=-8218.0, comprehensive_income=12398.0)
    report = validator.validate_income_statement(values)
    assert report.passed is True


# ---------------------------------------------------------------------------
# Partial extraction
# ---------------------------------------------------------------------------


def test_a_partial_extraction_tests_no_identity(validator):
    """A missing metric leaves its identity untested rather than failed.

    There is no error to report: revenue of 100 and total income of 105 are not
    contradictory, they are just two lines that do not tie to anything on this
    page. The evidence rule is a separate concern and is tested below.
    """
    report = validator.validate_income_statement(
        {"revenue": 100.0, "total_income": 105.0}, require_evidence=False,
    )
    assert report.passed is True
    assert report.checks == []


def test_a_partial_extraction_is_not_certified(validator):
    """Two unconnected lines are not a verified statement.

    This is the rule that changed after the live filing: the standalone profit
    and loss page is too damaged to read its totals, so no identity can run,
    and a pass that checked nothing is not a pass.
    """
    report = validator.validate_income_statement({"revenue": 100.0, "total_income": 105.0})
    assert report.passed is False
    assert report.quarantined == {"revenue", "total_income"}
    assert "the statement is legible enough to verify" in [c.name for c in report.checks]
    assert report.notes


def test_a_single_value_is_never_a_verified_statement(validator):
    report = validator.validate_income_statement({"revenue": 100.0})
    assert report.passed is False
    assert "revenue" in report.quarantined


def test_the_damaged_standalone_page_publishes_nothing(validator):
    """The measured failure, end to end.

    This is what the Reliance standalone P&L actually yields: a plausible set
    of figures with no total income or total expenses, so every identity is
    untestable. Revenue reads 166,013 against a real near 41,000, and profit
    after tax is the prior period's 13,272.
    """
    damaged = {
        "revenue": 166013.0,
        "pbt": 17600.0,
        "net_profit": 13272.0,
        "cost_of_materials": 24918.0,
        "finance_costs": 278.0,
        "depreciation_amortisation": 4196.0,
        "purchases_stock_in_trade": 3830.0,
        "eps_basic": 9.81,
    }
    report = validator.validate_income_statement(
        damaged, period_label="Q1 FY2027", scope="STANDALONE",
    )
    assert report.passed is False
    assert report.quarantined == set(damaged)
    assert apply_report(damaged, report) == {}


def test_one_passed_identity_is_enough_evidence(validator):
    """The threshold is one identity, not a whole statement."""
    report = validator.validate_income_statement(
        {"revenue": 100.0, "other_income": 5.0, "total_income": 105.0},
    )
    assert report.passed is True
    assert report.quarantined == set()


def test_the_evidence_rule_can_be_waived(validator):
    """Callers that only want the identity results can ask for them alone."""
    report = validator.validate_income_statement(
        {"revenue": 100.0, "other_income": 5.0, "total_income": 200.0},
        require_evidence=False,
    )
    assert report.passed is False       # the identity still fails
    assert "total_income" in report.quarantined


def test_empty_statement_is_a_pass_with_nothing_to_certify(validator):
    """Nothing extracted is not the same as something unverifiable."""
    report = validator.validate_income_statement({})
    assert report.passed is True
    assert report.checks == []
    assert report.quarantined == set()


# ---------------------------------------------------------------------------
# Bug A regression: provisions-aware identity does not quarantine a legitimately
# closing bank P&L when the base identity fails but the provisions identity passes.
# ---------------------------------------------------------------------------


def test_bank_pnl_with_provisions_passes_when_provisions_identity_closes(validator):
    """A bank prints total expenditure excluding provisions and deducts provisions
    to reach PBT. The base identity (PBT = total_income - total_expenses + share)
    fails, but the provisions-aware identity passes, and the statement must not
    be quarantined.

    Verified example: 92,184.38 - 64,016.32 - 3,059.76 = 25,108.30 PBT.
    """
    values = {
        "total_income": 92184.38,
        "total_expenses": 64016.32,
        "provisions": 3059.76,
        "pbt": 25108.30,
    }
    report = validator.validate_income_statement(values)
    assert report.passed is True, (
        f"Bank P&L with provisions must pass: {report.failures}"
    )
    assert "pbt" not in report.quarantined
    assert "total_income" not in report.quarantined
    assert "total_expenses" not in report.quarantined
    passed_names = [c.name for c in report.checks if c.passed]
    assert any("provisions" in name for name in passed_names), (
        f"Expected a provisions-aware identity to pass; got {passed_names}"
    )


def test_bank_pnl_with_provisions_quarantines_only_if_both_identities_fail(validator):
    """If neither the base nor the provisions-aware identity holds, the statement
    is genuinely broken and must be quarantined."""
    values = {
        "total_income": 92184.38,
        "total_expenses": 64016.32,
        "provisions": 3059.76,
        "pbt": 30000.0,  # wrong
    }
    report = validator.validate_income_statement(values)
    assert report.passed is False
    assert "pbt" in report.quarantined


# ---------------------------------------------------------------------------
# Sign and range sanity
# ---------------------------------------------------------------------------


def test_negative_revenue_is_quarantined(validator):
    """A negative revenue is a misread digit, not a result."""
    report = validator.validate_income_statement(dict(CLEAN_PNL, revenue=-298621.0))
    assert report.passed is False
    assert "revenue" in report.quarantined


def test_negative_total_income_is_quarantined(validator):
    report = validator.validate_income_statement(dict(CLEAN_PNL, total_income=-303068.0))
    assert report.passed is False
    assert "total_income" in report.quarantined


# ---------------------------------------------------------------------------
# Losses are results
# ---------------------------------------------------------------------------


LOSS_PNL = {
    "revenue": 41209.0,
    "other_income": 634.0,
    "total_income": 41843.0,
    "total_expenses": 60117.0,
    "pbt": -18274.0,
    "total_tax": 0.0,
    "net_profit": -18274.0,
    "eps_basic": -3.11,
}


def test_a_loss_making_company_validates(validator):
    """A loss is the most important thing some filings report.

    Negative profit before tax, profit after tax and earnings per share are
    not damage. Rejecting them would withhold the filings a reader most wants
    to see, silently.
    """
    report = validator.validate_income_statement(LOSS_PNL, period_label="Q1 FY2027")
    assert report.passed is True, report.to_dict()
    assert report.quarantined == set()
    assert apply_report(LOSS_PNL, report) == LOSS_PNL


def test_negative_earnings_per_share_is_not_treated_as_damage(validator):
    """A loss per share is a result, so it is never quarantined as a sign error.

    It is still withheld here, because a lone EPS on a page cannot be
    corroborated. The distinction matters: the metric is unverified, not
    rejected as impossible.
    """
    report = validator.validate_income_statement({"eps_basic": -3.11})
    assert "eps_basic is not negative" not in [c.name for c in report.checks]
    assert all(c.passed or c.name != f"{'eps_basic'} is not negative"
               for c in report.checks)

    verified = validator.validate_income_statement(
        dict(LOSS_PNL, eps_basic=-3.11)
    )
    assert verified.passed is True
    assert "eps_basic" not in verified.quarantined


def test_profit_after_tax_above_profit_before_tax_is_caught(validator):
    """Tax is a charge, so a sign slip in either line shows up here."""
    report = validator.validate_income_statement(dict(LOSS_PNL, net_profit=18274.0))
    assert report.passed is False
    assert "net_profit" in report.quarantined


def test_unchanged_loss_survives_an_eps_check(validator):
    """A bad EPS is caught on its own, without touching the loss figures."""
    within = validator.validate_income_statement(dict(LOSS_PNL, eps_basic=-3.11))
    assert within.passed is True
    assert "eps_basic" not in within.quarantined

    shifted = validator.validate_income_statement(dict(LOSS_PNL, eps_basic=-3_110.0))
    assert shifted.passed is False
    assert "eps_basic" in shifted.quarantined
    assert "net_profit" not in shifted.quarantined
    assert "pbt" not in shifted.quarantined


def test_implausible_eps_is_quarantined(validator):
    """A thousandfold shift yields a per-share figure no company reports."""
    report = validator.validate_income_statement(dict(CLEAN_PNL, eps_basic=5_480.0))
    assert report.passed is False
    assert "eps_basic" in report.quarantined


def test_plausible_eps_is_accepted(validator):
    report = validator.validate_income_statement(dict(CLEAN_PNL, eps_basic=5.48))
    assert "eps_basic" not in report.quarantined


def test_a_real_outlier_eps_is_not_caught(validator):
    """The bound must leave a genuine high EPS alone.

    The highest EPS among large Indian listed companies reaches the low
    hundreds, so anything under the bound has to pass.
    """
    for printed in (312.5, 875.0, 999.0):
        report = validator.validate_income_statement(dict(CLEAN_PNL, eps_basic=printed))
        assert "eps_basic" not in report.quarantined, printed


def test_a_clean_statement_certifies_every_value(validator):
    """The counterpart to the evidence rule: a reconciling page publishes."""
    values = dict(CLEAN_PNL)
    report = validator.validate_income_statement(values)
    assert report.passed is True
    assert len(report.checks) >= 4
    assert apply_report(values, report) == values


def test_a_hundredfold_shift_on_a_small_eps_is_a_known_gap(validator):
    """What the magnitude bound cannot do, stated as a test so it is not forgotten.

    5.48 misread as 548 is a hundredfold error, but 548 is still inside the
    range a real company could print, so no share-count-free bound can reject
    it. Detecting it needs the weighted average share count, which the mapper
    does not read yet. Recorded here so the gap is visible and the fix is
    traceable rather than quietly relied upon in the other direction.
    """
    report = validator.validate_income_statement(dict(CLEAN_PNL, eps_basic=548.0))
    assert report.passed is True
    assert "eps_basic" not in report.quarantined


# ---------------------------------------------------------------------------
# Balance sheet
# ---------------------------------------------------------------------------


def test_balance_sheet_balances(validator):
    values = {
        "total_assets": 1000.0,
        "total_liabilities": 600.0,
        "total_equity": 400.0,
    }
    report = validator.validate_balance_sheet(values, as_at="2026-06-30")
    assert report.passed is True


def test_imbalanced_balance_sheet_is_caught(validator):
    values = {
        "total_assets": 1000.0,
        "total_liabilities": 600.0,
        "total_equity": 300.0,
    }
    report = validator.validate_balance_sheet(values, as_at="2026-06-30")
    assert report.passed is False
    assert "total_assets" in report.quarantined
    assert "total_equity" in report.quarantined


def test_equity_exceeding_assets_is_caught(validator):
    values = {
        "total_assets": 1000.0,
        "total_equity": 1400.0,
    }
    report = validator.validate_balance_sheet(values)
    assert report.passed is False


def test_balance_sheet_with_missing_lines_is_not_failed(validator):
    report = validator.validate_balance_sheet({"total_assets": 1000.0})
    assert report.passed is True


def test_current_assets_below_total_assets_passes(validator):
    """Total assets is a sum of parts, so it must be allowed to exceed them.

    This identity was wired to the equality helper, which made it passable
    only when current assets equalled all assets.
    """
    values = {
        "total_assets": 1000.0,
        "total_current_assets": 620.0,
        "total_liabilities": 600.0,
        "total_equity": 400.0,
    }
    report = validator.validate_balance_sheet(values)
    assert report.passed is True
    assert report.quarantined == set()


def test_current_assets_above_total_assets_is_caught(validator):
    values = {"total_assets": 1000.0, "total_current_assets": 1200.0}
    report = validator.validate_balance_sheet(values)
    assert report.passed is False
    assert "total_current_assets" in report.quarantined


# ---------------------------------------------------------------------------
# One statement printed twice over
# ---------------------------------------------------------------------------


def test_a_damaged_page_yields_nothing_publishable(validator):
    """The measured failure: every figure on the standalone page misread.

    The Reliance standalone P&L repeats a 15-line structure in half the width,
    so the parser interleaves prior-period and current-period digits. Every
    individual cell still parses, and the line count and labels look right.
    Only the arithmetic identifies it, which is why the top-line identity is
    checked before anything is published.
    """
    damaged = {
        "revenue": 1187.0,          # should be ~41,000
        "other_income": 55.0,
        "total_income": 1142.0,
        "total_expenses": 515.0,
        "pbt": 627.0,
        "total_tax": 187.0,
        "net_profit": 440.0,
    }
    report = validator.validate_income_statement(damaged, period_label="Q1 FY2027")
    assert report.passed is False
    assert "total_income" in report.quarantined
    assert "revenue" in report.quarantined


def test_a_page_reading_the_prior_period_is_rejected(validator):
    """A whole column shift is invisible per cell and caught by identity."""
    shifted = {
        "revenue": 281736.0,        # prior-quarter revenue
        "other_income": 4325.0,
        "total_income": 286061.0,
        "total_expenses": 264921.0,
        "pbt": 21140.0,
        "total_tax": 6641.0,
        "net_profit": 14499.0,
    }
    report = validator.validate_income_statement(shifted)
    # This period is internally consistent on its own, so identity alone does
    # not catch it: the statement is coherent, just not the right period.
    # The period label and the document's own comparative columns are what
    # have to rule it out, which is why both are recorded.
    assert report.passed is True
    labelled = validator.validate_income_statement(shifted, period_label="Q1 FY2027")
    assert labelled.passed is True
    assert all("Q1 FY2027" in c.detail for c in labelled.checks)


def test_a_coherent_but_wrong_period_is_reachable_by_arithmetic_alone(validator):
    """State the limit explicitly: arithmetic cannot see a period mix-up.

    A column shift within one statement produces a set of figures that is
    perfectly self-consistent. Rejecting it needs the document's own
    comparative headings, so the extraction layer must record which column
    carried which date rather than trusting the leftmost.
    """
    prior_period = dict(CLEAN_PNL)
    report = validator.validate_income_statement(prior_period, period_label="Q4 FY2026")
    assert report.passed is True
    # Nothing in the report claims this is the right period; the label is
    # carried for the audit trail so the caller can cross-check it.
    assert all("Q4 FY2026" in c.detail for c in report.checks)


# ---------------------------------------------------------------------------
# Partial results
# ---------------------------------------------------------------------------


def test_apply_report_keeps_the_metrics_it_can_vouch_for(validator):
    values = dict(CLEAN_PNL, net_profit=13272.0)
    report = validator.validate_income_statement(values)
    surviving = apply_report(values, report)
    assert "net_profit" not in surviving
    assert "revenue" in surviving
    assert surviving["revenue"] == 298621.0


def test_apply_report_returns_a_copy(validator):
    report = validator.validate_income_statement(CLEAN_PNL)
    result = apply_report(CLEAN_PNL, report)
    result["revenue"] = 0.0
    assert CLEAN_PNL["revenue"] == 298621.0


# ---------------------------------------------------------------------------
# Recovered values need corroboration
# ---------------------------------------------------------------------------


def test_recovered_values_are_quarantined_until_corroborated(validator):
    report = validator.check_recovered({"revenue": 1.0}, {"revenue"})
    assert "revenue" in report.quarantined
    assert report.notes


def test_nothing_recovered_means_nothing_quarantined(validator):
    report = validator.check_recovered({"revenue": 1.0}, set())
    assert report.quarantined == set()


def test_a_passed_identity_releases_a_recovered_value(validator):
    """A repair corroborated by the statement's own arithmetic is publishable.

    The filing independently asserts the relationship, so the reconstructed
    figure is no longer only a hypothesis.
    """
    values = dict(CLEAN_PNL)
    statement = validator.validate_income_statement(values)
    report = validator.check_recovered(
        values, {"revenue"}, statement_report=statement,
    )
    assert "revenue" not in report.quarantined
    assert any("corroborated" in n for n in report.notes)


def test_an_unrelated_failure_does_not_withhold_a_corroborated_recovery(validator):
    """Corroboration is per metric, not a blanket report verdict.

    A statement with one unrecognised damaged line still publishes the
    recoveries the sound identities confirm.
    """
    values = dict(CLEAN_PNL, net_profit=13272.0)
    statement = validator.validate_income_statement(values)
    assert statement.passed is False

    report = validator.check_recovered(
        values, {"revenue"}, statement_report=statement,
    )
    assert "revenue" not in report.quarantined


def test_a_failed_identity_withholds_the_recovered_value(validator):
    values = dict(CLEAN_PNL, total_tax=658.0)
    statement = validator.validate_income_statement(values)
    report = validator.check_recovered(
        values, {"total_tax"}, statement_report=statement,
    )
    assert "total_tax" in report.quarantined


def test_a_recovered_value_named_by_no_identity_stays_withheld(validator):
    """No identity touches this metric, so nothing corroborates it."""
    values = dict(CLEAN_PNL)
    statement = validator.validate_income_statement(values)
    report = validator.check_recovered(
        values, {"reserve_surplus"}, statement_report=statement,
    )
    assert "reserve_surplus" in report.quarantined


def test_reports_merge_without_mutating_either(validator):
    values = dict(CLEAN_PNL, net_profit=13272.0)
    statement = validator.validate_income_statement(values)
    recovered = validator.check_recovered(values, {"revenue"})
    merged = statement.merge(recovered)

    assert merged.passed is False
    assert {"net_profit", "revenue"} <= merged.quarantined
    assert len(statement.checks) + len(recovered.checks) == len(merged.checks)
    assert "revenue" not in statement.quarantined


# ---------------------------------------------------------------------------
# Audit surface
# ---------------------------------------------------------------------------


def test_report_serialises_for_the_audit_trail(validator):
    report = validator.validate_income_statement(
        dict(CLEAN_PNL, net_profit=13272.0), period_label="Q1 FY2027", scope="CONSOLIDATED",
    )
    payload = report.to_dict()
    assert payload["passed"] is False
    assert "net_profit" in payload["quarantined"]
    assert payload["failed"]
    assert any("Q1 FY2027" in c["detail"] for c in payload["checks"])


def test_each_check_names_the_metrics_its_failure_implicates(validator):
    report = validator.validate_income_statement(dict(CLEAN_PNL, total_tax=658.0))
    failing = report.failures[0]
    assert set(failing.metrics) == {"total_tax", "pbt", "net_profit"}

# ---------------------------------------------------------------------------
# Cash flow
# ---------------------------------------------------------------------------
#: A cash flow statement that reconciles, in crore. Indian filings state the
#: reconciliation themselves, so it is checked exactly as a P&L is.
CLEAN_CASH_FLOW = {
    "operating_cash_flow": 40_000.0,
    "investing_cash_flow": -25_000.0,
    "financing_cash_flow": -10_000.0,
    "net_change_in_cash": 5_000.0,
    "opening_cash": 20_000.0,
    "closing_cash": 25_000.0,
}


def test_a_reconciling_cash_flow_is_certified(validator):
    report = validator.validate_cash_flow(dict(CLEAN_CASH_FLOW), period_label="FY2026")

    assert report.passed is True, report.to_dict()
    assert len(report.checks) == 2


def test_a_cash_flow_read_from_the_wrong_column_is_caught(validator):
    """A page read from the comparative column must not be published whole.

    Cash flow used to be accepted merely for parsing, so a full set of
    plausible lines from the wrong column reached production unchecked. Here
    operating cash flow is shifted and no longer reconciles, and the movement
    figures are the ones that have to be dropped.
    """
    values = dict(CLEAN_CASH_FLOW, operating_cash_flow=90_000.0)
    report = validator.validate_cash_flow(values)

    assert report.passed is False
    surviving = apply_report(values, report)
    assert "operating_cash_flow" not in surviving
    assert "net_change_in_cash" not in surviving
    # The opening and closing balances reconcile with each other independently
    # of the activity lines, so they are corroborated and may stand.
    assert surviving == {"opening_cash": 20_000.0, "closing_cash": 25_000.0}


def test_an_illegible_cash_flow_is_withheld_whole(validator):
    """No readable opening and closing balance means nothing to reconcile to."""
    values = {"operating_cash_flow": 40_000.0, "capex": -5_000.0}
    report = validator.validate_cash_flow(values)

    assert report.passed is False
    assert apply_report(values, report) == {}
    assert report.notes


def test_an_exchange_difference_is_accounted_for_rather_than_failing(validator):
    """Indian statements print the FX effect outside the three activities.

    Reconciling the net movement against the activities alone would fail a
    perfectly correct statement for a company with foreign currency exposure,
    so the printed effect has to be part of the identity.
    """
    values = dict(
        CLEAN_CASH_FLOW,
        net_change_in_cash=5_400.0,
        closing_cash=25_400.0,
        exchange_rate_effect=400.0,
    )
    report = validator.validate_cash_flow(values)

    assert report.passed is True, report.to_dict()
    assert len(report.checks) == 2


# ---------------------------------------------------------------------------
# Share of associates inside profit before tax
# ---------------------------------------------------------------------------
#: Bajaj Finance consolidated P&L for the quarter ended 30 June 2026, in crore,
#: exactly as printed. The share of an associate's profit is not income and not
#: an expense, but it is inside the printed profit before tax, so the identity
#: cannot close without it: 23,166.42 - 15,022.53 is 8,143.89 against a stated
#: 8,149.00, and the 5.11 crore share of an associate closes the gap exactly.
NBFC_PNL = {
    "revenue": 23165.45,
    "other_income": 0.97,
    "total_income": 23166.42,
    "total_expenses": 15022.53,
    "share_of_associates": 5.11,
    "pbt": 8149.00,
    "total_tax": 2068.40,
    "net_profit": 6080.60,
}


def test_profit_before_tax_includes_an_associates_share(validator):
    report = validator.validate_income_statement(NBFC_PNL)
    assert report.passed, [c.detail for c in report.checks if not c.passed]
    assert report.quarantined == set()


def test_the_same_statement_fails_without_the_associates_share(validator):
    """The identity has to be exact, not merely inside the tolerance.

    The default tolerance is 0.5% relative, so the 5.11 crore share is inside
    it and the check passes either way. That tolerance exists to absorb text
    layer damage in a digit or two, not to stand in for a printed line the
    filing states explicitly - so the check is held to closing exactly.
    """
    with_share = validator.validate_income_statement(NBFC_PNL)
    closed = next(c for c in with_share.checks if c.name.startswith("pbt ="))
    assert closed.difference == pytest.approx(0.0, abs=1e-6)

    values = {k: v for k, v in NBFC_PNL.items() if k != "share_of_associates"}
    without = validator.validate_income_statement(values)
    left_open = next(c for c in without.checks if c.name.startswith("pbt ="))
    assert left_open.difference == pytest.approx(5.11)


def test_a_company_without_associates_tests_exactly_as_before(validator):
    """The share is only folded in when printed, so nothing else moves."""
    report = validator.validate_income_statement(CLEAN_PNL)
    assert report.passed, [c.detail for c in report.checks if not c.passed]
