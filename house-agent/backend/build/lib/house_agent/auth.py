"""Who is making the request.

Single-user mode: every request acts as the default local user. If HOUSE_AGENT_PASSWORD is
set (it should be on any public deployment), requests must carry a signed session cookie,
obtained by POSTing the password to /api/auth/login.

To add real logins later, replace `get_current_user` (e.g. verify an OAuth session and load
that user). Routes already scope data by `user.id`, so nothing else changes.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .models import User

DEFAULT_EMAIL = os.environ.get("HOUSE_AGENT_USER_EMAIL", "me@localhost")
COOKIE = "house_agent_session"
SESSION_SECONDS = 30 * 24 * 3600


def _password() -> str:
    return os.environ.get("HOUSE_AGENT_PASSWORD", "")


def _secret() -> bytes:
    explicit = os.environ.get("HOUSE_AGENT_SECRET")
    if explicit:
        return explicit.encode()
    # Fall back to a key derived from the password; changing the password signs everyone out.
    return hashlib.sha256(b"house-agent:" + _password().encode()).digest()


def _sign(expires: int) -> str:
    mac = hmac.new(_secret(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{mac}"


def _valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expires, _, _mac = token.partition(".")
    if not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(token, _sign(int(expires)))


def ensure_default_user(session: Session) -> User:
    user = session.scalar(select(User).where(User.email == DEFAULT_EMAIL))
    if user is None:
        user = User(email=DEFAULT_EMAIL, display_name="Me")
        session.add(user)
        session.commit()
    return user


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    if _password() and not _valid(request.cookies.get(COOKIE)):
        raise HTTPException(401, "Sign in required")
    return ensure_default_user(session)


# ---- routes -----------------------------------------------------------------------------

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str


class AuthState(BaseModel):
    required: bool
    authenticated: bool


@router.get("/me", response_model=AuthState)
def me(request: Request) -> AuthState:
    required = bool(_password())
    return AuthState(
        required=required, authenticated=not required or _valid(request.cookies.get(COOKIE))
    )


@router.post("/login", response_model=AuthState)
def login(body: LoginIn, response: Response) -> AuthState:
    password = _password()
    if not password:
        return AuthState(required=False, authenticated=True)
    if not hmac.compare_digest(body.password.encode(), password.encode()):
        time.sleep(1)  # slow down guessing
        raise HTTPException(401, "Wrong password")
    expires = int(time.time()) + SESSION_SECONDS
    response.set_cookie(
        COOKIE,
        _sign(expires),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("HOUSE_AGENT_SECURE_COOKIES") == "1",
    )
    return AuthState(required=True, authenticated=True)


@router.post("/logout", response_model=AuthState)
def logout(response: Response) -> AuthState:
    response.delete_cookie(COOKIE)
    return AuthState(required=bool(_password()), authenticated=False)
