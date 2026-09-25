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
    anchor: str | None = Field(default=None, description="Code of the nearest anchor")
    drive_hours: float | None = Field(default=None, description="Estimated drive to the anchor")
    condition: Literal["good", "needs_updating", "unverified", "reject"]
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


class SearchResult(BaseModel):
    listings: list[FoundListing]
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
    note: str = ""


class CheckResult(BaseModel):
    checks: list[ListingCheck]
