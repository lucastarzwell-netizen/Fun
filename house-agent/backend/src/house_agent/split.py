"""Split a search with several locations into separate searches.

The chosen locations move to a new search with their counties and listings (active,
rejected, removed and dismissed, each with its history and links). Excluded addresses and
the buyer's "Include anyway" feedback are copied, so both searches keep what the agent has
been taught. Past runs stay with the original search; the new one gets a "split" run that
carries its counties' history, so they keep their site rotation and go straight to sweeps
instead of being searched from scratch.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentFeedback, ExcludedAddress, Listing, Run, SearchProfile
from .naming import unique_name
from .schemas import Criteria


class SplitError(ValueError):
    pass


def _renamed(name: str, codes: list[str]) -> str | None:
    """'Houses near BOS, ORD, DTW' -> 'Houses near DTW' for the codes given; None when the
    name doesn't follow that pattern."""
    m = re.match(r"^(.*\bnear )([A-Z0-9 ,&]+?)(\s*\(.*\))?$", name)
    if not m:
        return None
    return m.group(1) + ", ".join(codes)


def split_profile(
    session: Session, profile: SearchProfile, codes: list[str], new_name: str | None = None
) -> SearchProfile:
    criteria = Criteria.model_validate(profile.criteria)
    all_codes = [a.code for a in criteria.anchors]
    moving = [c for c in all_codes if c in set(codes)]
    staying = [c for c in all_codes if c not in set(moving)]
    if not moving:
        raise SplitError("Pick at least one location to move.")
    if not staying:
        raise SplitError("Leave at least one location in this search.")

    def part(keep: list[str]) -> dict:
        c = criteria.model_copy(deep=True)
        c.anchors = [a for a in c.anchors if a.code in keep]
        c.regions = [r for r in c.regions if r.anchor in keep]
        return c.model_dump(mode="json")

    labels = {f"{r.name}, {r.state}" for r in criteria.regions if r.anchor in moving}
    new = SearchProfile(
        owner_id=profile.owner_id,
        name=unique_name(
            session,
            profile.owner_id,
            new_name or _renamed(profile.name, moving) or f"{profile.name} ({', '.join(moving)})",
            profile.timezone,
        ),
        criteria=part(moving),
        schedule_cron=profile.schedule_cron,
        schedule_every=profile.schedule_every,
        schedule_anchor=profile.schedule_anchor,
        timezone=profile.timezone,
        enabled=profile.enabled,
        demo_visible=profile.demo_visible,
        notify=profile.notify,
    )
    session.add(new)
    profile.criteria = part(staying)
    if (renamed := _renamed(profile.name, staying)) is not None:
        profile.name = unique_name(
            session, profile.owner_id, renamed, profile.timezone, exclude_id=profile.id
        )
    session.flush()

    for listing in session.scalars(
        select(Listing).where(Listing.profile_id == profile.id, Listing.anchor.in_(moving))
    ):
        listing.profile_id = new.id
    for excl in session.scalars(
        select(ExcludedAddress).where(ExcludedAddress.profile_id == profile.id)
    ):
        session.add(
            ExcludedAddress(
                profile_id=new.id,
                address_key=excl.address_key,
                address=excl.address,
                city=excl.city,
                state=excl.state,
                reason=excl.reason,
                excluded_on=excl.excluded_on,
            )
        )
    for fb in session.scalars(select(AgentFeedback).where(AgentFeedback.profile_id == profile.id)):
        session.add(
            AgentFeedback(
                profile_id=new.id,
                listing_id=fb.listing_id,
                listing_label=fb.listing_label,
                agent_reason=fb.agent_reason,
                user_reason=fb.user_reason,
                created_at=fb.created_at,
            )
        )

    # Carry the moved counties' history: whether they've had a full search, their latest
    # stats (for quiet-county budgets) and which sites they used or were blocked on.
    region_stats: dict[str, dict] = {}
    site_status: dict[str, dict] = {}
    for run in session.scalars(
        select(Run)
        .where(Run.profile_id == profile.id, Run.status.in_(["succeeded", "partial", "cancelled"]))
        .order_by(Run.id.desc())
        .limit(60)
    ):
        summary = run.summary or {}
        for label, stats in (summary.get("region_stats") or {}).items():
            if label not in labels:
                continue
            if label not in region_stats:
                region_stats[label] = {**stats, "usage": {}}
            if stats.get("tier", "full") == "full":
                region_stats[label]["tier"] = "full"
        for label, status in (summary.get("site_status") or {}).items():
            if label in labels and label not in site_status:
                site_status[label] = status
    now = datetime.now(UTC)
    session.add(
        Run(
            profile_id=new.id,
            trigger="split",
            status="succeeded",
            started_at=now,
            finished_at=now,
            summary={
                "split_from": profile.name,
                "listings_moved": session.query(Listing)
                .filter(Listing.profile_id == new.id)
                .count(),
                "region_stats": region_stats,
                "site_status": site_status,
            },
        )
    )
    session.commit()
    return new
