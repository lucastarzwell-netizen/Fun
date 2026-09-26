"""In-process scheduler: one job per enabled search profile.

Weekly (and daily or other cron) schedules use a cron trigger. Every-two-weeks and monthly
schedules use ScheduleTrigger, which cron can't express: every other week counted from a
fixed first date, and a day of the month that falls back to the month's last day.
"""

from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.base import BaseTrigger
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


class ScheduleTrigger(BaseTrigger):
    """Every two weeks on a weekday (cron numbering, 0 = Sunday), counted from `anchor`, or
    monthly on a day of the month (29-31 mean the month's last day in shorter months)."""

    def __init__(
        self, every: str, minute: int, hour: int, day: int, timezone: str, anchor: date | None
    ):
        self.every, self.minute, self.hour, self.day, self.anchor = every, minute, hour, day, anchor
        self.timezone = ZoneInfo(timezone)

    def _matches(self, d: date) -> bool:
        if self.every == "month":
            return d.day == min(self.day, calendar.monthrange(d.year, d.month)[1])
        if (d.weekday() + 1) % 7 != self.day:  # Python: Monday = 0
            return False
        return self.anchor is None or ((d - self.anchor).days // 7) % 2 == 0

    def get_next_fire_time(self, previous_fire_time, now):
        start = now.astimezone(self.timezone)
        if previous_fire_time is not None:
            start = max(start, previous_fire_time + timedelta(seconds=1))
        d = start.date()
        for _ in range(800):
            if self._matches(d):
                at = datetime(d.year, d.month, d.day, self.hour, self.minute, tzinfo=self.timezone)
                if at >= start:
                    return at
            d += timedelta(days=1)
        return None

    def __str__(self) -> str:
        return f"{self.every} day={self.day} {self.hour:02d}:{self.minute:02d} anchor={self.anchor}"


_WEEKDAY_TIME = re.compile(r"^(\d{1,2}) (\d{1,2}) \* \* ([0-7])$")
_MONTHDAY_TIME = re.compile(r"^(\d{1,2}) (\d{1,2}) (\d{1,2}) \* \*$")


def build_trigger(cron: str, every: str, timezone: str, anchor: date | None = None) -> BaseTrigger:
    """The trigger for a schedule; ValueError if the schedule doesn't fit its frequency."""
    if every == "week":
        return cron_trigger(cron, timezone)
    pattern = _MONTHDAY_TIME if every == "month" else _WEEKDAY_TIME
    m = pattern.match(cron.strip())
    if m is None or every not in ("2weeks", "month"):
        raise ValueError(
            "Monthly schedules need one day of the month; every-two-weeks schedules need one "
            "day of the week."
        )
    minute, hour, day = (int(x) for x in m.groups())
    if not (0 <= minute < 60 and 0 <= hour < 24):
        raise ValueError("Invalid time of day")
    if every == "month" and not 1 <= day <= 31:
        raise ValueError("Day of the month must be 1-31")
    return ScheduleTrigger(
        every, minute, hour, day % 7 if every == "2weeks" else day, timezone, anchor
    )


def first_run_date(cron: str, timezone: str, now: datetime | None = None) -> date | None:
    """For an every-two-weeks schedule: the date of its next run from now, which becomes the
    anchor the fortnights are counted from."""
    trigger = build_trigger(cron, "2weeks", timezone)
    fire = trigger.get_next_fire_time(None, now or datetime.now(trigger.timezone))
    return fire.date() if fire else None


def trigger_for(profile: SearchProfile) -> BaseTrigger | None:
    if not profile.enabled or not profile.schedule_cron.strip():
        return None
    return build_trigger(
        profile.schedule_cron,
        profile.schedule_every or "week",
        profile.timezone,
        profile.schedule_anchor,
    )


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
