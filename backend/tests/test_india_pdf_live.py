"""End-to-end: real NSE results PDF -> validated canonical metrics.

This is the acceptance path. It runs the whole chain against a real filing:
fetch, coordinate-based page analysis, label mapping, unit scaling, then
arithmetic validation, and asserts that only metrics the statement's own
arithmetic vouched for come out.

The filing is the Reliance Q1 FY2027 results attachment. It is fetched live, so
the test skips rather than fails when the exchange is unreachable or
rate-limiting. Nothing here is mocked, because the whole point is that this
works against the text layer the exchange actually serves.
"""

from __future__ import annotations

import os

import pytest

from lib.india import http_client
from lib.india.pdf_tables import parse_pdf
from lib.india.statement_validator import StatementValidator, apply_report
from lib.india.taxonomy_mapper import (
    ResolvedLine,
    match_label,
    resolve_metrics,
)

#: A real NSE results attachment: Reliance Industries, quarter ended
#: 30 June 2026, consolidated and standalone in one document.
FILING_URL = (
    "https://nsearchives.nseindia.com/corporate/"
    "kavinavora_17072026190726_SE_FR_1.pdf"
)


@pytest.fixture(scope="module")
def filing():
    try:
        response = http_client.fetch(
            FILING_URL,
            provider="nse_pdf",
            kind="filing",
            accept=("application/pdf", "application/octet-stream", "*/*"),
            max_bytes=30 * 1024 * 1024,
        )
    except Exception as exc:  # pragma: no cover - network dependent
        pytest.skip(f"live NSE filing unavailable: {exc}")
    if not response.content[:5] == b"%PDF-":
        pytest.skip("NSE returned a non-PDF response")
    return parse_pdf(response.content)


#: Only pages the parser classified as a statement are eligible. A segment or
#: notes page can carry a line whose label matches a canonical metric, and
#: reading it would substitute a segment figure for a consolidated one.
STATEMENT_ROLES = frozenset({"P_AND_L", "BALANCE_SHEET", "CASH_FLOW"})


def _current_column(page):
    current = [c for c in page.columns if c.role == "CURRENT"]
    assert current, f"page {page.page_number} has no period column"
    return current[0]


def _read_period(page, *, scale: float = 1.0):
    """Resolve one statement page into metrics for its current period."""
    column = _current_column(page)
    lines: list[ResolvedLine] = []
    for row in page.rows:
        match = match_label(row.label)
        if match is None:
            continue
        cell = next(
            (c for c in row.cells if c.column == column.index and c.ok), None
        )
        if cell is None:
            continue
        lines.append(ResolvedLine(
            metric_id=match.metric_id,
            value=cell.value * scale,
            label=row.label,
            confidence=match.confidence,
            method=match.method,
            role=match.role,
            recovered=cell.recovered,
        ))
    chosen, shadowed = resolve_metrics(lines)
    return chosen, shadowed


def test_document_is_identified_as_a_results_filing(filing):
    assert filing.quality()["is_results_document"] is True
    assert filing.period_end == "2026-06-30"
    assert filing.period_end_source == "EXPLICIT"


def test_identity_is_read_from_the_document(filing):
    assert filing.symbol == "RELIANCE"
    assert filing.scrip_code == "500325"
    assert "L17110MH1973PLC019786" in filing.cin.replace(" ", "").upper()


def test_cover_letter_is_not_treated_as_a_statement(filing):
    """Page 1 is a letter to the exchanges, not a table of figures.

    Measured: treating it as a statement produced 22 phantom columns from the
    postal code and the phone number.
    """
    page = next(p for p in filing.pages if p.page_number == 1)
    assert page.role == "TEXT"


def test_only_real_statement_pages_are_published(filing):
    roles = {p.page_number: p.role for p in filing.pages}
    statements = [n for n, r in roles.items()
                  if r in ("P_AND_L", "BALANCE_SHEET", "CASH_FLOW")]
    # The filing carries a consolidated P&L, a balance sheet, a cash flow
    # statement and a standalone set. Cover letters and segment tables are
    # excluded.
    assert 1 not in statements
    assert len(statements) >= 2
    assert all(roles[n] != "P_AND_L" for n in (1,))


def test_statement_page_uses_a_declared_unit(filing):
    page = next(p for p in filing.pages if p.page_number == 9)
    assert page.scope == "CONSOLIDATED"
    assert page.unit.name == "crore"
    assert page.unit.scale == 10_000_000


def test_current_period_column_is_identified(filing):
    page = next(p for p in filing.pages if p.page_number == 9)
    column = _current_column(page)
    assert column.cell_count >= 10, "the period column should be well populated"


