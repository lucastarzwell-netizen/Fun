from datetime import date

from sqlalchemy import select

from house_agent.agent.runner import create_run, execute_run
from house_agent.auth import ensure_default_user
from house_agent.models import ExcludedAddress, Listing, SearchProfile
from house_agent.reconcile import dismiss
from house_agent.schemas import Criteria

from .fakes import AgentError, FakeAgent

CRITERIA = Criteria.model_validate(
    {
        "min_price": 100000,
        "max_price": 175000,
        "min_acres": 1,
        "anchors": [{"code": "DTW", "name": "Detroit Metro Airport", "max_drive_hours": 2}],
        "regions": [
            {"name": "Lenawee County", "state": "MI", "anchor": "DTW", "redfin_county_id": 1393},
            {"name": "Monroe County", "state": "MI", "anchor": "DTW", "redfin_county_id": 1405},
        ],
    }
).model_dump(mode="json")


def _found(address, city="Adrian", price=150000, acres=2.0, condition="good"):
    return {
        "address": address,
        "city": city,
        "state": "MI",
        "price": price,
        "acres": acres,
        "condition": condition,
        "url": f"https://www.redfin.com/MI/{city}/{address.replace(' ', '-')}",
        "drive_hours": 1.0,
    }


def _profile(session):
    user = ensure_default_user(session)
    profile = SearchProfile(owner_id=user.id, name="Test", criteria=CRITERIA)
    session.add(profile)
    session.commit()
    return profile


def _run(session, profile, agent):
    return execute_run(session, create_run(session, profile, "manual").id, agent)


def _call(agent, label):
    """The agent's search call for one county (counties aren't searched in list order)."""
    return next(c for c in agent.search_calls if c["label"] == label)


def _listing(session, profile, address):
    return session.scalar(
        select(Listing).where(Listing.profile_id == profile.id, Listing.address == address)
    )


def test_first_run_adds_matches_and_skips_rejects(session):
    profile = _profile(session)
    agent = FakeAgent(
        regions={
            "Lenawee County, MI": {
                "region_checked": True,
                "listings": [
                    _found("1 Farm Rd"),
                    _found("2 Wreck Rd", condition="reject"),
                    _found("3 Pricey Rd", price=250000),
                    _found("4 Small Lot Rd", acres=0.5),
                    _found("5 Tlc Rd", condition="needs_updating"),
                ],
            }
        }
    )
    run = _run(session, profile, agent)
    assert run.status == "succeeded"
    assert sorted(run.summary["added"]) == ["1 Farm Rd, Adrian, MI", "5 Tlc Rd, Adrian, MI"]
    assert _listing(session, profile, "5 Tlc Rd").condition == "needs_updating"
    assert _listing(session, profile, "1 Farm Rd").first_seen_run_id == run.id
    # Every county gets all the house sites; Redfin's URL follows the routine's pattern.
    plan = dict(agent.search_calls[0]["plan"])
    assert set(plan) == {"redfin", "zillow", "realtor", "homes"}  # no LandWatch for houses
    assert plan["redfin"].startswith("https://www.redfin.com/county/1393/MI/Lenawee")


def test_recheck_handles_price_cuts_and_removals(session):
    profile = _profile(session)
    _run(
        session,
        profile,
        FakeAgent(
            regions={
                "Lenawee County, MI": {
                    "region_checked": True,
                    "listings": [_found("1 Farm Rd"), _found("2 Barn Rd"), _found("3 Creek Rd")],
                }
            }
        ),
    )
    run2 = _run(
        session,
        profile,
        FakeAgent(
            checks={
                "1 Farm Rd": {"status": "active", "price": 140000, "condition": "good"},
                "2 Barn Rd": {"status": "sold"},
                "3 Creek Rd": {"status": "unknown", "note": "429"},
            }
        ),
    )
    assert run2.summary["price_changes"] == [
        {"listing": "1 Farm Rd, Adrian, MI", "old": 150000, "new": 140000}
    ]
    assert run2.summary["removed"][0]["listing"] == "2 Barn Rd, Adrian, MI"
    session.expire_all()
    assert _listing(session, profile, "1 Farm Rd").price == 140000
    assert _listing(session, profile, "2 Barn Rd").listing_state == "removed"
    # A page that failed to load keeps the listing rather than dropping it.
    assert _listing(session, profile, "3 Creek Rd").listing_state == "active"


