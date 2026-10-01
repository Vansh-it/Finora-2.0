"""Region scoping: the market the user picked is a constraint, not a hint.

These tests cover the behaviour that makes the region selector mean something.
Without them, two failures are invisible: the router quietly answering from the
market the user is *not* standing in, and the US pipeline running for a request
that never said which market it was for.

The routing rules are tested against synthetic candidates so they hold without a
network. Live routing is exercised separately and skipped when the exchange master
is unreachable, matching ``test_region_router``.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.core.regions import InvalidRegionError, Region
from lib.region_router import (
    AMBIGUOUS,
    MISMATCH,
    ROUTED,
    UNRESOLVED,
    RouteCandidate,
    coerce_region,
    route_company_query,
)


def _us_candidate(confidence=1.0, *, ambiguous=False, candidates=None,
                  method="exact_ticker"):
    return RouteCandidate(
        region=Region.US,
        country="US",
        confidence=confidence,
        method=method,
        display_name="Northwind Systems Inc",
        identifier="NWND",
        exchange="Nasdaq",
        ambiguous=ambiguous,
        candidates=list(candidates or []),
    )


def _india_candidate(confidence=1.0, *, ambiguous=False, candidates=None,
                     method="nse_symbol"):
    return RouteCandidate(
        region=Region.INDIA,
        country="IN",
        confidence=confidence,
        method=method,
        display_name="Northwind Industries Limited",
        identifier="NORTHWIND",
        exchange="NSE",
        ambiguous=ambiguous,
        candidates=list(candidates or []),
    )


@pytest.fixture
def only_us(monkeypatch):
    """A US universe that resolves the query to a real US company."""
    monkeypatch.setattr(
        "lib.region_router._resolve_us", lambda q: _us_candidate()
    )
    monkeypatch.setattr("lib.region_router._resolve_india", lambda q: None)


@pytest.fixture
def only_india(monkeypatch):
    """An NSE universe that resolves the query to a real Indian company."""
    monkeypatch.setattr("lib.region_router._resolve_us", lambda q: None)
    monkeypatch.setattr(
        "lib.region_router._resolve_india", lambda q: _india_candidate()
    )


@pytest.fixture
def both_markets(monkeypatch):
    """Both markets answer, each confidently — the ranking case."""
    monkeypatch.setattr(
        "lib.region_router._resolve_us", lambda q: _us_candidate()
    )
    monkeypatch.setattr(
        "lib.region_router._resolve_india", lambda q: _india_candidate()
    )


@pytest.fixture
def nowhere(monkeypatch):
    """Neither market can place the query."""
    monkeypatch.setattr("lib.region_router._resolve_us", lambda q: None)
    monkeypatch.setattr("lib.region_router._resolve_india", lambda q: None)


# ── Region parsing ──────────────────────────────────────────────────────────

class TestRegionParsing:
    def test_both_region_values_are_accepted_in_any_case(self):
        """Region arrives from a query string, so casing is not a constraint."""
        assert coerce_region("US") is Region.US
        assert coerce_region("us") is Region.US
        assert coerce_region(" India ") is Region.INDIA

    def test_absent_region_means_no_preference(self):
        assert coerce_region(None) is None
        assert coerce_region("") is None

    def test_an_unknown_region_is_refused_rather_than_ignored(self):
        """Silently dropping it would discard the constraint being asked for."""
        with pytest.raises(InvalidRegionError):
            coerce_region("EU")
        with pytest.raises(InvalidRegionError):
            coerce_region("america")


# ── The hard region constraint ─────────────────────────────────────────────

class TestSelectedRegionConstrainsRouting:
    def test_a_match_in_the_selected_market_routes(self, only_us):
        route = route_company_query("Northwind", region="US")
        assert route.status == ROUTED
        assert route.region is Region.US

    def test_an_indian_company_selected_as_us_is_a_mismatch(self, only_india):
        """The core rule: never answer from the market the user is not in."""
        route = route_company_query("Northwind", region="US")
        assert route.status == MISMATCH
        assert not route.routed

    def test_a_us_company_selected_as_india_is_a_mismatch(self, only_us):
        route = route_company_query("Northwind", region="INDIA")
        assert route.status == MISMATCH
        assert not route.routed

    def test_a_mismatch_never_routes_to_the_other_market(self, both_markets):
        """Both markets answer; the selected one still decides, and only it."""
        route = route_company_query("Northwind", region="INDIA")
        assert route.status == ROUTED
        assert route.region is Region.INDIA

        route_us = route_company_query("Northwind", region="US")
        assert route_us.status == ROUTED
        assert route_us.region is Region.US

    def test_a_mismatch_names_the_company_the_user_can_switch_to(self, only_india):
        """A refusal the user can act on has to say what was found."""
        route = route_company_query("Northwind", region="US")
        assert route.chosen is not None
        assert route.chosen.display_name == "Northwind Industries Limited"
        assert route.mismatch_target is Region.INDIA
        assert "Northwind Industries Limited" in route.message
        assert "India" in route.message

    def test_a_mismatch_exposes_no_pipeline_to_run(self, only_india):
        """A pipeline on a mismatch is exactly how a silent switch happens."""
        route = route_company_query("Northwind", region="US")
        payload = route.to_dict()
        assert payload["pipeline"] == ""
        assert payload["mismatch"] is True
        assert payload["mismatch_target"] == "INDIA"

    def test_the_selected_market_is_echoed_on_every_outcome(self, only_india):
        """The UI keeps the user's choice on screen, including on failure."""
        assert route_company_query("x", region="US").selected_region is Region.US
        assert route_company_query("", region="US").selected_region is Region.US
        assert route_company_query("", region="INDIA").selected_region is Region.INDIA

    def test_no_region_keeps_ranking_across_both_markets(self, both_markets):
        """The whole-world behaviour still works for callers that need it."""
        route = route_company_query("Northwind")
        assert route.status == ROUTED
        assert route.selected_region is None


