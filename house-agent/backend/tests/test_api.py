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
