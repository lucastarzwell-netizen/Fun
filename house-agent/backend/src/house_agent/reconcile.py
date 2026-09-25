"""Apply agent findings to the database.

This is plain code on purpose: the model reports what it saw, and these functions decide
what changes, so the week-to-week bookkeeping (new, price cuts, removals, exclusions,
reviewed flags) is predictable and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .addresses import address_key
from .agent.types import FoundListing, ListingCheck
from .models import (
    ACTIVE,
    DISMISSED,
    GOOD,
    NEEDS_UPDATING,
    REJECTED,
    REMOVED,
    UNVERIFIED,
    AgentFeedback,
    ExcludedAddress,
    Listing,
    ListingEvent,
    SearchProfile,
)


@dataclass
class RunChanges:
    added: list[str] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    price_changes: list[dict] = field(default_factory=list)
    relisted: list[str] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    status_changes: list[dict] = field(default_factory=list)
    condition_changes: list[dict] = field(default_factory=list)
    skipped_excluded: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "added": self.added,
            "removed": self.removed,
            "price_changes": self.price_changes,
            "relisted": self.relisted,
            "rejected": self.rejected,
            "status_changes": self.status_changes,
            "condition_changes": self.condition_changes,
            "skipped_excluded": self.skipped_excluded,
        }


def _label(listing: Listing) -> str:
    return f"{listing.address}, {listing.city}, {listing.state}"


def _event(listing: Listing, run_id: int | None, kind: str, old=None, new=None, note=None):
    listing.events.append(
        ListingEvent(
            run_id=run_id,
            kind=kind,
            old_value=None if old is None else str(old),
            new_value=None if new is None else str(new),
            note=note,
        )
    )


def excluded_keys(session: Session, profile_id: int) -> set[str]:
    return set(
        session.scalars(
            select(ExcludedAddress.address_key).where(ExcludedAddress.profile_id == profile_id)
        )
    )


def _money(n: float) -> str:
    return f"${n:,.0f}"


def criteria_problem(
    profile: SearchProfile, price: float | None, acres: float | None
) -> str | None:
    """Plain-language reason a listing fails the hard numeric criteria, or None."""
    c = profile.criteria
    if price is not None:
        if c.get("min_price") is not None and price < c["min_price"]:
            return f"Price {_money(price)} is below your {_money(c['min_price'])} minimum."
        if c.get("max_price") is not None and price > c["max_price"]:
            return f"Price {_money(price)} is above your {_money(c['max_price'])} maximum."
    if acres is not None:
        if c.get("min_acres") is not None and acres < c["min_acres"]:
            return f"{acres:g} acres is less than your {c['min_acres']:g}-acre minimum."
        if c.get("max_acres") is not None and acres > c["max_acres"]:
            return f"{acres:g} acres is more than your {c['max_acres']:g}-acre maximum."
    return None


PENDING_LABEL = {"pending": "pending", "contingent": "under contract"}


def pending_problem(profile: SearchProfile, market_status: str) -> str | None:
    """Reason to reject a pending / under-contract listing, if the user chose to skip them."""
    if market_status == "active" or profile.criteria.get("include_pending"):
        return None
    return (
        f"This listing is {PENDING_LABEL.get(market_status, market_status)}. "
        "You chose to skip pending and under-contract listings."
    )


def _set_market_status(listing: Listing, status: str, run_id: int | None, changes: RunChanges):
    if listing.market_status != status:
        _event(listing, run_id, "status_change", listing.market_status, status)
        changes.status_changes.append(
            {"listing": _label(listing), "old": listing.market_status, "new": status}
        )
        listing.market_status = status


def _reject(
    listing: Listing, run_id: int | None, reason: str, changes: RunChanges, notes: str = ""
) -> None:
    listing.listing_state = REJECTED
    listing.reject_reason = reason
    listing.removed_reason = None
    if notes:
        listing.condition_notes = notes
    _event(listing, run_id, "rejected", note=reason)
    changes.rejected.append({"listing": _label(listing), "reason": reason})


def _agent_reason(reject_reason: str, notes: str) -> str:
    return reject_reason.strip() or notes.strip() or "Didn't meet your search rules."


def apply_check(
    session: Session,
    listing: Listing,
    check: ListingCheck,
    run_id: int | None,
    today: date,
    changes: RunChanges,
) -> None:
    """Update an existing active listing from a re-check of its page."""
    listing.last_checked = today
    if check.url and not listing.url:
        listing.url = check.url

    if check.status in ("pending", "contingent", "active"):
        _set_market_status(listing, check.status, run_id, changes)

    if check.status in ("sold", "off_market", "not_found"):
        listing.listing_state = REMOVED
        listing.removed_reason = check.status.replace("_", " ")
        if check.note:
            listing.removed_reason += f" ({check.note})"
        _event(listing, run_id, "removed", note=listing.removed_reason)
        changes.removed.append({"listing": _label(listing), "reason": listing.removed_reason})
        return

    if check.status == "unknown":
        # Couldn't load the page; keep the row but don't pretend we verified it.
        _event(listing, run_id, "check_failed", note=check.note)
        return

    if check.price is not None and listing.price is not None and check.price != listing.price:
        _event(listing, run_id, "price_change", listing.price, check.price)
        changes.price_changes.append(
            {"listing": _label(listing), "old": listing.price, "new": check.price}
        )
        listing.price = check.price
    elif check.price is not None:
        listing.price = check.price

    if listing.user_included:
        # The user vouched for this one; only a sale or delisting removes it.
        return

    problem = pending_problem(listing.profile, listing.market_status) or criteria_problem(
        listing.profile, listing.price, listing.acres
    )
    if problem:
        _reject(listing, run_id, problem, changes)
        return

    if check.condition == "reject":
        reason = _agent_reason(check.reject_reason, check.condition_notes)
        _reject(listing, run_id, reason, changes, check.condition_notes)
        return

    if check.condition in (GOOD, NEEDS_UPDATING) and check.condition != listing.condition:
        _event(listing, run_id, "condition_change", listing.condition, check.condition)
        if listing.condition != UNVERIFIED:
            changes.condition_changes.append(
                {"listing": _label(listing), "old": listing.condition, "new": check.condition}
            )
        listing.condition = check.condition
    if check.condition_notes and not listing.condition_notes:
        listing.condition_notes = check.condition_notes


def apply_found(
    session: Session,
    profile: SearchProfile,
    found: FoundListing,
    run_id: int | None,
    today: date,
    changes: RunChanges,
    excluded: set[str],
) -> Listing | None:
    """Record a listing the agent reported: a new match, a rejection (kept, with the
    reason, so the user can see what was left out), or an update to one we know."""
    key = address_key(found.address, found.city, found.state)
    if key in excluded:
        changes.skipped_excluded.append(f"{found.address}, {found.city}, {found.state}")
        return None

    problem = pending_problem(profile, found.market_status) or criteria_problem(
        profile, found.price, found.acres
    )
    if problem is None and found.condition == "reject":
        problem = _agent_reason(found.reject_reason, found.condition_notes)

    existing = session.scalar(
        select(Listing).where(Listing.profile_id == profile.id, Listing.address_key == key)
    )
    if existing is not None:
        return _update_existing(existing, found, problem, run_id, today, changes)

    listing = Listing(
        profile_id=profile.id,
        address_key=key,
        address=found.address,
        city=found.city,
        state=found.state.upper(),
        zip=found.zip,
        price=found.price,
        beds=found.beds,
        baths=found.baths,
        acres=found.acres,
        sqft=found.sqft,
        year_built=found.year_built,
        anchor=found.anchor,
        drive_hours=found.drive_hours,
        condition=UNVERIFIED if found.condition == "reject" else found.condition,
        condition_notes=found.condition_notes or "",
        url=found.url,
        listing_state=ACTIVE,
        market_status=found.market_status,
        first_seen=today,
        last_checked=today,
        first_seen_run_id=run_id,
    )
    session.add(listing)
    if problem:
        _reject(listing, run_id, problem, changes)
        return listing
    _event(listing, run_id, "added", new=found.price)
    changes.added.append(_label(listing))
    return listing


def _update_existing(
    existing: Listing,
    found: FoundListing,
    problem: str | None,
    run_id: int | None,
    today: date,
    changes: RunChanges,
) -> Listing | None:
    if existing.listing_state == DISMISSED:
        return None
    existing.last_checked = today
    _set_market_status(existing, found.market_status, run_id, changes)
    if found.price is not None and existing.price != found.price:
        if existing.price is not None:
            _event(existing, run_id, "price_change", existing.price, found.price)
            if existing.listing_state != REJECTED:
                changes.price_changes.append(
                    {"listing": _label(existing), "old": existing.price, "new": found.price}
                )
        existing.price = found.price

    if problem and not existing.user_included:
        if existing.listing_state == REJECTED:
            existing.reject_reason = problem  # still out; keep the latest reason
        elif existing.listing_state == REMOVED:
            _reject(existing, run_id, problem, changes, found.condition_notes)
        # An active listing is judged by its re-check, not by a search-page sighting.
        return existing

    if existing.listing_state == REJECTED:
        existing.listing_state = ACTIVE
        existing.reject_reason = None
        if found.condition != "reject":
            existing.condition = found.condition
        if found.condition_notes:
            existing.condition_notes = found.condition_notes
        _event(existing, run_id, "now_matches")
        changes.added.append(_label(existing))
    elif existing.listing_state == REMOVED:
        existing.listing_state = ACTIVE
        existing.removed_reason = None
        _event(existing, run_id, "relisted")
        changes.relisted.append(_label(existing))
    return existing


def include(session: Session, listing: Listing, reason: str) -> AgentFeedback:
    """The user overrides a rejection: list it, and save their reason as agent feedback."""
    feedback = AgentFeedback(
        profile_id=listing.profile_id,
        listing_id=listing.id,
        listing_label=_label(listing),
        agent_reason=listing.reject_reason or "",
        user_reason=reason.strip(),
    )
    session.add(feedback)
    listing.listing_state = ACTIVE
    listing.user_included = True
    listing.reject_reason = None
    if listing.condition == UNVERIFIED:
        listing.condition = GOOD
    _event(listing, None, "included", note=reason.strip())
    return feedback


def dismiss(session: Session, listing: Listing, reason: str, today: date) -> ExcludedAddress:
    """Rule a listing out: hide it and add its address to the exclusion list."""
    listing.listing_state = DISMISSED
    listing.removed_reason = reason
    _event(listing, None, "dismissed", note=reason)
    excl = session.scalar(
        select(ExcludedAddress).where(
            ExcludedAddress.profile_id == listing.profile_id,
            ExcludedAddress.address_key == listing.address_key,
        )
    )
    if excl is None:
        excl = ExcludedAddress(
            profile_id=listing.profile_id,
            address_key=listing.address_key,
            address=listing.address,
            city=listing.city,
            state=listing.state,
            reason=reason,
            excluded_on=today,
        )
        session.add(excl)
    return excl


def restore(session: Session, excl: ExcludedAddress) -> Listing | None:
    """Undo an exclusion. A dismissed listing goes back to active."""
    listing = session.scalar(
        select(Listing).where(
            Listing.profile_id == excl.profile_id, Listing.address_key == excl.address_key
        )
    )
    if listing is not None and listing.listing_state == DISMISSED:
        listing.listing_state = ACTIVE
        listing.removed_reason = None
        _event(listing, None, "restored")
    session.delete(excl)
    return listing
