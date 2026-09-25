"""Run one search profile end to end: re-check tracked listings, then search each region."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from ..models import ACTIVE, DISMISSED, ExcludedAddress, Listing, Run, SearchProfile
from ..reconcile import RunChanges, apply_check, apply_found, excluded_keys
from ..schemas import Criteria
from .claude_agent import AgentError, ClaudeSearchAgent, SearchAgent
from .sources import redfin_county_url

log = logging.getLogger(__name__)

_running: set[int] = set()
_running_lock = threading.Lock()


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
        return _execute(session, run, profile, agent or ClaudeSearchAgent())
    finally:
        with _running_lock:
            _running.discard(profile.id)


def _execute(session: Session, run: Run, profile: SearchProfile, agent: SearchAgent) -> Run:
    criteria = Criteria.model_validate(profile.criteria)
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
    batch = max(1, settings.check_batch_size)
    for start in range(0, len(active), batch):
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

    # 2. Search each region for new listings.
    excluded = excluded_keys(session, profile.id)
    excluded_labels = [
        f"{e.address}, {e.city}, {e.state}"
        for e in session.scalars(
            select(ExcludedAddress).where(ExcludedAddress.profile_id == profile.id)
        )
    ]
    for region in criteria.regions:
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
        url = redfin_county_url(region, criteria)
        logline(f"Searching {label}")
        try:
            result = agent.search_region(
                criteria, label, region.anchor, url, known, excluded_labels
            )
        except AgentError as e:
            errors.append(f"{label}: {e}")
            skipped_regions.append(label)
            logline(f"{label} failed: {e}")
            continue
        if not result.region_checked:
            skipped_regions.append(label + (f" ({result.notes})" if result.notes else ""))
        for found in result.listings:
            if found.anchor is None:
                found.anchor = region.anchor
            apply_found(session, profile, found, run.id, today, changes, excluded)
        session.commit()
        logline(f"{label}: {len(result.listings)} candidates reported")

    run.summary = {
        **changes.as_dict(),
        "skipped_regions": skipped_regions,
        "errors": errors,
        "usage": agent.usage.as_dict(),
        "active_count": session.query(Listing)
        .filter(Listing.profile_id == profile.id, Listing.listing_state == ACTIVE)
        .count(),
    }
    run.status = "partial" if (errors or skipped_regions) else "succeeded"
    if errors and len(errors) >= len(criteria.regions) + (len(active) + batch - 1) // batch:
        run.status = "failed"
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