def test_price_rising_above_max_rejects_listing(session):
    profile = _profile(session)
    _run(
        session,
        profile,
        FakeAgent(
            regions={"Lenawee County, MI": {"region_checked": True, "listings": [_found("1 A Rd")]}}
        ),
    )
    run2 = _run(
        session, profile, FakeAgent(checks={"1 A Rd": {"status": "active", "price": 190000}})
    )
    assert run2.summary["rejected"] == [
        {
            "listing": "1 A Rd, Adrian, MI",
            "reason": "Price $190,000 is above your $175,000 maximum.",
        }
    ]
    assert _listing(session, profile, "1 A Rd").listing_state == "rejected"


def test_excluded_and_dismissed_never_come_back(session):
    profile = _profile(session)
    session.add(
        ExcludedAddress(
            profile_id=profile.id,
            address_key="x",
            address="9 Old Rd",
            city="Adrian",
            state="MI",
            reason="Ruled out",
            excluded_on=date.today(),
        )
    )
    from house_agent.addresses import address_key

    session.scalars(select(ExcludedAddress)).one().address_key = address_key(
        "9 Old Rd", "Adrian", "MI"
    )
    session.commit()

    regions = {
        "Lenawee County, MI": {
            "region_checked": True,
            "listings": [_found("9 Old Road"), _found("1 Farm Rd")],
        }
    }
    run = _run(session, profile, FakeAgent(regions=regions))
    assert run.summary["added"] == ["1 Farm Rd, Adrian, MI"]
    assert run.summary["skipped_excluded"] == ["9 Old Road, Adrian, MI"]

    dismiss(session, _listing(session, profile, "1 Farm Rd"), "Too close to highway", date.today())
    session.commit()
    run2 = _run(session, profile, FakeAgent(regions=regions))
    assert run2.summary["added"] == []
    assert _listing(session, profile, "1 Farm Rd").listing_state == "dismissed"


def test_removed_listing_found_again_is_relisted(session):
    profile = _profile(session)
    regions = {"Lenawee County, MI": {"region_checked": True, "listings": [_found("1 Farm Rd")]}}
    _run(session, profile, FakeAgent(regions=regions))
    _run(session, profile, FakeAgent(checks={"1 Farm Rd": {"status": "off_market"}}))
    run3 = _run(session, profile, FakeAgent(regions=regions))
    assert run3.summary["relisted"] == ["1 Farm Rd, Adrian, MI"]
    assert _listing(session, profile, "1 Farm Rd").listing_state == "active"


def test_region_errors_make_run_partial(session):
    profile = _profile(session)
    agent = FakeAgent(
        regions={
            "Lenawee County, MI": AgentError("rate limited"),
            "Monroe County, MI": {"region_checked": False, "notes": "429", "listings": []},
        }
    )
    run = _run(session, profile, agent)
    assert run.status in ("partial", "failed")
    assert "Lenawee County, MI" in run.summary["skipped_regions"]
    assert "Monroe County, MI (429)" in run.summary["skipped_regions"]


def test_run_saves_discovered_redfin_ids(session):
    user = ensure_default_user(session)
    criteria = {
        **CRITERIA,
        "regions": [{"name": "Hillsdale County", "state": "MI", "anchor": "DTW"}],
    }
    profile = SearchProfile(owner_id=user.id, name="No IDs", criteria=criteria)
    session.add(profile)
    session.commit()
    agent = FakeAgent(
        regions={
            "Hillsdale County, MI": {
                "region_checked": True,
                "listings": [],
                "redfin_county_id": 1377,
            }
        }
    )
    _run(session, profile, agent)
    assert dict(agent.search_calls[0]["plan"])["redfin"] is None  # no ID yet, so no direct URL
    session.expire_all()
    assert session.get(SearchProfile, profile.id).criteria["regions"][0]["redfin_county_id"] == 1377


def test_restart_closes_interrupted_runs(session):
    from house_agent.agent.runner import mark_interrupted_runs
    from house_agent.models import Run

    profile = _profile(session)
    stuck = create_run(session, profile, "schedule")
    stuck.status = "running"
    stuck.summary = {"progress": {"phase": "search", "done": 3, "total": 10, "current": "X"}}
    session.commit()
    assert mark_interrupted_runs(session) == 1
    session.expire_all()
    run = session.get(Run, stuck.id)
    assert run.status == "failed" and "restarted" in run.summary["errors"][0]
    assert run.finished_at is not None


