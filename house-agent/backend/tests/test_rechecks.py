"""Search-first re-checks, MLS numbers, per-site links, page budgets and usage."""

import dataclasses
from datetime import date, timedelta

from house_agent.agent import runner
from house_agent.agent.claude_agent import Usage
from house_agent.links import LinkPolicy, normalize_mls, update_primary
from house_agent.models import Listing, ListingEvent, Run

from .fakes import FakeAgent
from .test_runner import _found, _listing, _profile, _run

LENAWEE = "Lenawee County, MI"


def _seed(session, profile, *addresses, **extra):
    listings = [{**_found(a), **extra} for a in addresses]
    return _run(
        session,
        profile,
        FakeAgent(regions={LENAWEE: {"region_checked": True, "listings": listings}}),
    )


def test_normalize_mls():
    assert normalize_mls("MLS# 60012345") == "60012345"
    assert normalize_mls("mls #: 2024-1234") == "2024-1234"
    assert normalize_mls("MLS® Number X1234567") == "X1234567"
    assert normalize_mls("#") is None and normalize_mls(None) is None


def test_listings_seen_in_search_skip_their_own_check(session):
    profile = _profile(session)
    _seed(session, profile, "1 Farm Rd", "2 Barn Rd")
    agent = FakeAgent(
        regions={
            LENAWEE: {
                "region_checked": True,
                "listings": [],
                "seen": [
                    {
                        "address": "1 Farm Rd",
                        "price": 140000,
                        "url": "https://www.zillow.com/homedetails/1-Farm-Rd/1_zpid/",
                        "mls_number": "MLS# 600111",
                    }
                ],
            }
        },
        checks={"2 Barn Rd": {"status": "sold"}},
    )
    run = _run(session, profile, agent)
    # Only the listing the search didn't show got a status check...
    assert agent.status_calls == [["2 Barn Rd"]]
    # ...and only the one whose price changed was re-read for condition.
    assert agent.reread_calls == [["1 Farm Rd"]]
    assert run.summary["price_changes"] == [
        {"listing": "1 Farm Rd, Adrian, MI", "old": 150000, "new": 140000}
    ]
    assert run.summary["checks"] == {
        "seen_in_search": 1,
        "status_checked": 1,
        "skipped_recent": 0,
        "reread": 1,
        "new_read": 0,
    }
    session.expire_all()
    farm = _listing(session, profile, "1 Farm Rd")
    assert farm.mls_number == "600111"
    assert {s.site for s in farm.sources} == {"redfin", "zillow"}
    assert _listing(session, profile, "2 Barn Rd").listing_state == "removed"


def test_tracked_list_sent_to_each_county_is_that_countys_state_and_anchor(session):
    profile = _profile(session)
    _seed(session, profile, "1 Farm Rd")
    other = _listing(session, profile, "1 Farm Rd")
    session.add(
        Listing(
            profile_id=profile.id,
            address_key="elsewhere",
            address="7 Ohio Rd",
            city="Toledo",
            state="OH",
            anchor="DTW",
            first_seen=date.today(),
        )
    )
    session.commit()
    agent = FakeAgent()
    _run(session, profile, agent)
    tracked = agent.search_calls[0]["tracked"]
    assert [t["address"] for t in tracked] == ["1 Farm Rd"]
    assert tracked[0]["ref"] == other.id


def test_recently_checked_listings_are_not_checked_again(session, monkeypatch):
    monkeypatch.setattr(runner, "settings", dataclasses.replace(runner.settings, recheck_days=3))
    profile = _profile(session)
    _seed(session, profile, "1 Farm Rd", "2 Barn Rd")
    _listing(session, profile, "2 Barn Rd").last_checked = date.today() - timedelta(days=5)
    session.commit()
    agent = FakeAgent()
    run = _run(session, profile, agent)
    assert agent.status_calls == [["2 Barn Rd"]]
    assert run.summary["checks"]["skipped_recent"] == 1


