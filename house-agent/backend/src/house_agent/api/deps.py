"""Shared route helpers: load objects only if they belong to the current user."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Listing, Run, SearchProfile, User


def owned_profile(session: Session, user: User, profile_id: int) -> SearchProfile:
    profile = session.get(SearchProfile, profile_id)
    if profile is None or profile.owner_id != user.id:
        raise HTTPException(404, "Profile not found")
    return profile


def owned_listing(session: Session, user: User, listing_id: int) -> Listing:
    listing = session.get(Listing, listing_id)
    if listing is None or listing.profile.owner_id != user.id:
        raise HTTPException(404, "Listing not found")
    return listing


def owned_run(session: Session, user: User, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if run is None or run.profile.owner_id != user.id:
        raise HTTPException(404, "Run not found")
    return run


def last_finished_run(session: Session, profile_id: int) -> Run | None:
    return session.scalar(
        select(Run)
        .where(Run.profile_id == profile_id, Run.status.in_(["succeeded", "partial"]))
        .order_by(Run.id.desc())
        .limit(1)
    )
