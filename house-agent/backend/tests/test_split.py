"""Splitting a search with several locations into separate searches."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from house_agent.agent.runner import county_history
from house_agent.auth import ensure_default_user
from house_agent.main import app
from house_agent.models import (
    AgentFeedback,
    ExcludedAddress,
    Listing,
    ListingEvent,
    Run,
    SearchProfile,
)
from house_agent.split import SplitError, split_profile

CRITERIA = {
    "min_price": 100000,
    "max_price": 175000,
    "anchors": [
        {"code": "DTW", "name": "Detroit Metro Airport", "max_drive_hours": 2},
        {"code": "ORD", "name": "Chicago O'Hare", "max_drive_hours": 2},
    ],
    "regions": [
        {"name": "Lenawee County", "state": "MI", "anchor": "DTW"},
        {"name": "Kane County", "state": "IL", "anchor": "ORD"},
    ],
}


def _setup(session):
    user = ensure_default_user(session)
    profile = SearchProfile(owner_id=user.id, name="Houses near DTW, ORD", criteria=CRITERIA)
    session.add(profile)
    session.flush()
    for address, state, anchor, listing_state in [
        ("1 Farm Rd", "MI", "DTW", "active"),
        ("2 Prairie Rd", "IL", "ORD", "active"),
        ("3 Wreck Rd", "IL", "ORD", "rejected"),
    ]:
        listing = Listing(
            profile_id=profile.id,
            address_key=address.lower(),
            address=address,
            city="X",
            state=state,
            anchor=anchor,
            listing_state=listing_state,
            first_seen=date.today(),
        )
        listing.events.append(ListingEvent(kind="added"))
        session.add(listing)
    session.add(
        ExcludedAddress(
            profile_id=profile.id,
            address_key="9 old rd",
            address="9 Old Rd",
            city="X",
            state="IL",
            excluded_on=date.today(),
        )
    )
    session.add(
        AgentFeedback(
            profile_id=profile.id, listing_label="L", agent_reason="a", user_reason="TLC is fine"
        )
    )
    session.add(
        Run(
            profile_id=profile.id,
            status="succeeded",
            summary={
                "region_stats": {
                    "Lenawee County, MI": {"added": 1, "tier": "full"},
                    "Kane County, IL": {"added": 0, "tier": "full"},
                },
                "site_status": {"Kane County, IL": {"used": ["zillow"], "blocked": ["redfin"]}},
            },
        )
    )
    session.commit()
    return profile


def test_split_moves_locations_counties_and_listings(session):
    profile = _setup(session)
    new = split_profile(session, profile, ["ORD"])
    session.expire_all()

    assert new.name == "Houses near ORD"
    assert profile.name == "Houses near DTW"
    assert [a["code"] for a in new.criteria["anchors"]] == ["ORD"]
    assert [r["name"] for r in new.criteria["regions"]] == ["Kane County"]
    assert [a["code"] for a in profile.criteria["anchors"]] == ["DTW"]
    assert [r["name"] for r in profile.criteria["regions"]] == ["Lenawee County"]

    moved = {x.address: x for x in session.query(Listing).filter_by(profile_id=new.id)}
    assert set(moved) == {"2 Prairie Rd", "3 Wreck Rd"}
    assert moved["3 Wreck Rd"].listing_state == "rejected"
    assert len(moved["2 Prairie Rd"].events) == 1  # history goes with it
    assert session.query(Listing).filter_by(profile_id=profile.id).count() == 1

    # What the agent was taught applies to both searches.
    for p in (profile, new):
        assert session.query(ExcludedAddress).filter_by(profile_id=p.id).count() == 1
        assert session.query(AgentFeedback).filter_by(profile_id=p.id).count() == 1

    # The moved county keeps its history, so it goes straight to sweeps.
    history = county_history(session, new.id, current_run_id=0)
    assert history == {"Kane County, IL": {"full": True, "last_sweep": None}}
    split_run = session.query(Run).filter_by(profile_id=new.id).one()
    assert split_run.trigger == "split"
    assert split_run.summary["site_status"]["Kane County, IL"]["blocked"] == ["redfin"]


def test_split_needs_a_location_on_each_side(session):
    profile = _setup(session)
    with pytest.raises(SplitError):
        split_profile(session, profile, [])
    with pytest.raises(SplitError):
        split_profile(session, profile, ["DTW", "ORD"])


def test_split_api(session):
    profile = _setup(session)
    with TestClient(app) as client:
        r = client.post(
            f"/api/profiles/{profile.id}/split", json={"anchors": ["ORD"], "name": "Chicago"}
        )
        assert r.status_code == 201, r.text
        assert r.json()["name"] == "Chicago"
        names = {p["name"] for p in client.get("/api/profiles").json()}
        assert names == {"Chicago", "Houses near DTW"}
        bad = client.post(f"/api/profiles/{profile.id}/split", json={"anchors": ["DTW"]})
        assert bad.status_code == 422
