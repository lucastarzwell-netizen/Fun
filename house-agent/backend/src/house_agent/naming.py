"""Keep search names distinguishable.

Names that differ only by capitals, spacing or singular/plural ("Land near DCA" vs
"Lands near DCA") count as the same. A duplicate gets a date/time stamp, e.g.
"Land near DCA (Sep 25, 9:14 PM)", so the user can tell which is which.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import SearchProfile


def _singular(word: str) -> str:
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def norm(name: str) -> str:
    return " ".join(_singular(w) for w in name.casefold().split())


def stamp_label(when: datetime, tz: str) -> str:
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    if when.tzinfo is None:  # SQLite drops tzinfo; stored times are UTC
        when = when.replace(tzinfo=UTC)
    t = when.astimezone(zone)
    return f"{t:%b} {t.day}, {t.hour % 12 or 12}:{t:%M %p}"


def _with_stamp(name: str, label: str, taken: set[str]) -> str:
    candidate = f"{name} ({label})"
    n = 2
    while norm(candidate) in taken:  # two in the same minute
        candidate = f"{name} ({label} #{n})"
        n += 1
    return candidate


def unique_name(
    session: Session,
    owner_id: int,
    name: str,
    tz: str = "UTC",
    exclude_id: int | None = None,
    now: datetime | None = None,
) -> str:
    """Return `name`, or `name (Sep 25, 9:14 PM)` if the user already has one like it."""
    name = " ".join(name.split()) or "My search"
    q = select(SearchProfile.name).where(SearchProfile.owner_id == owner_id)
    if exclude_id is not None:
        q = q.where(SearchProfile.id != exclude_id)
    taken = {norm(n) for n in session.scalars(q)}
    if norm(name) not in taken:
        return name
    return _with_stamp(name, stamp_label(now or datetime.now(UTC), tz), taken)


def fix_existing_duplicates(session: Session) -> list[tuple[str, str]]:
    """One-time cleanup for searches created before names were kept unique: the oldest
    keeps its name, later look-alikes get their creation time. Returns (old, new) pairs."""
    renamed: list[tuple[str, str]] = []
    profiles = list(session.scalars(select(SearchProfile).order_by(SearchProfile.id)))
    by_owner: dict[int, list[SearchProfile]] = {}
    for p in profiles:
        by_owner.setdefault(p.owner_id, []).append(p)
    for owned in by_owner.values():
        taken = {norm(p.name) for p in owned}
        seen: set[str] = set()
        for p in sorted(owned, key=lambda p: (p.created_at, p.id)):
            key = norm(p.name)
            if key not in seen:
                seen.add(key)
                continue
            new = _with_stamp(p.name, stamp_label(p.created_at, p.timezone), taken)
            taken.add(norm(new))
            renamed.append((p.name, new))
            p.name = new
    if renamed:
        session.commit()
    return renamed
