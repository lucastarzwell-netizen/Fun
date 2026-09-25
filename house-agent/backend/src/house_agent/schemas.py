"""Pydantic schemas: search criteria and API request/response bodies."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# SQLite drops tzinfo; all stored datetimes are UTC, so mark them as such on the way out.
UTCDatetime = Annotated[
    datetime, AfterValidator(lambda d: d.replace(tzinfo=UTC) if d.tzinfo is None else d)
]

DEFAULT_CONDITION_RULES = """\
Exclude anything that needs major repairs to be habitable, e.g. "cash only", foreclosure sold \
as-is with no access, "extensive TLC", "needs work throughout", fixer-upper/restore/rehab, \
mold/leaks/damage, stripped to studs, unfinished shell.
Houses that only need cosmetic updating or "some TLC" stay, marked needs_updating.
Plain "as-is" or estate as-is with no repair language is fine."""


class Anchor(BaseModel):
    """A place the search is centered on (e.g. an airport), with a drive-time limit."""

    code: str = Field(description="Short label shown in the UI, e.g. DTW")
    name: str
    max_drive_hours: float = 2.0


class Region(BaseModel):
    """An area to search. For Redfin, a county page."""

    name: str = Field(description="e.g. Lenawee County")
    state: str = Field(min_length=2, max_length=2)
    anchor: str = Field(description="Anchor code this region is searched for")
    redfin_county_id: int | None = None


class LandPrefs(BaseModel):
    """What the buyer wants from vacant land. Values are plain-language labels."""

    uses: list[str] = Field(default=[], description="Intended use, e.g. 'Build a home'")
    must_have: list[str] = Field(default=[], description="Reject land without these")
    nice_to_have: list[str] = []
    zoning: list[str] = Field(default=[], description="Acceptable zoning; empty = any")
    avoid: list[str] = []


class Criteria(BaseModel):
    property_types: list[str] = ["house"]
    min_price: int | None = None
    max_price: int | None = None
    min_acres: float | None = None
    max_acres: float | None = None
    min_beds: float | None = None
    min_baths: float | None = None
    anchors: list[Anchor] = []
    regions: list[Region] = []
    include_nearby: bool = Field(
        default=True,
        description="Keep 'nearby' results from other areas if within an anchor's drive limit",
    )
    condition_rules: str = DEFAULT_CONDITION_RULES
    land: LandPrefs | None = None
    sites: list[str] = Field(
        default=["redfin", "zillow", "realtor", "homes", "landwatch"],
        description="Listing sites to search, in preference order (LandWatch only for land)",
    )
    include_pending: bool = Field(
        default=False,
        description="Also list pending / under-contract (contingent) listings",
    )
    extra_instructions: str = ""
    # Filled in by the runner from AgentFeedback rows; never stored on the profile.
    feedback: list[str] = Field(default=[], exclude=True)


# ---- profiles ---------------------------------------------------------------------------


class ProfileIn(BaseModel):
    name: str
    criteria: Criteria
    schedule_cron: str = "0 7 * * 5"
    timezone: str = "America/New_York"
    enabled: bool = True


class ProfileOut(ProfileIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: UTCDatetime
    updated_at: UTCDatetime
    next_run_at: UTCDatetime | None = None


# ---- listings ---------------------------------------------------------------------------

ListingState = Literal["active", "removed", "dismissed", "rejected"]
Condition = Literal["good", "needs_updating", "unverified"]


class ListingEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    kind: str
    old_value: str | None
    new_value: str | None
    note: str | None
    created_at: UTCDatetime


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    address: str
    city: str
    state: str
    zip: str | None
    price: float | None
    beds: float | None
    baths: float | None
    acres: float | None
    sqft: int | None
    year_built: int | None
    anchor: str | None
    drive_hours: float | None
    condition: Condition
    condition_notes: str
    url: str | None
    listing_state: ListingState
    removed_reason: str | None
    reject_reason: str | None = None
    user_included: bool = False
    market_status: str = "active"
    reviewed: bool
    first_seen: date
    last_checked: date | None
    is_new: bool = False
    previous_price: float | None = None


class ListingDetailOut(ListingOut):
    events: list[ListingEventOut] = []


class ListingPatch(BaseModel):
    reviewed: bool | None = None


class IncludeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    listing_id: int | None
    listing_label: str
    agent_reason: str
    user_reason: str
    created_at: UTCDatetime


class DismissIn(BaseModel):
    reason: str = "Dismissed"


# ---- exclusions -------------------------------------------------------------------------


class ExcludedIn(BaseModel):
    address: str
    city: str
    state: str = Field(min_length=2, max_length=2)
    reason: str = "Ruled out"


class ExcludedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    address: str
    city: str
    state: str
    reason: str
    excluded_on: date


# ---- runs -------------------------------------------------------------------------------


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    trigger: str
    status: str
    started_at: UTCDatetime | None
    finished_at: UTCDatetime | None
    created_at: UTCDatetime
    summary: dict[str, Any]
    stopping: bool = False


class RunDetailOut(RunOut):
    log: str


class StatsOut(BaseModel):
    active: int
    new_this_run: int
    needs_updating: int
    unreviewed: int
    price_changes_last_run: int
    removed_last_run: int
    excluded: int
    rejected: int = 0
    by_anchor: dict[str, int]
    last_run: RunOut | None
