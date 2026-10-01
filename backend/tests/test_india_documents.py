"""Classification and period inference for Indian exchange filings.

The regression these tests exist for: every quarterly results announcement was
being filed as ``AUDITED_FINANCIALS`` because the substring ``audited`` occurs
inside ``unaudited``, so the classifier's first rule matched the word it meant
to exclude. Audit status is carried separately by the taxonomy; the document
kind names the period the filing reports.
"""

from __future__ import annotations

from datetime import date

import pytest

from lib.india.documents import (
    DocumentKind,
    classify,
    detect_period_end,
    detect_quarter,
    fiscal_year_for_period,
    infer_period_end,
    _doc_from_record,
)


# ---------------------------------------------------------------------------
# Audit status must not be read out of "unaudited"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Unaudited Financial Results for the quarter ended June 30, 2026",
        "Unaudited Consolidated Financial Results for the Quarter ended 30th June 2026",
        "Unaudited Financial Results",
        "Un-Audited Financial Results",
        "Un_Audited Financial Results",
        "UNAUDITED STANDALONE FINANCIAL RESULTS FOR THE QUARTER ENDED JUNE 2026",
    ],
)
def test_unaudited_results_are_never_called_audited(text):
    kind = classify("Financials", text, None)
    assert kind == DocumentKind.QUARTERLY_RESULT, (
        f"{text!r} was classified {kind}; the word 'unaudited' must not "
        "satisfy the audited-results rule"
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Audited Financial Results for the year ended March 31, 2026",
         DocumentKind.ANNUAL_RESULT),
        ("Statement of Audited Consolidated Financial Results",
         DocumentKind.AUDITED_FINANCIALS),
        ("Annual Report 2025-26", DocumentKind.ANNUAL_REPORT),
        ("Financial Results for the year ended 31st March 2026",
         DocumentKind.ANNUAL_RESULT),
        ("Quarterly Results for the quarter ended June 30, 2026",
         DocumentKind.QUARTERLY_RESULT),
    ],
)
def test_period_specific_kinds_win_over_audit_wording(text, expected):
    assert classify("Financials", text, None) == expected


def test_audited_rule_still_fires_on_genuinely_audited_text():
    """The guard must not disable the rule it was meant to protect."""
    assert classify("Financials", "Audited Financial Results", None) == \
        DocumentKind.AUDITED_FINANCIALS


def test_non_financial_documents_are_unaffected():
    assert classify("Shareholding", "Shareholding Pattern as on 30-Jun-2026", None) == \
        DocumentKind.SHAREHOLDING
    assert classify("Board Meeting", "Outcome of Board Meeting", None) == \
        DocumentKind.BOARD_MEETING


# ---------------------------------------------------------------------------
# Indian fiscal periods
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Unaudited Financial Results for the quarter ended December 31, 2025",
         "2025-12-31"),
        ("Financial Results for the quarter ended 31st January, 2026", "2026-01-31"),
        ("Unaudited Financial Results for the quarter ended June 30, 2026",
         "2026-06-30"),
        ("Audited Financial Results for the year ended March 31, 2026",
         "2026-03-31"),
        ("Unaudited Financial Results for the quarter ended 30th September 2025",
         "2025-09-30"),
    ],
)
def test_explicit_period_end_is_read_from_prose(text, expected):
    assert detect_period_end(text) == expected


@pytest.mark.parametrize(
    "text",
    ["Audited Financial Results", "Financial Results", "", "Notice of Board Meeting"],
)
def test_prose_without_a_date_yields_no_period(text):
    assert detect_period_end(text) == ""


@pytest.mark.parametrize(
    "filed, expected",
    [
        # A filing published in January or February describes the December
        # quarter of the previous fiscal year.
        (date(2026, 1, 14), "2025-12-31"),
        (date(2026, 2, 10), "2025-12-31"),
        # A July filing describes the June quarter.
        (date(2026, 7, 17), "2026-06-30"),
        # A May filing describes the March full year.
        (date(2026, 5, 21), "2026-03-31"),
    ],
)
def test_period_end_inferred_from_filing_month(filed, expected):
    assert infer_period_end(filed, DocumentKind.QUARTERLY_RESULT) == expected


@pytest.mark.parametrize(
    "period_end, expected_fy",
    [
        # The fiscal year is named for the year the period ends in, so a June
        # 2026 quarter belongs to FY2027, not FY2026.
        ("2026-03-31", 2026),
        ("2026-06-30", 2027),
        ("2025-12-31", 2026),
        ("2025-09-30", 2026),
    ],
)
def test_fiscal_year_is_named_for_the_ending_year(period_end, expected_fy):
    assert fiscal_year_for_period(period_end) == expected_fy


@pytest.mark.parametrize(
    "period_end, expected_quarter",
    [
        ("2026-03-31", 4),
        ("2026-06-30", 1),
        ("2025-09-30", 2),
        ("2025-12-31", 3),
    ],
)
def test_quarter_follows_the_period_end_month(period_end, expected_quarter):
    assert detect_quarter("", period_end) == expected_quarter


def test_explicit_quarter_wording_beats_the_period_derivation():
    assert detect_quarter("Q3 results", "2026-06-30") == 3


def test_bare_quarter_wording_is_read():
    assert detect_quarter("Q3 FY27 PAT was flat", "2026-06-30") == 3
    assert detect_quarter("Q1 results", "2025-06-30") == 1


# ---------------------------------------------------------------------------
# A quarter is only an attribute of a period document
# ---------------------------------------------------------------------------


def _filing(text: str, filed: date, category: str = "Financials"):
    """Build a FilingDocument from a synthetic NSE announcement record."""
    record = {
        "symbol": "TEST",
        "desc": category,
        "attchmntText": text,
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/x.pdf",
        "an_dt": f"{filed.isoformat()} 10:00:00",
        "attFileSize": "250000",
        "seq_id": "1",
    }
    return _doc_from_record(record, "TEST")


def test_annual_report_is_not_given_a_derived_quarter():
    """An annual report covering December 2024 is not "Q3"."""
    doc = _filing("Integrated Filing for the year ended December 31, 2024",
                  date(2025, 1, 10))
    assert doc.period_end == "2024-12-31"
    assert doc.quarter is None


def test_annual_result_ending_march_is_q4():
    doc = _filing("Audited Financial Results for the year ended March 31, 2026",
                  date(2026, 4, 24))
    assert doc.kind is DocumentKind.ANNUAL_RESULT
    assert doc.quarter == 4


def test_quarterly_result_keeps_its_quarter():
    doc = _filing("Unaudited Financial Results for the quarter ended June 30, 2026",
                  date(2026, 7, 17))
    assert doc.period_end == "2026-06-30"
    assert doc.quarter == 1
    assert doc.fiscal_year == 2027


def test_non_period_documents_carry_no_quarter():
    for category, text in (
        ("Shareholding", "Shareholding Pattern as on 30-Jun-2026"),
        ("Rating", "Credit Rating- Revision"),
        ("Dividend", "Record Date for Dividend"),
    ):
        doc = _filing(text, date(2026, 7, 1), category=category)
        assert doc.quarter is None, \
            f"{doc.kind} was stamped with quarter {doc.quarter}"


def test_period_kind_classification():
    assert DocumentKind.QUARTERLY_RESULT.is_period_document is True
    assert DocumentKind.ANNUAL_RESULT.is_period_document is True
    assert DocumentKind.ANNUAL_RESULT.is_annual is True
    assert DocumentKind.QUARTERLY_RESULT.is_annual is False
    assert DocumentKind.SHAREHOLDING.is_period_document is False
    assert DocumentKind.AGM.is_annual is False
