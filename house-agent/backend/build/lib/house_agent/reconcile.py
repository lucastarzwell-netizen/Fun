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
    REMOVED,
    UNVERIFIED,
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
    condition_changes: list[dict] = field(default_factory=list)
    skipped_excluded: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "added": self.added,
            "removed": self.removed,
            "price_changes": self.price_changes,
            "relisted": self.relisted,
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


def _within_criteria(profile: SearchProfile, price: float | None, acres: float | None) -> bool:
    c = profile.criteria
    if price is not None:
        if c.get("min_price") is not None and price < c["min_price"]:
            return False
        if c.get("max_price") is not None and price > c["max_price"]:
            return False
    if acres is not None:
        if c.get("min_acres") is not None and acres < c["min_acres"]:
            return False
        if c.get("max_acres") is not None and acres > c["max_acres"]:
            return False
    return True


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

    if check.status in ("pending", "contingent", "sold", "off_market", "not_found"):
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

    if not _within_criteria(listing.profile, listing.price, listing.acres):
        listing.listing_state = REMOVED
        listing.removed_reason = "no longer matches criteria"
        _event(listing, run_id, "removed", note=listing.removed_reason)
        changes.removed.append({"listing": _label(listing), "reason": listing.removed_reason})
        return

    if check.condition == "reject":
        listing.listing_state = REMOVED
        listing.removed_reason = f"condition: {check.condition_notes or 'major repairs'}"
        _event(listing, run_id, "removed", note=listing.removed_reason)
        changes.removed.append({"listing": _label(listing), "reason": listing.removed_reason})
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
    """Add a newly found listing, or revive one that was previously removed."""
    key = address_key(found.address, found.city, found.state)
    if key in excluded:
        changes.skipped_excluded.append(f"{found.address}, {found.city}, {found.state}")
        return None
    if found.condition == "reject" or not _within_criteria(profile, found.price, found.acres):
        return None

    existing = session.scalar(
        select(Listing).where(Listing.profile_id == profile.id, Listing.address_key == key)
    )
    if existing is not None:
        if existing.listing_state == DISMISSED:
            return None
        if existing.listing_state == REMOVED:
            existing.listing_state = ACTIVE
            existing.removed_reason = None
            _event(existing, run_id, "relisted")
            changes.relisted.append(_label(existing))
        if found.price is not None and existing.price != found.price:
            if existing.price is not None:
                _event(existing, run_id, "price_change", existing.price, found.price)
                changes.price_changes.append(
                    {"listing": _label(existing), "old": existing.price, "new": found.price}
                )
            existing.price = found.price
        existing.last_checked = today
        return existing

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
        condition=found.condition,
        condition_notes=found.condition_notes or "",
        url=found.url,
        listing_state=ACTIVE,
        first_seen=today,
        last_checked=today,
        first_seen_run_id=run_id,
    )
    session.add(listing)
    _event(listing, run_id, "added", new=found.price)
    changes.added.append(_label(listing))
    return listing


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
