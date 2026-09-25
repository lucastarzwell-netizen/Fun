import pytest
from fastapi.testclient import TestClient

from house_agent import notify
from house_agent.main import app
from house_agent.schemas import NotifySettings

from .fakes import FakeAgent
from .test_runner import _found, _listing, _profile, _run

SENT: list = []


class FakeSMTP:
    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        if password == "wrong":
            import smtplib

            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, msg):
        SENT.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    SENT.clear()
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("HOUSE_AGENT_SMTP_USER", "sender@gmail.com")
    monkeypatch.setenv("HOUSE_AGENT_SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("HOUSE_AGENT_EMAIL_FROM", "alerts@example.com")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://house-agent.example")
    return SENT


def _enable(session, profile, to, top_n=5):
    profile.notify = {"email_enabled": True, "email_to": to, "top_n": top_n}
    session.commit()


def test_addresses_validated_and_deduplicated():
    s = NotifySettings(email_to=[" a@x.com", "A@x.com", "", "b@y.org"])
    assert s.email_to == ["a@x.com", "b@y.org"]
    with pytest.raises(ValueError):
        NotifySettings(email_to=["not-an-email"])


def test_run_emails_summary_to_every_address_with_top_listings(session, smtp):
    profile = _profile(session)
    _enable(session, profile, ["me@example.com", "partner@example.com"], top_n=2)
    listings = [_found("1 A Rd", price=120000), _found("2 B Rd", price=110000), _found("3 C Rd")]
    run = _run(
        session,
        profile,
        FakeAgent(regions={"Lenawee County, MI": {"region_checked": True, "listings": listings}}),
    )
    assert len(smtp) == 1
    msg = smtp[0]
    assert msg["To"] == "me@example.com, partner@example.com"
    assert msg["From"] == "House Agent <alerts@example.com>"  # the alias, not the login
    assert msg["Subject"] == "3 new listings · Test"
    body = msg.get_body(("plain",)).get_content()
    # top_n=2: the two cheapest new listings, then nothing more
    assert "$110,000  2 B Rd" in body and "$120,000  1 A Rd" in body and "3 C Rd" not in body
    assert "https://house-agent.example" in body
    html_body = msg.get_body(("html",)).get_content()
    assert "New this run" in html_body and "Open House Agent" in html_body
    assert run.summary["email"] == "Summary emailed to me@example.com, partner@example.com"


def test_no_email_when_off_or_cancelled(session, smtp):
    profile = _profile(session)
    _run(session, profile, FakeAgent())
    assert smtp == []  # off by default

    from house_agent.agent.runner import create_run, execute_run, request_stop

    _enable(session, profile, ["me@example.com"])
    run = create_run(session, profile, "manual")
    request_stop(run.id)
    execute_run(session, run.id, FakeAgent())
    assert smtp == []  # stopped by the user


def test_email_problems_are_recorded_not_raised(session, monkeypatch, smtp):
    profile = _profile(session)
    _enable(session, profile, ["me@example.com"])
    monkeypatch.setenv("HOUSE_AGENT_SMTP_PASSWORD", "wrong")
    run = _run(session, profile, FakeAgent())
    assert run.status == "succeeded"
    assert run.summary["email"].startswith("Email not sent: The mail server rejected")

    monkeypatch.delenv("HOUSE_AGENT_SMTP_PASSWORD")
    run = _run(session, profile, FakeAgent())
    assert "isn't set up" in run.summary["email"]


def test_unreviewed_listings_fill_the_top_list(session, smtp):
    profile = _profile(session)
    regions = {"Lenawee County, MI": {"region_checked": True, "listings": [_found("1 Old Rd")]}}
    _run(session, profile, FakeAgent(regions=regions))
    _enable(session, profile, ["me@example.com"])
    _run(session, profile, FakeAgent())  # nothing new this time
    body = smtp[-1].get_body(("plain",)).get_content()
    assert smtp[-1]["Subject"] == "No new listings this time · Test"
    assert "Still waiting for your review:" in body and "1 Old Rd" in body
    _listing(session, profile, "1 Old Rd").reviewed = True
    session.commit()
    _run(session, profile, FakeAgent())
    assert "1 Old Rd" not in smtp[-1].get_body(("plain",)).get_content()


def test_email_endpoints(smtp, monkeypatch):
    with TestClient(app) as client:
        assert client.get("/api/email/status").json() == {
            "configured": True,
            "sender": "alerts@example.com",
        }
        body = {
            "name": "Mail test",
            "criteria": {"anchors": [], "regions": []},
            "notify": {"email_enabled": True, "email_to": ["me@example.com"], "top_n": 3},
        }
        created = client.post("/api/profiles", json=body).json()
        assert created["notify"]["email_to"] == ["me@example.com"]
        pid = created["id"]
        r = client.post(f"/api/profiles/{pid}/test-email", json={"to": ["me@example.com"]})
        assert r.status_code == 200 and smtp[-1]["Subject"].startswith("[Test] ")
        assert client.post(f"/api/profiles/{pid}/test-email", json={"to": []}).status_code == 422
        bad = {**body, "notify": {"email_enabled": True, "email_to": ["nope"]}}
        assert client.post("/api/profiles", json=bad).status_code == 422

        monkeypatch.delenv("HOUSE_AGENT_SMTP_USER")
        assert client.get("/api/email/status").json()["configured"] is False
        r = client.post(f"/api/profiles/{pid}/test-email", json={"to": ["me@example.com"]})
        assert r.status_code == 503 and "isn't set up" in r.json()["detail"]
