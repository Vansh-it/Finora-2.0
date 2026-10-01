"""Tests for India ownership: the SEBI shareholding pattern.

The live source is a flat quarterly master plus a dimensional XBRL attachment
per quarter. Two failure modes here were both silent and both produced numbers
that looked plausible, which is why they get explicit regression tests:

1. Percentages are published as decimal fractions, so 0.4962 is 49.62%.
2. One XBRL attachment covers every quarter a filer has reported, and the
   taxonomy publishes an aggregate member alongside the components it is made
   of. Summing naively reported foreign institutional holding at 36.5% for
   Reliance when the filing says 18.33%.

Every test here runs offline against synthetic filings built to the shape the
exchange actually returns.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from lib.india import http_client, ownership
from lib.india.ownership import (
    OwnershipRecord,
    fetch_ownership,
    parse_shareholding_xbrl,
)


# ---------------------------------------------------------------------------
# Synthetic fixtures shaped like the real filings
# ---------------------------------------------------------------------------

_SHAREHOLDING_NS = "http://www.bseindia.com/xbrl/shp/2025-10-31/in-bse-shp"


def _xbrl(quarters: dict[str, dict[str, float]], *, scale: str | None = None) -> bytes:
    """Build a dimensional shareholding XBRL document.

    ``quarters`` maps an ISO instant to ``{taxonomy member: fraction}``. The
    member is suffixed with ``Member`` exactly as the exchange writes it, and
    the dimension member lives in the ``xbrldi`` namespace, which is a different
    namespace from the instance itself.
    """
    contexts: list[str] = []
    facts: list[str] = []
    for instant, members in quarters.items():
        for name, value in members.items():
            member = name if name.endswith("Member") else f"{name}Member"
            context_id = f"c{len(contexts)}"
            contexts.append(
                f'<xbrli:context id="{context_id}">'
                f"<xbrli:period><xbrli:instant>{instant}</xbrli:instant>"
                "</xbrli:period>"
                "<xbrli:entity><xbrli:identifier scheme=\"http://www.nseindia.com\">"
                "TEST</xbrli:identifier></xbrli:entity>"
                "<xbrli:scenario>"
                f'<xbrldi:explicitMember dimension="{_SHAREHOLDING_NS}:'
                f'CategoryOfShareholdersAxis">{_SHAREHOLDING_NS}:{member}'
                "</xbrldi:explicitMember></xbrli:scenario></xbrli:context>"
            )
            scale_attr = f' scale="{scale}"' if scale is not None else ""
            facts.append(
                f'<shp:PercentageOfTotalVotingRights contextRef="{context_id}"'
                f' unitRef="u"{scale_attr}>{value}</shp:PercentageOfTotalVotingRights>'
            )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"'
        ' xmlns:xbrldi="http://xbrl.org/2006/xbrldi"'
        f' xmlns:shp="{_SHAREHOLDING_NS}">'
        f"{''.join(contexts)}{''.join(facts)}</xbrli:xbrl>"
    ).encode("utf-8")


#: The Reliance quarter that exposed both bugs: five quarters in one
#: attachment, and a foreign-institutions aggregate published next to the three
#: sub-members that make it up.
_FIVE_QUARTERS = {
    "2025-06-30": {"ShareholdingOfPromoterAndPromoterGroup": 0.4925},
    "2025-09-30": {
        "ShareholdingOfPromoterAndPromoterGroup": 0.4911,
        "InstitutionsForeign": 0.1831,
        "InstitutionsForeignPortfolioInvestorCategoryOne": 0.1760,
        "InstitutionsForeignPortfolioInvestorCategoryTwo": 0.0060,
        "OtherInstitutionsForeign": 0.0011,
        "InstitutionsDomestic": 0.1996,
        "PublicShareholding": 0.4909,
    },
    "2025-12-31": {
        "ShareholdingOfPromoterAndPromoterGroup": 0.4911,
        "InstitutionsForeign": 0.1874,
        "InstitutionsDomestic": 0.1982,
        "PublicShareholding": 0.4910,
    },
    "2026-03-31": {
        "ShareholdingOfPromoterAndPromoterGroup": 0.4911,
        "InstitutionsForeign": 0.1833,
        "InstitutionsDomestic": 0.2018,
        "PublicShareholding": 0.4911,
    },
    "2026-06-30": {
        "ShareholdingOfPromoterAndPromoterGroup": 0.4962,
        "InstitutionsForeign": 0.1690,
        "InstitutionsDomestic": 0.2083,
        "PublicShareholding": 0.4868,
    },
}


def _master(*rows: dict[str, Any]) -> list[dict[str, Any]]:
    return list(rows)


def _master_row(
    date: str,
    promoter: Any,
    public: Any,
    record_id: str,
    xbrl: str = "",
) -> dict[str, Any]:
    return {
        "date": date,
        "pr_and_prgrp": promoter,
        "public_val": public,
        "recordId": record_id,
        "xbrl": xbrl,
    }


# ---------------------------------------------------------------------------
# Percentage conversion
# ---------------------------------------------------------------------------


class TestPercentageScale:
    def test_decimal_fraction_becomes_a_percentage(self) -> None:
        parsed = parse_shareholding_xbrl(
            _xbrl({"2026-06-30": {"PublicShareholding": 0.4868}})
        )
        assert parsed["2026-06-30"]["public_total"] == pytest.approx(48.68)

    def test_explicit_scale_attribute_is_honoured(self) -> None:
        """Some filers publish the value already scaled instead of as a fraction."""
        parsed = parse_shareholding_xbrl(
            _xbrl({"2026-06-30": {"PublicShareholding": 48.68}}, scale="2")
        )
        assert parsed["2026-06-30"]["public_total"] == pytest.approx(4868.0)

    def test_a_value_above_one_is_already_a_percentage(self) -> None:
        """A filer writing 48.68 must not be inflated to 4868%."""
        parsed = parse_shareholding_xbrl(
            _xbrl({"2026-06-30": {"PublicShareholding": 48.68}})
        )
        assert parsed["2026-06-30"]["public_total"] == pytest.approx(48.68)


# ---------------------------------------------------------------------------
# Period selection
# ---------------------------------------------------------------------------


class TestPeriodSelection:
    def test_quarters_are_not_summed_together(self) -> None:
        """The regression: five quarters in one attachment gave FII 36.5%."""
        parsed = parse_shareholding_xbrl(_xbrl(_FIVE_QUARTERS))
        assert len(parsed) == 5
        assert parsed["2026-03-31"]["fii"] == pytest.approx(18.33)
        assert parsed["2026-06-30"]["fii"] == pytest.approx(16.90)

    def test_aggregate_is_not_double_counted_with_its_components(self) -> None:
        """FII is 18.31%, not 18.31 + 17.60 + 0.60 + 0.11."""
        parsed = parse_shareholding_xbrl(_xbrl(_FIVE_QUARTERS))
        assert parsed["2025-09-30"]["fii"] == pytest.approx(18.31)

    def test_components_are_summed_when_the_aggregate_is_absent(self) -> None:
        parsed = parse_shareholding_xbrl(_xbrl({
            "2026-06-30": {
                "InstitutionsForeignPortfolioInvestorCategoryOne": 0.1600,
                "InstitutionsForeignPortfolioInvestorCategoryTwo": 0.0100,
                "OtherInstitutionsForeign": 0.0005,
            }
        }))
        assert parsed["2026-06-30"]["fii"] == pytest.approx(17.05)

    def test_an_unknown_quarter_has_no_bucket(self) -> None:
        parsed = parse_shareholding_xbrl(_xbrl(_FIVE_QUARTERS))
        assert "2024-03-31" not in parsed


class TestPickPeriod:
    def test_exact_match_wins(self) -> None:
        by_date = {"2026-03-31": {"fii": 18.0}, "2026-06-30": {"fii": 17.0}}
        assert ownership._pick_period(by_date, "2026-06-30") == (
            "2026-06-30", {"fii": 17.0}
        )

    def test_nearest_prior_quarter_is_accepted(self) -> None:
        """A filer stamping the taxonomy a few days off still gets its data."""
        by_date = {"2026-06-30": {"fii": 17.0}}
        period, values = ownership._pick_period(by_date, "2026-07-09")
        assert period == "2026-06-30"
        assert values["fii"] == 17.0

    def test_a_later_quarter_is_never_borrowed(self) -> None:
        """Using a future quarter would leak later data into an earlier record."""
        by_date = {"2026-06-30": {"fii": 17.0}}
        assert ownership._pick_period(by_date, "2026-03-31") == ("", {})

    def test_a_gap_longer_than_a_quarter_is_refused(self) -> None:
        by_date = {"2025-06-30": {"fii": 17.0}}
        assert ownership._pick_period(by_date, "2026-06-30") == ("", {})


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------


class TestCategoryMapping:
    @pytest.mark.parametrize("member,expected", [
        ("in-bse-shp:ShareholdingOfPromoterAndPromoterGroupMember", "promoter"),
        ("in-bse-shp:InstitutionsForeignMember", "fii"),
        ("in-bse-shp:InstitutionsForeignPortfolioInvestorCategoryOneMember",
         "fii_component"),
        ("in-bse-shp:MutualFundsOrUTIMember", "mutual_fund"),
        ("in-bse-shp:InsuranceCompaniesMember", "insurance"),
        ("in-bse-shp:PublicShareholdingMember", "public_total"),
    ])
    def test_members_map_to_categories(self, member: str, expected: str) -> None:
        assert ownership._member_to_category(member) == expected

    def test_a_prefix_collision_does_not_fold_into_the_aggregate(self) -> None:
        """The exact bug: a component sharing the aggregate's prefix."""
        assert ownership._member_to_category(
            "in-bse-shp:InstitutionsForeignPortfolioInvestorCategoryOneMember"
        ) != "fii"

    def test_an_unrecognised_member_is_dropped_not_guessed(self) -> None:
        assert ownership._member_to_category("in-bse-shp:SomeNewMemberAxis") == ""

    def test_retail_is_the_exact_public_residual(self) -> None:
        """SEBI's non-institutions member is wider than retail."""
        parsed = parse_shareholding_xbrl(_xbrl({
            "2026-06-30": {
                "InstitutionsForeign": 0.1690,
                "InstitutionsDomestic": 0.2083,
                "PublicShareholding": 0.4868,
                "NonInstitutions": 0.1789,
            }
        }))
        categories = parsed["2026-06-30"]
        assert categories["retail"] == pytest.approx(10.95)
        assert categories["non_institution"] == pytest.approx(17.89)

    def test_dii_components_reconcile_with_the_disclosed_total(self) -> None:
        """The parts a filer discloses must add up to the total it discloses.

        Figures mirror a real quarter: 9.93 + 9.05 + 0.05 + 1.52 + 0.19 + 0.09
        is 20.83, the domestic-institutions total for the same period.
        """
        parsed = parse_shareholding_xbrl(_xbrl({
            "2026-06-30": {
                "InstitutionsDomestic": 0.2083,
                "MutualFundsOrUTI": 0.0993,
                "InsuranceCompanies": 0.0905,
                "Banks": 0.0005,
                "ProvidentFundsOrPensionFunds": 0.0152,
                "AlternativeInvestmentFunds": 0.0019,
                "SovereignWealthFundsDomestic": 0.0009,
            }
        }))
        categories = parsed["2026-06-30"]
        parts = sum(
            categories[k] for k in
            ("mutual_fund", "insurance", "bank", "pension_fund", "aif",
             "domestic_swf")
        )
        assert parts == pytest.approx(categories["dii_total"], abs=0.01)

    def test_a_disclosed_dii_total_survives_when_parts_are_absent(self) -> None:
        parsed = parse_shareholding_xbrl(_xbrl({
            "2026-06-30": {"InstitutionsDomestic": 0.2083},
        }))
        assert parsed["2026-06-30"]["dii_total"] == pytest.approx(20.83)


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_empty_payload(self) -> None:
        assert parse_shareholding_xbrl(b"") == {}

    def test_not_xml(self) -> None:
        assert parse_shareholding_xbrl(b"<html>403 Forbidden</html>") == {}

    def test_non_numeric_fact_is_skipped(self) -> None:
        parsed = parse_shareholding_xbrl(_xbrl({
            "2026-06-30": {"PublicShareholding": "not-a-number"},
        }))
        assert "public_total" not in parsed.get("2026-06-30", {})

    def test_external_entities_are_not_resolved(self) -> None:
        """An XXE payload must not read the filesystem or the network."""
        payload = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
            f'xmlns:shp="{_SHAREHOLDING_NS}">'
            "<xbrli:context id=\"c0\"><period><instant>2026-06-30</instant>"
            "</period></xbrli:context>"
            "<shp:PercentageOfTotalVotingRights contextRef=\"c0\">&xxe;"
            "</shp:PercentageOfTotalVotingRights></xbrli:xbrl>"
        ).encode()
        parsed = parse_shareholding_xbrl(payload)
        assert all(
            "root:" not in str(value)
            for values in parsed.values() for value in values.values()
        )


