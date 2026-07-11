"""Raw-to-clean transform tests, driven end-to-end from the saved fixtures."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from genpicks.db.models import (
    Base,
    Match,
    Player,
    PlayerAlias,
    PlayerMatchStats,
    Team,
    Venue,
    VenueAlias,
)
from genpicks.ingest.names import prettify_player_name
from genpicks.ingest.resolve import Resolver
from genpicks.ingest.rlp_loader import load_match_detail, load_season_rows
from genpicks.scrape import rlp

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(scope="module")
def season_rows():
    html = (FIXTURES / "rlp-nrl-2025-results.html").read_text(encoding="utf-8")
    return rlp.parse_season_results(html, 2025)


@pytest.fixture(scope="module")
def match_detail():
    html = (FIXTURES / "rlp-match-103171.html").read_text(encoding="utf-8")
    return rlp.parse_match(html, "103171")


def test_season_load_is_idempotent(session, season_rows):
    load_season_rows(session, season_rows)
    session.commit()
    first_counts = (
        session.scalar(select(func.count()).select_from(Match)),
        session.scalar(select(func.count()).select_from(Team)),
        session.scalar(select(func.count()).select_from(Venue)),
    )
    load_season_rows(session, season_rows)
    session.commit()
    second_counts = (
        session.scalar(select(func.count()).select_from(Match)),
        session.scalar(select(func.count()).select_from(Team)),
        session.scalar(select(func.count()).select_from(Venue)),
    )
    assert first_counts == second_counts
    assert first_counts[0] == 213
    assert first_counts[1] == 17  # every NRL club in 2025


def test_season_load_populates_match_fields(session, season_rows):
    matches = load_season_rows(session, season_rows)
    opener = matches["103171"]
    assert opener.season == 2025
    assert opener.round == "1"
    assert opener.match_date == date(2025, 3, 1)
    assert (opener.home_score, opener.away_score) == (30, 8)
    home = session.get(Team, opener.home_team_id)
    assert home.name == "Canberra Raiders"
    venue = session.get(Venue, opener.venue_id)
    assert venue.name == "Allegiant"


def test_venue_sponsor_rename_resolves_to_same_venue(session):
    resolver = Resolver(session, "rlp")
    first = resolver.venue("8", "Pirtek Stadium")
    renamed = resolver.venue("8", "CommBank Stadium")
    assert renamed.id == first.id
    aliases = set(session.scalars(select(VenueAlias.alias).where(VenueAlias.venue_id == first.id)))
    assert aliases == {"8", "Pirtek Stadium", "CommBank Stadium"}


def test_new_source_id_adopts_orphan_player_created_by_another_source(session):
    # A debut can reach the DB through NRL.com first (real minutes, but RLP
    # lists only a reserve slot); when RLP later credits the player under a
    # fresh id, that id must claim the existing human, not mint a second one
    # (observed live: Xavier Savage, 2021).
    orphan = Player(full_name="Xavier Savage")
    session.add(orphan)
    session.flush()
    session.add(PlayerAlias(player_id=orphan.id, alias="510220", source="nrl"))
    session.commit()

    resolver = Resolver(session, "rlp")
    adopted = resolver.player("31266", "Xavier SAVAGE")
    assert adopted.id == orphan.id
    assert session.scalar(select(func.count()).select_from(Player)) == 1

    # same-name players already claimed by this source are never adopted:
    # a second unseen rlp id with the same name is a different human
    second = resolver.player("99999", "Xavier SAVAGE")
    assert second.id != orphan.id
    assert session.scalar(select(func.count()).select_from(Player)) == 2


def test_same_display_name_different_ids_stay_separate_venues(session):
    # Old and new Sydney Football Stadium: different RLP ids, both "Allianz".
    resolver = Resolver(session, "rlp")
    new_sfs = resolver.venue("1096", "Allianz")
    old_sfs = resolver.venue("30", "Allianz")
    session.commit()
    assert old_sfs.id != new_sfs.id
    assert new_sfs.name == "Allianz"
    assert old_sfs.name == "Allianz (rlp 30)"


def test_match_detail_load(session, season_rows, match_detail):
    matches = load_season_rows(session, season_rows)
    match = matches["103171"]
    count = load_match_detail(session, match, match_detail)
    session.commit()
    assert count >= 34  # both 17-player squads

    stats = list(
        session.scalars(select(PlayerMatchStats).where(PlayerMatchStats.match_id == match.id))
    )
    assert len(stats) == count

    # tries reconcile with the 30-8 scoreline (5 and 2 tries)
    home_tries = sum(s.tries for s in stats if s.team_id == match.home_team_id)
    away_tries = sum(s.tries for s in stats if s.team_id == match.away_team_id)
    assert (home_tries, away_tries) == (5, 2)
    # appearance without a scoresheet entry means zero tries, not unknown
    assert all(s.tries is not None for s in stats)

    # double try scorer, resolved through the player alias table by RLP id
    kris_alias = session.scalar(
        select(PlayerAlias).where(PlayerAlias.source == "rlp", PlayerAlias.alias == "28599")
    )
    kris_stats = next(s for s in stats if s.player_id == kris_alias.player_id)
    assert kris_stats.tries == 2
    assert session.get(Player, kris_alias.player_id).full_name == "Sebastian Kris"

    # idempotent on re-ingest
    assert load_match_detail(session, match, match_detail) == count
    session.commit()
    total = session.scalar(select(func.count()).select_from(PlayerMatchStats))
    assert total == count


def test_prettify_player_name():
    assert prettify_player_name("Sebastian KRIS") == "Sebastian Kris"
    assert prettify_player_name("Roger TUIVASA-SHECK") == "Roger Tuivasa-Sheck"
    assert prettify_player_name("KL IRO") == "KL Iro"
    assert prettify_player_name("Charnze NICOLL-KLOKSTAD") == "Charnze Nicoll-Klokstad"
