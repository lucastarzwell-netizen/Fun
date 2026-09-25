"""Import a search profile plus its listings and exclusions from a JSON seed file.

Seed format (see seed.example.json):
{
  "profile": {"name": ..., "criteria": {...}, "schedule_cron": ..., "timezone": ...},
  "listings": [{"status": "Active - needs updating", "airport": "DTW", "drive_hours": 1.2,
                "address": ..., "city": ..., "state": ..., "price": ..., "beds": ...,
                "baths": ..., "acres": ..., "condition_notes": ..., "link": ...,
                "first_seen": "2026-09-23", "last_checked": "2026-09-25",
                "reviewed": true}],
  "excluded": [{"address": ..., "city": ..., "state": ..., "reason": ...,
                "date_excluded": "2026-09-23"}]
}
Listing "status" uses the Google Sheet's values: Active, Active - needs updating,
New this week, Unverified.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .addresses import address_key
from .models import (
    ACTIVE,
    GOOD,
    NEEDS_UPDATING,
    UNVERIFIED,
    ExcludedAddress,
    Listing,
    ListingEvent,
    Run,
    SearchProfile,
    User,
)
from .schemas import ProfileIn

_CONDITION = {
    "active": GOOD,
    "new this week": GOOD,
    "active - needs updating": NEEDS_UPDATING,
    "unverified": UNVERIFIED,
}


def import_seed(session: Session, user: User, path: Path) -> SearchProfile:
    data = json.loads(path.read_text())
    body = ProfileIn.model_validate(data["profile"])
    profile = session.scalar(
        select(SearchProfile).where(
            SearchProfile.owner_id == user.id, SearchProfile.name == body.name
        )
    )
    if profile is None:
        profile = SearchProfile(owner_id=user.id, **body.model_dump(mode="json"))
        session.add(profile)
    else:
        for key, value in body.model_dump(mode="json").items():
            setattr(profile, key, value)
    session.flush()

    # A synthetic run marks the import, so rows flagged "New this week" show as new.
    now = datetime.now(UTC)
    run = Run(
        profile_id=profile.id,
        trigger="import",
        status="succeeded",
        started_at=now,
        finished_at=now,
        summary={"imported_from": path.name},
    )
    session.add(run)
    session.flush()

    added = 0
    for row in data.get("listings", []):
        key = address_key(row["address"], row["city"], row["state"])
        if session.scalar(
            select(Listing).where(Listing.profile_id == profile.id, Listing.address_key == key)
        ):
            continue
        status = row.get("status", "Active").strip().lower()
        listing = Listing(
            profile_id=profile.id,
            address_key=key,
            address=row["address"],
            city=row["city"],
            state=row["state"].upper(),
            price=row.get("price"),
            beds=row.get("beds"),
            baths=row.get("baths"),
            acres=row.get("acres"),
            anchor=row.get("airport"),
            drive_hours=row.get("drive_hours"),
            condition=_CONDITION.get(status, UNVERIFIED),
            condition_notes=row.get("condition_notes", ""),
            url=row.get("link"),
            listing_state=ACTIVE,
            reviewed=bool(row.get("reviewed", False)),
            first_seen=date.fromisoformat(row["first_seen"]),
            last_checked=date.fromisoformat(row["last_checked"])
            if row.get("last_checked")
            else None,
            first_seen_run_id=run.id if status == "new this week" else None,
        )
        listing.events.append(
            ListingEvent(run_id=run.id, kind="imported", new_value=str(row.get("price")))
        )
        session.add(listing)
        added += 1

    excluded = 0
    for row in data.get("excluded", []):
        key = address_key(row["address"], row["city"], row["state"])
        if session.scalar(
            select(ExcludedAddress).where(
                ExcludedAddress.profile_id == profile.id, ExcludedAddress.address_key == key
            )
        ):
            continue
        session.add(
            ExcludedAddress(
                profile_id=profile.id,
                address_key=key,
                address=row["address"],
                city=row["city"],
                state=row["state"].upper(),
                reason=row.get("reason", "Ruled out"),
                excluded_on=date.fromisoformat(
                    row.get("date_excluded") or date.today().isoformat()
                ),
            )
        )
        excluded += 1

    run.summary = {**run.summary, "listings_imported": added, "excluded_imported": excluded}
    session.commit()
    return profile