# ---------------------------------------------------------------------------
# The flat master
# ---------------------------------------------------------------------------


class TestMasterParsing:
    def test_quarters_are_ordered_oldest_first(self) -> None:
        records = ownership._records_from_master("RELIANCE", _master(
            _master_row("30-JUN-2026", "50.48", "49.52", "2"),
            _master_row("31-MAR-2026", "50.00", "50.00", "1"),
            _master_row("30-SEP-2025", "50.01", "49.99", "0"),
        ))
        assert [r.as_of for r in records] == [
            "2025-09-30", "2026-03-31", "2026-06-30"
        ]

    def test_a_duplicate_quarter_is_kept_once(self) -> None:
        records = ownership._records_from_master("RELIANCE", _master(
            _master_row("30-JUN-2026", "50.48", "49.52", "2"),
            _master_row("30-JUN-2026", "50.48", "49.52", "2"),
        ))
        assert len(records) == 1

    def test_an_unparseable_date_drops_the_row(self) -> None:
        records = ownership._records_from_master("RELIANCE", _master(
            _master_row("not-a-date", "50.48", "49.52", "2"),
        ))
        assert records == []

    def test_a_row_missing_percentages_still_keeps_the_quarter(self) -> None:
        records = ownership._records_from_master("RELIANCE", _master(
            _master_row("30-JUN-2026", "-", "NA", "2"),
        ))
        assert len(records) == 1
        assert records[0].promoter_pct is None
        assert records[0].public_pct is None

    def test_source_id_is_derived_from_the_record_id(self) -> None:
        records = ownership._records_from_master("RELIANCE", _master(
            _master_row("30-JUN-2026", "50.48", "49.52", "211570"),
        ))
        assert records[0].source_id == "nse_shp_master:211570"

    def test_an_unpromoted_company_reports_zero_promoter(self) -> None:
        """Banks are wholly public; zero is a value, not a missing value."""
        records = ownership._records_from_master("HDFCBANK", _master(
            _master_row("30-JUN-2026", "0.00", "100.00", "1"),
        ))
        assert records[0].promoter_pct == 0.0
        assert records[0].public_pct == 100.0

    @pytest.mark.parametrize("raw,expected", [
        ("30-JUN-2026", "2026-06-30"),
        ("30-jun-2026", "2026-06-30"),
        ("2026-06-30", "2026-06-30"),
        ("", ""),
        ("-", ""),
        (None, ""),
    ])
    def test_date_formats(self, raw: Any, expected: str) -> None:
        assert ownership._parse_date(raw) == expected


