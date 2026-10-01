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

When the caller states which market the user is researching, that statement is a
*constraint*, not a hint. The routing key becomes the caller's region, and the
other market's resolver is not consulted at all. This is what makes the region
selection in the UI mean something: with the user in the US tab, an Indian
company cannot be quietly researched through the SEC pipeline because the SEC
file happens to carry its ADR. A query that only exists in the other market is
reported as :data:`MISMATCH`, carrying the company that was actually found so the
user can be offered the switch instead of being handed the wrong company.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Optional

from lib.core.regions import (
    REGIONS,
    InvalidRegionError,
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

#: Shortest word that can carry identity evidence. Below this, a word is an
#: article or a syllable fragment, and matching it proves nothing.
_MIN_EVIDENCE_TOKEN_LEN = 4

#: Ordinary words that show up in both search queries and company boilerplate.
#:
#: Sharing one of these is not identity evidence, even at identical length and
#: identical spelling: "ALEXANDRIA REAL ESTATE EQUITIES" and the nonsense query
#: "Zzzqqx Not A Real Company 9999" agree on the word "real" and nothing else.
#: Blocking containment was not enough, because a shared *whole* word from this
#: set is just as uninformative as a shared fragment. A fuzzy hit that rests only
#: on these words is a guess, and the router declines to guess.
_NON_EVIDENCE_WORDS = frozenset({
    "real", "list", "listed", "company", "companys", "group", "holding",
    "holdings", "limited", "corporation", "corp", "incorporated", "inc",
    "international", "global", "national", "general", "services", "service",
    "systems", "system", "technologies", "enterprise", "enterprises",
    "industries", "industry", "partners", "capital", "ventures",
})

#: Two words are only evidence for each other when their lengths are close. This
#: is what stops substring matches from counting: ``here`` is wholly contained in
#: ``anywhere``, so a partial-ratio scorer rates that pair ~90 even though the two
#: words share no identity at all.
_MIN_TOKEN_LENGTH_RATIO = 0.8

#: Methods where the resolver is *estimating* a match rather than asserting one.
#:
#: A fuzzy or prefix hit is a similarity score over a candidate pool, so it can
#: fire on a company the user never named. An exact ticker, exact legal name, or
#: alias is the resolver claiming "this is the entity", and only that kind of
#: claim is allowed to outrank the other market.
#:
#: This is what separates the two senses of "found in the selected market". A
#: USA-prefix hit on ``RELIANCE, INC.`` for the query ``Reliance Industries`` is
#: a guess sitting in the user's chosen market; India's exact-name match on
#: ``Reliance Industries Limited`` is an assertion of identity. The guess must
#: not win, because routing on it researches a company the user did not name -
#: the USA resolver absorbing Indian company names, which is the hazard this
#: boundary exists to close.
_GUESS_METHODS = frozenset({"fuzzy", "prefix"})

#: Similarity required between two same-length words before one corroborates the
#: other. Set below a typo-tolerant level so ``Microsft`` still evidences
#: ``Microsoft``.
_MIN_TOKEN_SIMILARITY = 0.86

#: Route outcomes. ``ROUTED`` is the only one that names a pipeline.
#:
#: ``MISMATCH`` means the query was placed, but in the market the caller did *not*
#: ask for. It is deliberately not a failure: the company is known and named, so
#: the only thing wrong is the region the user is standing in. Keeping it separate
#: from :data:`UNRESOLVED` is what lets the UI offer "switch to India" rather than
#: "search again" — and what stops the pipeline from starting on the wrong market.
ROUTED = "ROUTED"
AMBIGUOUS = "AMBIGUOUS"
UNRESOLVED = "UNRESOLVED"
MISMATCH = "MISMATCH"


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
    def asserts_identity(self) -> bool:
        """Whether this candidate claims to *be* the queried entity.

        Distinct from :attr:`definitive`, which is only about confidence. A fuzzy
        hit can clear the confidence bar and still be a guess: ``Reliance
        Industries`` scores 0.98 against the NYSE-listed ``RELIANCE, INC.``
        because the two names resemble each other, but the user meant the NSE
        company of that exact name. Only an exact ticker, exact legal name, or
        alias is the resolver standing behind the identification.
        """
        return not self.ambiguous and self.method not in _GUESS_METHODS

    @property
    def rank(self) -> tuple[int, float]:
        """Sort key across regions: definitive first, then confidence.

        The third element is the domestic-listing tie-break, and it is explicit
        rather than left to whichever resolver happened to be consulted first.
        The SEC universe carries ADRs, so an equal-strength US match for an
        Indian issuer is the *foreign* listing of a company whose primary listing
        is in India. When two markets are equally sure of the same issuer, the
        primary domestic listing is the answer a reader expects, so India wins
        that tie.
        """
        return (
            1 if self.definitive else 0,
            self.confidence,
            1 if self.region is Region.INDIA else 0,
        )

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
    """The router's verdict for one query.

    ``selected_region`` is the market the caller asked for, and is preserved on
    every outcome — including the failures — so the UI can keep the user's choice
    on screen instead of resetting it. It is ``None`` only for callers that
    genuinely express no preference, which is the original whole-world behaviour.
    """

    query: str
    status: str = UNRESOLVED
    region: Optional[Region] = None
    country: str = ""
    message: str = ""
    chosen: Optional[RouteCandidate] = None
    considered: list[RouteCandidate] = field(default_factory=list)
    selected_region: Optional[Region] = None

    @property
    def routed(self) -> bool:
        return self.status == ROUTED and self.region is not None

    @property
    def mismatched(self) -> bool:
        """True when the company was found, but in the other market."""
        return self.status == MISMATCH

    @property
    def pipeline(self) -> str:
        """The module path that serves the routed region."""
        return info_for_region(self.region).adapter if self.region else ""

    @property
    def exchanges(self) -> list[str]:
        return list(info_for_region(self.region).exchanges) if self.region else []

    @property
    def mismatch_target(self) -> Optional[Region]:
        """The market the query actually belongs to, when it is the other one.

        ``None`` unless this is a :data:`MISMATCH`, so a caller cannot read it as
        "the region to run" and skip the check. The switch is only ever offered to
        a user who has to press a button on it.
        """
        return self.region if self.status == MISMATCH and self.region else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "status": self.status,
            "region": self.region.value if self.region else None,
            "country": self.country,
            "pipeline": self.pipeline if self.routed else "",
            "exchanges": self.exchanges,
            "message": self.message,
            "selected_region": (
                self.selected_region.value if self.selected_region else None
            ),
            "mismatch": self.status == MISMATCH,
            "mismatch_target": (
                self.mismatch_target.value if self.mismatch_target else None
            ),
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


#: Region -> the name of its resolver, resolved at call time.
#:
#: Names rather than the functions themselves: a dict captured at import would keep
#: pointing at the original functions, so a caller (or a test) that swaps a
#: resolver out would find routing still using the old one. Looking the name up in
#: the module namespace means what routing calls is what the module currently
#: holds.
_RESOLVER_NAMES = {
    Region.INDIA: "_resolve_india",
    Region.US: "_resolve_us",
}


def _resolver_for(region: Region):
    """Return the resolver that is authoritative for ``region``, if any."""
    name = _RESOLVER_NAMES.get(region)
    if name is None:
        return None
    return globals().get(name)


# ── Query evidence ──────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    """Split ``text`` into comparable lowercase words."""
    return _TOKEN_RE.findall((text or "").lower())


def _shares_evidence(query: str, *texts: str) -> bool:
    """True when the query corroborates the matched entity by a real word.

    A similarity score on its own is not evidence that two strings name the same
    company. ``rapidfuzz``'s partial-ratio family scores containment, so any short
    word hidden inside a longer one scores near-perfect: the nonsense query
    ``"Zzzqqx Not A Listed Company Anywhere 12345"`` scores 90 against ``HERE
    Group Ltd`` purely because ``here`` sits inside ``anywhere``. Routing on that
    score researches a company the user never named.

    The fix is to require *shared identity*, not shared shape. A word counts as
    evidence when it is long enough to be distinctive, when the word it is being
    compared against is of comparable length — which is what rules out the
    substring case — and when the two are genuinely similar. Exact symbols and
    legal names are unaffected because their resolvers already answer in the
    definitive band and never reach here.
    """
    query_tokens = [
        t
        for t in _tokens(query)
        if len(t) >= _MIN_EVIDENCE_TOKEN_LEN and t not in _NON_EVIDENCE_WORDS
    ]
    if not query_tokens:
        # A query of nothing but short words ("ASML", "BAC") carries no evidence
        # by this measure. It can still route on an exact ticker, so absence here
        # is not a refusal — only a refusal to *corroborate* a fuzzy hit.
        return False

    target_tokens = [
        t
        for text in texts
        for t in _tokens(text)
        if len(t) >= _MIN_EVIDENCE_TOKEN_LEN and t not in _NON_EVIDENCE_WORDS
    ]
    if not target_tokens:
        return False

    for q_tok in query_tokens:
        for t_tok in target_tokens:
            longest = max(len(q_tok), len(t_tok))
            if min(len(q_tok), len(t_tok)) / longest < _MIN_TOKEN_LENGTH_RATIO:
                continue  # containment, not identity
            if SequenceMatcher(None, q_tok, t_tok).ratio() >= _MIN_TOKEN_SIMILARITY:
                return True
    return False


def _is_supported_evidence(query: str, candidate: "RouteCandidate") -> bool:
    """Whether ``candidate`` is allowed to stand as the route for ``query``.

    A definitive match — exact ticker, exact legal name, alias, exchange-master
    key — is the resolver asserting the identity, and is always honoured. Anything
    below that band is a guess, and a guess has to be backed by a shared word
    before the router will act on it. This is the same rule that keeps an
    unplaceable query unplaceable in the USA universe: refusal, not a silent
    fallback to whichever pipeline is wired.
    """
    if candidate.definitive:
        return True
    return _shares_evidence(query, candidate.display_name, candidate.identifier)


# ── Public API ───────────────────────────────────────────────────────────────

def coerce_region(region: Any) -> Optional[Region]:
    """Accept a :class:`Region`, its ``"US"``/``"INDIA"`` string, or nothing.

    Region arrives from a query string or a JSON body, so it is text by the time
    it gets here. An unrecognised value is an error rather than a silent ``None``:
    quietly treating a typo'd region as "no preference" would drop the hard
    constraint the caller asked for and let the other market answer.
    """
    if region is None or region == "":
        return None
    if isinstance(region, Region):
        return region
    try:
        return Region(str(region).strip().upper())
    except ValueError:
        raise InvalidRegionError(region) from None


def _resolve_order(selected: Optional[Region]) -> list:
    """Resolvers allowed to decide the route, in priority order.

    With a selected market only that market's resolver runs: the other universe is
    not a lower-priority option, it is off-limits for routing. Without one, both
    run and are ranked as before.
    """
    if selected is not None:
        resolver = _resolver_for(selected)
        return [resolver] if resolver else []
    return [
        r for r in (_resolver_for(region) for region in REGIONS) if r is not None
    ]


def _mismatch_probe(query: str, selected: Region) -> Optional[RouteCandidate]:
    """Ask the *other* market whether this company exists there, for reporting only.

    Detecting a mismatch requires knowing what was missed, and that knowledge sits
    in the market the user is not standing in. So when the selected market comes
    back empty, the other resolver is consulted once — and its answer may only ever
    become a :data:`MISMATCH`, never a route.

    The distinction matters: routing on this answer would be exactly the silent
    region switch the constraint forbids, because the user asked about one market
    and would get a report for another. Reporting it instead is what turns a
    dead-end search into a choice they can make.
    """
    other = next((r for r in REGIONS if r is not selected), None)
    if other is None:
        return None
    resolver = _resolver_for(other)
    if resolver is None:
        return None
    try:
        candidate = resolver(query)
    except Exception as exc:  # a probe must never break routing
        logger.info("[region_router] mismatch probe failed for %r: %s", query, exc)
        return None
    if candidate is None or candidate.ambiguous or candidate.confidence <= 0.0:
        return None
    if not _is_supported_evidence(query, candidate):
        return None
    return candidate


def route_company_query(
    query: str, region: Any = None
) -> RegionRoute:
    """Decide which region pipeline ``query`` belongs to.

    Returns a :class:`RegionRoute` and never raises: an unroutable query is a
    result the caller reports, not an exception. It is deliberately impossible
    for this function to return ``ROUTED`` with a region no pipeline serves.

    ``region`` is the market the user is researching. When given it is binding:

    * a match in that market routes, and no other resolver is consulted;
    * a match that exists only in the other market returns :data:`MISMATCH` with
      the found company attached, so the caller can offer the switch — it never
      routes to the market the user did not pick;
    * nothing found returns :data:`UNRESOLVED`.

    Omitting it keeps the original behaviour of considering both markets, which is
    what the India dashboard and any whole-world caller still rely on.
    """
    selected = coerce_region(region)
    q = (query or "").strip()
    if not q:
        return RegionRoute(
            query=q, status=UNRESOLVED, selected_region=selected,
            message="Enter a company name or ticker to research.",
        )

    considered = [
        c for c in (r(q) for r in _resolve_order(selected)) if c is not None
    ]
    # A resolver's answer only competes for the route when it survives the
    # evidence gate. Unsupported guesses stay in ``considered`` so the caller can
    # see what was examined, but they never win.
    placed = [
        c for c in considered
        if not c.ambiguous and c.confidence > 0.0 and _is_supported_evidence(q, c)
    ]

    if not placed:
        route = RegionRoute(
            query=q, status=UNRESOLVED, considered=considered,
            selected_region=selected,
        )
        ambiguous = [c for c in considered if c.ambiguous and c.candidates]
        if ambiguous:
            route.status = AMBIGUOUS
            route.message = _ambiguity_message(q, ambiguous)
        elif selected is not None:
            probe = _mismatch_probe(q, selected)
            if probe is not None:
                found_region = probe.region or next(
                    (r for r in REGIONS if r is not selected), Region.US
                )
                probe.region = found_region
                route.status = MISMATCH
                route.region = found_region
                route.country = probe.country
                route.chosen = probe
                route.message = _mismatch_message(q, probe, selected, found_region)
                return route
            # Nothing here and nothing there: a genuine dead end. Say it in the
            # selected market's terms rather than implying the world was searched.
            route.message = (
                f"'{q}' was not found on "
                f"{' / '.join(info_for_region(selected).exchanges)} or anywhere "
                "else Finora researches. Check the spelling, or use the full "
                "company name or its ticker."
            )
        else:
            rejected = [
                c for c in considered
                if not c.ambiguous and c.confidence > 0.0
            ]
            if rejected:
                # Something scored, but nothing it scored against is a word this
                # query actually contains. Saying so is more useful than claiming
                # nothing matched at all.
                near = rejected[0]
                route.message = (
                    f"Finora could not confirm which company '{q}' refers to. "
                    "Something close was found "
                    f"({near.display_name or near.identifier}) but the name does "
                    "not match what you typed. Search using the full company "
                    "name or its ticker."
                )
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
            selected_region=selected,
            message=(
                f"'{winner.display_name or q}' is listed in {winner.country}, "
                "which Finora does not research yet. Finora currently researches "
                "US and Indian listed companies."
            ),
            considered=considered,
        )

    winner.region = region

    if selected is not None and not winner.asserts_identity:
        # The selected market returned a *guess*, not an identification. The other
        # market gets one look, because if it can name this company outright then
        # the user is researching that company and simply has the wrong terminal
        # open. A guess in the selected market cannot outrank that claim.
        probe = _mismatch_probe(q, selected)
        if probe is not None and probe.asserts_identity:
            probe.region = probe.region or next(
                (r for r in REGIONS if r is not selected), Region.US
            )
            return RegionRoute(
                query=q, status=MISMATCH, region=probe.region,
                country=probe.country, selected_region=selected,
                chosen=probe, considered=considered + [probe],
                message=_mismatch_message(q, probe, selected, probe.region),
            )
        # No identity claim anywhere else: the guess stands, because refusing to
        # route on it would strand a legitimate search the selected market can
        # still answer.

    if selected is not None and region is not selected:
        # The company was found, and it is in the market the user did not pick.
        # Named, but not routed: switching markets is a decision the user makes.
        found = winner.display_name or q
        sym = winner.identifier
        return RegionRoute(
            query=q, status=MISMATCH, region=region, country=winner.country,
            selected_region=selected,
            message=(
                f"{found}{f' ({sym})' if sym else ''} is listed in "
                f"{winner.country}, not in "
                f"{info_for_region(selected).country_code}. Switch to the "
                f"{_region_label(region)} market to research it."
            ),
            chosen=winner, considered=considered,
        )

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
        selected_region=selected,
        message=message, chosen=winner, considered=considered,
    )


def _region_label(region: Optional[Region]) -> str:
    if region is Region.INDIA:
        return "India"
    if region is Region.US:
        return "US"
    return "selected"


def _mismatch_message(
    query: str, found: RouteCandidate, selected: Region, found_region: Region
) -> str:
    """Name the company that was found and offer the switch, without taking it."""
    name = found.display_name or query
    sym = found.identifier
    exchanges = " / ".join(info_for_region(found_region).exchanges)
    return (
        f"{name}{f' ({sym})' if sym else ''} is listed on {exchanges}, "
        f"which is the {_region_label(found_region)} market — not the "
        f"{_region_label(selected)} market you are searching. "
        "Switch region to research it, or search the "
        f"{_region_label(selected)} market for a different company."
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
    "MISMATCH",
    "RegionRoute",
    "RouteCandidate",
    "ROUTED",
    "UNRESOLVED",
    "coerce_region",
    "route_company_query",
]
