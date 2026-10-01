"""Region dispatch: a query must reach the pipeline that serves its exchange.

The bug this guards against is concrete. The main research flow resolved every
query against the SEC ticker universe and ran the SEC pipeline on the result, so
"Reliance Industries" researched Linkers Industries Ltd and "HCL" matched four
unrelated US registrants. Routing is decided from resolution evidence — never
from a currency, and never from a list of company names — so these tests use
arbitrary companies rather than the ones that happened to break.

Live resolution is exercised only when the exchange master is reachable; the
ranking rules are tested against synthetic candidates so they hold offline.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.core.regions import Region
from lib.region_router import (
    AMBIGUOUS,
    DEFINITIVE_CONFIDENCE,
    ROUTED,
    UNRESOLVED,
    RegionRoute,
    RouteCandidate,
    route_company_query,
)


def _candidate(region, confidence, *, method="exact_name", ambiguous=False,
               display_name="X", candidates=None):
    return RouteCandidate(
        region=region,
        country="IN" if region is Region.INDIA else "US",
        confidence=confidence,
        method=method,
        display_name=display_name,
        identifier="SYM",
        exchange="NSE" if region is Region.INDIA else "NASDAQ",
        ambiguous=ambiguous,
        candidates=list(candidates or []),
    )


# ── Ranking between resolvers ─────────────────────────────────────────────

class TestRanking:
    def test_definitive_match_outranks_a_guess_from_another_region(self):
        """An exact listing beats a fuzzy match even when the guess scores high."""
        strong = _candidate(Region.INDIA, 0.99, method="name")
        weak = _candidate(Region.US, 0.95, method="prefix")
        assert strong.rank > weak.rank

    def test_higher_confidence_wins_within_a_tier(self):
        assert _candidate(Region.INDIA, 1.0).rank > _candidate(Region.US, 0.99).rank

    def test_a_foreign_listing_never_outranks_the_domestic_listing(self):
        """The SEC file carries ADRs, so a high-confidence US match is not enough.

        "HDFC Bank" matches the NYSE ADR in the SEC universe at 0.99, an exact
        legal-name match. The NSE listing of the same issuer is the primary one
        and is the answer a reader expects.
        """
        domestic = _candidate(Region.INDIA, 1.0, method="name")
        foreign_adr = _candidate(Region.US, 0.99, method="exact_name")
        assert domestic.rank > foreign_adr.rank

    def test_ambiguous_answers_do_not_compete(self):
        ambiguous = _candidate(Region.INDIA, 0.0, ambiguous=True)
        assert not ambiguous.definitive
        assert _candidate(Region.INDIA, 0.6).rank > ambiguous.rank

    def test_definitive_threshold_is_the_resolvers_top_band(self):
        assert DEFINITIVE_CONFIDENCE <= 0.99  # US exact_name
        assert DEFINITIVE_CONFIDENCE > 0.95   # US prefix
        assert _candidate(Region.US, 1.0, method="exact_ticker").definitive
        assert not _candidate(Region.US, 0.811, method="fuzzy").definitive


# ── Route contract ─────────────────────────────────────────────────────────

class TestRouteContract:
    def test_empty_query_is_unresolved_with_a_reason(self):
        route = route_company_query("   ")
        assert route.status == UNRESOLVED
        assert not route.routed
        assert route.message

    def test_unroutable_query_never_names_a_region(self):
        """A query Finora cannot place must not default to the US pipeline."""
        route = route_company_query("")
        assert route.region is None
        assert route.pipeline == ""
        assert route.exchanges == []

    def test_routed_query_reports_its_pipeline(self):
        route = RegionRoute(query="X", status=ROUTED, region=Region.INDIA,
                            country="IN")
        assert route.pipeline == "lib.india.adapter"
        assert "NSE" in route.exchanges and "BSE" in route.exchanges

    def test_us_route_reports_the_sec_pipeline(self):
        route = RegionRoute(query="X", status=ROUTED, region=Region.US, country="US")
        assert route.pipeline == "lib.sec_client"
        assert "NASDAQ" in route.exchanges

    def test_ambiguity_is_reported_not_resolved(self):
        candidates = [{"display_name": "Northwind Utilities Ltd", "nse_symbol": "NORTH"}]
        c = _candidate(Region.INDIA, 0.0, ambiguous=True, candidates=candidates)
        assert not c.definitive

    def test_routing_never_consults_currency(self):
        """The router's inputs are resolver answers, which carry no currency."""
        c = _candidate(Region.INDIA, 1.0, method="name")
        d = c.to_dict()
        assert "currency" not in d


# ── Live routing ───────────────────────────────────────────────────────────
# Skipped when the exchange master is unreachable: the ranking rules above are
# the part that must hold everywhere, and a network outage says nothing about
# them.

def _india_master_available() -> bool:
    try:
        from lib.india import live_resolver
        return bool(live_resolver.get_master().available)
    except Exception:
        return False


requires_master = pytest.mark.skipif(
    not _india_master_available(),
    reason="live NSE equity master unavailable",
)


@requires_master
class TestLiveRouting:
    @pytest.mark.parametrize("query, symbol", [
        ("Reliance Industries", "RELIANCE"),
        ("HDFC Bank", "HDFCBANK"),
        ("Bajaj Finance", "BAJFINANCE"),
        ("Asian Paints", "ASIANPAINT"),
        ("HCL Technologies", "HCLTECH"),
    ])
    def test_indian_companies_route_to_india(self, query, symbol):
        route = route_company_query(query)
        assert route.status == ROUTED
        assert route.region is Region.INDIA
        assert route.pipeline == "lib.india.adapter"
        assert route.country == "IN"
        assert route.chosen is not None
        assert route.chosen.identifier == symbol

    @pytest.mark.parametrize("query", ["Apple", "AAPL", "Microsoft"])
    def test_us_companies_route_to_the_sec_pipeline(self, query):
        route = route_company_query(query)
        assert route.status == ROUTED
        assert route.region is Region.US
        assert route.pipeline == "lib.sec_client"

    def test_a_us_ticker_resolving_to_an_indian_name_still_routes_by_country(self):
        """A query that matches nothing in India must reach the SEC pipeline."""
        route = route_company_query("AAPL")
        assert route.region is Region.US
        assert route.country == "US"

    def test_nothing_is_routed_when_neither_exchange_places_the_query(self):
        route = route_company_query("Zzzqqx Not A Listed Company Anywhere 12345")
        assert not route.routed
        assert route.region is None
        assert route.message
