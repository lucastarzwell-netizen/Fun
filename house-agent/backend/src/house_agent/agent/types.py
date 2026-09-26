"""Structured results the agent submits through its `submit_*` tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FoundListing(BaseModel):
    address: str = Field(description="Street address only, e.g. '8821 Barnes Rd'")
    city: str
    state: str = Field(description="Two-letter state code")
    zip: str | None = None
    price: float | None = None
    beds: float | None = None
    baths: float | None = None
    acres: float | None = None
    sqft: int | None = None
    year_built: int | None = None
    url: str | None = Field(default=None, description="Listing page URL")
    mls_number: str | None = Field(
        default=None, description="MLS number if the page shows one (e.g. 'MLS# 60012345')"
    )
    anchor: str | None = Field(default=None, description="Code of the nearest anchor")
    drive_hours: float | None = Field(default=None, description="Estimated drive to the anchor")
    drive_km: float | None = Field(
        default=None, description="Canadian searches: estimated driving distance in km"
    )
    condition: Literal["good", "needs_updating", "unverified", "reject"]
    days_on_market: int | None = Field(
        default=None, description="Days on market / on the site, if the page shows it"
    )
    market_status: Literal["active", "pending", "contingent"] = Field(
        default="active", description="Listing status as shown on the listing page"
    )
    condition_notes: str = Field(
        default="", description="Short notes: year built, updates, repair language, extras"
    )
    reject_reason: str = Field(
        default="",
        description="Required when condition is reject: one sentence, addressed to the buyer, "
        "naming the rule it failed",
    )


class TrackedSighting(BaseModel):
    """A listing the buyer already tracks, seen on a results page during a county search."""

    ref: int = Field(description="The ref number of the tracked listing")
    price: float | None = Field(default=None, description="Price shown now")
    market_status: Literal["active", "pending", "contingent"] = "active"
    url: str | None = Field(default=None, description="Its listing URL on the site you saw it")
    mls_number: str | None = Field(default=None, description="MLS number, if shown")


class SearchResult(BaseModel):
    listings: list[FoundListing]
    seen_tracked: list[TrackedSighting] = Field(
        default=[],
        description="Tracked listings (from the list you were given) that you saw on a results "
        "page, with the price and status shown there",
    )
    notes: str = Field(default="", description="Problems, e.g. page blocked or rate-limited")
    region_checked: bool = Field(description="False if the region's results could not be loaded")
    sites_used: list[str] = Field(
        default=[], description="Keys of the sites whose results you used, e.g. ['zillow']"
    )
    sites_blocked: list[str] = Field(
        default=[],
        description="Keys of sites that refused access (403/429, CAPTCHA, 'access denied')",
    )
    redfin_county_id: int | None = Field(
        default=None,
        description="If you used Redfin's results page for this county, the number after "
        "/county/ in its URL",
    )


class ListingCheck(BaseModel):
    ref: int = Field(description="The ref number given for the listing")
    status: Literal["active", "pending", "contingent", "sold", "off_market", "not_found", "unknown"]
    price: float | None = None
    url: str | None = None
    condition: Literal["good", "needs_updating", "unverified", "reject"] = "unverified"
    condition_notes: str = ""
    reject_reason: str = Field(default="", description="Required when condition is reject")
    mls_number: str | None = Field(default=None, description="MLS number, if shown")
    dead_urls: list[str] = Field(
        default=[], description="Given URLs that no longer work (page gone or listing removed)"
    )
    note: str = ""


class CheckResult(BaseModel):
    checks: list[ListingCheck]


class StatusCheck(BaseModel):
    """A quick status/price check (no condition judgement)."""

    ref: int = Field(description="The ref number given for the listing")
    status: Literal["active", "pending", "contingent", "sold", "off_market", "not_found", "unknown"]
    price: float | None = Field(default=None, description="Current asking price, if shown")
    url: str | None = Field(default=None, description="The URL where you confirmed it")
    mls_number: str | None = Field(default=None, description="MLS number, if shown")
    dead_urls: list[str] = Field(
        default=[], description="Given URLs that no longer work (page gone or listing removed)"
    )
    note: str = Field(default="", description="Where you found the status, or what went wrong")


class StatusCheckResult(BaseModel):
    checks: list[StatusCheck]
