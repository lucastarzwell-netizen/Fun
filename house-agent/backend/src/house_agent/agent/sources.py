"""Listing-site URL builders."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from ..schemas import Criteria, Region

# Lot-size values Redfin accepts in its filter URLs.
_REDFIN_LOT_ACRES = [0.25, 0.5, 1, 2, 3, 4, 5, 10, 20, 40, 100]


def _k(price: int) -> str:
    thousands = price / 1000
    return f"{thousands:g}k"


def redfin_filter(criteria: Criteria) -> str:
    parts = []
    if criteria.property_types:
        parts.append("property-type=" + "+".join(criteria.property_types))
    if criteria.min_price is not None:
        parts.append(f"min-price={_k(criteria.min_price)}")
    if criteria.max_price is not None:
        parts.append(f"max-price={_k(criteria.max_price)}")
    # Redfin applies bed/bath filters to every result, and land has neither, so with land in
    # the search these would hide all land. The agent applies them to homes instead.
    if "land" not in criteria.property_types:
        if criteria.min_beds:
            parts.append(f"min-beds={criteria.min_beds:g}")
        if criteria.min_baths:
            parts.append(f"min-baths={criteria.min_baths:g}")
    if criteria.min_acres:
        allowed = [a for a in _REDFIN_LOT_ACRES if a <= criteria.min_acres]
        if allowed:
            lot = allowed[-1]
            parts.append(f"min-lot-size={lot:g}-acre")
    return ",".join(parts)


def redfin_county_url(region: Region, criteria: Criteria) -> str | None:
    if region.redfin_county_id is None:
        return None
    name = re.sub(r"[^A-Za-z0-9 -]", "", region.name.removesuffix(" County")).replace(" ", "-")
    return (
        f"https://www.redfin.com/county/{region.redfin_county_id}/{region.state.upper()}/"
        f"{name}-County/filter/{redfin_filter(criteria)}"
    )


# ---- multiple listing sites -------------------------------------------------------------
#
# Each site gets a best-guess county results URL as a starting point. The agent is told to
# fall back to web_search if a URL doesn't work, and to move on (never work around) when a
# site blocks automated access.

_STATE_NAMES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
    "CO": "colorado", "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": "georgia",
    "HI": "hawaii", "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa",
    "KS": "kansas", "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new-hampshire", "NJ": "new-jersey", "NM": "new-mexico", "NY": "new-york",
    "NC": "north-carolina", "ND": "north-dakota", "OH": "ohio", "OK": "oklahoma",
    "OR": "oregon", "PA": "pennsylvania", "RI": "rhode-island", "SC": "south-carolina",
    "SD": "south-dakota", "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont",
    "VA": "virginia", "WA": "washington", "WV": "west-virginia", "WI": "wisconsin",
    "WY": "wyoming",
}  # fmt: skip


def _county_slug(region: Region) -> str:
    """'St. Clair County' -> 'st-clair-county'."""
    name = region.name if region.name.lower().endswith("county") else f"{region.name} County"
    return "-".join(re.sub(r"[^a-z0-9 ]", "", name.lower()).split())


def _zillow(region: Region, criteria: Criteria) -> str:
    return f"https://www.zillow.com/{_county_slug(region)}-{region.state.lower()}/"


def _realtor(region: Region, criteria: Criteria) -> str:
    name = "-".join(w.capitalize() for w in _county_slug(region).split("-"))
    return f"https://www.realtor.com/realestateandhomes-search/{name}_{region.state.upper()}"


def _homes(region: Region, criteria: Criteria) -> str:
    return f"https://www.homes.com/{_county_slug(region)}-{region.state.lower()}/"


def _landwatch(region: Region, criteria: Criteria) -> str:
    state = _STATE_NAMES.get(region.state.upper(), region.state.lower())
    return f"https://www.landwatch.com/{state}-land-for-sale/{_county_slug(region)}"


def _search_only(region: Region, criteria: Criteria) -> None:
    """No reliable URL pattern: the agent finds the region's results page with web_search."""
    return None


@dataclass(frozen=True)
class Site:
    key: str
    name: str
    county_url: Callable[[Region, Criteria], str | None]
    land_only: bool = False
    country: str = "US"


SITES: dict[str, Site] = {
    s.key: s
    for s in [
        Site("redfin", "Redfin", redfin_county_url),
        Site("zillow", "Zillow", _zillow),
        Site("realtor", "Realtor.com", _realtor),
        Site("homes", "Homes.com", _homes),
        Site("landwatch", "LandWatch", _landwatch, land_only=True),
        # Canada
        Site("realtor_ca", "Realtor.ca", _search_only, country="CA"),
        Site("zolo", "Zolo", _search_only, country="CA"),
        Site("point2", "Point2 Homes", _search_only, country="CA"),
        Site("redfin_ca", "Redfin.ca", _search_only, country="CA"),
    ]
}
DEFAULT_SITES_BY_COUNTRY = {
    "US": ["redfin", "zillow", "realtor", "homes", "landwatch"],
    "CA": ["realtor_ca", "zolo", "point2", "redfin_ca"],
}
DEFAULT_SITES = DEFAULT_SITES_BY_COUNTRY["US"]


def sites_for(criteria: Criteria) -> list[str]:
    """The search's chosen sites for its country, or that country's defaults."""
    keys = [k for k in criteria.sites if k in SITES and SITES[k].country == criteria.country]
    return keys or list(DEFAULT_SITES_BY_COUNTRY[criteria.country])


def site_plan(
    criteria: Criteria,
    region: Region,
    rotation: int,
    used_last_time: set[str] = frozenset(),
    blocked_last_time: set[str] = frozenset(),
    skip: set[str] = frozenset(),
) -> list[tuple[str, str | None]]:
    """Ordered (site key, starting URL) pairs for one county.

    Every site misses some listings, so each run leads with a site this county did NOT use
    last time; over a few runs every county gets covered by every site that allows access.
    Order: sites not used last run, then the ones that were, then sites that blocked it.
    Within each group, `rotation` (run number + county index) spreads load across sites.
    """
    keys = sites_for(criteria)
    if "land" not in criteria.property_types:
        keys = [k for k in keys if not SITES[k].land_only]
    # Sites that nearly always block the agent are left out (unless that would leave none).
    keys = [k for k in keys if k not in skip] or keys
    if not keys:
        return []
    shift = rotation % len(keys)
    keys = keys[shift:] + keys[:shift]

    def group(k: str) -> int:
        if k in blocked_last_time:
            return 2
        return 1 if k in used_last_time else 0

    keys.sort(key=group)  # stable sort keeps the rotation within each group
    return [(k, SITES[k].county_url(region, criteria)) for k in keys]


# Host name -> site key, for filing a listing URL under the site it came from.
_DOMAINS = {
    "redfin.com": "redfin",
    "zillow.com": "zillow",
    "realtor.com": "realtor",
    "homes.com": "homes",
    "landwatch.com": "landwatch",
    "realtor.ca": "realtor_ca",
    "zolo.ca": "zolo",
    "point2homes.com": "point2",
    "redfin.ca": "redfin_ca",
}


def site_for_url(url: str) -> str:
    """'https://www.zillow.com/homedetails/...' -> 'zillow'; other sites -> their host name."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for domain, key in _DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return key
    return host[:80] or "unknown"


def site_name(key: str) -> str:
    return SITES[key].name if key in SITES else key
