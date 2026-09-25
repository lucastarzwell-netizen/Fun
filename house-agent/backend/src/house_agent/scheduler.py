"""In-process scheduler: one cron job per enabled search profile."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from .agent.runner import start_run_in_background
from .db import SessionLocal
from .models import SearchProfile

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job_id(profile_id: int) -> str:
    return f"profile-{profile_id}"


def _fire(profile_id: int) -> None:
    try:
        start_run_in_background(SessionLocal, profile_id, "schedule")
    except Exception:
        log.exception("Scheduled run for profile %s failed to start", profile_id)


_DAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def cron_trigger(expr: str, timezone: str) -> CronTrigger:
    """Build a trigger from a standard 5-field cron expression.

    Standard cron numbers weekdays 0-7 with 0 and 7 = Sunday, but APScheduler 3 numbers
    them 0 = Monday, so numeric weekdays would all fire a day late. Convert them to names.
    """
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"Expected 5 fields (minute hour day month weekday), got {len(fields)}")
    minute, hour, day, month, dow = fields
    dow = re.sub(r"\b[0-7]\b", lambda m: _DAY_NAMES[int(m.group())], dow)
    return CronTrigger(
        minute=minute, hour=hour, day=day, month=month, day_of_week=dow, timezone=timezone
    )


def trigger_for(profile: SearchProfile) -> CronTrigger | None:
    if not profile.enabled or not profile.schedule_cron.strip():
        return None
    return cron_trigger(profile.schedule_cron, profile.timezone)


def sync_profile(profile: SearchProfile) -> None:
    if _scheduler is None:
        return
    job_id = _job_id(profile.id)
    trigger = trigger_for(profile)
    if trigger is None:
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
        return
    _scheduler.add_job(
        _fire,
        trigger,
        args=[profile.id],
        id=job_id,
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=6 * 3600,
    )


def remove_profile(profile_id: int) -> None:
    if _scheduler is not None and _scheduler.get_job(_job_id(profile_id)):
        _scheduler.remove_job(_job_id(profile_id))


def next_run_at(profile: SearchProfile) -> datetime | None:
    if _scheduler is not None:
        job = _scheduler.get_job(_job_id(profile.id))
        return job.next_run_time if job else None
    trigger = trigger_for(profile)
    return trigger.get_next_fire_time(None, datetime.now(trigger.timezone)) if trigger else None


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.start()
    with SessionLocal() as session:
        for profile in session.scalars(select(SearchProfile)):
            sync_profile(profile)


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
