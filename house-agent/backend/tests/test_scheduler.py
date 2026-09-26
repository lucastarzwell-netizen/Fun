from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from house_agent.scheduler import cron_trigger

TZ = "America/New_York"
# Friday, Sep 25 2026, 5pm Eastern
NOW = datetime(2026, 9, 25, 17, 0, tzinfo=ZoneInfo(TZ))


def next_fire(expr: str) -> str:
    return cron_trigger(expr, TZ).get_next_fire_time(None, NOW).strftime("%a %b %d %H:%M")


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("0 7 * * 0", "Sun Sep 27 07:00"),  # standard cron: 0 = Sunday
        ("0 7 * * 7", "Sun Sep 27 07:00"),  # 7 = Sunday too
        ("0 7 * * 1", "Mon Sep 28 07:00"),
        ("0 7 * * 5", "Fri Oct 02 07:00"),  # today's 7am already passed
        ("30 18 * * 5", "Fri Sep 25 18:30"),
        ("0 7 * * 6", "Sat Sep 26 07:00"),
        ("0 9 * * 1-5", "Mon Sep 28 09:00"),  # weekdays
        ("0 9 * * 0,6", "Sat Sep 26 09:00"),  # weekends
        ("0 7 * * *", "Sat Sep 26 07:00"),  # daily
        ("0 7 * * sun", "Sun Sep 27 07:00"),  # names still work
    ],
)
def test_weekdays_follow_standard_cron(expr, expected):
    assert next_fire(expr) == expected


def test_bad_expression_rejected():
    with pytest.raises(ValueError):
        cron_trigger("0 7 * *", TZ)


# ---- every two weeks / monthly -----------------------------------------------------------

from datetime import date  # noqa: E402

from house_agent.scheduler import build_trigger, first_run_date  # noqa: E402


def fires(cron, every, anchor=None, count=4, now=NOW):
    trigger = build_trigger(cron, every, TZ, anchor)
    out, prev = [], None
    for _ in range(count):
        prev = trigger.get_next_fire_time(prev, now)
        out.append(prev.strftime("%a %b %d %H:%M"))
    return out


def test_every_two_weeks_counts_from_the_anchor():
    # Anchored on Fri Oct 2: Oct 2, Oct 16, Oct 30, Nov 13 (not Oct 9 or Oct 23).
    assert fires("0 7 * * 5", "2weeks", anchor=date(2026, 10, 2)) == [
        "Fri Oct 02 07:00",
        "Fri Oct 16 07:00",
        "Fri Oct 30 07:00",
        "Fri Nov 13 07:00",
    ]
    # Anchored a week later, the other Fridays.
    assert fires("0 7 * * 5", "2weeks", anchor=date(2026, 10, 9), count=2) == [
        "Fri Oct 09 07:00",
        "Fri Oct 23 07:00",
    ]


def test_first_run_date_is_the_next_matching_day():
    assert first_run_date("0 7 * * 5", TZ, NOW) == date(2026, 10, 2)  # today's 7am passed
    assert first_run_date("30 18 * * 5", TZ, NOW) == date(2026, 9, 25)  # later today


def test_monthly_uses_the_last_day_in_shorter_months():
    assert fires("0 7 31 * *", "month", count=6) == [
        "Wed Sep 30 07:00",  # September has 30 days
        "Sat Oct 31 07:00",
        "Mon Nov 30 07:00",
        "Thu Dec 31 07:00",
        "Sun Jan 31 07:00",
        "Sun Feb 28 07:00",  # 2027 isn't a leap year
    ]
    assert fires("0 7 15 * *", "month", count=2) == ["Thu Oct 15 07:00", "Sun Nov 15 07:00"]
    assert fires("0 7 29 * *", "month", count=6)[-1] == "Sun Feb 28 07:00"


def test_monthly_keeps_local_time_across_daylight_saving():
    # Nov 1 2026: clocks go back. Still 7am local on either side.
    assert fires("0 7 1 * *", "month", count=2) == ["Thu Oct 01 07:00", "Sun Nov 01 07:00"]


@pytest.mark.parametrize(
    "cron, every",
    [
        ("0 7 * * 1-5", "2weeks"),  # one weekday only
        ("0 7 * * *", "2weeks"),
        ("0 7 * * 5", "month"),  # monthly needs a date
        ("0 7 32 * *", "month"),
        ("0 25 1 * *", "month"),
    ],
)
def test_schedule_must_fit_its_frequency(cron, every):
    with pytest.raises(ValueError):
        build_trigger(cron, every, TZ)
