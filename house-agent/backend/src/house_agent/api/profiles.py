from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import notify, scheduler
from ..agent import runner
from ..auth import get_current_user, is_demo
from ..db import SessionLocal, get_session
from ..models import SearchProfile, User
from ..naming import unique_name
from ..schemas import NotifySettings, ProfileIn, ProfileOut, RunOut
from ..split import SplitError, split_profile
from .deps import last_finished_run, owned_profile

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _out(profile: SearchProfile, demo: bool = False) -> ProfileOut:
    out = ProfileOut.model_validate(profile)
    out.next_run_at = scheduler.next_run_at(profile)
    if demo:
        out.notify = out.notify.model_copy(update={"email_to": []})
        out.email_hidden = True
    return out


def _validate_cron(body: ProfileIn) -> None:
    if body.schedule_cron.strip():
        try:
            scheduler.build_trigger(body.schedule_cron, body.schedule_every, body.timezone)
        except Exception as e:
            raise HTTPException(422, f"Invalid schedule: {e}") from e


def _set_anchor(profile: SearchProfile, schedule_changed: bool) -> None:
    """Every-two-weeks schedules count fortnights from their first run's date. Keep that date
    while the schedule stays the same, so saving other settings doesn't shift the weeks."""
    if profile.schedule_every != "2weeks" or not profile.schedule_cron.strip():
        profile.schedule_anchor = None
    elif schedule_changed or profile.schedule_anchor is None:
        profile.schedule_anchor = scheduler.first_run_date(profile.schedule_cron, profile.timezone)


@router.get("", response_model=list[ProfileOut])
def list_profiles(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    demo = is_demo(request)
    q = select(SearchProfile).where(SearchProfile.owner_id == user.id)
    if demo:
        q = q.where(SearchProfile.demo_visible.is_(True))
    return [_out(p, demo) for p in session.scalars(q.order_by(SearchProfile.id))]


@router.post("", response_model=ProfileOut, status_code=201)
def create_profile(
    body: ProfileIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    _validate_cron(body)
    data = body.model_dump(mode="json")
    data["name"] = unique_name(session, user.id, body.name, body.timezone)
    profile = SearchProfile(owner_id=user.id, **data)
    _set_anchor(profile, schedule_changed=True)
    session.add(profile)
    session.commit()
    scheduler.sync_profile(profile)
    return _out(profile)


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(
    profile_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return _out(owned_profile(session, user, profile_id), is_demo(request))


@router.put("/{profile_id}", response_model=ProfileOut)
def update_profile(
    profile_id: int,
    body: ProfileIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    _validate_cron(body)
    profile = owned_profile(session, user, profile_id)
    data = body.model_dump(mode="json")
    data["name"] = unique_name(session, user.id, body.name, body.timezone, exclude_id=profile.id)
    before = (profile.schedule_cron, profile.schedule_every, profile.timezone)
    for key, value in data.items():
        setattr(profile, key, value)
    _set_anchor(
        profile, (profile.schedule_cron, profile.schedule_every, profile.timezone) != before
    )
    session.commit()
    scheduler.sync_profile(profile)
    return _out(profile)


@router.delete("/{profile_id}", status_code=204)
def delete_profile(
    profile_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    profile = owned_profile(session, user, profile_id)
    if runner.is_running(profile.id):
        raise HTTPException(409, "This search is running. Stop it first, then delete it.")
    scheduler.remove_profile(profile.id)
    session.delete(profile)
    session.commit()


class SplitIn(BaseModel):
    anchors: list[str]
    name: str | None = None


@router.post("/{profile_id}/split", response_model=ProfileOut, status_code=201)
def split(
    profile_id: int,
    body: SplitIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Move some of this search's locations (with their counties and listings) into a new
    search. Returns the new search."""
    profile = owned_profile(session, user, profile_id)
    if runner.is_running(profile.id):
        raise HTTPException(409, "This search is running. Stop it first, then split it.")
    try:
        new = split_profile(session, profile, body.anchors, (body.name or "").strip() or None)
    except SplitError as e:
        raise HTTPException(422, str(e)) from e
    scheduler.sync_profile(profile)
    scheduler.sync_profile(new)
    return _out(new)


@router.post("/{profile_id}/runs", response_model=RunOut, status_code=202)
def start_run(
    profile_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    profile = owned_profile(session, user, profile_id)
    if runner.is_running(profile.id):
        raise HTTPException(409, "A run is already in progress for this search")
    run_id = runner.start_run_in_background(SessionLocal, profile.id, "manual")
    from ..models import Run

    session.expire_all()
    return session.get(Run, run_id)


# ---- email summaries --------------------------------------------------------------------

email_router = APIRouter(prefix="/api", tags=["email"])


class TestEmailIn(BaseModel):
    to: list[str]


@email_router.get("/email/status")
def email_status(request: Request, user: User = Depends(get_current_user)) -> dict:
    cfg = notify.smtp_config()
    sender = cfg.sender if cfg and not is_demo(request) else None
    return {"configured": cfg is not None, "sender": sender}


@email_router.post("/profiles/{profile_id}/test-email")
def test_email(
    profile_id: int,
    body: TestEmailIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """Send the summary of this search's latest finished run (or an empty one) now."""
    profile = owned_profile(session, user, profile_id)
    try:
        to = NotifySettings(email_to=body.to).email_to
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if not to:
        raise HTTPException(422, "Add at least one email address")
    # With no finished run yet, preview with an empty run (not saved anywhere).
    run = last_finished_run(session, profile.id) or SimpleNamespace(
        id=-1, profile_id=profile.id, profile=profile, status="succeeded", summary={}
    )
    settings = NotifySettings.model_validate(profile.notify or {})
    subject, text, html_body = notify.build_summary(session, run, settings.top_n)
    try:
        notify.send_email(to, "[Test] " + subject, text, html_body)
    except notify.EmailError as e:
        raise HTTPException(503, str(e)) from e
    return {"sent_to": to}
