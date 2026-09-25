"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _default_db_url() -> str:
    return f"sqlite:///{_BACKEND_ROOT / 'data' / 'house_agent.db'}"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get("HOUSE_AGENT_DATABASE_URL", _default_db_url())
    )
    # Model used by the search agent. Override with HOUSE_AGENT_MODEL.
    model: str = field(default_factory=lambda: os.environ.get("HOUSE_AGENT_MODEL", "claude-opus-5"))
    effort: str = field(default_factory=lambda: os.environ.get("HOUSE_AGENT_EFFORT", "high"))
    # Comma-separated list of origins allowed to call the API (the Vite dev server by default).
    cors_origins: list[str] = field(
        default_factory=lambda: os.environ.get(
            "HOUSE_AGENT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
    )
    # Set to "0" to disable the in-process scheduler (e.g. when an external cron calls the API).
    scheduler_enabled: bool = field(
        default_factory=lambda: os.environ.get("HOUSE_AGENT_SCHEDULER", "1") != "0"
    )
    # How many listings the agent re-checks per model call.
    check_batch_size: int = field(
        default_factory=lambda: int(os.environ.get("HOUSE_AGENT_CHECK_BATCH", "6"))
    )


settings = Settings()