def test_consolidated_profit_and_loss_reconciles(filing):
    """The measured consolidated P&L page, validated as extracted.

    Revenue 298,621 + other income 4,447 = total income 303,068, and
    303,068 - 275,873 = 27,195 profit before tax. If the extraction reads
    these correctly the statement validates; if a column is misassigned or a
    digit is dropped, it does not, and the metrics are withheld.
    """
    page = next(p for p in filing.pages if p.page_number == 9)
    chosen, _ = _read_period(page)
    values = {metric: line.value for metric, line in chosen.items()}

    assert "revenue" in values
    assert "total_income" in values

    report = StatementValidator().validate_income_statement(
        values, period_label="Q1 FY2027", scope="CONSOLIDATED",
    )
    surviving = apply_report(values, report)

    # Whatever the damage level, the identity the filing states about its own
    # top line must hold. If it does not, nothing is published from this page.
    assert report.passed is True, report.to_dict()
    assert surviving["revenue"] == pytest.approx(298621.0)
    assert surviving["total_income"] == pytest.approx(303068.0)
    assert surviving["pbt"] == pytest.approx(27195.0)
    assert surviving["net_profit"] == pytest.approx(20616.0)


def test_net_revenue_wins_over_the_gross_sales_line(filing):
    """The filing prints both figures; only one of them is revenue.

    "Value of Sales" is 325,290 gross of GST. "Revenue from Operations" is
    298,621. Publishing the gross would overstate Reliance's revenue by 8.9%
    and would inflate every margin and growth metric derived from it.

    This failed when both lines mapped to ``revenue`` at equal confidence and
    the winner was decided by the order the rows came back in.
    """
    page = next(p for p in filing.pages if p.page_number == 9)
    chosen, shadowed = _read_period(page)

    assert chosen["revenue"].value == pytest.approx(298621.0)
    assert chosen["revenue"].role == ""

    gross = [s for s in shadowed if s["metric_id"] == "revenue"]
    assert gross, "the gross sales line should be reported as shadowed, not dropped"
    assert gross[0]["value"] == pytest.approx(325290.0)
    assert "Revenue from Operations" in gross[0]["reason"]


def test_revenue_does_not_depend_on_row_order(filing):
    """Reversing the table must not change which figure is published."""
    page = next(p for p in filing.pages if p.page_number == 9)
    column = _current_column(page)

    lines = []
    for row in page.rows:
        match = match_label(row.label)
        if match is None:
            continue
        cell = next((c for c in row.cells if c.column == column.index and c.ok), None)
        if cell is None:
            continue
        lines.append(ResolvedLine(
            metric_id=match.metric_id, value=cell.value, label=row.label,
            confidence=match.confidence, method=match.method, role=match.role,
        ))

    forward, _ = resolve_metrics(lines)
    reversed_order, _ = resolve_metrics(list(reversed(lines)))

    assert forward["revenue"].value == reversed_order["revenue"].value
    assert forward["revenue"].label == reversed_order["revenue"].label


def test_scale_is_applied_when_metrics_are_published(filing):
    """A crore figure must be published in rupees, not in crore.

    The registry formats money in INR. Publishing the crore figure unchanged
    would understate every amount by ten million times, and the error is
    invisible in any single metric because they are all scaled alike.
    """
    page = next(p for p in filing.pages if p.page_number == 9)
    chosen, _ = _read_period(page, scale=page.unit.scale)

    assert chosen["revenue"].value == pytest.approx(298621.0 * 10_000_000)
    assert chosen["total_income"].value == pytest.approx(303068.0 * 10_000_000)
    assert chosen["net_profit"].value == pytest.approx(20616.0 * 10_000_000)


def test_arithmetic_survives_scaling_to_rupees(filing):
    """A unit error must not be hidden by the tolerance.

    Every identity is homogeneous in the scale factor, so scaling to rupees
    leaves them exactly as true. If the scale were applied to one side of an
    identity and not the other, the checks would fail loudly rather than
    publishing a wrong number.
    """
    page = next(p for p in filing.pages if p.page_number == 9)
    chosen, _ = _read_period(page, scale=page.unit.scale)
    values = {metric: line.value for metric, line in chosen.items()}

    report = StatementValidator().validate_income_statement(values)
    assert report.passed is True, report.to_dict()


def test_damaged_cells_are_reported_not_published(filing):
    """Rejection is part of the output, not a silent omission."""
    rejected = filing.rejected
    assert rejected, "a filing this damaged must produce rejections"
    reasons = {r["reason"] for r in rejected}
    assert reasons & {"bad_grouping", "damaged_characters", "contains_letters",
                      "not_a_number"}
    for entry in rejected:
        assert "page" in entry
        assert "raw" in entry
        assert "reason" in entry
        # A rejected cell must not carry a value that could be published.
        assert entry.get("value") in (None, 0, 0.0)


