"""ORM models.

Ownership: every SearchProfile belongs to a User, and everything else (listings,
exclusions, runs) hangs off a profile. API routes scope every query through the
current user's profiles, so adding real authentication later only means replacing
``auth.get_current_user``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profiles: Mapped[list[SearchProfile]] = relationship(back_populates="owner")


class SearchProfile(Base):
    """A saved search: criteria (see schemas.Criteria), schedule and agent settings."""

    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    criteria: Mapped[dict[str, Any]] = mapped_column(JSON)
    # Standard 5-field cron, evaluated in `timezone`. Empty = manual runs only.
    schedule_cron: Mapped[str] = mapped_column(String(100), default="0 7 * * 5")
    # "week": schedule_cron as is. "2weeks": "M H * * D" every other week, counting from
    # schedule_anchor (the first run's date). "month": "M H D * *" on day D, or the month's
    # last day when it's shorter.
    schedule_every: Mapped[str] = mapped_column(String(10), default="week")
    schedule_anchor: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Shown to read-only demo sessions (auth.DEMO). Off unless the owner turns it on.
    demo_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    # Email summary settings (schemas.NotifySettings); NULL = off.
    notify: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    owner: Mapped[User] = relationship(back_populates="profiles")
    listings: Mapped[list[Listing]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    exclusions: Mapped[list[ExcludedAddress]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    runs: Mapped[list[Run]] = relationship(back_populates="profile", cascade="all, delete-orphan")


# Listing.state values
ACTIVE = "active"
REMOVED = "removed"  # sold / pending / off-market / no longer matches
DISMISSED = "dismissed"  # ruled out by the user (also recorded in ExcludedAddress)
REJECTED = "rejected"  # the agent looked and left it out; reject_reason says why

# Listing.condition values (mirror the sheet's Status column)
GOOD = "good"  # "Active"
NEEDS_UPDATING = "needs_updating"  # "Active - needs updating"
UNVERIFIED = "unverified"  # "Unverified"


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("profile_id", "address_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("search_profiles.id", ondelete="CASCADE"), index=True
    )
    address_key: Mapped[str] = mapped_column(String(300), index=True)
    address: Mapped[str] = mapped_column(String(300))
    city: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(2))
    zip: Mapped[str | None] = mapped_column(String(10), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    beds: Mapped[float | None] = mapped_column(Float, nullable=True)
    baths: Mapped[float | None] = mapped_column(Float, nullable=True)
    acres: Mapped[float | None] = mapped_column(Float, nullable=True)
    sqft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchor: Mapped[str | None] = mapped_column(String(20), nullable=True)
    drive_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    drive_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    condition: Mapped[str] = mapped_column(String(20), default=UNVERIFIED)
    condition_notes: Mapped[str] = mapped_column(Text, default="")
    # The main link, chosen from `sources` (see links.choose_primary).
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # MLS number as shown on the listing ("MLS# 60012345"), normalized. The same on every
    # site that syndicates the listing, so it's the best key for matching across sites.
    mls_number: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    listing_state: Mapped[str] = mapped_column(String(20), default=ACTIVE, index=True)
    removed_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # active | pending | contingent (the last two only when the search includes them)
    market_status: Mapped[str] = mapped_column(String(20), default="active")
    # The user overrode a rejection ("Include anyway"); later runs won't re-reject it.
    user_included: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[date] = mapped_column(Date)
    last_checked: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_seen_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )

    profile: Mapped[SearchProfile] = relationship(back_populates="listings")
    events: Mapped[list[ListingEvent]] = relationship(
        back_populates="listing", cascade="all, delete-orphan", order_by="ListingEvent.id"
    )
    sources: Mapped[list[ListingSource]] = relationship(
        back_populates="listing", cascade="all, delete-orphan", order_by="ListingSource.id"
    )


class ListingSource(Base):
    """One place a listing has been seen: a site and the listing's URL there.

    A listing keeps one row per site. Every sighting refreshes it (and updates the URL if
    the site moved it); a link that stops working is marked dead and never used as the main
    link again unless it's seen working later.
    """

    __tablename__ = "listing_sources"
    __table_args__ = (UniqueConstraint("listing_id", "site"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    # A key from agent.sources.SITES ("zillow"), or the host name for other sites.
    site: Mapped[str] = mapped_column(String(80))
    url: Mapped[str] = mapped_column(String(500))
    first_seen: Mapped[date] = mapped_column(Date)
    last_seen: Mapped[date] = mapped_column(Date)
    dead: Mapped[bool] = mapped_column(Boolean, default=False)

    listing: Mapped[Listing] = relationship(back_populates="sources")


class ListingEvent(Base):
    """History for a listing: added, price_change, removed, relisted, dismissed, ..."""

    __tablename__ = "listing_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(30))
    old_value: Mapped[str | None] = mapped_column(String(300), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(300), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    listing: Mapped[Listing] = relationship(back_populates="events")


class ExcludedAddress(Base):
    """Addresses the user ruled out. The agent never adds these back."""

    __tablename__ = "excluded_addresses"
    __table_args__ = (UniqueConstraint("profile_id", "address_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("search_profiles.id", ondelete="CASCADE"), index=True
    )
    address_key: Mapped[str] = mapped_column(String(300))
    address: Mapped[str] = mapped_column(String(300))
    city: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(2))
    reason: Mapped[str] = mapped_column(String(300), default="Dismissed")
    excluded_on: Mapped[date] = mapped_column(Date)

    profile: Mapped[SearchProfile] = relationship(back_populates="exclusions")


class AgentFeedback(Base):
    """Why the user overrode the agent. Sent with every later search so it learns."""

    __tablename__ = "agent_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("search_profiles.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("listings.id", ondelete="SET NULL"), nullable=True
    )
    listing_label: Mapped[str] = mapped_column(String(400))
    agent_reason: Mapped[str] = mapped_column(Text, default="")
    user_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("search_profiles.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual | schedule
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # queued | running | succeeded | partial | failed
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    log: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profile: Mapped[SearchProfile] = relationship(back_populates="runs")
