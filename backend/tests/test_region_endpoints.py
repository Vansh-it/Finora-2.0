"""Region-aware autocomplete and the region gate on the research entrypoint.

The suggest endpoint and ``/api/research/run`` are the two places where a region
can be quietly dropped or quietly defaulted, so both are tested at the HTTP
boundary rather than through their helpers:

* ``/api/company/suggest`` must search one market, normalise both markets into one
  result shape, and refuse an unknown region instead of guessing;
* ``/api/research/run`` must refuse a request with no region at all, because that
  endpoint starts the pipeline without routing through ``/api/research/route`` —
  which is exactly the US-pipeline-by-default path the selector exists to close.

Resolvers are swapped for synthetic ones, so these hold without a network.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.core.regions import Region
from lib.region_router import RouteCandidate


@pytest.fixture
def client():
    from app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _us_candidate():
    return RouteCandidate(
        region=Region.US, country="US", confidence=1.0, method="exact_ticker",
        display_name="Northwind Systems Inc", identifier="NWND",
        exchange="Nasdaq",
    )


def _india_candidate():
    return RouteCandidate(
        region=Region.INDIA, country="IN", confidence=1.0, method="nse_symbol",
        display_name="Northwind Industries Limited", identifier="NORTHWIND",
        exchange="NSE",
    )


def _authed():
    """Auth is checked before the region gate, so it has to pass first."""
    from lib.auth_service import User

    return patch(
        "app.get_user_from_token",
        return_value=User(
            user_id="region_user", email="r@example.com", name="Region"
        ),
    )


# ── /api/company/suggest ────────────────────────────────────────────────────

class TestSuggestIsScopedToOneMarket:
    def test_the_us_region_searches_the_us_universe(self, client):
        with patch("app.suggest_companies", return_value=[
            {"name": "Northwind Systems Inc", "ticker": "NWND",
             "exchange": "Nasdaq", "cik": "0000000001", "score": 100.0}
        ]) as us, patch("app.india_search") as india:
            res = client.get("/api/company/suggest?q=north&region=US")

        assert res.status_code == 200
        assert us.called
        assert not india.called
        assert res.get_json()["region"] == "US"

    def test_the_india_region_searches_the_nse_universe(self, client):
        with patch("app.suggest_companies") as us, patch(
            "app.india_search",
            return_value=[{"display_name": "Northwind Industries Limited",
                           "nse_symbol": "NORTHWIND", "isin": "INE000000001",
                           "country": "IN", "currency": "INR", "score": 0.98}],
        ) as india:
            res = client.get("/api/company/suggest?q=north&region=INDIA")

        assert res.status_code == 200
        assert india.called
        assert not us.called
        assert res.get_json()["region"] == "INDIA"

    def test_no_region_still_searches_the_us_universe(self, client):
        """The pre-region contract: no region means US, not both markets."""
        with patch("app.suggest_companies", return_value=[]) as us, patch(
            "app.india_search"
        ) as india:
            res = client.get("/api/company/suggest?q=apple")

        assert res.status_code == 200
        assert us.called
        assert not india.called

    def test_both_markets_return_the_same_result_shape(self, client):
        """One dropdown, one row shape — the client renders a single list.

        The fields the UI reads must be identical for both markets. Only the
        market's own identifier is allowed to differ (``cik`` vs ``isin``), since
        neither exchange issues the other's.
        """
        us_row = {"name": "Northwind Systems Inc", "ticker": "NWND",
                  "exchange": "Nasdaq", "cik": "0000000001", "score": 100.0}
        in_row = {"display_name": "Northwind Industries Limited",
                  "nse_symbol": "NORTHWIND", "isin": "INE000000001",
                  "country": "IN", "currency": "INR", "score": 0.98}

        with patch("app.suggest_companies", return_value=[us_row]):
            us_json = client.get("/api/company/suggest?q=n&region=US").get_json()
        with patch("app.india_search", return_value=[in_row]):
            in_json = client.get("/api/company/suggest?q=n&region=INDIA").get_json()

        shared = {"ticker", "name", "exchange", "country", "currency", "score",
                  "region"}
        assert shared <= set(us_json["results"][0])
        assert shared <= set(in_json["results"][0])
        assert us_json["results"][0]["ticker"] == "NWND"
        assert in_json["results"][0]["ticker"] == "NORTHWIND"

    def test_rows_carry_their_own_market_and_currency(self, client):
        """A row that does not say where it is listed invites the wrong pick."""
        with patch("app.suggest_companies", return_value=[
            {"name": "Northwind Systems Inc", "ticker": "NWND", "exchange": "Nasdaq"}
        ]):
            us_row = client.get(
                "/api/company/suggest?q=n&region=US"
            ).get_json()["results"][0]
        with patch("app.india_search", return_value=[
            {"display_name": "Northwind Industries Limited",
             "nse_symbol": "NORTHWIND"}
        ]):
            in_row = client.get(
                "/api/company/suggest?q=n&region=INDIA"
            ).get_json()["results"][0]

        assert us_row["region"] == "US" and us_row["currency"] == "USD"
        assert in_row["region"] == "INDIA" and in_row["currency"] == "INR"

    def test_an_unknown_region_is_a_400_not_a_guess(self, client):
        with patch("app.suggest_companies") as us, patch("app.india_search") as india:
            res = client.get("/api/company/suggest?q=apple&region=EU")

        assert res.status_code == 400
        assert not us.called and not india.called
        assert "region" in res.get_json()["error"].lower()

    def test_an_empty_query_returns_nothing_without_searching(self, client):
        with patch("app.suggest_companies") as us, patch("app.india_search") as india:
            res = client.get("/api/company/suggest?q=&region=US")

        assert res.status_code == 200
        assert res.get_json()["results"] == []
        assert not us.called and not india.called

    def test_a_resolver_failure_degrades_to_an_empty_list(self, client):
        """Autocomplete is advisory: a dead exchange master must not 500."""
        with patch("app.suggest_companies", side_effect=RuntimeError("unreachable")):
            res = client.get("/api/company/suggest?q=apple&region=US")

        assert res.status_code == 200
        assert res.get_json()["results"] == []

    def test_the_limit_is_clamped_to_a_sane_range(self, client):
        """An unbounded limit would let one request pull the whole exchange list."""
        with patch("app.suggest_companies", return_value=[]) as us:
            assert client.get(
                "/api/company/suggest?q=a&region=US&limit=99999"
            ).status_code == 200
            assert us.call_args.kwargs["limit"] <= 25

            client.get("/api/company/suggest?q=a&region=US&limit=abc")
            assert us.call_args.kwargs["limit"] == 8

    def test_a_query_over_the_length_limit_is_refused(self, client):
        """Autocomplete echoes text back into a list; cap it."""
        with patch("app.suggest_companies") as us:
            res = client.get(
                "/api/company/suggest?q=" + "x" * 500 + "&region=US"
            )

        assert res.status_code == 400
        assert not us.called


# ── /api/research/run: the region gate ──────────────────────────────────────

class TestResearchRunRequiresARegion:
    def test_a_request_with_no_region_is_refused(self, client):
        """The USA bypass: no region must not mean "run the US pipeline"."""
        with _authed(), patch("app.can_use_research") as quota:
            quota.return_value = {"allowed": True, "remaining": 4, "limit": 5}
            res = client.post("/api/research/run", json={"company": "Northwind"})

        assert res.status_code == 400
        assert "region" in res.get_json()["error"].lower()

    def test_the_refusal_happens_before_any_session_is_created(self, client):
        with _authed(), patch("app.grant_permission") as grant:
            res = client.post("/api/research/run", json={"company": "Northwind"})

        assert res.status_code == 400
        assert not grant.called

    def test_an_unknown_region_is_refused(self, client):
        with _authed():
            res = client.post(
                "/api/research/run", json={"company": "Northwind", "region": "EU"}
            )

        assert res.status_code == 400

    def test_a_cross_market_request_is_refused_before_research_starts(
        self, client
    ):
        """An Indian company asked for as US must not reach the SEC pipeline."""
        with _authed(), patch(
            "app.route_company_query", return_value=_mismatch_route()
        ), patch("app.grant_permission") as grant:
            quota = MagicMock()
            with patch("app.can_use_research", return_value=quota.return_value):
                res = client.post(
                    "/api/research/run",
                    json={"company": "Northwind", "region": "US"},
                )

        assert res.status_code == 409
        assert not grant.called
        payload = res.get_json()
        assert payload["mismatch"] is True
        assert payload["mismatch_target"] == "INDIA"
        assert payload["pipeline"] == ""

    def test_a_mismatch_names_the_company_the_user_could_switch_to(self, client):
        with _authed(), patch(
            "app.route_company_query", return_value=_mismatch_route()
        ):
            res = client.post(
                "/api/research/run",
                json={"company": "Northwind", "region": "US"},
            )

        payload = res.get_json()
        assert payload["identity"]["display_name"] == "Northwind Industries Limited"
        assert "India" in payload["error"]

    def test_an_unplaceable_query_is_refused(self, client):
        route = MagicMock()
        route.status = "UNRESOLVED"
        route.routed = False
        route.mismatched = False
        route.message = "No listed company matched."
        route.to_dict.return_value = {"status": "UNRESOLVED"}

        with _authed(), patch("app.route_company_query", return_value=route):
            res = client.post(
                "/api/research/run",
                json={"company": "Zzzqqx", "region": "US"},
            )

        assert res.status_code == 409

    def test_a_matching_request_passes_the_gate(self, client):
        """The gate must not block the normal path.

        Execution is stopped deliberately at the next step — creating the research
        session — so reaching that point at all proves the gate admitted the
        request. A clean 200 would mean the whole pipeline ran, which is not what
        this test is about.
        """
        route = MagicMock()
        route.status = "ROUTED"
        route.routed = True
        route.mismatched = False

        with _authed(), patch(
            "app.route_company_query", return_value=route
        ) as routed, patch(
            "app.grant_permission",
            side_effect=RuntimeError("stop here: gate passed"),
        ):
            with pytest.raises(RuntimeError, match="gate passed"):
                client.post(
                    "/api/research/run",
                    json={"company": "Northwind", "region": "US"},
                )

        routed.assert_called_once()
        assert routed.call_args.kwargs["region"] is Region.US


def _mismatch_route():
    """A route verdict for 'Indian company asked for as US'."""
    from lib.region_router import MISMATCH, RegionRoute

    return RegionRoute(
        query="Northwind",
        status=MISMATCH,
        region=Region.INDIA,
        country="IN",
        selected_region=Region.US,
        message=(
            "Northwind Industries Limited (NORTHWIND) is listed on NSE / BSE, "
            "which is the India market."
        ),
        chosen=_india_candidate(),
    )


# ── /api/research/route ─────────────────────────────────────────────────────

class TestRouteEndpointAcceptsARegion:
    def test_the_region_reaches_the_router(self, client):
        with patch("app.route_company_query") as routed:
            routed.return_value = _mismatch_route()
            client.post(
                "/api/research/route",
                json={"query": "Northwind", "region": "INDIA"},
            )

        routed.assert_called_once_with("Northwind", region=Region.INDIA)

    def test_a_mismatch_answers_409_with_the_switch_available(self, client):
        """The endpoint, not a stub: an Indian company asked for as US.

        Both resolvers are stubbed to disagree so the verdict is deterministic
        offline, and the point is the HTTP contract — 409, no pipeline, and the
        other market named so the client can offer the switch.
        """
        with patch("app.route_company_query", return_value=_mismatch_route()):
            res = client.post(
                "/api/research/route", json={"query": "Northwind", "region": "US"}
            )

        assert res.status_code == 409
        payload = res.get_json()
        assert payload["mismatch"] is True
        assert payload["mismatch_target"] == "INDIA"
        assert payload["pipeline"] == ""
        assert payload["identity"]["display_name"] == "Northwind Industries Limited"
        assert payload["selected_region"] == "US"

    def test_a_routed_request_answers_200_with_its_pipeline(self, client):
        from lib.region_router import ROUTED, RegionRoute

        route = RegionRoute(
            query="Northwind", status=ROUTED, region=Region.US, country="US",
            selected_region=Region.US, chosen=_us_candidate(),
        )
        with patch("app.route_company_query", return_value=route):
            res = client.post(
                "/api/research/route", json={"query": "Northwind", "region": "US"}
            )

        assert res.status_code == 200
        payload = res.get_json()
        assert payload["pipeline"] == "lib.sec_client"
        assert payload["mismatch"] is False

    def test_an_unknown_region_is_a_400(self, client):
        res = client.post(
            "/api/research/route", json={"query": "Northwind", "region": "EU"}
        )
        assert res.status_code == 400

    def test_a_missing_query_is_a_400(self, client):
        res = client.post("/api/research/route", json={"region": "US"})
        assert res.status_code == 400