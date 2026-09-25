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
