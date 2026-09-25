import json

from fastapi.testclient import TestClient

from house_agent.main import app

SEED = {
    "profile": {
        "name": "Sample search",
        "criteria": {
            "min_price": 100000,
            "max_price": 175000,
            "min_acres": 1,
            "anchors": [{"code": "DTW", "name": "Detroit Metro Airport", "max_drive_hours": 2}],
            "regions": [{"name": "Lenawee County", "state": "MI", "anchor": "DTW"}],
        },
        "schedule_cron": "0 7 * * 5",
        "timezone": "America/New_York",
    },
    "listings": [
        {
            "status": "New this week",
            "airport": "DTW",
            "drive_hours": 1.0,
            "address": "1 Farm Rd",
            "city": "Adrian",
            "state": "MI",
            "price": 150000,
            "beds": 3,
            "baths": 1,
            "acres": 2,
            "condition_notes": "Built 1950",
            "link": "https://www.redfin.com/x",
            "first_seen": "2026-09-23",
            "last_checked": "2026-09-25",
            "reviewed": False,
        },
        {
            "status": "Active - needs updating",
            "airport": "DTW",
            "drive_hours": 1.2,
            "address": "2 Barn Rd",
            "city": "Adrian",
            "state": "MI",
            "price": 120000,
            "acres": 1.5,
            "first_seen": "2026-09-23",
            "reviewed": True,
        },
    ],
    "excluded": [
        {
            "address": "9 Old Rd",
            "city": "Adrian",
            "state": "MI",
            "reason": "Ruled out",
            "date_excluded": "2026-09-23",
        }
    ],
}


def _seed(tmp_path):
    from house_agent.auth import ensure_default_user
    from house_agent.db import SessionLocal
    from house_agent.importer import import_seed

    path = tmp_path / "seed.json"
    path.write_text(json.dumps(SEED))
    with SessionLocal() as s:
        return import_seed(s, ensure_default_user(s), path).id


def test_import_and_dashboard_endpoints(tmp_path):
    pid = _seed(tmp_path)
    with TestClient(app) as client:
        profiles = client.get("/api/profiles").json()
        assert [p["name"] for p in profiles] == ["Sample search"]
        assert profiles[0]["next_run_at"] is not None

        listings = client.get(f"/api/profiles/{pid}/listings").json()
        by_addr = {x["address"]: x for x in listings}
        assert by_addr["1 Farm Rd"]["is_new"] is True
        assert by_addr["2 Barn Rd"]["condition"] == "needs_updating"
        assert by_addr["2 Barn Rd"]["reviewed"] is True

        stats = client.get(f"/api/profiles/{pid}/stats").json()
        assert stats["active"] == 2 and stats["new_this_run"] == 1 and stats["excluded"] == 1

        lid = by_addr["1 Farm Rd"]["id"]
        assert client.patch(f"/api/listings/{lid}", json={"reviewed": True}).json()["reviewed"]

        excl = client.post(f"/api/listings/{lid}/dismiss", json={"reason": "Too small"}).json()
        assert excl["reason"] == "Too small"
        assert len(client.get(f"/api/profiles/{pid}/listings").json()) == 1
        assert len(client.get(f"/api/profiles/{pid}/excluded").json()) == 2

        # Restoring the exclusion brings the listing back.
        assert client.delete(f"/api/excluded/{excl['id']}").status_code == 204
        assert len(client.get(f"/api/profiles/{pid}/listings").json()) == 2

        detail = client.get(f"/api/listings/{lid}").json()
        assert [e["kind"] for e in detail["events"]] == ["imported", "dismissed", "restored"]


def test_profile_crud_and_validation():
    with TestClient(app) as client:
        body = {**SEED["profile"], "name": "Another"}
        created = client.post("/api/profiles", json=body)
        assert created.status_code == 201
        pid = created.json()["id"]

        bad = client.put(f"/api/profiles/{pid}", json={**body, "schedule_cron": "not cron"})
        assert bad.status_code == 422

        body["criteria"]["max_price"] = 200000
        assert (
            client.put(f"/api/profiles/{pid}", json=body).json()["criteria"]["max_price"] == 200000
        )
        assert client.delete(f"/api/profiles/{pid}").status_code == 204
        assert client.get(f"/api/profiles/{pid}").status_code == 404


def test_add_manual_exclusion():
    with TestClient(app) as client:
        pid = client.post("/api/profiles", json=SEED["profile"]).json()["id"]
        r = client.post(
            f"/api/profiles/{pid}/excluded",
            json={"address": "5 Lane Ct", "city": "Grass Lake", "state": "MI"},
        )
        assert r.status_code == 201
        assert client.get(f"/api/profiles/{pid}/excluded").json()[0]["address"] == "5 Lane Ct"


