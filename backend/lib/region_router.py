"""Region dispatch for a free-text company query.

Finora has more than one research pipeline, and which one should run is decided
*before* any research starts, from the resolved entity's own country. Nothing
here reads a currency and nothing branches on a company name: the routing key is
whatever each region's own resolver concludes about the query.

Two resolvers are consulted, because they are the only authorities on their own
exchange universes:

* :mod:`lib.company_resolver` over the SEC ticker file, for US registrants.
* :mod:`lib.india.live_resolver` over the live NSE equity master, for Indian
  listed companies.

Each is asked the same question and each answers for itself. A resolver that
cannot place the query — no match, or an ambiguity it refuses to guess at — does
not compete for the route.

Why a single resolver is not enough: the SEC ticker file contains foreign
private issuers, so an Indian company's ADR resolves there under the same words
the user typed. "HDFC Bank" matches ``HDB`` in the SEC universe at high
confidence, and "HCL" matches four unrelated US registrants outright. Resolving
against one universe and then looking at the country is how a search for
"Reliance Industries" ends up researching Linkers Industries Ltd.

Ranking between the two answers is by strength of match, not by region:

1. A *definitive* match — one the resolver asserts outright rather than guesses
   (exact ticker, exact legal name, alias, ISIN, exchange listing code) —
   outranks a best-effort one regardless of which region produced it.
2. Within a tier, the higher confidence wins.

A company's primary domestic listing therefore wins over a foreign listing of
the same issuer, which is the same answer a reader expects, and it is derived
from resolution evidence rather than from a name list.

The router never falls back to a region on its own authority. If neither
resolver can place the query, or the only answer is an ambiguity, it says so and
the caller must refuse rather than fall through to whichever pipeline happens to
be wired.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from lib.core.regions import (
    Region,
    info_for_region,
    region_for_company,
    region_for_country,
)

logger = logging.getLogger("finora.region_router")


#: A resolver at or above this confidence is asserting the match rather than
#: guessing at it. Both resolvers use the same scale, and both reserve the top
#: band for exact symbol, exact legal name, alias and exchange-master keys;
#: prefix and fuzzy matching sit below it.
DEFINITIVE_CONFIDENCE = 0.97

#: Route outcomes. ``ROUTED`` is the only one that names a pipeline.
ROUTED = "ROUTED"
AMBIGUOUS = "AMBIGUOUS"
UNRESOLVED = "UNRESOLVED"


@dataclass
class RouteCandidate:
    """One resolver's answer for a query.

    ``ambiguous`` marks an answer the resolver declined to make: the candidates
    are real, but choosing between them is the user's call, not the router's.
    """

    region: Optional[Region]
    country: str
    confidence: float
    method: str
    display_name: str = ""
    identifier: str = ""
    exchange: str = ""
    entity_type: str = ""
    ambiguous: bool = False
    message: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def definitive(self) -> bool:
        return not self.ambiguous and self.confidence >= DEFINITIVE_CONFIDENCE

    @property
    def rank(self) -> tuple[int, float]:
        """Sort key across regions: definitive first, then confidence."""
        return (1 if self.definitive else 0, self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "region": self.region.value if self.region else None,
            "country": self.country,
            "confidence": round(self.confidence, 4),
            "method": self.method,
            "display_name": self.display_name,
            "identifier": self.identifier,
            "exchange": self.exchange,
            "entity_type": self.entity_type,
            "definitive": self.definitive,
            "ambiguous": self.ambiguous,
            "message": self.message,
            "candidates": self.candidates,
        }


@dataclass
class RegionRoute:
    """The router's verdict for one query."""

    query: str
    status: str = UNRESOLVED
    region: Optional[Region] = None
    country: str = ""
    message: str = ""
    chosen: Optional[RouteCandidate] = None
    considered: list[RouteCandidate] = field(default_factory=list)

    @property
    def routed(self) -> bool:
        return self.status == ROUTED and self.region is not None

    @property
    def pipeline(self) -> str:
        """The module path that serves the routed region."""
        return info_for_region(self.region).adapter if self.region else ""

    @property
    def exchanges(self) -> list[str]:
        return list(info_for_region(self.region).exchanges) if self.region else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "status": self.status,
            "region": self.region.value if self.region else None,
            "country": self.country,
            "pipeline": self.pipeline,
            "exchanges": self.exchanges,
            "message": self.message,
            "identity": self.chosen.to_dict() if self.chosen else None,
            "considered": [c.to_dict() for c in self.considered],
        }


# ── Region resolvers ──────────────────────────────────────────────────────────

