from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import scheduler
from ..agent import runner
from ..auth import get_current_user
from ..db import SessionLocal, get_session
from ..models import SearchProfile, User
from ..naming import unique_name
from ..schemas import ProfileIn, ProfileOut, RunOut
from .deps import owned_profile

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _out(profile: SearchProfile) -> ProfileOut:
    out = ProfileOut.model_validate(profile)
    out.next_run_at = scheduler.next_run_at(profile)
    return out


def _validate_cron(body: ProfileIn) -> None:
    if body.schedule_cron.strip():
        try:
            scheduler.cron_trigger(body.schedule_cron, body.timezone)
        except Exception as e:
            raise HTTPException(422, f"Invalid schedule: {e}") from e


@router.get("", response_model=list[ProfileOut])
def list_profiles(session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    profiles = session.scalars(
        select(SearchProfile).where(SearchProfile.owner_id == user.id).order_by(SearchProfile.id)
    )
    return [_out(p) for p in profiles]


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
    session.add(profile)
    session.commit()
    scheduler.sync_profile(profile)
    return _out(profile)


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(
    profile_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return _out(owned_profile(session, user, profile_id))


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
    for key, value in data.items():
        setattr(profile, key, value)
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
    scheduler.remove_profile(profile.id)
    session.delete(profile)
    session.commit()


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