def test_stop_endpoint(tmp_path):
    from house_agent.db import SessionLocal
    from house_agent.models import Run

    pid = _seed(tmp_path)
    with SessionLocal() as s:
        run = Run(profile_id=pid, trigger="manual", status="running", summary={})
        s.add(run)
        s.commit()
        rid = run.id
    with TestClient(app) as client:
        # The app's startup closes runs left over from a previous process, so re-open it.
        with SessionLocal() as s:
            s.get(Run, rid).status = "running"
            s.commit()
        # Not executing in this process (left over): closed immediately.
        r = client.post(f"/api/runs/{rid}/stop")
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
        assert client.post(f"/api/runs/{rid}/stop").status_code == 409

        # Executing: flagged, and the runner stops at the next step.
        from house_agent.agent import runner

        with SessionLocal() as s:
            s.get(Run, rid).status = "running"
            s.commit()
        runner._running.add(pid)
        try:
            r = client.post(f"/api/runs/{rid}/stop")
            assert r.status_code == 200 and r.json()["stopping"] is True
            runs = client.get(f"/api/profiles/{pid}/runs").json()
            assert any(x["id"] == rid and x["stopping"] for x in runs)
        finally:
            runner._running.discard(pid)
        assert client.post("/api/runs/999/stop").status_code == 404


def test_rejected_tab_include_and_feedback(tmp_path):
    from house_agent.db import SessionLocal
    from house_agent.models import Listing

    pid = _seed(tmp_path)
    with SessionLocal() as s:
        row = s.query(Listing).filter_by(address="2 Barn Rd").one()
        row.listing_state = "rejected"
        row.reject_reason = "Listing says it needs a new roof."
        s.commit()
        lid = row.id
    with TestClient(app) as client:
        rejected = client.get(f"/api/profiles/{pid}/listings?state=rejected").json()
        assert [(x["address"], x["reject_reason"]) for x in rejected] == [
            ("2 Barn Rd", "Listing says it needs a new roof.")
        ]
        assert client.get(f"/api/profiles/{pid}/stats").json()["rejected"] == 1

        assert client.post(f"/api/listings/{lid}/include", json={"reason": "x"}).status_code == 422
        r = client.post(f"/api/listings/{lid}/include", json={"reason": "I'll replace the roof."})
        assert r.status_code == 200
        assert r.json()["listing_state"] == "active" and r.json()["user_included"] is True
        assert (
            client.post(f"/api/listings/{lid}/include", json={"reason": "again"}).status_code == 409
        )

        fb = client.get(f"/api/profiles/{pid}/feedback").json()
        assert fb[0]["agent_reason"] == "Listing says it needs a new roof."
        assert fb[0]["user_reason"] == "I'll replace the roof."
        assert client.delete(f"/api/feedback/{fb[0]['id']}").status_code == 204
        assert client.get(f"/api/profiles/{pid}/feedback").json() == []


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3

    from sqlalchemy import inspect

    from house_agent.db import init_db, make_engine

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)  # listings table as created by the first release
    con.execute(
        "CREATE TABLE listings (id INTEGER PRIMARY KEY, profile_id INTEGER, address_key "
        "VARCHAR(300), address VARCHAR(300), city VARCHAR(120), state VARCHAR(2), "
        "condition VARCHAR(20), condition_notes TEXT, listing_state VARCHAR(20), "
        "reviewed BOOLEAN, first_seen DATE)"
    )
    con.execute(
        "INSERT INTO listings (profile_id, address_key, address, city, state, condition, "
        "condition_notes, listing_state, reviewed, first_seen) "
        "VALUES (1, 'k', '1 A Rd', 'X', 'MI', 'good', '', 'active', 0, '2026-09-25')"
    )
    con.commit()
    con.close()
    engine = make_engine(f"sqlite:///{path}")
    init_db(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("listings")}
    assert {"reject_reason", "user_included", "market_status"} <= cols
    with engine.connect() as conn:
        from sqlalchemy import text

        row = conn.execute(text("SELECT user_included, market_status FROM listings")).one()
    assert tuple(row) == (0, "active")
    init_db(engine)  # running again is a no-op


def test_duplicate_search_names_get_a_number():
    with TestClient(app) as client:
        body = {**SEED["profile"], "name": "Land near DCA"}
        names = [client.post("/api/profiles", json=body).json()["name"] for _ in range(3)]
        assert names == ["Land near DCA", "Land near DCA 2", "Land near DCA 3"]

        # Case and spacing don't make a name different.
        r = client.post("/api/profiles", json={**body, "name": "  land  near dca "})
        assert r.json()["name"] == "land near dca 4"

        # Renaming onto a taken name gets a number too; keeping your own name doesn't.
        pid = client.post("/api/profiles", json={**body, "name": "Houses near BOS"}).json()["id"]
        assert client.put(f"/api/profiles/{pid}", json=body).json()["name"] == "Land near DCA 5"
        again = client.put(f"/api/profiles/{pid}", json={**body, "name": "Land near DCA 5"})
        assert again.json()["name"] == "Land near DCA 5"
