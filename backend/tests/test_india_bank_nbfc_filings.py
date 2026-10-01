"""Bank and NBFC filings, which do not look like the ones this pipeline was built on.

Two things separate a bank's results from a corporate one's. The statement sets a
footnote list beside every caption, and the pages are sometimes scans rather
than text. Both were found by running the pipeline against HDFC Bank and Bajaj
Finance live, and both produced confident wrong answers rather than errors:

- The footnote list sits furthest left and is dense enough to look like data, so
  it was marked as the period being reported and the whole statement went
  unread. On Bajaj Finance it ran 1, 2, 3, 7, 9, 11, 12, 13 down the page.
- HDFC Bank's results are images. The cover letter is born-digital and its text
  says "financial results", so the document passed the results check, and the
  run then reported the unhelpful "no filing yielded a validated statement"
  instead of saying the pages cannot be read at all.

The ordering tests here are the same defect seen from the other side. The
exchange labels its own filings, and those labels are not a measure of
recency: HDFC Bank classifies results only up to December 2024 and files its
current results as a board-meeting attachment, so ranking classified filings
first published twenty-month-old figures as current.
"""

from __future__ import annotations

import pytest

from lib.india.adapter import IndiaAdapter
from lib.india.documents import DocumentKind, FilingDocument
from lib.india.pdf_tables import parse_pdf


# ---------------------------------------------------------------------------
# Which filings to open
# ---------------------------------------------------------------------------
class _StubRegistry:
    """Only the two accessors ``_financial_candidates`` uses."""

    def __init__(self, classified, speculative):
        self._classified = classified
        self._speculative = speculative

    def latest_financials(self, limit: int = 12):
        return list(self._classified)[:limit]

    def promotable(self, limit: int = 12):
        return list(self._speculative)[:limit]


def _filing(doc_id, period_end, filed_at, size=500_000):
    return FilingDocument(
        doc_id=doc_id,
        kind=DocumentKind.QUARTERLY_RESULT,
        category="Financial Results",
        title=doc_id,
        source="nse",
        source_url=f"https://example.invalid/{doc_id}.pdf",
        filed_at=filed_at,
        period_end=period_end,
        size_bytes=size,
        is_current=True,
    )


def test_a_recent_board_meeting_beats_an_old_classified_result():
    """Classification is the exchange's label, not a measure of recency."""
    old = _filing("classified-2024", "2024-12-31", "2025-01-31")
    recent = _filing("board-2026", "2026-06-30", "2026-07-18")
    candidates = IndiaAdapter()._financial_candidates(
        _StubRegistry([old], [recent])
    )
    assert [c.doc_id for c in candidates] == ["board-2026", "classified-2024"]


def test_classification_breaks_a_tie_between_filings_for_the_same_period():
    """Two filings for one period: the one typed as results wins."""
    classified = _filing("classified", "2026-06-30", "2026-07-18")
    speculative = _filing("speculative", "2026-06-30", "2026-07-20")
    candidates = IndiaAdapter()._financial_candidates(
        _StubRegistry([classified], [speculative])
    )
    assert candidates[0].doc_id == "classified"


def test_candidates_are_capped_at_the_configured_maximum():
    """The cap must drop the oldest, not truncate a sorted list arbitrarily."""
    filings = [
        _filing(f"d{index}", f"2026-0{index}-30", f"2026-0{index}-31")
        for index in range(1, 8)
    ]
    adapter = IndiaAdapter()
    adapter.max_filings = 3
    candidates = adapter._financial_candidates(_StubRegistry([], filings))
    assert [c.period_end for c in candidates] == [
        "2026-07-30", "2026-06-30", "2026-05-30",
    ]


def test_a_filing_with_no_period_is_ranked_by_its_filing_date():
    """A document that names no period is ranked, never dropped."""
    dated = _filing("dated", "2026-06-30", "2026-07-18")
    undated = _filing("undated", None, "2026-08-01")
    candidates = IndiaAdapter()._financial_candidates(
        _StubRegistry([], [dated, undated])
    )
    # With nothing else to go on, the filing date is the best ordering
    # available, so the later-filed document leads.
    assert [c.doc_id for c in candidates] == ["undated", "dated"]


# ---------------------------------------------------------------------------
# Scanned filings
# ---------------------------------------------------------------------------
def _build_pdf(page_texts: list[str]) -> bytes:
    """A minimal PDF whose pages carry only the given text.

    Written by hand because no PDF-producing library is a declared dependency,
    and the scanned-page case needs a document whose later pages hold no text
    at all - which is what an image-only scan looks like to the parser.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # object numbers are 1-based

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id = len(objects) + 1 + 2 * len(page_texts)  # reserved, set below
    page_ids: list[int] = []
    for text in page_texts:
        stream = (
            b"BT /F1 12 Tf 20 150 Td (" + text.encode("latin-1") + b") Tj ET"
        )
        content = add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )
        page_ids.append(add(
            b"<< /Type /Page /Parent " + str(pages_id).encode()
            + b" 0 R /MediaBox [0 0 300 200] /Contents "
            + str(content).encode() + b" 0 R /Resources << /Font << /F1 "
            + str(font).encode() + b" 0 R >> >> >>"
        ))
    kids = b" ".join(str(i).encode() + b" 0 R" for i in page_ids)
    actual_pages_id = add(
        b"<< /Type /Pages /Kids [" + kids + b"] /Count "
        + str(len(page_ids)).encode() + b" >>"
    )
    assert actual_pages_id == pages_id, (actual_pages_id, pages_id)
    catalog = add(b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(index).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size " + str(len(objects) + 1).encode()
        + b" /Root " + str(catalog).encode() + b" 0 R >>\nstartxref\n"
        + str(start).encode() + b"\n%%EOF\n"
    )
    return bytes(out)


def test_a_later_page_with_no_text_is_not_parsed_as_a_statement():
    """Sanity check on the fixture: the text pages really do carry text."""
    filing = parse_pdf(_build_pdf(["Statement of Profit and Loss"] * 3))
    assert filing.page_count == 3
    assert sum(p.char_count for p in filing.pages) > 0
    assert filing.is_scanned is False


def test_a_page_of_prose_is_not_mistaken_for_an_image():
    """No table is not the same as no text.

    A cover letter or an auditor's report has neither rows nor columns. Reading
    that as an unreadable page would report a perfectly legible filing as a
    scan, so the detection is on characters recovered.
    """
    filing = parse_pdf(_build_pdf(
        ["Independent Auditor's Report", "We have audited the accompanying",
         "financial statements", "for the year ended 31st March"]
    ))
    assert all(p.char_count > 0 for p in filing.pages)
    assert filing.is_scanned is False


def test_a_document_whose_pages_are_images_is_reported_as_a_scan():
    """A cover letter in text, statement pages as images: say so plainly.

    HDFC Bank posts its results this way. The document used to be reported as
    not a results filing, which is wrong - it is the results, just unreadable -
    and the run as a whole said only that no filing validated, which gives a
    reader nothing to act on.
    """
    filing = parse_pdf(_build_pdf(["Outcome of Board Meeting"] + [""] * 5))
    assert filing.page_count == 6
    assert filing.is_scanned is True


def test_a_birthday_of_a_page_that_holds_no_table_is_not_a_scan():
    """A document with text throughout is never called a scan.

    The detection needs a majority of textless pages, so one blank separator
    page in an otherwise readable filing must not change anything.
    """
    filing = parse_pdf(
        _build_pdf(["Revenue from Operations 1,234.56", "",
                    "Profit Before Tax 234.56", "Total Expenses 1,000.00"])
    )
    assert filing.is_scanned is False
