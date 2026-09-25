"""Email summaries after a search finishes.

Sending uses SMTP. Configure with environment variables (Gmail defaults shown):
  HOUSE_AGENT_SMTP_USER       the account to send from (e.g. you@gmail.com)
  HOUSE_AGENT_SMTP_PASSWORD   its password; for Gmail, an app password
  HOUSE_AGENT_SMTP_HOST       default smtp.gmail.com
  HOUSE_AGENT_SMTP_PORT       default 587 (STARTTLS); 465 uses SSL
  HOUSE_AGENT_EMAIL_FROM      the "From" address, e.g. an alias; default: the SMTP user.
                              Gmail only sends from the account or a verified "Send mail
                              as" alias, and swaps in the account address otherwise.
  HOUSE_AGENT_EMAIL_NAME      display name shown to recipients; default "House Agent"
  HOUSE_AGENT_PUBLIC_URL      link in the email; defaults to Render's RENDER_EXTERNAL_URL
"""

from __future__ import annotations

import html
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ACTIVE, Listing, Run, SearchProfile
from .schemas import NotifySettings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    sender_name: str


def smtp_config() -> SmtpConfig | None:
    user = os.environ.get("HOUSE_AGENT_SMTP_USER", "").strip()
    password = os.environ.get("HOUSE_AGENT_SMTP_PASSWORD", "").strip()
    if not user or not password:
        return None
    return SmtpConfig(
        host=os.environ.get("HOUSE_AGENT_SMTP_HOST", "smtp.gmail.com"),
        port=int(os.environ.get("HOUSE_AGENT_SMTP_PORT", "587")),
        user=user,
        password=password,
        sender=os.environ.get("HOUSE_AGENT_EMAIL_FROM", "").strip() or user,
        sender_name=os.environ.get("HOUSE_AGENT_EMAIL_NAME", "").strip() or "House Agent",
    )