def test_same_mls_number_matches_a_differently_written_address(session):
    profile = _profile(session)
    _seed(session, profile, "1 Farm Rd", mls_number="600111")
    other_site = {
        **_found("1 North Farm Road"),
        "mls_number": "MLS 600111",
        "url": "https://www.realtor.com/realestateandhomedetail/1-N-Farm-Rd",
    }
    run = _run(
        session,
        profile,
        FakeAgent(regions={LENAWEE: {"region_checked": True, "listings": [other_site]}}),
    )
    assert run.summary["added"] == []
    assert session.query(Listing).count() == 1
    assert {s.site for s in _listing(session, profile, "1 Farm Rd").sources} == {
        "redfin",
        "realtor",
    }


def test_main_link_prefers_reliable_sites_and_skips_dead_links(session):
    profile = _profile(session)
    _seed(session, profile, "1 Farm Rd")
    farm = _listing(session, profile, "1 Farm Rd")
    redfin_url = farm.url
    zillow_url = "https://www.zillow.com/homedetails/1-Farm-Rd/1_zpid/"

    # Seen on Zillow too; Zillow blocks the agent far less often, so it becomes the main link.
    agent = FakeAgent(
        regions={
            LENAWEE: {
                "region_checked": True,
                "listings": [],
                "seen": [{"address": "1 Farm Rd", "price": 150000, "url": zillow_url}],
            }
        }
    )
    for _ in range(3):
        session.add(
            Run(
                profile_id=profile.id,
                status="succeeded",
                summary={"sites": {"redfin": {"used": 0, "blocked": 4}, "zillow": {"used": 4}}},
            )
        )
    session.commit()
    _run(session, profile, agent)
    session.expire_all()
    farm = _listing(session, profile, "1 Farm Rd")
    assert farm.url == zillow_url
    change = session.query(ListingEvent).filter_by(kind="link_changed").one()
    assert (change.old_value, change.new_value) == ("Redfin", "Zillow")

    # The Zillow page dies: the working Redfin link takes over again.
    policy = LinkPolicy({"zillow": 0.9, "redfin": 0.2})
    next(s for s in farm.sources if s.site == "zillow").dead = True
    update_primary(farm, policy, None)
    assert farm.url == redfin_url


def test_quiet_counties_get_a_smaller_page_budget(session, monkeypatch):
    s = dataclasses.replace(
        runner.settings, search_fetches=20, quiet_search_fetches=10, quiet_after_runs=2
    )
    monkeypatch.setattr(runner, "settings", s)
    profile = _profile(session)
    for added in (0, 0):
        session.add(
            Run(
                profile_id=profile.id,
                status="succeeded",
                summary={
                    "region_stats": {
                        LENAWEE: {"added": added},
                        "Monroe County, MI": {"added": 2},
                    }
                },
            )
        )
    session.commit()
    agent = FakeAgent()
    run = _run(session, profile, agent)
    budgets = {c["label"]: c["fetch_budget"] for c in agent.search_calls}
    assert budgets == {LENAWEE: 10, "Monroe County, MI": 20}
    assert run.summary["region_stats"][LENAWEE]["fetch_budget"] == 10


def test_usage_is_split_by_model_with_cost_estimate():
    from types import SimpleNamespace

    usage = Usage()
    call = SimpleNamespace(
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        server_tool_use=None,
    )
    usage.add(call, "claude-opus-5")
    before = usage.snapshot()
    usage.add(call, "claude-sonnet-5")
    out = usage.as_dict()
    assert out["calls"] == 2 and out["input_tokens"] == 2_000_000
    assert out["by_model"]["claude-opus-5"]["est_cost_usd"] == 7.5  # $5 + 0.1M * $25
    assert out["by_model"]["claude-sonnet-5"]["est_cost_usd"] == 3.0  # $2 + 0.1M * $10
    assert out["est_cost_usd"] == 10.5
    assert list(usage.since(before)["by_model"]) == ["claude-sonnet-5"]


def _settings(monkeypatch, **changes):
    monkeypatch.setattr(runner, "settings", dataclasses.replace(runner.settings, **changes))


