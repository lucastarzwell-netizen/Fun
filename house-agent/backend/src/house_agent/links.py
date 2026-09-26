"""Where a listing can be found: its MLS number and the sites it has been seen on.

A listing isn't tied to the URL it was first found at. Every sighting (county search,
status check, re-read) records the site and URL; the main link shown in the app and tried
first on re-checks is picked from the working ones, preferring sites that block the agent
least, then the most recently seen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent.sources import site_for_url, site_name
from .models import Listing, ListingEvent, ListingSource, Run

# How many recent runs' site tallies feed the reliability score.
RELIABILITY_RUNS = 8


def normalize_mls(value: str | None) -> str | None:
    """'MLS# 60012345' / 'mls #: 6001-2345' -> '60012345' / '6001-2345'. None if unusable."""
    if not value:
        return None
    text = re.sub(r"(?i)^\s*mls\s*®?\s*(number|no\.?)?\s*[#:]*\s*", "", value.strip())
    text = re.sub(r"[^A-Za-z0-9-]", "", text).upper().strip("-")
    return text if 3 <= len(text) <= 30 else None


@dataclass
class LinkPolicy:
    """How to rank a listing's links: per-site reliability (0-1) and the search's site order."""

    reliability: dict[str, float] = field(default_factory=dict)
    site_order: list[str] = field(default_factory=list)

    def rank(self, source: ListingSource) -> tuple:
        # Reliability in coarse steps so a small difference doesn't beat a fresher link.
        score = round(self.reliability.get(source.site, 0.5), 1)
        order = (
            self.site_order.index(source.site)
            if source.site in self.site_order
            else len(self.site_order)
        )
        return (-score, -source.last_seen.toordinal(), order, source.id or 0)


def site_reliability(session: Session, profile_id: int) -> dict[str, float]:
    """Share of recent county searches where each site let the agent in.

    Smoothed so a site with little history sits near 0.5 instead of 0 or 1.
    """
    used: dict[str, int] = {}
    blocked: dict[str, int] = {}
    runs = session.scalars(
        select(Run)
        .where(Run.profile_id == profile_id, Run.status.in_(["succeeded", "partial", "cancelled"]))
        .order_by(Run.id.desc())
        .limit(RELIABILITY_RUNS)
    )
    for run in runs:
        for key, tally in ((run.summary or {}).get("sites") or {}).items():
            used[key] = used.get(key, 0) + int(tally.get("used", 0))
            blocked[key] = blocked.get(key, 0) + int(tally.get("blocked", 0))
    return {
        key: (used.get(key, 0) + 1) / (used.get(key, 0) + blocked.get(key, 0) + 2)
        for key in set(used) | set(blocked)
    }


def _source_for(listing: Listing, site: str) -> ListingSource | None:
    return next((s for s in listing.sources if s.site == site), None)


def record_sighting(listing: Listing, url: str | None, today: date) -> ListingSource | None:
    """The listing was seen at `url`: add or refresh that site's link."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    url = url[:500]
    site = site_for_url(url)
    source = _source_for(listing, site)
    if source is None:
        source = ListingSource(site=site, url=url, first_seen=today, last_seen=today)
        listing.sources.append(source)
    else:
        source.url = url
        source.last_seen = max(source.last_seen, today)
        source.dead = False
    return source


def mark_dead(listing: Listing, url: str) -> None:
    """A link that no longer works (page gone, 'no longer available')."""
    for source in listing.sources:
        if source.url.rstrip("/") == url.rstrip("/"):
            source.dead = True


def live_sources(listing: Listing, policy: LinkPolicy) -> list[ListingSource]:
    """Working links, best first."""
    return sorted((s for s in listing.sources if not s.dead), key=policy.rank)


def update_primary(listing: Listing, policy: LinkPolicy, run_id: int | None) -> None:
    """Point the main link at the best working one; note the switch in the history."""
    ranked = live_sources(listing, policy)
    if not ranked:
        return
    best = ranked[0]
    if listing.url == best.url:
        return
    if listing.url:
        old_site = site_for_url(listing.url)
        listing.events.append(
            ListingEvent(
                run_id=run_id,
                kind="link_changed",
                old_value=site_name(old_site),
                new_value=site_name(best.site),
                note=best.url,
            )
        )
    listing.url = best.url


def set_mls(listing: Listing, value: str | None, run_id: int | None) -> None:
    mls = normalize_mls(value)
    if mls is None or mls == listing.mls_number:
        return
    if listing.mls_number:
        # A new number at the same address usually means it was withdrawn and relisted.
        listing.events.append(
            ListingEvent(
                run_id=run_id,
                kind="mls_changed",
                old_value=listing.mls_number,
                new_value=mls,
                note="New MLS number: usually means the listing was withdrawn and relisted.",
            )
        )
    listing.mls_number = mls


def backfill_sources(session: Session) -> int:
    """Listings saved before per-site links existed: file their URL as their first link."""
    count = 0
    for listing in session.scalars(
        select(Listing).where(Listing.url.is_not(None), ~Listing.sources.any())
    ):
        seen = listing.last_checked or listing.first_seen
        listing.sources.append(
            ListingSource(
                site=site_for_url(listing.url),
                url=listing.url[:500],
                first_seen=listing.first_seen,
                last_seen=seen,
            )
        )
        count += 1
    session.commit()
    return count