# ---------------------------------------------------------------------------
# Canonical conversion
# ---------------------------------------------------------------------------


class TestCanonicalConversion:
    @staticmethod
    def _result() -> ownership.OwnershipResult:
        records = [
            OwnershipRecord(as_of="2025-06-30", promoter_pct=50.0, public_pct=50.0),
            OwnershipRecord(as_of="2025-09-30", promoter_pct=50.1, public_pct=49.9),
            OwnershipRecord(as_of="2025-12-31", promoter_pct=50.2, public_pct=49.8),
            OwnershipRecord(as_of="2026-03-31", promoter_pct=50.3, public_pct=49.7),
            OwnershipRecord(as_of="2026-06-30", promoter_pct=50.48, public_pct=49.52),
        ]
        return ownership.OwnershipResult(symbol="TEST", records=records)

    def test_quarter_over_quarter_promoter_change(self) -> None:
        rows = self._result().to_canonical()
        assert rows[0].promoter_change_qoq is None
        assert rows[1].promoter_change_qoq == pytest.approx(0.1)
        assert rows[4].promoter_change_qoq == pytest.approx(0.18)

    def test_year_over_year_promoter_change(self) -> None:
        rows = self._result().to_canonical()
        assert rows[3].promoter_change_yoy is None
        assert rows[4].promoter_change_yoy == pytest.approx(0.48)

    def test_a_promoter_reduction_is_negative(self) -> None:
        records = [
            OwnershipRecord(as_of="2026-03-31", promoter_pct=50.5),
            OwnershipRecord(as_of="2026-06-30", promoter_pct=50.0),
        ]
        rows = ownership.OwnershipResult(symbol="T", records=records).to_canonical()
        assert rows[1].promoter_change_qoq == pytest.approx(-0.5)

    def test_institutional_is_fii_plus_dii(self) -> None:
        record = OwnershipRecord(
            as_of="2026-06-30", promoter_pct=50.0, public_pct=50.0,
            categories={"fii": 18.33, "dii_total": 20.18},
        )
        row = ownership.OwnershipResult(symbol="T", records=[record]).to_canonical()[0]
        assert row.institutional_pct == pytest.approx(38.51)

    def test_missing_categories_stay_missing_rather_than_zero(self) -> None:
        record = OwnershipRecord(as_of="2026-06-30", promoter_pct=50.0)
        row = ownership.OwnershipResult(symbol="T", records=[record]).to_canonical()[0]
        assert row.fii_pct is None
        assert row.dii_pct is None
        assert row.institutional_pct is None

    def test_dii_falls_back_to_summing_components(self) -> None:
        record = OwnershipRecord(
            as_of="2026-06-30",
            categories={"mutual_fund": 9.93, "insurance": 9.05, "bank": 0.05},
        )
        row = ownership.OwnershipResult(symbol="T", records=[record]).to_canonical()[0]
        assert row.dii_pct == pytest.approx(19.03)

    def test_a_disclosed_dii_total_is_preferred_over_the_sum(self) -> None:
        record = OwnershipRecord(
            as_of="2026-06-30",
            categories={
                "dii_total": 20.83, "mutual_fund": 9.93, "insurance": 9.05,
                "pension_fund": 1.52,
            },
        )
        row = ownership.OwnershipResult(symbol="T", records=[record]).to_canonical()[0]
        assert row.dii_pct == pytest.approx(20.83)


