"""Run one search profile end to end.

1. Search each county. Tracked listings seen on results pages are confirmed there.
2. Quick status checks (cheaper model) for tracked listings the searches didn't show.
3. Re-read condition only for listings whose price or status changed, or never read.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from ..links import LinkPolicy, live_sources, site_reliability
from ..models import (
    ACTIVE,
    REJECTED,
    UNVERIFIED,
    AgentFeedback,
    ExcludedAddress,
    Listing,
    Run,
    SearchProfile,
)
from ..notify import email_run_summary
from ..reconcile import RunChanges, apply_check, apply_found, apply_sighting, excluded_keys
from ..schemas import Criteria
from .claude_agent import AgentError, ClaudeSearchAgent, SearchAgent
from .sources import site_plan, sites_for
from .types import ListingCheck

log = logging.getLogger(__name__)

FINISHED = ("succeeded", "partial", "failed", "cancelled")

_running: set[int] = set()
_running_lock = threading.Lock()


# Runs the user asked to stop. Checked between steps, so the model call in flight finishes
# first (usually well under a couple of minutes).
_stop_requested: set[int] = set()


def request_stop(run_id: int) -> None:
    with _running_lock:
        _stop_requested.add(run_id)


def stop_requested(run_id: int) -> bool:
    with _running_lock:
        return run_id in _stop_requested


def is_running(profile_id: int) -> bool:
    with _running_lock:
        return profile_id in _running


def _now() -> datetime:
    return datetime.now(UTC)


def _today(profile: SearchProfile) -> date:
    return datetime.now(ZoneInfo(profile.timezone)).date()


class _Log:
    def __init__(self, session: Session, run: Run):
        self.session, self.run, self.lines = session, run, []

    def __call__(self, msg: str) -> None:
        log.info("run %s: %s", self.run.id, msg)
        self.lines.append(f"{_now():%H:%M:%S} {msg}")
        self.run.log = "\n".join(self.lines)
        self.session.commit()


def _progress(session: Session, run: Run, phase: str, done: int, total: int, current: str) -> None:
    """Live progress for the dashboard; replaced by the final summary when the run ends."""
    run.summary = {"progress": {"phase": phase, "done": done, "total": total, "current": current}}
    session.commit()


def mark_interrupted_runs(session: Session) -> int:
    """Runs execute in-process, so a restart (e.g. a deploy) kills any run in flight.
    Called at startup to close those out instead of leaving them 'running' forever."""
    stale = list(session.scalars(select(Run).where(Run.status.in_(["queued", "running"]))))
    for run in stale:
        run.status = "failed"
        run.finished_at = _now()
        run.summary = {
            "errors": [
                "Interrupted because the server restarted (for example, a new deploy). "
                "Listings found before the restart were kept; run the search again to finish."
            ]
        }
    session.commit()
    return len(stale)


def create_run(session: Session, profile: SearchProfile, trigger: str) -> Run:
    run = Run(profile_id=profile.id, trigger=trigger, status="queued")
    session.add(run)
    session.commit()
    return run


def execute_run(session: Session, run_id: int, agent: SearchAgent | None = None) -> Run:
    run = session.get(Run, run_id)
    assert run is not None
    profile = run.profile
    with _running_lock:
        if profile.id in _running:
            run.status = "failed"
            run.summary = {"errors": ["Another run for this profile is in progress."]}
            session.commit()
            return run
        _running.add(profile.id)
    try:
        run = _execute(session, run, profile, agent or ClaudeSearchAgent())
    finally:
        with _running_lock:
            _running.discard(profile.id)
    try:
        email_run_summary(session, run)
    except Exception:  # an email problem must never fail the search
        log.exception("Run %s: emailing the summary failed", run.id)
    return run


def quiet_regions(session: Session, profile_id: int, current_run_id: int) -> set[str]:
    """Counties that found nothing new in each of their last few searches.

    They get a smaller page budget. Runs from before per-county stats were recorded don't
    count, so a county needs `quiet_after_runs` recorded searches before it can be quiet.
    """
    needed = settings.quiet_after_runs
    if needed <= 0:
        return set()
    history: dict[str, list[int]] = {}
    for run in session.scalars(
        select(Run)
        .where(
            Run.profile_id == profile_id,
            Run.id != current_run_id,
            Run.status.in_(["succeeded", "partial"]),
        )
        .order_by(Run.id.desc())
        .limit(needed * 3)
    ):
        for label, stats in ((run.summary or {}).get("region_stats") or {}).items():
            history.setdefault(label, []).append(int(stats.get("added", 0)))
    return {
        label
        for label, added in history.items()
        if len(added) >= needed and not any(added[:needed])
    }


def _item(listing: Listing, ref: int, links: LinkPolicy) -> dict:
    return {
        "ref": ref,
        "address": listing.address,
        "city": listing.city,
        "state": listing.state,
        "price": listing.price,
        "mls": listing.mls_number,
        "urls": [s.url for s in live_sources(listing, links)][:3],
    }


def _execute(session: Session, run: Run, profile: SearchProfile, agent: SearchAgent) -> Run:
    criteria = Criteria.model_validate(profile.criteria)
    criteria.feedback = [
        f"{f.listing_label}: you rejected it"
        + (f' ("{f.agent_reason}")' if f.agent_reason else "")
        + f'; the buyer included it anyway: "{f.user_reason}"'
        for f in session.scalars(
            select(AgentFeedback)
            .where(AgentFeedback.profile_id == profile.id)
            .order_by(AgentFeedback.id.desc())
            .limit(25)
        )
    ]
    today = _today(profile)
    changes = RunChanges()
    errors: list[str] = []
    skipped_regions: list[str] = []
    logline = _Log(session, run)
    links = LinkPolicy(site_reliability(session, profile.id), sites_for(criteria))
    steps = 0  # model calls attempted, to tell "some steps failed" from "everything failed"

    run.status = "running"
    run.started_at = _now()
    session.commit()

    # Tracked listings confirmed during this run (seen on a results page, or re-found), and
    # the ones whose price or status changed, whose condition gets re-read at the end.
    confirmed: set[int] = set()
    changed: set[int] = set()

    def note_change(listing: Listing, before: tuple) -> None:
        if listing.listing_state == ACTIVE and (listing.price, listing.market_status) != before:
            changed.add(listing.id)

    # 1. Search each county. Tracked listings the agent passes on results pages count as
    # checked, so most never need their own page opened.
    excluded = excluded_keys(session, profile.id)
    excluded_labels = [
        f"{e.address}, {e.city}, {e.state}"
        for e in session.scalars(
            select(ExcludedAddress).where(ExcludedAddress.profile_id == profile.id)
        )
    ]
    learned_ids = False
    # Which sites blocked each county last time, so they're tried last this time.
    previous = session.scalar(
        select(Run)
        .where(Run.profile_id == profile.id, Run.id != run.id, Run.status.in_(FINISHED))
        .order_by(Run.id.desc())
        .limit(1)
    )
    history: dict = (previous.summary or {}).get("site_status", {}) if previous else {}
    run_number = session.query(Run).filter(Run.profile_id == profile.id).count()
    quiet = quiet_regions(session, profile.id, run.id)
    site_status: dict[str, dict[str, list[str]]] = {}
    site_tally: dict[str, dict[str, int]] = {}
    region_stats: dict[str, dict] = {}
    for region_index, region in enumerate(criteria.regions):
        if stop_requested(run.id):
            break
        label = f"{region.name}, {region.state}"
        # Only this county's state and anchor, to keep the prompt short.
        tracked = list(
            session.scalars(
                select(Listing)
                .where(
                    Listing.profile_id == profile.id,
                    Listing.listing_state == ACTIVE,
                    Listing.state == region.state.upper(),
                    or_(Listing.anchor == region.anchor, Listing.anchor.is_(None)),
                )
                .order_by(Listing.id)
            )
        )
        rejected = [
            f"{a}, {c}, {st} (was ${p:,.0f})" if p is not None else f"{a}, {c}, {st}"
            for a, c, st, p in session.execute(
                select(Listing.address, Listing.city, Listing.state, Listing.price).where(
                    Listing.profile_id == profile.id,
                    Listing.listing_state == REJECTED,
                    Listing.state == region.state.upper(),
                )
            )
        ]
        last = history.get(label, {})
        if isinstance(last, list):  # older runs recorded only blocked sites
            last = {"blocked": last}
        plan = site_plan(
            criteria,
            region,
            run_number + region_index,
            used_last_time=set(last.get("used", [])),
            blocked_last_time=set(last.get("blocked", [])),
        )
        budget = settings.quiet_search_fetches if label in quiet else settings.search_fetches
        logline(
            f"Searching {label}" + (" (quiet county, smaller budget)" if label in quiet else "")
        )
        _progress(session, run, "search", region_index, len(criteria.regions), label)
        before_usage = agent.usage.snapshot()
        steps += 1
        try:
            result = agent.search_region(
                criteria,
                label,
                region.anchor,
                plan,
                [_item(t, t.id, links) for t in tracked],
                excluded_labels,
                rejected,
                fetch_budget=budget,
            )
        except AgentError as e:
            errors.append(f"{label}: {e}")
            skipped_regions.append(label)
            logline(f"{label} failed: {e}")
            continue
        if region.redfin_county_id is None and result.redfin_county_id:
            region.redfin_county_id = result.redfin_county_id
            learned_ids = True
        site_status[label] = {
            "used": sorted(set(result.sites_used)),
            "blocked": sorted(set(result.sites_blocked)),
        }
        for key in set(result.sites_used):
            site_tally.setdefault(key, {"used": 0, "blocked": 0})["used"] += 1
        for key in set(result.sites_blocked):
            site_tally.setdefault(key, {"used": 0, "blocked": 0})["blocked"] += 1
        if not result.region_checked:
            skipped_regions.append(label + (f" ({result.notes})" if result.notes else ""))

        by_id = {t.id: t for t in tracked}
        sightings = 0
        for sighting in result.seen_tracked:
            listing = by_id.get(sighting.ref)
            if listing is None or listing.id in confirmed:
                continue
            state_before = (listing.price, listing.market_status)
            apply_sighting(session, listing, sighting, run.id, today, changes, links)
            confirmed.add(listing.id)
            note_change(listing, state_before)
            sightings += 1

        added_before = len(changes.added)
        tracked_before = {t.id: (t.price, t.market_status) for t in tracked}
        for found in result.listings:
            if found.anchor is None:
                found.anchor = region.anchor
            listing = apply_found(session, profile, found, run.id, today, changes, excluded, links)
            if listing is not None and listing.id in tracked_before:
                # A tracked listing reported again: confirmed like a sighting.
                confirmed.add(listing.id)
                note_change(listing, tracked_before[listing.id])
        session.commit()
        region_stats[label] = {
            "added": len(changes.added) - added_before,
            "reported": len(result.listings),
            "seen_tracked": sightings,
            "fetch_budget": budget,
            "usage": agent.usage.since(before_usage),
        }
        logline(
            f"{label}: {len(result.listings)} candidates reported, "
            f"{sightings} tracked listings seen on results pages"
        )

    if learned_ids:
        # Save discovered county IDs so later runs open the results page directly.
        profile.criteria = criteria.model_dump(mode="json")
        session.commit()

    # 2. Quick status checks (cheaper model) for tracked listings the searches didn't show
    # and that weren't confirmed in the last few days.
    cutoff = today - timedelta(days=settings.recheck_days)
    active = list(
        session.scalars(
            select(Listing)
            .where(Listing.profile_id == profile.id, Listing.listing_state == ACTIVE)
            .order_by(Listing.id)
        )
    )
    to_check = [
        listing
        for listing in active
        if listing.id not in confirmed
        and listing.first_seen_run_id != run.id
        and not (listing.last_checked is not None and listing.last_checked > cutoff)
    ]
    skipped_recent = sum(
        1
        for listing in active
        if listing.id not in confirmed
        and listing.first_seen_run_id != run.id
        and listing not in to_check
    )
    if not stop_requested(run.id):
        logline(
            f"Status-checking {len(to_check)} tracked listings not seen in the searches "
            f"({len(confirmed)} seen, {skipped_recent} checked recently)"
        )
    batch = max(1, settings.status_batch_size)
    for start in range(0, len(to_check), batch):
        if stop_requested(run.id):
            break
        _progress(session, run, "recheck", start, len(to_check), "Checking tracked listings")
        chunk = to_check[start : start + batch]
        steps += 1
        try:
            result = agent.status_check(criteria, [_item(x, i, links) for i, x in enumerate(chunk)])
        except AgentError as e:
            errors.append(f"Status check batch {start // batch + 1}: {e}")
            logline(f"Status check batch failed: {e}")
            continue
        by_ref = {c.ref: c for c in result.checks}
        for i, listing in enumerate(chunk):
            status = by_ref.get(i)
            if status is None:
                continue
            state_before = (listing.price, listing.market_status)
            check = ListingCheck(
                ref=i,
                status=status.status,
                price=status.price,
                url=status.url,
                mls_number=status.mls_number,
                dead_urls=status.dead_urls,
                note=status.note,
            )
            apply_check(session, listing, check, run.id, today, changes, links)
            note_change(listing, state_before)
        session.commit()
        logline(f"Status-checked {min(start + batch, len(to_check))}/{len(to_check)}")

    # 3. Re-read condition, with the main model, only where it may have changed: price or
    # status changed this run, then listings whose condition couldn't be read yet.
    unverified = [
        listing.id
        for listing in session.scalars(
            select(Listing)
            .where(
                Listing.profile_id == profile.id,
                Listing.listing_state == ACTIVE,
                Listing.condition == UNVERIFIED,
                Listing.user_included.is_(False),
            )
            .order_by(Listing.id)
        )
    ]
    reread_ids = [*sorted(changed), *(i for i in unverified if i not in changed)]
    reread = [
        x
        for x in (session.get(Listing, i) for i in reread_ids[: max(0, settings.relabel_limit)])
        if x is not None and x.listing_state == ACTIVE
    ]
    if reread and not stop_requested(run.id):
        logline(f"Re-reading {len(reread)} listings for condition")
    batch = max(1, settings.check_batch_size)
    for start in range(0, len(reread), batch):
        if stop_requested(run.id):
            break
        _progress(session, run, "reread", start, len(reread), "Re-reading changed listings")
        chunk = reread[start : start + batch]
        steps += 1
        try:
            result = agent.check_listings(
                criteria, [_item(x, i, links) for i, x in enumerate(chunk)]
            )
        except AgentError as e:
            errors.append(f"Re-read batch {start // batch + 1}: {e}")
            logline(f"Re-read batch failed: {e}")
            continue
        by_ref = {c.ref: c for c in result.checks}
        for i, listing in enumerate(chunk):
            check = by_ref.get(i)
            if check is not None:
                apply_check(session, listing, check, run.id, today, changes, links)
        session.commit()

    run.summary = {
        **changes.as_dict(),
        "skipped_regions": skipped_regions,
        "errors": errors,
        "usage": agent.usage.as_dict(),
        "sites": site_tally,
        "site_status": site_status,
        "region_stats": region_stats,
        "checks": {
            "seen_in_search": len(confirmed),
            "status_checked": len(to_check),
            "skipped_recent": skipped_recent,
            "reread": len(reread),
        },
        "active_count": session.query(Listing)
        .filter(Listing.profile_id == profile.id, Listing.listing_state == ACTIVE)
        .count(),
    }
    run.status = "partial" if (errors or skipped_regions) else "succeeded"
    if errors and len(errors) >= steps:
        run.status = "failed"
    if stop_requested(run.id):
        run.status = "cancelled"
        with _running_lock:
            _stop_requested.discard(run.id)
    run.finished_at = _now()
    logline(f"Done: {run.status}")
    session.commit()
    return run


def start_run_in_background(session_factory: sessionmaker, profile_id: int, trigger: str) -> int:
    """Create a run row and execute it on a worker thread. Returns the run id."""
    with session_factory() as session:
        profile = session.get(SearchProfile, profile_id)
        if profile is None:
            raise ValueError(f"No profile {profile_id}")
        run_id = create_run(session, profile, trigger).id

    def work() -> None:
        with session_factory() as session:
            try:
                execute_run(session, run_id)
            except Exception as e:  # keep the thread from dying silently
                log.exception("Run %s crashed", run_id)
                run = session.get(Run, run_id)
                if run is not None:
                    run.status = "failed"
                    run.finished_at = _now()
                    run.summary = {**(run.summary or {}), "errors": [f"Crashed: {e}"]}
                    session.commit()

    threading.Thread(target=work, name=f"run-{run_id}", daemon=True).start()
    return run_id
