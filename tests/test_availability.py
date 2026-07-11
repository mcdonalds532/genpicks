"""Lineup-availability features: pre-match discipline and team-list serving."""

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from genpicks.db.models import (
    Base,
    Match,
    Player,
    PlayerMatchStats,
    Team,
    TeamListEntry,
)
from genpicks.ml.features import build_match_dataset

TEAM_A_LINEUP = set(range(1, 18))  # players 1-17
TEAM_B_LINEUP = set(range(21, 38))  # players 21-37


def add_match(session, match_id, day, home=1, away=2, played=True):
    session.add(
        Match(
            id=match_id,
            season=2025,
            round=str(match_id),
            match_date=date(2025, 3, 1) + timedelta(days=7 * (match_id - 1)),
            home_team_id=home,
            away_team_id=away,
            home_score=20 if played else None,
            away_score=10 if played else None,
            source="t",
            source_key=f"m{match_id}",
        )
    )


def add_lineup(session, match_id, team_id, player_ids, minutes=80):
    session.add_all(
        PlayerMatchStats(
            match_id=match_id,
            player_id=player_id,
            team_id=team_id,
            minutes_played=minutes,
        )
        for player_id in player_ids
    )


@pytest.fixture()
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Team(id=1, name="Alpha"), Team(id=2, name="Beta")])
        session.add_all(Player(id=n, full_name=f"Player {n}") for n in range(1, 60))
        # six played rounds: both teams field an unchanged 17 in rounds 1-5,
        # then round 6 sees team A lose five regulars (players 13-17)
        for match_id in range(1, 7):
            add_match(session, match_id, match_id)
            lineup_a = (
                TEAM_A_LINEUP
                if match_id < 6
                else (TEAM_A_LINEUP - {13, 14, 15, 16, 17})
                | {
                    41,
                    42,
                    43,
                    44,
                    45,
                }
            )
            add_lineup(session, match_id, 1, lineup_a)
            add_lineup(session, match_id, 2, TEAM_B_LINEUP)
        session.commit()
    return engine


def test_first_match_has_no_availability_history(engine):
    data = build_match_dataset(engine)
    first = data.iloc[0]
    assert math.isnan(first["home_returning_share"])
    assert math.isnan(first["home_regulars_available"])


def test_returning_share_compares_against_previous_lineup(engine):
    data = build_match_dataset(engine)
    # round 2: identical 17 to round 1
    assert data.iloc[1]["home_returning_share"] == 1.0
    # round 6: team A returns 12 of the previous 17
    round6 = data.iloc[5]
    assert round6["home_returning_share"] == pytest.approx(12 / 17)
    assert round6["away_returning_share"] == 1.0
    assert round6["returning_share_diff"] == pytest.approx(12 / 17 - 1.0)


def test_regulars_available_needs_history_then_tracks_missing_regulars(engine):
    data = build_match_dataset(engine)
    # rounds 2-5: fewer than five past lineups -> NaN
    assert math.isnan(data.iloc[4]["home_regulars_available"])
    # round 6: five lineups of history, all 17 are regulars, 12 available
    round6 = data.iloc[5]
    assert round6["home_regulars_available"] == pytest.approx(12 / 17)
    assert round6["away_regulars_available"] == 1.0


def test_zero_minute_junk_rows_are_not_lineup_members(engine):
    with Session(engine) as session:
        add_match(session, 7, 7)
        add_lineup(session, 7, 1, TEAM_A_LINEUP)
        add_lineup(session, 7, 2, TEAM_B_LINEUP)
        add_lineup(session, 7, 2, {55, 56}, minutes=0)  # junk reserve rows
        session.commit()
    data = build_match_dataset(engine)
    # if the junk rows counted, away returning share would drop below 1
    assert data.iloc[6]["away_returning_share"] == 1.0


def test_unplayed_match_uses_official_team_list(engine):
    with Session(engine) as session:
        add_match(session, 8, 8, played=False)
        # team A names its round-6 side again; team B has no list yet
        round6_lineup = (TEAM_A_LINEUP - {13, 14, 15, 16, 17}) | {41, 42, 43, 44, 45}
        for jersey, player_id in enumerate(sorted(round6_lineup), start=1):
            session.add(
                TeamListEntry(
                    match_id=8,
                    team_id=1,
                    player_id=player_id,
                    player_name=f"Player {player_id}",
                    jersey_number=jersey,
                    source="nrl",
                    captured_at=datetime(2025, 4, 15, tzinfo=UTC),
                )
            )
        session.commit()
    data = build_match_dataset(engine, include_unplayed=True)
    upcoming = data[data["match_id"] == 8].iloc[0]
    # same 17 as team A's last played match -> full returning share, and
    # regulars from rounds 1-5 minus the five who left stay unavailable
    assert upcoming["home_returning_share"] == 1.0
    assert upcoming["home_regulars_available"] == pytest.approx(12 / 17)
    # no list for team B -> NaN, never a guess
    assert math.isnan(upcoming["away_returning_share"])


def test_unplayed_snapshot_never_updates_lineup_state(engine):
    with Session(engine) as session:
        add_match(session, 8, 8, played=False)
        session.commit()
    with_unplayed = build_match_dataset(engine, include_unplayed=True)
    played_only = build_match_dataset(engine)
    # the unplayed fixture must not perturb any played match's features
    for col in ("home_returning_share", "home_regulars_available"):
        a = with_unplayed[with_unplayed["match_id"] <= 6][col]
        b = played_only[col]
        assert list(a.fillna(-1)) == list(b.fillna(-1))
