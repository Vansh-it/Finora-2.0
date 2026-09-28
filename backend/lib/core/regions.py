"""Region routing contracts.

Finora routes resolved companies to a region pipeline. The resolved company
identity carries an explicit ISO-3166 country code; currency is NEVER used to
infer country.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Region(str, Enum):
    """Finora research regions."""

    US = "US"
    INDIA = "INDIA"


@dataclass(frozen=True)
class RegionInfo:
    """Static description of a Finora region pipeline."""

    region: Region
    country_code: str
    default_currency: str
    display_currency_symbol: str
    exchanges: tuple[str, ...]
    adapter: str  # dotted path of the adapter that serves this region


REGIONS: dict[Region, RegionInfo] = {
    Region.US: RegionInfo(
        region=Region.US,
        country_code="US",
        default_currency="USD",
        display_currency_symbol="$",
        exchanges=("NASDAQ", "NYSE", "AMEX"),
        adapter="lib.sec_client",  # existing SEC pipeline (unchanged)
    ),
    Region.INDIA: RegionInfo(
        region=Region.INDIA,
        country_code="IN",
        default_currency="INR",
        display_currency_symbol="₹",
        exchanges=("NSE", "BSE"),
        adapter="lib.india.adapter",  # populated in India Adapter phase
    ),
}


REGION_PIPELINES_AVAILABLE: dict[Region, bool] = {
    Region.US: True,
    # India is a fixture-only foundation until the live adapter ships. Flip
    # this when lib.india.adapter is real, and require_supported_region()
    # starts routing Indian companies instead of refusing them.
    Region.INDIA: False,
}


def region_for_country(country_code: str) -> Region:
    """Map an ISO-3166 alpha-2 country code to a Finora region.

    Country — not currency — is the routing key.
    """
    code = (country_code or "").strip().upper()
    for info in REGIONS.values():
        if info.country_code == code:
            return info.region
    raise ValueError(f"Unsupported country code: {country_code!r}")


def info_for_region(region: Region) -> RegionInfo:
    """Return the static region description."""
    return REGIONS[region]


def routes_through_us(region: Region) -> bool:
    """True when a region uses the existing SEC/US pipeline."""
    return region == Region.US


class UnsupportedRegionError(ValueError):
    """A resolved company belongs to a region Finora cannot yet research.

    Covers both "we know this region but have no live pipeline" and "we do not
    recognise this country at all". Both are refusals of a *resolved* company,
    so both must not be reported as resolution failures.
    """

    def __init__(self, country_code: str, region: Optional[Region] = None):
        self.region = region
        self.country_code = country_code
        supported = "/".join(r.value for r in REGIONS if routes_through_us(r))
        if region is None:
            super().__init__(
                f"Finora does not support companies domiciled in "
                f"{country_code!r}. Finora currently researches {supported} "
                f"companies."
            )
            return
        info = REGIONS[region]
        super().__init__(
            f"{region.value} research is not available yet "
            f"(country {country_code!r}). Finora currently researches "
            f"{supported} companies through {info.adapter!r}."
        )


def region_for_company(company: object) -> Region:
    """Route a resolved company to its region pipeline.

    The routing key is the company's own ISO-3166 country code. Currency is
    never consulted: a US-domiciled issuer that trades in INR is still a US
    company, and an Indian issuer reporting in USD is still an Indian company.

    Objects without an explicit country are treated as US, which is what the
    SEC ticker universe is: every record in it is a US registrant by
    construction, so the existing resolution path is unchanged.
    """
    code = getattr(company, "country", None) or "US"
    return region_for_country(code)


def require_supported_region(company: object) -> RegionInfo:
    """Return the region info for a company, or refuse clearly.

    Call this before starting a region-specific pipeline. Without it an
    unsupported company falls through to whichever pipeline happens to be
    wired, which fails much later with an error that says nothing about the
    real cause.

    An unrecognised country code is refused here too, rather than allowed to
    escape as a bare ``ValueError`` — the company resolved fine, so reporting
    a resolution failure would send the reader looking in the wrong place.
    """
    code = getattr(company, "country", None) or "US"
    try:
        region = region_for_country(code)
    except ValueError:
        raise UnsupportedRegionError(code, None) from None
    info = REGIONS[region]
    if not routes_through_us(region) and not REGION_PIPELINES_AVAILABLE.get(region, False):
        raise UnsupportedRegionError(info.country_code, region)
    return info