# ── Nothing found anywhere ─────────────────────────────────────────────────

class TestUnresolvable:
    def test_an_empty_query_is_unresolved_whatever_the_region(self, nowhere):
        for region in ("US", "INDIA"):
            route = route_company_query("   ", region=region)
            assert route.status == UNRESOLVED
            assert route.region is None

    def test_an_unknown_company_is_unresolved_not_mismatched(self, nowhere):
        """No company means no company to switch to."""
        route = route_company_query("Zzzqqx Nowhere 12345", region="US")
        assert route.status == UNRESOLVED
        assert route.region is None
        assert route.mismatch_target is None
        assert "nowhere" in route.message.lower() or "not found" in route.message.lower()

    def test_the_message_does_not_claim_the_whole_world_was_searched(self, nowhere):
        """Only one market was searched, so the message must not imply two."""
        route = route_company_query("Zzzqqx", region="US")
        assert "NSE" not in route.message
        assert "BSE" not in route.message

    def test_an_unsupported_country_is_refused_not_forced_into_us(
        self, monkeypatch
    ):
        """A company in a market Finora has no pipeline for is never run as US."""
        abroad = RouteCandidate(
            region=None, country="GB", confidence=1.0, method="exact_name",
            display_name="Northwind plc", identifier="NWND",
        )
        monkeypatch.setattr(
            "lib.region_router._resolve_us", lambda q: abroad
        )
        monkeypatch.setattr("lib.region_router._resolve_india", lambda q: None)

        route = route_company_query("Northwind", region="US")
        assert route.status == UNRESOLVED
        assert route.region is None
        assert "GB" in route.message


# ── Ambiguity ───────────────────────────────────────────────────────────────

class TestAmbiguity:
    def test_ambiguity_is_reported_and_never_routed(self, monkeypatch):
        cands = [{"display_name": "Northwind A Ltd", "nse_symbol": "NWDA"}]
        monkeypatch.setattr(
            "lib.region_router._resolve_us", lambda q: None
        )
        monkeypatch.setattr(
            "lib.region_router._resolve_india",
            lambda q: _india_candidate(0.0, ambiguous=True, candidates=cands),
        )
        route = route_company_query("Northwind", region="INDIA")
        assert route.status == AMBIGUOUS
        assert not route.routed
        assert route.chosen is None

    def test_ambiguity_carries_the_candidates_the_user_can_choose(self, monkeypatch):
        cands = [{"display_name": "Northwind A Ltd", "nse_symbol": "NWDA"}]
        monkeypatch.setattr("lib.region_router._resolve_us", lambda q: None)
        monkeypatch.setattr(
            "lib.region_router._resolve_india",
            lambda q: _india_candidate(0.0, ambiguous=True, candidates=cands),
        )
        route = route_company_query("Northwind", region="INDIA")
        payload = route.to_dict()
        considered = payload["considered"]
        assert any(c["ambiguous"] for c in considered)
        assert considered[0]["candidates"][0]["nse_symbol"] == "NWDA"


# ── Mismatch is never a silent switch ──────────────────────────────────────

class TestNoSilentSwitch:
    def test_the_other_market_is_probed_only_to_name_the_company(
        self, monkeypatch
    ):
        """The probe must not be able to produce a route."""
        calls: list[str] = []

        def us(q):
            calls.append("US")
            return None

        def india(q):
            calls.append("INDIA")
            return _india_candidate()

        monkeypatch.setattr("lib.region_router._resolve_us", us)
        monkeypatch.setattr("lib.region_router._resolve_india", india)

        route = route_company_query("Northwind", region="US")
        assert route.status == MISMATCH
        # US first (the selection), then India for the mismatch report.
        assert calls == ["US", "INDIA"]
        assert route.region is Region.INDIA
        assert not route.routed

    def test_a_probed_answer_is_never_considered_placed(self, monkeypatch):
        monkeypatch.setattr("lib.region_router._resolve_us", lambda q: None)
        monkeypatch.setattr(
            "lib.region_router._resolve_india", lambda q: _india_candidate()
        )
        route = route_company_query("Northwind", region="US")
        # The probe's candidate is attached for display but is not a routing winner.
        assert route.chosen is not None
        assert route.status == MISMATCH
        assert route.to_dict()["pipeline"] == ""

    def test_a_crashing_probe_does_not_break_routing(self, monkeypatch):
        def boom(q):
            raise RuntimeError("exchange master down")

        monkeypatch.setattr("lib.region_router._resolve_us", lambda q: None)
        monkeypatch.setattr("lib.region_router._resolve_india", boom)

        route = route_company_query("Northwind", region="US")
        assert route.status == UNRESOLVED
        assert route.region is None