# ---------------------------------------------------------------------------
# The public entry point, against a stubbed exchange
# ---------------------------------------------------------------------------


def _ok(text: str = "", content: bytes = b"") -> http_client.FetchResult:
    return http_client.FetchResult(ok=True, url="https://www.nseindia.com/x", text=text,
                                   content=content)


def _bad() -> http_client.FetchResult:
    return http_client.FetchResult(ok=False, url="https://www.nseindia.com/x",
                                   text="", content=b"")


class TestFetchOwnership:
    def test_a_no_promoter_company_is_still_available(self, monkeypatch) -> None:
        payload = json.dumps([_master_row("30-JUN-2026", "0.00", "100.00", "1")])
        monkeypatch.setattr(
            ownership, "fetch_shareholding_master", lambda symbol: (json.loads(payload), None)
        )
        monkeypatch.setattr(ownership, "_enrich_with_xbrl", lambda *a, **k: None)
        result = fetch_ownership("HDFCBANK")
        assert result.available is True
        assert result.latest.promoter_pct == 0.0

    def test_the_exchange_going_down_is_a_failure_not_an_exception(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            ownership, "fetch_shareholding_master",
            lambda symbol: ([], {"stage": "shareholding_master", "reason": "403"}),
        )
        result = fetch_ownership("RELIANCE")
        assert result.available is False
        assert result.failures[0]["reason"] == "403"

    def test_an_empty_symbol_is_refused(self) -> None:
        result = fetch_ownership("")
        assert result.available is False

    def test_a_master_with_no_patterns_is_unavailable(self, monkeypatch) -> None:
        monkeypatch.setattr(
            ownership, "fetch_shareholding_master", lambda symbol: ([], None)
        )
        result = fetch_ownership("RELIANCE")
        assert result.available is False
        assert "no shareholding pattern" in result.failures[0]["reason"]