def test_progress_is_replaced_by_summary(session):
    profile = _profile(session)
    run = _run(session, profile, FakeAgent())
    assert "progress" not in run.summary and "added" in run.summary


def test_stop_request_ends_run_after_current_step(session):
    from house_agent.agent.runner import request_stop

    profile = _profile(session)
    run = create_run(session, profile, "manual")

    class StopsAfterFirstRegion(FakeAgent):
        def search_region(self, *args, **kwargs):
            result = super().search_region(*args, **kwargs)
            request_stop(run.id)  # user clicks Stop while the first county is being searched
            return result

    agent = StopsAfterFirstRegion(
        regions={"Lenawee County, MI": {"region_checked": True, "listings": [_found("1 Farm Rd")]}}
    )
    done = execute_run(session, run.id, agent)
    assert done.status == "cancelled"
    assert len(agent.search_calls) == 1  # Monroe County never searched
    assert done.summary["added"] == ["1 Farm Rd, Adrian, MI"]  # work so far is kept


def test_rejections_are_kept_with_reasons(session):
    profile = _profile(session)
    wreck = {**_found("2 Wreck Rd", condition="reject"), "reject_reason": "Needs a new foundation."}
    regions = {
        "Lenawee County, MI": {
            "region_checked": True,
            "listings": [_found("1 Farm Rd"), wreck, _found("3 Pricey Rd", price=250000)],
        }
    }
    run = _run(session, profile, FakeAgent(regions=regions))
    assert run.summary["added"] == ["1 Farm Rd, Adrian, MI"]
    assert {r["listing"]: r["reason"] for r in run.summary["rejected"]} == {
        "2 Wreck Rd, Adrian, MI": "Needs a new foundation.",
        "3 Pricey Rd, Adrian, MI": "Price $250,000 is above your $175,000 maximum.",
    }
    wreck_row = _listing(session, profile, "2 Wreck Rd")
    assert wreck_row.listing_state == "rejected" and wreck_row.condition == "unverified"

    # A price cut into range on a later run brings it onto the list.
    cut = {"region_checked": True, "listings": [_found("3 Pricey Rd", price=170000)]}
    run2 = _run(session, profile, FakeAgent(regions={"Lenawee County, MI": cut}))
    assert run2.summary["added"] == ["3 Pricey Rd, Adrian, MI"]
    assert _listing(session, profile, "3 Pricey Rd").listing_state == "active"


def test_include_anyway_sticks_and_records_feedback(session):
    from house_agent.models import AgentFeedback
    from house_agent.reconcile import include

    profile = _profile(session)
    wreck = {**_found("2 Wreck Rd", condition="reject"), "reject_reason": "Says needs TLC."}
    _run(
        session,
        profile,
        FakeAgent(regions={"Lenawee County, MI": {"region_checked": True, "listings": [wreck]}}),
    )
    row = _listing(session, profile, "2 Wreck Rd")
    fb = include(session, row, "Cosmetic TLC is fine for me.")
    session.commit()
    assert row.listing_state == "active" and row.user_included and row.condition == "good"
    assert fb.agent_reason == "Says needs TLC." and fb.user_reason == "Cosmetic TLC is fine for me."
    assert session.query(AgentFeedback).count() == 1

    # The agent rejecting it again on re-check doesn't undo the user's decision...
    _run(
        session,
        profile,
        FakeAgent(checks={"2 Wreck Rd": {"status": "active", "condition": "reject"}}),
    )
    assert _listing(session, profile, "2 Wreck Rd").listing_state == "active"
    # ...but it still drops off when it sells.
    _run(session, profile, FakeAgent(checks={"2 Wreck Rd": {"status": "sold"}}))
    assert _listing(session, profile, "2 Wreck Rd").listing_state == "removed"


def test_pending_listings_go_to_rejected_when_user_skips_them(session):
    profile = _profile(session)  # include_pending not set: skip pending listings
    pending = {**_found("5 Contract Ln"), "market_status": "contingent"}
    run = _run(
        session,
        profile,
        FakeAgent(
            regions={
                "Lenawee County, MI": {
                    "region_checked": True,
                    "listings": [pending, _found("1 Farm Rd")],
                }
            }
        ),
    )
    assert run.summary["added"] == ["1 Farm Rd, Adrian, MI"]
    assert run.summary["rejected"][0]["reason"].startswith("This listing is under contract.")
    assert _listing(session, profile, "5 Contract Ln").listing_state == "rejected"

    # A tracked listing that goes pending moves to Rejected too.
    run2 = _run(session, profile, FakeAgent(checks={"1 Farm Rd": {"status": "pending"}}))
    assert run2.summary["rejected"][0]["listing"] == "1 Farm Rd, Adrian, MI"
    row = _listing(session, profile, "1 Farm Rd")
    assert row.listing_state == "rejected" and row.market_status == "pending"


