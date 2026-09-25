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
    # The first region's URL follows the routine's Redfin pattern.
    assert agent.search_calls[0][1].startswith("https://www.redfin.com/county/1393/MI/Lenawee")


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
                "2 Barn Rd": {"status": "pending"},
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


def test_price_rising_above_max_removes_listing(session):
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
    assert run2.summary["removed"][0]["reason"] == "no longer matches criteria"


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
    _run(session, profile, FakeAgent(checks={"1 Farm Rd": {"status": "pending"}}))
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
    assert agent.search_calls[0][1] is None  # no ID yet, so no direct URL
    session.expire_all()
    assert session.get(SearchProfile, profile.id).criteria["regions"][0]["redfin_county_id"] == 1377
