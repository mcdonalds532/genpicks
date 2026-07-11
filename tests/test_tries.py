"""Try-model tests: team-rate leakage, share shrinkage, lineup normalisation."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from genpicks.db.models import Base, Match, Player, PlayerMatchStats, Team, TryEvent
from genpicks.ml.tries import (
    build_share_dataset,
    build_team_try_dataset,
    load_try_data,
    position_priors,
)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Team(id=1, name="Alpha"), Team(id=2, name="Beta")])
        session.add_all([Player(id=n, full_name=f"P{n}") for n in range(1, 7)])
        session.add_all(
            [
                Match(
                    id=1,
                    season=2024,
                    round="1",
                    match_date=date(2024, 3, 1),
                    home_team_id=1,
                    away_team_id=2,
                    home_score=16,
                    away_score=4,
                    source="t",
                    source_key="m1",
                ),
                Match(
                    id=2,
                    season=2024,
                    round="2",
                    match_date=date(2024, 3, 8),
                    home_team_id=2,
                    away_team_id=1,
                    home_score=8,
                    away_score=8,
                    source="t",
                    source_key="m2",
                ),
            ]
        )
        # match 1: Alpha scores 3 tries (P1 x2, P2 x1), Beta 1 try (P4)
        session.add_all(
            [
                PlayerMatchStats(match_id=1, player_id=1, team_id=1, position="Wing", tries=2),
                PlayerMatchStats(match_id=1, player_id=2, team_id=1, position="Prop", tries=1),
                PlayerMatchStats(match_id=1, player_id=3, team_id=1, position="Prop", tries=0),
                PlayerMatchStats(match_id=1, player_id=4, team_id=2, position="Wing", tries=1),
                PlayerMatchStats(match_id=1, player_id=5, team_id=2, position="Prop", tries=0),
                # match 2: one try each side
                PlayerMatchStats(match_id=2, player_id=4, team_id=2, position="Wing", tries=1),
                PlayerMatchStats(match_id=2, player_id=1, team_id=1, position="Wing", tries=1),
                PlayerMatchStats(match_id=2, player_id=6, team_id=1, position="Prop", tries=0),
            ]
        )
        session.add(TryEvent(match_id=1, team_id=1, player_id=1, scoring_order=1, minute=5))
        session.commit()
    return engine


def test_team_dataset_is_pre_match(engine):
    data = load_try_data(engine)
    rows = build_team_try_dataset(data)
    assert len(rows) == 4  # 2 matches x 2 teams

    match1_home = rows[(rows["match_id"] == 1) & (rows["team_id"] == 1)].iloc[0]
    assert match1_home["tries"] == 3  # target from player stats
    assert match1_home["tries_for_5"] != match1_home["tries_for_5"]  # NaN: no history

    match2_alpha = rows[(rows["match_id"] == 2) & (rows["team_id"] == 1)].iloc[0]
    assert match2_alpha["is_home"] == 0
    assert match2_alpha["tries_for_5"] == 3.0  # only match 1, not match 2 itself
    assert match2_alpha["tries_against_5"] == 1.0
    assert match2_alpha["opp_tries_for_5"] == 1.0


def test_position_priors(engine):
    data = load_try_data(engine)
    priors, fallback = position_priors(data, {2024})
    # wingers scored 4 tries in 3 winger-games; props 1 in 4 prop-games
    assert priors["Wing"] > priors["Prop"] > 0
    assert fallback > 0


def test_share_shrinks_to_prior_without_history(engine):
    data = load_try_data(engine)
    priors, fallback = position_priors(data, {2024})
    shares = build_share_dataset(data, priors, fallback)

    first = shares[shares["match_id"] == 1]
    # nobody has history before match 1: raw share equals the position prior
    for row in first.itertuples():
        assert row.share_raw == pytest.approx(priors[row.position], abs=1e-9)
    # lineup renormalisation: shares sum to 1 per team
    for (_, _), group in shares.groupby(["match_id", "team_id"]):
        assert group["share"].sum() == pytest.approx(1.0)


def test_share_moves_toward_observed_rate_with_history(engine):
    data = load_try_data(engine)
    priors, fallback = position_priors(data, {2024})
    shares = build_share_dataset(data, priors, fallback)

    # P1 scored 2 of Alpha's 3 tries in match 1 (observed share 2/3). His
    # match-2 estimate must sit strictly between that observation and the
    # Wing prior — shrinkage pulls toward the prior, history pulls away.
    p1_match2 = shares[(shares["match_id"] == 2) & (shares["player_id"] == 1)].iloc[0]
    low, high = sorted([priors["Wing"], 2 / 3])
    assert low < p1_match2.share_raw < high
    assert p1_match2.history_games == 1

    # and P6 (debut, no history) still sits exactly on his prior
    p6 = shares[(shares["match_id"] == 2) & (shares["player_id"] == 6)].iloc[0]
    assert p6.share_raw == pytest.approx(priors["Prop"], abs=1e-9)


def test_first_scorer_loaded(engine):
    data = load_try_data(engine)
    assert data.first_scorers == {1: 1}