def _resolve_us(query: str) -> Optional[RouteCandidate]:
    """Ask the SEC-universe resolver about ``query``."""
    from lib.company_resolver import AmbiguousCompanyError, get_universe

    try:
        result = get_universe().resolve(query)
    except AmbiguousCompanyError as exc:
        return RouteCandidate(
            region=Region.US,
            country="US",
            confidence=0.0,
            method="ambiguous",
            display_name="",
            identifier="",
            exchange="",
            ambiguous=True,
            message=str(exc),
            candidates=list(exc.candidates or []),
        )
    except Exception as exc:
        logger.info("[region_router] US resolution failed for %r: %s", query, exc)
        return None

    company = result.company
    return RouteCandidate(
        region=region_for_company(company),
        country=(company.country or "US").upper(),
        confidence=float(result.confidence),
        method=result.method,
        display_name=company.name,
        identifier=company.ticker,
        exchange=company.exchange,
        entity_type="",
        ambiguous=False,
        message=result.message,
        candidates=list(result.candidates or []),
    )


def _resolve_india(query: str) -> Optional[RouteCandidate]:
    """Ask the NSE equity master about ``query``."""
    from lib.india import live_resolver

    try:
        result = live_resolver.resolve(query)
    except Exception as exc:
        logger.info("[region_router] India resolution failed for %r: %s", query, exc)
        return None

    if result.company is None:
        return RouteCandidate(
            region=Region.INDIA,
            country="IN",
            confidence=0.0,
            method="ambiguous" if result.is_ambiguous else "no_match",
            ambiguous=result.is_ambiguous,
            message=result.message,
            candidates=list(result.candidates or []),
        )

    company = result.company
    return RouteCandidate(
        region=Region.INDIA,
        country=(company.country or "IN").upper(),
        confidence=float(result.confidence),
        method=result.method,
        display_name=company.display_name,
        identifier=company.nse_symbol or company.isin or "",
        exchange=company.primary_exchange or "NSE",
        entity_type=company.entity_type or "",
        ambiguous=False,
        message=result.message,
        candidates=list(result.candidates or []),
    )


_RESOLVERS = {
    Region.INDIA: _resolve_india,
    Region.US: _resolve_us,
}


# ── Public API ───────────────────────────────────────────────────────────────

def route_company_query(query: str) -> RegionRoute:
    """Decide which region pipeline ``query`` belongs to.

    Returns a :class:`RegionRoute` and never raises: an unroutable query is a
    result the caller reports, not an exception. It is deliberately impossible
    for this function to return ``ROUTED`` with a region no pipeline serves.
    """
    q = (query or "").strip()
    if not q:
        return RegionRoute(
            query=q, status=UNRESOLVED,
            message="Enter a company name or ticker to research.",
        )

    considered = [c for c in (r(q) for r in _RESOLVERS.values()) if c is not None]
    placed = [c for c in considered if not c.ambiguous and c.confidence > 0.0]

    if not placed:
        route = RegionRoute(query=q, status=UNRESOLVED, considered=considered)
        ambiguous = [c for c in considered if c.ambiguous and c.candidates]
        if ambiguous:
            route.status = AMBIGUOUS
            route.message = _ambiguity_message(q, ambiguous)
        else:
            route.message = (
                f"No listed company matched '{q}' in any market Finora "
                "researches. Check the spelling, or use the full company name."
            )
        return route

    winner = max(placed, key=lambda c: c.rank)
    try:
        region = region_for_country(winner.country)
    except ValueError:
        # A resolved entity in a market Finora has no pipeline for. Reported
        # rather than forced into the US pipeline, which would research the
        # wrong filings.
        return RegionRoute(
            query=q, status=UNRESOLVED, country=winner.country,
            message=(
                f"'{winner.display_name or q}' is listed in {winner.country}, "
                "which Finora does not research yet. Finora currently researches "
                "US and Indian listed companies."
            ),
            considered=considered,
        )

    winner.region = region
    runner_up = next(
        (c for c in sorted(placed, key=lambda c: c.rank, reverse=True)[1:]),
        None,
    )
    message = f"Resolved {winner.display_name or q} to the {region.value} pipeline."
    if runner_up is not None:
        # Recorded, not refused: the two resolvers disagreed and the stronger
        # match won, which the user should be able to see.
        other = runner_up.display_name or (
            runner_up.region.value if runner_up.region else "another market"
        )
        message += (
            f" {other} also matched in the other market's universe; the "
            "stronger match was used."
        )
    return RegionRoute(
        query=q, status=ROUTED, region=region, country=winner.country,
        message=message, chosen=winner, considered=considered,
    )


def _ambiguity_message(
    query: str, ambiguous: list[RouteCandidate]
) -> str:
    """Say which companies are in play, and refuse to pick for the user."""
    parts: list[str] = []
    for candidate in ambiguous:
        market = "India (NSE/BSE)" if candidate.region is Region.INDIA else "US (SEC)"
        names = ", ".join(
            str(c.get("display_name") or c.get("name") or c.get("nse_symbol") or "?")
            for c in candidate.candidates[:4]
        )
        parts.append(f"{market}: {names}")
    return (
        f"'{query}' matches more than one company, so Finora will not guess. "
        f"Re-enter the full company name. Candidates — " + "; ".join(parts) + "."
    )


__all__ = [
    "AMBIGUOUS",
    "DEFINITIVE_CONFIDENCE",
    "RegionRoute",
    "RouteCandidate",
    "ROUTED",
    "UNRESOLVED",
    "route_company_query",
]
