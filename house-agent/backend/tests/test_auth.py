from fastapi.testclient import TestClient

from house_agent.main import app


def test_open_when_no_password(monkeypatch):
    monkeypatch.delenv("HOUSE_AGENT_PASSWORD", raising=False)
    with TestClient(app) as client:
        assert client.get("/api/auth/me").json() == {
            "required": False,
            "authenticated": True,
            "demo": False,
        }
        assert client.get("/api/profiles").status_code == 200


def test_password_gate(monkeypatch):
    monkeypatch.setenv("HOUSE_AGENT_PASSWORD", "hunter2-long")
    monkeypatch.setattr("house_agent.auth.time.sleep", lambda s: None)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/profiles").status_code == 401
        assert client.post("/api/wizard/regions", json={"anchors": []}).status_code in (401, 422)
        assert client.get("/api/auth/me").json() == {
            "required": True,
            "authenticated": False,
            "demo": False,
        }

        assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
        assert client.get("/api/profiles").status_code == 401

        r = client.post("/api/auth/login", json={"password": "hunter2-long"})
        assert r.status_code == 200 and "house_agent_session" in r.cookies
        assert client.get("/api/profiles").status_code == 200

        client.cookies.set("house_agent_session", "9999999999.forged")
        assert client.get("/api/profiles").status_code == 401

        client.post("/api/auth/login", json={"password": "hunter2-long"})
        client.post("/api/auth/logout")
        client.cookies.clear()
        assert client.get("/api/profiles").status_code == 401


def test_changing_password_invalidates_sessions(monkeypatch):
    monkeypatch.setenv("HOUSE_AGENT_PASSWORD", "first-password")
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"password": "first-password"})
        assert client.get("/api/profiles").status_code == 200
        monkeypatch.setenv("HOUSE_AGENT_PASSWORD", "second-password")
        assert client.get("/api/profiles").status_code == 401


def test_demo_password_is_read_only_and_hides_email(monkeypatch, session):
    from house_agent.auth import ensure_default_user
    from house_agent.models import Run, SearchProfile

    monkeypatch.setenv("HOUSE_AGENT_PASSWORD", "owner-password")
    monkeypatch.setenv("HOUSE_AGENT_DEMO_PASSWORD", "demo-password")
    user = ensure_default_user(session)
    profile = SearchProfile(
        owner_id=user.id,
        name="Mine",
        criteria={},
        notify={"email_enabled": True, "email_to": ["me@example.com"], "top_n": 5},
        demo_visible=True,
    )
    hidden = SearchProfile(owner_id=user.id, name="Private", criteria={})
    session.add_all([profile, hidden])
    session.flush()
    session.add(Run(profile_id=hidden.id, status="succeeded", summary={}))
    session.add(
        Run(
            profile_id=profile.id,
            status="succeeded",
            summary={"email": "Summary emailed to me@example.com"},
        )
    )
    session.commit()

    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"password": "demo-password"})
        assert r.status_code == 200 and r.json()["demo"] is True
        assert client.get("/api/auth/me").json()["demo"] is True

        # Only the searches the owner chose to show...
        profiles = client.get("/api/profiles").json()
        assert [p["name"] for p in profiles] == ["Mine"]
        for path in (
            f"/api/profiles/{hidden.id}",
            f"/api/profiles/{hidden.id}/listings",
            f"/api/profiles/{hidden.id}/runs",
            f"/api/profiles/{hidden.id}/stats",
        ):
            assert client.get(path).status_code == 404, path
        # ...without the owner's email addresses.
        assert profiles[0]["notify"]["email_to"] == [] and profiles[0]["email_hidden"] is True
        runs = client.get(f"/api/profiles/{profile.id}/runs").json()
        assert runs[0]["summary"]["email"] == "Summary emailed"
        assert "me@example.com" not in client.get(f"/api/runs/{runs[0]['id']}").text

        # Nothing can be changed or started.
        blocked = [
            client.post(f"/api/profiles/{profile.id}/runs"),
            client.post("/api/wizard/regions", json={"anchors": []}),
            client.post(f"/api/profiles/{profile.id}/test-email", json={"to": ["a@b.co"]}),
            client.delete(f"/api/profiles/{profile.id}"),
            client.post("/api/profiles", json={"name": "x", "criteria": {}}),
        ]
        assert [b.status_code for b in blocked] == [403] * 5
        assert "read-only demo" in blocked[0].json()["detail"]

        # The owner password still gets full access.
        client.post("/api/auth/logout")
        client.post("/api/auth/login", json={"password": "owner-password"})
        assert client.get("/api/auth/me").json()["demo"] is False
        owner_view = client.get("/api/profiles").json()
        assert [p["name"] for p in owner_view] == ["Mine", "Private"]
        assert owner_view[0]["notify"]["email_to"] == ["me@example.com"]

    # Turning demo access off ends demo sessions.
    monkeypatch.delenv("HOUSE_AGENT_DEMO_PASSWORD")
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"password": "demo-password"}).status_code == 401