def test_first_search_is_full_then_counties_are_swept(session, monkeypatch):
    _settings(monkeypatch, audit_every_runs=0, model="claude-opus-5", sweep_model="claude-sonnet-5")
    profile = _profile(session)
    first = FakeAgent()
    run1 = _run(session, profile, first)
    assert {c["mode"] for c in first.search_calls} == {"full"}
    assert run1.summary["region_stats"][LENAWEE]["why"] == "first search"

    second = FakeAgent()
    run2 = _run(session, profile, second)
    assert {c["mode"] for c in second.search_calls} == {"sweep"}
    assert run2.summary["region_stats"][LENAWEE]["model"] == "claude-sonnet-5"


def test_same_model_for_sweeps_turns_tiers_off(session, monkeypatch):
    _settings(monkeypatch, model="claude-opus-5", sweep_model="claude-opus-5")
    profile = _profile(session)
    _run(session, profile, FakeAgent())
    agent = FakeAgent()
    _run(session, profile, agent)
    assert {c["mode"] for c in agent.search_calls} == {"full"}


def test_sweep_finds_are_read_by_the_main_model(session, monkeypatch):
    _settings(monkeypatch, audit_every_runs=0, model="claude-opus-5", sweep_model="claude-sonnet-5")
    profile = _profile(session)
    _run(session, profile, FakeAgent())
    sweep = {
        LENAWEE: {
            "region_checked": True,
            "listings": [
                _found("7 New Rd", condition="unverified"),
                _found("8 Wreck Rd", condition="unverified"),
            ],
        }
    }
    agent = FakeAgent(
        regions=sweep,
        checks={
            "7 New Rd": {"status": "active", "condition": "good"},
            "8 Wreck Rd": {
                "status": "active",
                "condition": "reject",
                "reject_reason": "Needs a new foundation.",
            },
        },
    )
    run = _run(session, profile, agent)
    assert agent.reread_calls == [["7 New Rd", "8 Wreck Rd"]]
    assert run.summary["checks"]["new_read"] == 2
    # Only the one that passed the main model's reading counts as new.
    assert run.summary["added"] == ["7 New Rd, Adrian, MI"]
    assert run.summary["rejected"][0]["reason"] == "Needs a new foundation."
    assert _listing(session, profile, "7 New Rd").condition == "good"
    assert _listing(session, profile, "8 Wreck Rd").listing_state == "rejected"


def test_rotating_check_records_what_sweeps_missed(session, monkeypatch):
    _settings(monkeypatch, audit_every_runs=0, model="claude-opus-5", sweep_model="claude-sonnet-5")
    profile = _profile(session)
    _run(session, profile, FakeAgent())  # first (full) search
    _run(session, profile, FakeAgent())  # sweep
    _settings(monkeypatch, audit_every_runs=1, model="claude-opus-5", sweep_model="claude-sonnet-5")
    old = {**_found("9 Old Listing Rd"), "days_on_market": 30}
    fresh = {**_found("10 Just Listed Rd"), "days_on_market": 0}
    agent = FakeAgent(regions={LENAWEE: {"region_checked": True, "listings": [old, fresh]}})
    run = _run(session, profile, agent)
    assert {c["mode"] for c in agent.search_calls} == {"full"}
    assert run.summary["region_stats"][LENAWEE]["why"] == "rotating check"
    assert run.summary["sweep_misses"] == [
        {"listing": "9 Old Listing Rd, Adrian, MI", "county": LENAWEE, "days_on_market": 30}
    ]


def test_full_searches_run_before_sweeps(session, monkeypatch):
    _settings(monkeypatch, audit_every_runs=0, model="claude-opus-5", sweep_model="claude-sonnet-5")
    profile = _profile(session)
    _run(session, profile, FakeAgent())
    # A county added later gets its first (full) search before the swept ones.
    profile.criteria = {
        **profile.criteria,
        "regions": [
            *profile.criteria["regions"],
            {"name": "Hillsdale County", "state": "MI", "anchor": "DTW"},
        ],
    }
    session.commit()
    agent = FakeAgent()
    _run(session, profile, agent)
    assert [(c["label"], c["mode"]) for c in agent.search_calls][0] == (
        "Hillsdale County, MI",
        "full",
    )