def test_pending_listings_kept_when_user_includes_them(session):
    profile = _profile(session)
    profile.criteria = {**profile.criteria, "include_pending": True}
    session.commit()
    pending = {**_found("5 Contract Ln"), "market_status": "pending"}
    run = _run(
        session,
        profile,
        FakeAgent(regions={"Lenawee County, MI": {"region_checked": True, "listings": [pending]}}),
    )
    assert run.summary["added"] == ["5 Contract Ln, Adrian, MI"]
    row = _listing(session, profile, "5 Contract Ln")
    assert row.listing_state == "active" and row.market_status == "pending"

    # Back on the market: status updates, and it stays listed.
    run2 = _run(session, profile, FakeAgent(checks={"5 Contract Ln": {"status": "active"}}))
    assert run2.summary["status_changes"] == [
        {"listing": "5 Contract Ln, Adrian, MI", "old": "pending", "new": "active"}
    ]
    assert _listing(session, profile, "5 Contract Ln").market_status == "active"


def test_feedback_and_rejections_reach_the_agent(session):
    from house_agent.reconcile import include

    profile = _profile(session)
    wreck = {**_found("2 Wreck Rd", condition="reject"), "reject_reason": "Says needs TLC."}
    _run(
        session,
        profile,
        FakeAgent(
            regions={
                "Lenawee County, MI": {
                    "region_checked": True,
                    "listings": [wreck, _found("3 Mold Rd", condition="reject")],
                }
            }
        ),
    )
    include(session, _listing(session, profile, "2 Wreck Rd"), "TLC is fine.")
    session.commit()

    seen = {}

    class Spy(FakeAgent):
        def search_region(self, criteria, *args, **kwargs):
            seen.setdefault("feedback", criteria.feedback)
            return super().search_region(criteria, *args, **kwargs)

    agent = Spy()
    _run(session, profile, agent)
    assert seen["feedback"] == [
        '2 Wreck Rd, Adrian, MI: you rejected it ("Says needs TLC."); '
        'the buyer included it anyway: "TLC is fine."'
    ]
    rejected_arg = agent.search_calls[0]["rejected"]
    assert rejected_arg == ["3 Mold Rd, Adrian, MI (was $150,000)"]


def test_each_run_leads_with_a_site_the_county_did_not_use_last_time(session):
    profile = _profile(session)
    lenawee = "Lenawee County, MI"
    first = FakeAgent(
        regions={
            lenawee: {
                "region_checked": True,
                "listings": [],
                "sites_used": ["realtor"],
                "sites_blocked": ["zillow"],
            }
        }
    )
    run = _run(session, profile, first)
    assert [k for k, _ in _call(first, lenawee)["plan"]][0] != [
        k for k, _ in _call(first, "Monroe County, MI")["plan"]
    ][0]
    assert run.summary["site_status"][lenawee] == {"used": ["realtor"], "blocked": ["zillow"]}
    assert run.summary["sites"]["realtor"] == {"used": 1, "blocked": 0}
    assert run.summary["sites"]["zillow"] == {"used": 0, "blocked": 1}

    # Next run: fresh sites first, last run's site after them, the blocked site last.
    second = FakeAgent(
        regions={lenawee: {"region_checked": True, "listings": [], "sites_used": ["redfin"]}}
    )
    _run(session, profile, second)
    order = [k for k, _ in _call(second, lenawee)["plan"]]
    assert order[0] in {"redfin", "homes"}
    assert order[-2:] == ["realtor", "zillow"]

    # The run after that leads with the one site this county hasn't led with yet.
    third = FakeAgent()
    _run(session, profile, third)
    order = [k for k, _ in _call(third, lenawee)["plan"]]
    assert order[0] != "redfin" and order[-1] == "redfin"


def test_drive_km_is_stored_for_canadian_listings(session):
    profile = _profile(session)
    found = {**_found("1 Lake Rd"), "drive_km": 118.0}
    _run(
        session,
        profile,
        FakeAgent(regions={"Lenawee County, MI": {"region_checked": True, "listings": [found]}}),
    )
    assert _listing(session, profile, "1 Lake Rd").drive_km == 118.0
