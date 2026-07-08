"""Schema smoke tests: tables create cleanly and alias resolution works."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from genpicks.db.models import Base, Team, TeamAlias, Venue, VenueAlias


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_all_tables_created(session):
    expected = {
        "teams",
        "team_aliases",
        "venues",
        "venue_aliases",
        "players",
        "player_aliases",
        "matches",
        "match_source_keys",
        "player_match_stats",
        "team_list_entries",
        "try_events",
        "odds_snapshots",
        "predictions",
    }
    assert expected == set(Base.metadata.tables)


def test_venue_aliases_resolve_to_one_location(session):
    # The same physical stadium under two sponsor names must resolve to one venue.
    venue = Venue(name="Sydney Football Stadium", city="Sydney", state="NSW")
    venue.aliases = [
        VenueAlias(alias="Allianz Stadium", source="nrl.com"),
        VenueAlias(alias="Aussie Stadium", source="rugbyleagueproject"),
    ]
    session.add(venue)
    session.commit()

    ids = {
        session.scalar(select(VenueAlias.venue_id).where(VenueAlias.alias == a))
        for a in ("Allianz Stadium", "Aussie Stadium")
    }
    assert ids == {venue.id}


def test_team_alias_unique_per_source(session):
    team = Team(name="Wests Tigers")
    session.add(team)
    session.commit()
    session.add(TeamAlias(team_id=team.id, alias="Tigers", source="tab"))
    session.commit()
    session.add(TeamAlias(team_id=team.id, alias="Tigers", source="tab"))
    with pytest.raises(Exception):
        session.commit()
