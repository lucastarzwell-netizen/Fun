"""Run one search profile end to end: re-check tracked listings, then search each region."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from ..models import (
    ACTIVE,
    DISMISSED,
    REJECTED,
    AgentFeedback,
    ExcludedAddress,
    Listing,
    Run,
    SearchProfile,
)
from ..notify import email_run_summary
from ..reconcile import RunChanges, apply_check, apply_found, excluded_keys
from ..schemas import Criteria
from .claude_agent import AgentError, ClaudeSearchAgent, SearchAgent
from .sources import site_plan

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

    run.status = "running"
    run.started_at = _now()
    session.commit()

    # 1. Re-check everything currently active.
    active = list(
        session.scalars(
            select(Listing)
            .where(Listing.profile_id == profile.id, Listing.listing_state == ACTIVE)
            .order_by(Listing.id)
        )
    )
    logline(f"Re-checking {len(active)} tracked listings")
    if active:
        _progress(session, run, "recheck", 0, len(active), "Re-checking tracked listings")
    batch = max(1, settings.check_batch_size)
    for start in range(0, len(active), batch):
        if stop_requested(run.id):
            break
        chunk = active[start : start + batch]
        items = [
            {
                "ref": i,
                "address": listing.address,
                "city": listing.city,
                "state": listing.state,
                "price": listing.price,
                "url": listing.url,
            }
            for i, listing in enumerate(chunk)
        ]
        try:
            result = agent.check_listings(criteria, items)
        except AgentError as e:
            errors.append(f"Re-check batch {start // batch + 1}: {e}")
            logline(f"Re-check batch failed: {e}")
            continue
        by_ref = {c.ref: c for c in result.checks}
        for i, listing in enumerate(chunk):
            check = by_ref.get(i)
            if check is None:
                continue
            apply_check(session, listing, check, run.id, today, changes)
        session.commit()
        logline(f"Re-checked {min(start + batch, len(active))}/{len(active)}")
        _progress(
            session,
            run,
            "recheck",
            min(start + batch, len(active)),
            len(active),
            "Re-checking tracked listings",
        )

    # 2. Search each region for new listings.
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
    site_status: dict[str, dict[str, list[str]]] = {}
    site_tally: dict[str, dict[str, int]] = {}
    for region_index, region in enumerate(criteria.regions):
        if stop_requested(run.id):
            break
        label = f"{region.name}, {region.state}"
        known = [
            f"{a}, {c}, {s}"
            for a, c, s in session.execute(
                select(Listing.address, Listing.city, Listing.state).where(
                    Listing.profile_id == profile.id,
                    Listing.listing_state.in_([ACTIVE, DISMISSED]),
                )
            )
        ]
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
        logline(f"Searching {label}")
        _progress(
            session, run, "search", criteria.regions.index(region), len(criteria.regions), label
        )
        try:
            result = agent.search_region(
                criteria, label, region.anchor, plan, known, excluded_labels, rejected
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
        for found in result.listings:
            if found.anchor is None:
                found.anchor = region.anchor
            apply_found(session, profile, found, run.id, today, changes, excluded)
        session.commit()
        logline(f"{label}: {len(result.listings)} candidates reported")

    if learned_ids:
        # Save discovered county IDs so later runs open the results page directly.
        profile.criteria = criteria.model_dump(mode="json")

    run.summary = {
        **changes.as_dict(),
        "skipped_regions": skipped_regions,
        "errors": errors,
        "usage": agent.usage.as_dict(),
        "sites": site_tally,
        "site_status": site_status,
        "active_count": session.query(Listing)
        .filter(Listing.profile_id == profile.id, Listing.listing_state == ACTIVE)
        .count(),
    }
    run.status = "partial" if (errors or skipped_regions) else "succeeded"
    if errors and len(errors) >= len(criteria.regions) + (len(active) + batch - 1) // batch:
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