def public_url() -> str:
    return (
        os.environ.get("HOUSE_AGENT_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or ""
    ).rstrip("/")


class EmailError(RuntimeError):
    pass


def send_email(to: list[str], subject: str, text: str, html_body: str) -> None:
    cfg = smtp_config()
    if cfg is None:
        raise EmailError("Email isn't set up on the server yet (SMTP user and password).")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg.sender_name, cfg.sender))
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    try:
        if cfg.port == 465:
            with smtplib.SMTP_SSL(
                cfg.host, cfg.port, context=ssl.create_default_context(), timeout=30
            ) as s:
                s.login(cfg.user, cfg.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(cfg.user, cfg.password)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise EmailError("The mail server rejected the SMTP user/password.") from e
    except (smtplib.SMTPException, OSError) as e:
        raise EmailError(f"Couldn't send email: {e}") from e


# ---- content ------------------------------------------------------------------------------


def _money(n: float | None) -> str:
    return "—" if n is None else f"${n:,.0f}"


def _facts(listing: Listing) -> str:
    parts = []
    if listing.beds is not None:
        parts.append(f"{listing.beds:g} bd")
    if listing.baths is not None:
        parts.append(f"{listing.baths:g} ba")
    if listing.acres is not None:
        parts.append(f"{listing.acres:g} acres")
    if listing.drive_hours is not None:
        drive = f"{listing.drive_hours:g} hr"
        if listing.drive_km is not None:
            drive += f" · {listing.drive_km:.0f} km"
        parts.append(f"{drive} to {listing.anchor}" if listing.anchor else drive)
    return " · ".join(parts)


def top_listings(session: Session, run: Run, n: int) -> tuple[list[Listing], list[Listing]]:
    """(new this run, other active listings not yet reviewed), together at most n."""
    new = list(
        session.scalars(
            select(Listing)
            .where(
                Listing.profile_id == run.profile_id,
                Listing.first_seen_run_id == run.id,
                Listing.listing_state == ACTIVE,
            )
            .order_by(Listing.price)
            .limit(n)
        )
    )
    others: list[Listing] = []
    if len(new) < n:
        others = list(
            session.scalars(
                select(Listing)
                .where(
                    Listing.profile_id == run.profile_id,
                    Listing.listing_state == ACTIVE,
                    Listing.reviewed.is_(False),
                    Listing.id.not_in([x.id for x in new] or [0]),
                )
                .order_by(Listing.first_seen.desc(), Listing.price)
                .limit(n - len(new))
            )
        )
    return new, others


def build_summary(session: Session, run: Run, top_n: int) -> tuple[str, str, str]:
    """Subject, plain text and HTML for a finished run."""
    profile: SearchProfile = run.profile
    s = run.summary or {}
    new, others = top_listings(session, run, top_n)
    added = len(s.get("added", []))
    price_changes = s.get("price_changes", [])
    removed = len(s.get("removed", []))
    rejected = len(s.get("rejected", []))
    status_note = {
        "partial": "Some areas couldn't be checked.",
        "failed": "The search ran into errors.",
    }.get(run.status, "")

    if added:
        subject = f"{added} new listing{'s' if added != 1 else ''} · {profile.name}"
    else:
        subject = f"No new listings this time · {profile.name}"

    stats = [
        f"{added} new",
        f"{len(price_changes)} price change{'s' if len(price_changes) != 1 else ''}",
        f"{removed} removed",
        f"{rejected} rejected",
    ]
    url = public_url()

    # Plain text
    lines = [f"{profile.name}: search finished.", " · ".join(stats)]
    if status_note:
        lines.append(status_note)
    for title, group in (("New this run", new), ("Still waiting for your review", others)):
        if group:
            lines += ["", title + ":"]
            for x in group:
                lines.append(
                    f"- {_money(x.price)}  {x.address}, {x.city}, {x.state}  ({_facts(x)})"
                )
                if x.condition_notes:
                    lines.append(f"  {x.condition_notes}")
                if x.url:
                    lines.append(f"  {x.url}")
    if price_changes:
        lines += ["", "Price changes:"]
        lines += [
            f"- {p['listing']}: {_money(p.get('old'))} -> {_money(p.get('new'))}"
            for p in price_changes
        ]
    if url:
        lines += ["", f"Open House Agent: {url}"]
    text = "\n".join(lines)

    # HTML
    e = html.escape

    def card(x: Listing) -> str:
        link = f'<a href="{e(x.url)}" style="color:#1f5f4a">View listing</a>' if x.url else ""
        notes = (
            f'<div style="color:#57534e;font-size:13px;margin-top:4px">{e(x.condition_notes)}</div>'
            if x.condition_notes
            else ""
        )
        return (
            '<div style="border:1px solid #e7e5e4;border-radius:10px;padding:12px 14px;'
            'margin:8px 0">'
            f'<div style="font-size:18px;font-weight:600">{_money(x.price)}</div>'
            f'<div style="font-weight:500">{e(x.address)}, {e(x.city)}, {e(x.state)}</div>'
            f'<div style="color:#57534e;font-size:13px">{e(_facts(x))}</div>{notes}'
            f'<div style="margin-top:6px;font-size:13px">{link}</div></div>'
        )

    sections = []
    for title, group in (("New this run", new), ("Still waiting for your review", others)):
        if group:
            sections.append(
                f'<h3 style="margin:18px 0 4px">{title}</h3>' + "".join(card(x) for x in group)
            )
    if price_changes:
        items = "".join(
            f"<li>{e(p['listing'])}: {_money(p.get('old'))} → {_money(p.get('new'))}</li>"
            for p in price_changes
        )
        sections.append(f'<h3 style="margin:18px 0 4px">Price changes</h3><ul>{items}</ul>')
    button = (
        f'<p style="margin-top:20px"><a href="{e(url)}" style="background:#1f5f4a;color:#fff;'
        'padding:10px 16px;border-radius:8px;text-decoration:none">Open House Agent</a></p>'
        if url
        else ""
    )
    html_body = (
        '<div style="font-family:Inter,Arial,sans-serif;color:#292524;max-width:560px">'
        f'<h2 style="margin:0 0 4px">{e(profile.name)}</h2>'
        f'<div style="color:#57534e">Search finished · {" · ".join(stats)}</div>'
        + (f'<div style="color:#b45309;margin-top:4px">{status_note}</div>' if status_note else "")
        + "".join(sections)
        + (
            ""
            if (new or others)
            else '<p style="color:#57534e">Nothing new to review this time.</p>'
        )
        + button
        + "</div>"
    )
    return subject, text, html_body


def email_run_summary(session: Session, run: Run) -> None:
    """Send the summary if this search has email turned on; record the outcome on the run."""
    settings = NotifySettings.model_validate(run.profile.notify or {})
    if not settings.email_enabled or not settings.email_to or run.status == "cancelled":
        return
    try:
        subject, text, html_body = build_summary(session, run, settings.top_n)
        send_email(settings.email_to, subject, text, html_body)
        outcome = f"Summary emailed to {', '.join(settings.email_to)}"
    except EmailError as e:
        outcome = f"Email not sent: {e}"
        log.warning("Run %s: %s", run.id, outcome)
    run.summary = {**(run.summary or {}), "email": outcome}
    session.commit()
