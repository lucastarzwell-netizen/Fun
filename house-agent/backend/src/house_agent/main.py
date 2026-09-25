"""FastAPI application."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import scheduler
from .agent.runner import mark_interrupted_runs
from .api import listings, profiles, wizard
from .auth import ensure_default_user
from .auth import router as auth_router
from .config import settings
from .db import SessionLocal, init_db
from .naming import fix_existing_duplicates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Built frontend (npm run build) is served from here when present.
FRONTEND_DIST = Path(
    os.environ.get(
        "HOUSE_AGENT_FRONTEND_DIST", Path(__file__).resolve().parents[3] / "frontend" / "dist"
    )
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log = logging.getLogger(__name__)
    with SessionLocal() as session:
        ensure_default_user(session)
        # Housekeeping must never keep the app from starting.
        try:
            if n := mark_interrupted_runs(session):
                log.warning("Closed %d run(s) interrupted by a restart", n)
            for old_name, new_name in fix_existing_duplicates(session):
                log.info("Renamed duplicate search %r to %r", old_name, new_name)
        except Exception:
            session.rollback()
            log.exception("Startup housekeeping failed; continuing")
    if settings.scheduler_enabled:
        scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="House Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(profiles.router)
app.include_router(listings.router)
app.include_router(wizard.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        file = FRONTEND_DIST / path
        if path and file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
