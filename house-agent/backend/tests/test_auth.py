from fastapi.testclient import TestClient

from house_agent.main import app


def test_open_when_no_password(monkeypatch):
    monkeypatch.delenv("HOUSE_AGENT_PASSWORD", raising=False)
    with TestClient(app) as client:
        assert client.get("/api/auth/me").json() == {"required": False, "authenticated": True}
        assert client.get("/api/profiles").status_code == 200


def test_password_gate(monkeypatch):
    monkeypatch.setenv("HOUSE_AGENT_PASSWORD", "hunter2-long")
    monkeypatch.setattr("house_agent.auth.time.sleep", lambda s: None)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/profiles").status_code == 401
        assert client.post("/api/wizard/regions", json={"anchors": []}).status_code in (401, 422)
        assert client.get("/api/auth/me").json() == {"required": True, "authenticated": False}

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