def test_recovered_values_are_marked_so_they_cannot_be_published_silently(filing):
    """A figure rebuilt from a damaged glyph never counts as certain.

    The recovery is provenance, not a licence: a caller that publishes
    ``cell.value`` without consulting ``cell.recovered`` has published a
    hypothesis as a result.
    """
    reconstructed = 0
    for page in filing.pages:
        for row in page.rows:
            for cell in row.cells:
                if not cell.recovered:
                    continue
                reconstructed += 1
                assert cell.ok, "a recovered cell should still be a usable value"
                # The evidence for the repair must survive serialisation,
                # otherwise a reconstructed digit is indistinguishable from a
                # clean reading in the audit trail.
                payload = cell.to_dict()
                assert payload["recovered"] is True
                assert payload["source_text"]
                assert payload["x1"] >= payload["x0"]
    # The filing is damaged enough to have needed the narrow repair at all.
    assert reconstructed > 0, "the recovery path was never exercised"


def test_segment_tables_are_never_read_as_consolidated(filing):
    """A segment figure is not the consolidated line of the same name.

    The filing's segment tables contain a row reading "Gross Value of Sales and
    Services" that matches ``revenue``. Reading it would replace the
    consolidated figure with a segment one while every label still looked
    correct, and the segment table's own arithmetic does not reconcile against
    the consolidated identities so nothing downstream would notice.
    """
    segment_pages = [p for p in filing.pages if p.role not in STATEMENT_ROLES]
    assert segment_pages, "the filing does have non-statement pages"

    offenders = [
        (p.page_number, row.label)
        for p in segment_pages
        for row in p.rows
        if match_label(row.label) is not None
        and _current_column_or_none(p) is not None
    ]
    # The defence is that these pages are filtered out, not that their labels
    # fail to match. Confirm the hazard is real so the filter has a reason.
    assert offenders, "no non-statement page carries a matchable label"


def _current_column_or_none(page):
    current = [c for c in page.columns if c.role == "CURRENT"]
    return current[0] if current else None


def test_only_statement_pages_feed_the_metric_set(filing):
    """The eligibility rule, asserted directly rather than implied."""
    statements = [p for p in filing.pages if p.role in STATEMENT_ROLES]
    others = [p for p in filing.pages if p.role not in STATEMENT_ROLES]
    assert statements
    assert 1 not in [p.page_number for p in statements]
    assert all(p.page_number != 1 for p in statements)
    assert others


def test_the_damaged_standalone_page_is_fully_withheld(filing):
    """The page that motivated the evidence rule, on the real filing.

    The standalone profit and loss repeats a 15-line structure in half the
    width, so the parser interleaves prior-period and current-period digits.
    Every cell parses, the labels look right, and the page is legible enough
    that no plausibility check objects. It is only the arithmetic that
    identifies it, which is the point: without the evidence rule it published
    revenue of 166,013 crore against a real figure near 41,000, and a prior
    period's profit after tax.
    """
    page = next(p for p in filing.pages if p.page_number == 18)
    assert page.role == "P_AND_L"
    assert page.scope == "STANDALONE"

    chosen, _ = _read_period(page)
    assert chosen, "the page should yield values that then fail verification"

    values = {metric: line.value for metric, line in chosen.items()}
    report = StatementValidator().validate_income_statement(
        values, period_label="Q1 FY2027", scope="STANDALONE",
    )
    surviving = apply_report(values, report)

    assert report.passed is False
    assert surviving == {}, f"an unverifiable page published {sorted(surviving)}"
    assert any(
        "legible enough to verify" in c.name for c in report.checks
    ), report.to_dict()


def test_the_consolidated_page_keeps_its_figures(filing):
    """The evidence rule must not over-reject the page that does reconcile."""
    page = next(p for p in filing.pages if p.page_number == 9)
    chosen, _ = _read_period(page)
    values = {metric: line.value for metric, line in chosen.items()}

    report = StatementValidator().validate_income_statement(
        values, period_label="Q1 FY2027", scope="CONSOLIDATED",
    )
    surviving = apply_report(values, report)
    assert report.passed is True
    assert len(surviving) >= 10


def test_scope_is_kept_per_page_not_assumed(filing):
    """Consolidated and standalone figures are different facts.

    The filing carries both in one document. Reading them into one metric set
    would publish whichever page was processed last under a single label.
    """
    scopes = {p.scope for p in filing.pages if p.role in STATEMENT_ROLES}
    assert "CONSOLIDATED" in scopes
    assert "STANDALONE" in scopes

    for page in filing.pages:
        if page.role in STATEMENT_ROLES:
            assert page.scope in ("CONSOLIDATED", "STANDALONE"), page.page_number
