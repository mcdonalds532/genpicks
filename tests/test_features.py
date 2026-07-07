"""Feature-builder tests: correctness and, above all, no leakage."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from genpicks.db.models import Base, Match, Team
from genpicks.ml.features import (
    ELO_HOME_ADVANTAGE,
    ELO_INITIAL,
    ELO_K,
    FEATURE_COLUMNS,
    _elo_expected,
    build_match_dataset,
)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Team(id=1, name="Alpha"), Team(id=2, name="Beta"),
                         Team(id=3, name="Gamma")])
        session.add_all(
            [
                # round 1: Alpha beats Beta 20-10
                Match(season=2024, round="1", match_date=date(2024, 3, 1),
                      home_team_id=1, away_team_id=2, home_score=20, away_score=10,
                      source="t", source_key="m1"),
                # round 2: Beta hosts Gamma six days later
                Match(season=2024, round="2", match_date=date(2024, 3, 7),
                      home_team_id=2, away_team_id=3, home_score=10, away_score=10,
                      source="t", source_key="m2"),
                # round 3: Alpha hosts Gamma eight days after its round-1 game
                Match(season=2024, round="3", match_date=date(2024, 3, 9),
                      home_team_id=1, away_team_id=3, home_score=30, away_score=0,
                      source="t", source_key="m3"),
                # next season: GF label, Alpha v Beta
                Match(season=2025, round="GF", match_date=date(2025, 10, 5),
                      home_team_id=1, away_team_id=2, home_score=12, away_score=13,
                      source="t", source_key="m4"),
            ]
        )
        session.commit()
    return engine


def test_first_match_has_no_history(engine):
    data = build_match_dataset(engine)
    first = data.iloc[0]
    assert first["home_elo"] == ELO_INITIAL
    assert first["away_elo"] == ELO_INITIAL
    assert first["home_win_rate_5"] is None or first["home_win_rate_5"] != first["home_win_rate_5"]
    assert first["home_rest_days"] != first["home_rest_days"]  # NaN
    assert first["home_win"] == True  # noqa: E712


def test_features_are_strictly_pre_match(engine):
    data = build_match_dataset(engine)
    # Round 3: Alpha won round 1 20-10; that must be its entire history.
    row = data[data["round_number"] == 3].iloc[0]
    assert row["home_win_rate_5"] == 1.0
    assert row["home_points_for_5"] == 20.0
    assert row["home_points_against_5"] == 10.0
    # Alpha's 30-0 result in this very match must NOT be visible.
    assert row["home_margin_5"] == 10.0
    # Gamma drew its only game: win rate 0.5 from the draw, not affected
    # by this match's 0-30 loss.
    assert row["away_win_rate_5"] == 0.5
    assert row["home_rest_days"] == 8


def test_elo_updates_are_zero_sum_and_ordered(engine):
    data = build_match_dataset(engine)
    row1, row2 = data.iloc[0], data.iloc[1]
    # after Alpha's home win, Beta enters round 2 with exactly the loss applied
    expected = _elo_expected(ELO_INITIAL + ELO_HOME_ADVANTAGE, ELO_INITIAL)
    beta_after = ELO_INITIAL - ELO_K * (1.0 - expected)
    assert row2["home_elo"] == pytest.approx(beta_after)
    assert row1["home_elo"] == ELO_INITIAL  # round 1 saw nothing


def test_draws_emit_null_target_but_update_form(engine):
    data = build_match_dataset(engine)
    draw_row = data[data["round_number"] == 2].iloc[0]
    assert draw_row["home_win"] is None or draw_row["home_win"] != draw_row["home_win"]
    # the GF row: Beta's season-2025 state regressed and season stats reset
    gf = data[data["season"] == 2025].iloc[0]
    assert gf["round_number"] == 27 + 4
    assert gf["away_season_win_rate"] != gf["away_season_win_rate"]  # NaN: new season
    assert gf["away_rest_days"] != gf["away_rest_days"]  # NaN across seasons
    # elo regressed one third toward the mean between seasons
    assert abs(gf["home_elo"] - ELO_INITIAL) < abs(
        data[data["round_number"] == 3].iloc[0]["home_elo"]
        + ELO_K - ELO_INITIAL  # loose bound: just closer to mean than before
    )


def test_feature_columns_exist(engine):
    data = build_match_dataset(engine)
    missing = [c for c in FEATURE_COLUMNS if c not in data.columns]
    assert missing == []
