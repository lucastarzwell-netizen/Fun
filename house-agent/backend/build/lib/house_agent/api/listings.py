from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..addresses import address_key
from ..auth import get_current_user
from ..db import get_session
from ..models import (
    ACTIVE,
    NEEDS_UPDATING,
    ExcludedAddress,
    Listing,
    ListingEvent,
    Run,
    User,
)
from ..reconcile import dismiss, restore
from ..schemas import (
    DismissIn,
    ExcludedIn,
    ExcludedOut,
    ListingDetailOut,
    ListingOut,
    ListingPatch,
    RunDetailOut,
    RunOut,
    StatsOut,
)
from .deps import last_finished_run, owned_listing, owned_profile, owned_run

router = APIRouter(prefix="/api", tags=["listings"])


def _previous_price(listing: Listing) -> float | None:
    for ev in reversed(listing.events):
        if ev.kind == "price_change" and ev.old_value:
            try:
                return float(ev.old_value)
            except ValueError:
                return None
    return None


def _to_out(listing: Listing, last_run: Run | None, cls=ListingOut):
    out = cls.model_validate(listing)
    out.is_new = last_run is not None and listing.first_seen_run_id == last_run.id
    out.previous_price = _previous_price(listing)
    return out


@router.get("/profiles/{profile_id}/listings", response_model=list[ListingOut])
def list_listings(
    profile_id: int,
    state: Literal["active", "removed", "dismissed", "all"] = "active",
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    owned_profile(session, user, profile_id)
    q = (
        select(Listing)
        .where(Listing.profile_id == profile_id)
        .options(selectinload(Listing.events))
        .order_by(Listing.anchor, Listing.price)
    )
    if state != "all":
        q = q.where(Listing.listing_state == state)
    last_run = last_finished_run(session, profile_id)
    return [_to_out(listing, last_run) for listing in session.scalars(q)]


@router.get("/listings/{listing_id}", response_model=ListingDetailOut)
def get_listing(
    listing_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    listing = owned_listing(session, user, listing_id)
    return _to_out(listing, last_finished_run(session, listing.profile_id), ListingDetailOut)


@router.patch("/listings/{listing_id}", response_model=ListingOut)
def patch_listing(
    listing_id: int,
    body: ListingPatch,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    listing = owned_listing(session, user, listing_id)
    if body.reviewed is not None:
        listing.reviewed = body.reviewed
    session.commit()
    return _to_out(listing, last_finished_run(session, listing.profile_id))


@router.post("/listings/{listing_id}/dismiss", response_model=ExcludedOut)
def dismiss_listing(
    listing_id: int,
    body: DismissIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    listing = owned_listing(session, user, listing_id)
    excl = dismiss(session, listing, body.reason, date.today())
    session.commit()
    return excl


# ---- exclusions -------------------------------------------------------------------------


@router.get("/profiles/{profile_id}/excluded", response_model=list[ExcludedOut])
def list_excluded(
    profile_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    owned_profile(session, user, profile_id)
    return session.scalars(
        select(ExcludedAddress)
        .where(ExcludedAddress.profile_id == profile_id)
        .order_by(ExcludedAddress.excluded_on.desc(), ExcludedAddress.id.desc())
    ).all()


@router.post("/profiles/{profile_id}/excluded", response_model=ExcludedOut, status_code=201)
def add_excluded(
    profile_id: int,
    body: ExcludedIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    owned_profile(session, user, profile_id)
    key = address_key(body.address, body.city, body.state)
    listing = session.scalar(
        select(Listing).where(Listing.profile_id == profile_id, Listing.address_key == key)
    )
    if listing is not None:
        excl = dismiss(session, listing, body.reason, date.today())
    else:
        excl = session.scalar(
            select(ExcludedAddress).where(
                ExcludedAddress.profile_id == profile_id, ExcludedAddress.address_key == key
            )
        )
        if excl is None:
            excl = ExcludedAddress(
                profile_id=profile_id,
                address_key=key,
                address=body.address,
                city=body.city,
                state=body.state.upper(),
                reason=body.reason,
                excluded_on=date.today(),
            )
            session.add(excl)
    session.commit()
    return excl


@router.delete("/excluded/{excluded_id}", status_code=204)
def delete_excluded(
    excluded_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    excl = session.get(ExcludedAddress, excluded_id)
    if excl is None or excl.profile.owner_id != user.id:
        raise HTTPException(404, "Not found")
    restore(session, excl)
    session.commit()


# ---- runs & stats -----------------------------------------------------------------------


@router.get("/profiles/{profile_id}/runs", response_model=list[RunOut])
def list_runs(
    profile_id: int,
    limit: int = 20,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    owned_profile(session, user, profile_id)
    return session.scalars(
        select(Run).where(Run.profile_id == profile_id).order_by(Run.id.desc()).limit(limit)
    ).all()


@router.get("/runs/{run_id}", response_model=RunDetailOut)
def get_run(
    run_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return owned_run(session, user, run_id)


@router.get("/profiles/{profile_id}/stats", response_model=StatsOut)
def stats(
    profile_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    owned_profile(session, user, profile_id)
    active = list(
        session.scalars(
            select(Listing).where(Listing.profile_id == profile_id, Listing.listing_state == ACTIVE)
        )
    )
    last_run = last_finished_run(session, profile_id)
    by_anchor: dict[str, int] = {}
    for listing in active:
        by_anchor[listing.anchor or "?"] = by_anchor.get(listing.anchor or "?", 0) + 1

    def count_events(kind: str) -> int:
        if last_run is None:
            return 0
        return (
            session.scalar(
                select(func.count(ListingEvent.id)).where(
                    ListingEvent.run_id == last_run.id, ListingEvent.kind == kind
                )
            )
            or 0
        )

    return StatsOut(
        active=len(active),
        new_this_run=sum(
            1 for x in active if last_run is not None and x.first_seen_run_id == last_run.id
        ),
        needs_updating=sum(1 for x in active if x.condition == NEEDS_UPDATING),
        unreviewed=sum(1 for x in active if not x.reviewed),
        price_changes_last_run=count_events("price_change"),
        removed_last_run=count_events("removed"),
        excluded=session.scalar(
            select(func.count(ExcludedAddress.id)).where(ExcludedAddress.profile_id == profile_id)
        )
        or 0,
        by_anchor=by_anchor,
        last_run=RunOut.model_validate(last_run) if last_run else None,
    )
