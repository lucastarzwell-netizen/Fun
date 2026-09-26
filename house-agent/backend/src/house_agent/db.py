"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover - trivial
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


# Columns added after the first release. create_all() makes new tables but never alters
# existing ones, so add these to databases created by older versions.
_ADDED_COLUMNS = {
    "search_profiles": {
        "notify": ("JSON",) * 2,
        "demo_visible": ("BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE"),
    },
    "listings": {
        "reject_reason": ("TEXT", "TEXT"),
        "user_included": ("BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE"),
        "market_status": ("VARCHAR(20) NOT NULL DEFAULT 'active'",) * 2,
        "drive_km": ("FLOAT",) * 2,
        "mls_number": ("VARCHAR(40)",) * 2,
    },
}


def _migrate(bind) -> None:
    insp = inspect(bind)
    sqlite = bind.dialect.name == "sqlite"
    with bind.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, (sqlite_type, other_type) in columns.items():
                if name not in have:
                    ddl = sqlite_type if sqlite else other_type
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db(bind=None) -> None:
    from . import models  # noqa: F401  (register tables)

    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    _migrate(bind)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
