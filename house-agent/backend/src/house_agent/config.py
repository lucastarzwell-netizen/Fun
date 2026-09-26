"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _default_db_url() -> str:
    return f"sqlite:///{_BACKEND_ROOT / 'data' / 'house_agent.db'}"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get("HOUSE_AGENT_DATABASE_URL", _default_db_url())
    )
    # County searches and condition re-reads: the judgement-heavy work.
    model: str = field(default_factory=lambda: os.environ.get("HOUSE_AGENT_MODEL", "claude-opus-5"))
    effort: str = field(default_factory=lambda: os.environ.get("HOUSE_AGENT_EFFORT", "medium"))
    # Quick status/price checks of tracked listings: a cheaper model is plenty. Must support
    # the same web tools (Claude Sonnet 5 or an Opus model; not Haiku).
    check_model: str = field(
        default_factory=lambda: os.environ.get("HOUSE_AGENT_CHECK_MODEL", "claude-sonnet-5")
    )
    check_effort: str = field(
        default_factory=lambda: os.environ.get("HOUSE_AGENT_CHECK_EFFORT", "low")
    )
    # County searches after a county's first one ("sweeps") work from results pages with a
    # smaller page budget and lower effort; new finds are then judged by `model`. Measured on
    # real runs, Opus at low effort was cheaper per page than Sonnet, so sweeps default to the
    # main model. HOUSE_AGENT_SWEEPS=0 makes every county search a full one.
    sweeps_enabled: bool = field(
        default_factory=lambda: os.environ.get("HOUSE_AGENT_SWEEPS", "1") != "0"
    )
    sweep_model: str = field(
        default_factory=lambda: os.environ.get(
            "HOUSE_AGENT_SWEEP_MODEL", os.environ.get("HOUSE_AGENT_MODEL", "claude-opus-5")
        )
    )
    sweep_effort: str = field(
        default_factory=lambda: os.environ.get("HOUSE_AGENT_SWEEP_EFFORT", "low")
    )
    sweep_fetches: int = field(default_factory=lambda: _int("HOUSE_AGENT_SWEEP_FETCHES", 10))
    # Site every county search starts with (if the search uses it and it isn't being
    # skipped): Redfin has the smallest pages and its links carry the buyer's filters.
    lead_site: str = field(
        default_factory=lambda: os.environ.get("HOUSE_AGENT_LEAD_SITE", "redfin")
    )
    # A site that blocked the agent in at least `blocked_share` of its last attempts (and at
    # least `blocked_min_tries` of them) is skipped, except every `blocked_retry_every` runs.
    blocked_min_tries: int = field(default_factory=lambda: _int("HOUSE_AGENT_BLOCKED_MIN_TRIES", 4))
    blocked_share: float = field(
        default_factory=lambda: float(os.environ.get("HOUSE_AGENT_BLOCKED_SHARE", "0.8"))
    )
    blocked_retry_every: int = field(
        default_factory=lambda: _int("HOUSE_AGENT_BLOCKED_RETRY_EVERY", 4)
    )
    # Each county also gets a full search with `model` every this many runs (staggered, so
    # about 1/N of counties per run), which also measures what sweeps miss. 0 = never.
    audit_every_runs: int = field(default_factory=lambda: _int("HOUSE_AGENT_AUDIT_EVERY", 4))
    # Most new sweep finds whose condition is read by `model` in the run that found them;
    # the rest wait for the next run.
    new_read_limit: int = field(default_factory=lambda: _int("HOUSE_AGENT_NEW_READ_LIMIT", 40))
    # Most text kept from each page the agent opens (tokens). Results pages list their
    # listings well before this; what's cut is mostly page footer and "similar homes".
    page_tokens: int = field(default_factory=lambda: _int("HOUSE_AGENT_PAGE_TOKENS", 25000))
    # Page opens per county search, and for counties that found nothing new in their last
    # `quiet_after_runs` searches.
    search_fetches: int = field(default_factory=lambda: _int("HOUSE_AGENT_SEARCH_FETCHES", 20))
    quiet_search_fetches: int = field(default_factory=lambda: _int("HOUSE_AGENT_QUIET_FETCHES", 10))
    quiet_after_runs: int = field(default_factory=lambda: _int("HOUSE_AGENT_QUIET_AFTER", 3))
    search_web_searches: int = field(
        default_factory=lambda: _int("HOUSE_AGENT_SEARCH_WEB_SEARCHES", 10)
    )
    # Tracked listings confirmed within this many days aren't checked again.
    recheck_days: int = field(default_factory=lambda: _int("HOUSE_AGENT_RECHECK_DAYS", 3))
    # Most listings re-read for condition per run (changed price/status first, then
    # listings whose condition couldn't be read yet).
    relabel_limit: int = field(default_factory=lambda: _int("HOUSE_AGENT_RELABEL_LIMIT", 12))
    # Comma-separated list of origins allowed to call the API (the Vite dev server by default).
    cors_origins: list[str] = field(
        default_factory=lambda: [
            origin
            for origin in os.environ.get(
                "HOUSE_AGENT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if origin.strip()
        ]
    )
    # Set to "0" to disable the in-process scheduler (e.g. when an external cron calls the API).
    scheduler_enabled: bool = field(
        default_factory=lambda: os.environ.get("HOUSE_AGENT_SCHEDULER", "1") != "0"
    )
    # Listings per model call: condition re-reads, and quick status checks.
    check_batch_size: int = field(default_factory=lambda: _int("HOUSE_AGENT_CHECK_BATCH", 6))
    status_batch_size: int = field(default_factory=lambda: _int("HOUSE_AGENT_STATUS_BATCH", 8))


settings = Settings()