class TestMasterFetch:
    def test_a_json_object_instead_of_a_list_is_rejected(self, monkeypatch) -> None:
        monkeypatch.setattr(http_client, "fetch", lambda *a, **k: _ok(text='{"a": 1}'))
        rows, failure = ownership.fetch_shareholding_master("RELIANCE")
        assert rows == []
        assert "unexpected shape" in failure["reason"]

    def test_a_non_json_body_is_reported(self, monkeypatch) -> None:
        monkeypatch.setattr(http_client, "fetch", lambda *a, **k: _ok(text="<html/>"))
        rows, failure = ownership.fetch_shareholding_master("RELIANCE")
        assert rows == []
        assert "not JSON" in failure["reason"]

    def test_the_symbol_and_index_are_sent_as_query_parameters(
        self, monkeypatch
    ) -> None:
        """The endpoint returns nothing useful without these."""
        seen: dict[str, Any] = {}

        def _capture(url, **kwargs):
            seen["params"] = kwargs.get("params")
            return _ok(text="[]")

        monkeypatch.setattr(http_client, "fetch", _capture)
        ownership.fetch_shareholding_master("RELIANCE")
        assert seen["params"] == {"index": "equities", "symbol": "RELIANCE"}


class TestXbrlEnrichment:
    def test_categories_are_attached_to_the_matching_quarter(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            http_client, "fetch",
            lambda *a, **k: _ok(content=_xbrl(_FIVE_QUARTERS)),
        )
        records = [
            OwnershipRecord(as_of="2026-06-30", xbrl_url="https://nseindia.com/x.xml"),
            OwnershipRecord(as_of="2026-03-31", xbrl_url="https://nseindia.com/x.xml"),
        ]
        failures: list[dict[str, Any]] = []
        ownership._enrich_with_xbrl(records, failures)
        assert records[0].categories["fii"] == pytest.approx(16.90)
        assert records[1].categories["fii"] == pytest.approx(18.33)
        assert failures == []

    def test_one_attachment_is_fetched_once_for_every_quarter(
        self, monkeypatch
    ) -> None:
        calls: list[str] = []

        def _capture(url, **kwargs):
            calls.append(url)
            return _ok(content=_xbrl(_FIVE_QUARTERS))

        monkeypatch.setattr(http_client, "fetch", _capture)
        records = [
            OwnershipRecord(as_of="2026-06-30", xbrl_url="https://nseindia.com/x.xml"),
            OwnershipRecord(as_of="2026-03-31", xbrl_url="https://nseindia.com/x.xml"),
        ]
        ownership._enrich_with_xbrl(records, [])
        assert len(calls) == 1

    def test_a_blocked_attachment_is_recorded_as_a_failure(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(http_client, "fetch", lambda *a, **k: _bad())
        records = [
            OwnershipRecord(as_of="2026-06-30", xbrl_url="https://nseindia.com/x.xml"),
        ]
        failures: list[dict[str, Any]] = []
        ownership._enrich_with_xbrl(records, failures)
        assert records[0].categories == {}
        assert failures[0]["stage"] == "shareholding_xbrl"

    def test_a_quarter_absent_from_the_attachment_is_not_backfilled(
        self, monkeypatch
    ) -> None:
        """An older quarter must stay empty rather than inherit a neighbour."""
        monkeypatch.setattr(
            http_client, "fetch",
            lambda *a, **k: _ok(content=_xbrl(_FIVE_QUARTERS)),
        )
        records = [
            OwnershipRecord(as_of="2019-03-31", xbrl_url="https://nseindia.com/x.xml"),
        ]
        failures: list[dict[str, Any]] = []
        ownership._enrich_with_xbrl(records, failures)
        assert records[0].categories == {}
        assert failures[0]["reason"] == "attachment has no category facts for this period"

    def test_a_record_without_an_attachment_is_skipped(self, monkeypatch) -> None:
        def _explode(*a, **k):
            raise AssertionError("should not fetch a record with no XBRL link")

        monkeypatch.setattr(http_client, "fetch", _explode)
        records = [OwnershipRecord(as_of="2026-06-30", xbrl_url="")]
        ownership._enrich_with_xbrl(records, [])
        assert records[0].categories == {}


class TestResultShape:
    def test_category_coverage_counts_quarters(self, monkeypatch) -> None:
        payload = json.dumps([
            _master_row("31-MAR-2026", "50.0", "50.0", "1", "https://nseindia.com/x.xml"),
            _master_row("30-JUN-2026", "50.48", "49.52", "2", "https://nseindia.com/x.xml"),
        ])
        monkeypatch.setattr(
            ownership, "fetch_shareholding_master",
            lambda symbol: (json.loads(payload), None),
        )
        monkeypatch.setattr(
            http_client, "fetch",
            lambda *a, **k: _ok(content=_xbrl(_FIVE_QUARTERS)),
        )
        result = fetch_ownership("RELIANCE", xbrl_periods=2)
        assert result.category_coverage["fii"] == 2

    def test_latest_is_the_newest_quarter(self) -> None:
        records = [
            OwnershipRecord(as_of="2025-09-30"),
            OwnershipRecord(as_of="2026-06-30"),
        ]
        assert ownership.OwnershipResult(symbol="T", records=records).latest.as_of \
            == "2026-06-30"

    def test_latest_is_none_without_records(self) -> None:
        assert ownership.OwnershipResult(symbol="T").latest is None
