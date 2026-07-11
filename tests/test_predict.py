"""Lineup selection for serving: official team lists vs projection."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from genpicks.db.models import (
    Base,
    Match,
    Player,
    Prediction,
    Team,
    TeamListEntry,
)
from genpicks.ml.predict import newest_generation, official_lineups

NOW = datetime.now(UTC)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Team(id=1, name="Alpha"), Team(id=2, name="Beta")])
        session.add(
            Match(
                id=1,
                season=2026,
                round="19",
                match_date=date.today(),
                home_team_id=1,
                away_team_id=2,
                source="t",
                source_key="m1",
            )
        )
        session.add_all(Player(id=n, full_name=f"Player {n}") for n in range(1, 41))
        yield session


def entry(match_id, team_id, player_id, jersey, position="Wing"):
    return TeamListEntry(
        match_id=match_id,
        team_id=team_id,
        player_id=player_id,
        player_name=f"Player {player_id or '?'}",
        position=position,
        jersey_number=jersey,
        source="nrl",
        captured_at=NOW,
    )


def test_official_lineups_take_the_matchday_17_and_need_13_resolved(session):
    # team 1: full 17 named, plus cover (18, 20) and an unresolved debutant
    session.add_all(entry(1, 1, player_id=n, jersey=n) for n in range(1, 18))
    session.add_all(
        [
            entry(1, 1, player_id=18, jersey=18),  # 18th man: excluded
            entry(1, 1, player_id=19, jersey=20),  # reserve: excluded
            entry(1, 1, player_id=None, jersey=None),  # unresolved, unnumbered
        ]
    )
    # team 2: only 5 of its names resolved -> not usable as a lineup
    session.add_all(entry(1, 2, player_id=20 + n, jersey=n) for n in range(1, 6))
    session.flush()

    lineups = official_lineups(session, {1})
    assert set(lineups) == {(1, 1)}
    assert sorted(pid for pid, _ in lineups[(1, 1)]) == list(range(1, 18))
    assert all(pos == "Wing" for _, pos in lineups[(1, 1)])


def test_newest_generation_reports_latest_lineup_source(session):
    session.add_all(
        [
            Prediction(
                model_version="v",
                match_id=1,
                market="anytime_try",
                team_id=1,
                player_id=1,
                probability=0.4,
                generated_at=NOW - timedelta(hours=2),
                lineup_source="projected",
            ),
            Prediction(
                model_version="v",
                match_id=1,
                market="anytime_try",
                team_id=1,
                player_id=1,
                probability=0.5,
                generated_at=NOW,
                lineup_source="official",
            ),
        ]
    )
    session.flush()

    assert newest_generation(session, "v", "anytime_try") == {1: "official"}
    assert newest_generation(session, "other", "anytime_try") == {}


def test_newest_generation_treats_legacy_null_source_as_projected(session):
    # h2h rows written before availability features carried no lineup_source;
    # they must read as projected so the official pass supersedes them once
    session.add(
        Prediction(
            model_version="v",
            match_id=1,
            market="h2h",
            team_id=1,
            probability=0.6,
            generated_at=NOW - timedelta(days=1),
            lineup_source=None,
        )
    )
    session.flush()

    assert newest_generation(session, "v", "h2h") == {1: "projected"}
