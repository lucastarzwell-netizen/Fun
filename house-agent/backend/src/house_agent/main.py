"""FastAPI application."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import scheduler
from .agent.runner import mark_interrupted_runs
from .api import listings, profiles, wizard
from .auth import demo_request, ensure_default_user, is_demo
from .auth import router as auth_router
from .config import settings
from .db import SessionLocal, init_db
from .links import backfill_sources
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
            if n := backfill_sources(session):
                log.info("Filed %d existing listing link(s) by site", n)
        except Exception:
            session.rollback()
            log.exception("Startup housekeeping failed; continuing")
    if settings.scheduler_enabled:
        scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="House Agent", lifespan=lifespan)


# Methods that only read. Anything else changes data or starts paid work (searches, county
# suggestions, test emails), which a demo session may not do.
_READ_ONLY = {"GET", "HEAD", "OPTIONS"}
_DEMO_ALLOWED = {"/api/auth/login", "/api/auth/logout"}


@app.middleware("http")
async def demo_is_read_only(request: Request, call_next):
    demo = is_demo(request)
    demo_request.set(demo)
    if (
        demo
        and request.method not in _READ_ONLY
        and request.url.path.startswith("/api/")
        and request.url.path not in _DEMO_ALLOWED
    ):
        return JSONResponse(
            {"detail": "This is a read-only demo: it can't change anything or run searches."},
            status_code=403,
        )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(profiles.router)
app.include_router(profiles.email_router)
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
        # Always revalidate the page itself so an update shows up on the next load
        # (the hashed JS/CSS files it points to can be cached forever).
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})
