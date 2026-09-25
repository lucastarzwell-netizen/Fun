"""Who is making the request.

Single-user mode for now: every request acts as the default local user. To add real
logins later, replace `get_current_user` (e.g. verify a session cookie or bearer token
and load that user). Routes already scope data by `user.id`, so nothing else changes.
"""

from __future__ import annotations

import os

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .models import User

DEFAULT_EMAIL = os.environ.get("HOUSE_AGENT_USER_EMAIL", "me@localhost")


def ensure_default_user(session: Session) -> User:
    user = session.scalar(select(User).where(User.email == DEFAULT_EMAIL))
    if user is None:
        user = User(email=DEFAULT_EMAIL, display_name="Me")
        session.add(user)
        session.commit()
    return user


def get_current_user(session: Session = Depends(get_session)) -> User:
    return ensure_default_user(session)
