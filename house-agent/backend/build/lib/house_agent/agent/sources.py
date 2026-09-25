"""Listing-site URL builders."""

from __future__ import annotations

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
    name = region.name.removesuffix(" County").replace(" ", "-")
    return (
        f"https://www.redfin.com/county/{region.redfin_county_id}/{region.state.upper()}/"
        f"{name}-County/filter/{redfin_filter(criteria)}"
    )
