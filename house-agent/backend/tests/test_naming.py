from datetime import UTC, datetime

from house_agent.auth import ensure_default_user
from house_agent.models import SearchProfile
from house_agent.naming import fix_existing_duplicates, norm, unique_name


def test_plural_capitals_and_spacing_are_the_same_name():
    assert norm("Lands near DCA") == norm("land  near dca")
    assert norm("Houses near BOS") == norm("House near BOS")
    assert norm("Glass house") != norm("Glas house")  # "ss" isn't a plural
    assert norm("Bus stop") == norm("Bus stop")


def test_new_lookalike_gets_a_stamp(session):
    user = ensure_default_user(session)
    session.add(SearchProfile(owner_id=user.id, name="Lands near DCA", criteria={}))
    session.commit()
    now = datetime(2026, 9, 26, 1, 14, tzinfo=UTC)
    assert (
        unique_name(session, user.id, "Land near DCA", "America/New_York", now=now)
        == "Land near DCA (Sep 25, 9:14 PM)"
    )


def test_existing_duplicates_fixed_once_oldest_keeps_its_name(session):
    user = ensure_default_user(session)
    older = SearchProfile(
        owner_id=user.id,
        name="Lands near DCA",
        criteria={},
        timezone="America/New_York",
        created_at=datetime(2026, 9, 25, 20, 10, tzinfo=UTC),
    )
    newer = SearchProfile(
        owner_id=user.id,
        name="Land near DCA",
        criteria={},
        timezone="America/New_York",
        created_at=datetime(2026, 9, 25, 20, 27, tzinfo=UTC),
    )
    other = SearchProfile(owner_id=user.id, name="Houses near BOS", criteria={})
    session.add_all([older, newer, other])
    session.commit()

    assert fix_existing_duplicates(session) == [
        ("Land near DCA", "Land near DCA (Sep 25, 4:27 PM)")
    ]
    session.expire_all()
    assert session.get(SearchProfile, older.id).name == "Lands near DCA"
    assert session.get(SearchProfile, newer.id).name == "Land near DCA (Sep 25, 4:27 PM)"
    assert session.get(SearchProfile, other.id).name == "Houses near BOS"
    assert fix_existing_duplicates(session) == []  # nothing left to do on the next start
