"""Who is making the request.

Single-user mode: every request acts as the default local user. If HOUSE_AGENT_PASSWORD is
set (it should be on any public deployment), requests must carry a signed session cookie,
obtained by POSTing the password to /api/auth/login.

A second password, HOUSE_AGENT_DEMO_PASSWORD, signs in a read-only "demo" session: it sees the
same searches and results but can't change anything or start anything that costs money
(enforced for every write request in main.py), and email addresses are hidden from it.

To add real logins later, replace `get_current_user` (e.g. verify an OAuth session and load
that user). Routes already scope data by `user.id`, so nothing else changes.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from contextvars import ContextVar

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .models import User

DEFAULT_EMAIL = os.environ.get("HOUSE_AGENT_USER_EMAIL", "me@localhost")
COOKIE = "house_agent_session"
SESSION_SECONDS = 30 * 24 * 3600


OWNER = "owner"
DEMO = "demo"


def _password() -> str:
    return os.environ.get("HOUSE_AGENT_PASSWORD", "")


def _demo_password() -> str:
    return os.environ.get("HOUSE_AGENT_DEMO_PASSWORD", "")


def _secret() -> bytes:
    explicit = os.environ.get("HOUSE_AGENT_SECRET")
    if explicit:
        return explicit.encode()
    # Fall back to a key derived from the password; changing the password signs everyone out.
    return hashlib.sha256(b"house-agent:" + _password().encode()).digest()


def _sign(expires: int, role: str = OWNER) -> str:
    # Owner tokens keep the original "expires.mac" form, so existing sessions stay valid.
    body = str(expires) if role == OWNER else f"{expires}.{role}"
    mac = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def _role(token: str | None) -> str | None:
    """The session's role if the token is genuine and unexpired, else None."""
    if not token or "." not in token:
        return None
    parts = token.split(".")
    expires = parts[0]
    role = parts[1] if len(parts) == 3 else OWNER
    if len(parts) not in (2, 3) or role not in (OWNER, DEMO) or not expires.isdigit():
        return None
    if int(expires) < time.time():
        return None
    if role == DEMO and not _demo_password():
        return None  # demo access switched off
    return role if hmac.compare_digest(token, _sign(int(expires), role)) else None


def _valid(token: str | None) -> bool:
    return _role(token) is not None


def session_role(request: Request) -> str:
    """OWNER or DEMO. With no password set the app is open and everyone is the owner."""
    if not _password():
        return OWNER
    return _role(request.cookies.get(COOKIE)) or OWNER


def is_demo(request: Request) -> bool:
    return bool(_password()) and _role(request.cookies.get(COOKIE)) == DEMO


# Set per request by main.py's middleware, so data-access helpers (api/deps.py) can limit a
# demo session to the searches the owner chose to show without every route passing it along.
demo_request: ContextVar[bool] = ContextVar("demo_request", default=False)


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
    demo: bool = False


@router.get("/me", response_model=AuthState)
def me(request: Request) -> AuthState:
    required = bool(_password())
    return AuthState(
        required=required,
        authenticated=not required or _valid(request.cookies.get(COOKIE)),
        demo=is_demo(request),
    )


@router.post("/login", response_model=AuthState)
def login(body: LoginIn, response: Response) -> AuthState:
    password = _password()
    if not password:
        return AuthState(required=False, authenticated=True)
    demo = _demo_password()
    if hmac.compare_digest(body.password.encode(), password.encode()):
        role = OWNER
    elif demo and hmac.compare_digest(body.password.encode(), demo.encode()):
        role = DEMO
    else:
        time.sleep(1)  # slow down guessing
        raise HTTPException(401, "Wrong password")
    expires = int(time.time()) + SESSION_SECONDS
    response.set_cookie(
        COOKIE,
        _sign(expires, role),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("HOUSE_AGENT_SECURE_COOKIES") == "1",
    )
    return AuthState(required=True, authenticated=True, demo=role == DEMO)


@router.post("/logout", response_model=AuthState)
def logout(response: Response) -> AuthState:
    response.delete_cookie(COOKIE)
    return AuthState(required=bool(_password()), authenticated=False)
