"""Match-winner feature dataset.

One row per played match, features strictly pre-match:

- Elo per team (K=32, +60 home advantage in expectation only, ratings
  regressed one third to the mean at season boundaries)
- rolling form over the last 5 and 10 games per team: win rate, points
  for/against, margin
- season-to-date win rate
- rest days since the team's previous match (venue-local match_date)
- numeric round (finals map past the last regular round)
- travel: city-level km from each team's home city to the venue (diff),
  plus whether the nominal home side is on its own patch (Vegas and other
  neutral grounds erode the home advantage the Elo term assumes)
- lineup availability: share of the previous match's side returning, and
  share of the team's recent regulars in today's lineup — the actual 17
  for played matches, the official team list for upcoming ones (the same
  information a bettor has from Tuesday)

Draws (rare in the NRL) keep Elo/form updates at 0.5 but rows are emitted
with home_win None so the caller decides how to treat them.
"""

import math
from collections import deque
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from genpicks.db.models import Match, PlayerMatchStats, Team, TeamListEntry, Venue
from genpicks.ml.geo import METRO_KM, travel_km

ELO_INITIAL = 1500.0
ELO_K = 32.0
ELO_HOME_ADVANTAGE = 60.0
ELO_SEASON_REGRESSION = 1 / 3  # pull toward the mean between seasons

FINALS_ORDER = {"QF": 1, "EF": 1, "SF": 2, "PF": 3, "GF": 4}


@dataclass
class _TeamState:
    elo: float = ELO_INITIAL
    recent: deque = field(default_factory=lambda: deque(maxlen=10))
    season_wins: float = 0.0
    season_games: int = 0
    last_match_date: object = None  # datetime.date
    last_season: int | None = None
    # lineup history persists across the offseason on purpose: a season
    # opener against last year's final lineup measures roster continuity,
    # and a regular who left over summer is exactly a missing regular
    last_lineup: set[int] | None = None
    lineup_history: deque = field(default_factory=lambda: deque(maxlen=10))


MIN_LINEUP = 13  # fewer resolved players than this = not a usable lineup
REGULAR_SHARE = 0.6  # in >=60% of the last 10 lineups = a regular
MIN_LINEUP_HISTORY = 5  # games before "regulars" means anything


def _availability(state: _TeamState, lineup: set[int] | None, prefix: str) -> dict:
    """Pre-match lineup features: who is playing, of those who usually do.

    `lineup` is the actual 17 for played matches (training) and the official
    team list for upcoming ones (serving) — the same information a bettor has
    from Tuesday. NaN when no usable lineup exists; XGBoost handles missing.
    """
    row = {f"{prefix}_returning_share": math.nan, f"{prefix}_regulars_available": math.nan}
    if lineup is None or len(lineup) < MIN_LINEUP:
        return row
    if state.last_lineup:
        row[f"{prefix}_returning_share"] = len(lineup & state.last_lineup) / len(
            state.last_lineup
        )
    if len(state.lineup_history) >= MIN_LINEUP_HISTORY:
        threshold = REGULAR_SHARE * len(state.lineup_history)
        counts: dict[int, int] = {}
        for past in state.lineup_history:
            for player_id in past:
                counts[player_id] = counts.get(player_id, 0) + 1
        regulars = {player_id for player_id, n in counts.items() if n >= threshold}
        if regulars:
            row[f"{prefix}_regulars_available"] = len(lineup & regulars) / len(regulars)
    return row


def _round_number(round_label: str, last_regular: int = 27) -> int:
    if round_label in FINALS_ORDER:
        return last_regular + FINALS_ORDER[round_label]
    return int(round_label)


def _elo_expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(rating_a - rating_b) / 400.0))


def _form(state: _TeamState, window: int, prefix: str) -> dict:
    games = list(state.recent)[-window:]
    if not games:
        return {
            f"{prefix}_win_rate_{window}": None,
            f"{prefix}_points_for_{window}": None,
            f"{prefix}_points_against_{window}": None,
            f"{prefix}_margin_{window}": None,
        }
    n = len(games)
    return {
        f"{prefix}_win_rate_{window}": sum(g[0] for g in games) / n,
        f"{prefix}_points_for_{window}": sum(g[1] for g in games) / n,
        f"{prefix}_points_against_{window}": sum(g[2] for g in games) / n,
        f"{prefix}_margin_{window}": sum(g[1] - g[2] for g in games) / n,
    }


def _snapshot(state: _TeamState, prefix: str, match_date, season: int) -> dict:
    row = {
        f"{prefix}_elo": state.elo,
        f"{prefix}_season_win_rate": (
            state.season_wins / state.season_games if state.season_games else None
        ),
        f"{prefix}_games_played": len(state.recent),
        f"{prefix}_rest_days": (
            min((match_date - state.last_match_date).days, 30)
            if state.last_match_date is not None and state.last_season == season
            else None
        ),
    }
    row.update(_form(state, 5, prefix))
    row.update(_form(state, 10, prefix))
    return row


def _roll_season(state: _TeamState, season: int) -> None:
    if state.last_season is not None and state.last_season != season:
        state.elo = state.elo + (ELO_INITIAL - state.elo) * ELO_SEASON_REGRESSION
        state.season_wins = 0.0
        state.season_games = 0


def build_match_dataset(engine: Engine, include_unplayed: bool = False) -> pd.DataFrame:
    """One row per match, chronological, features strictly pre-match.

    Unplayed fixtures (include_unplayed=True) are snapshotted with the same
    pre-match state but never update it, so they can be scored for serving
    without touching the training path.
    """
    with Session(engine) as session:
        query = (
            select(Match)
            .where(Match.match_date.is_not(None))
            .order_by(Match.match_date, Match.kickoff_utc, Match.id)
        )
        if not include_unplayed:
            query = query.where(Match.home_score.is_not(None))
        matches = list(session.scalars(query))
        team_names = dict(session.execute(select(Team.id, Team.name)).tuples().all())
        venue_cities = dict(session.execute(select(Venue.id, Venue.city)).tuples().all())

        # played lineups: everyone who took the field or sat an unused bench
        # spot (minutes stays NULL on old RLP-only rows; 0 marks junk reserve
        # rows from early loader versions, never a real appearance)
        lineups: dict[tuple[int, int], set[int]] = {}
        for match_id, team_id, player_id in session.execute(
            select(
                PlayerMatchStats.match_id, PlayerMatchStats.team_id, PlayerMatchStats.player_id
            ).where(
                (PlayerMatchStats.minutes_played.is_(None))
                | (PlayerMatchStats.minutes_played > 0)
            )
        ):
            lineups.setdefault((match_id, team_id), set()).add(player_id)

        if include_unplayed:
            # official team lists stand in for unplayed fixtures: jerseys 1-17
            # are the matchday side, unresolved debutants are simply absent
            for match_id, team_id, player_id in session.execute(
                select(TeamListEntry.match_id, TeamListEntry.team_id, TeamListEntry.player_id)
                .join(Match, Match.id == TeamListEntry.match_id)
                .where(
                    Match.home_score.is_(None),
                    TeamListEntry.player_id.is_not(None),
                    TeamListEntry.jersey_number <= 17,
                )
            ):
                lineups.setdefault((match_id, team_id), set()).add(player_id)

    states: dict[int, _TeamState] = {}
    rows = []
    for match in matches:
        home = states.setdefault(match.home_team_id, _TeamState())
        away = states.setdefault(match.away_team_id, _TeamState())
        _roll_season(home, match.season)
        _roll_season(away, match.season)

        row = {
            "match_id": match.id,
            "season": match.season,
            "round_number": _round_number(match.round),
            "match_date": match.match_date,
            "home_team_id": match.home_team_id,
            "away_team_id": match.away_team_id,
            "home_score": match.home_score,
            "away_score": match.away_score,
            "home_win": (
                None
                if match.home_score is None
                or match.away_score is None
                or match.home_score == match.away_score
                else match.home_score > match.away_score
            ),
            "elo_expected_home": _elo_expected(home.elo + ELO_HOME_ADVANTAGE, away.elo),
        }
        venue_city = venue_cities.get(match.venue_id) if match.venue_id is not None else None
        home_travel = travel_km(team_names[match.home_team_id], venue_city)
        away_travel = travel_km(team_names[match.away_team_id], venue_city)
        row["home_travel_km"] = home_travel
        row["away_travel_km"] = away_travel
        row["travel_km_diff"] = home_travel - away_travel
        # nominal home side actually on its own patch (Vegas/magic-round
        # style neutral grounds erode the home advantage the Elo term assumes)
        row["home_at_home"] = (
            math.nan if math.isnan(home_travel) else float(home_travel <= METRO_KM)
        )
        home_lineup = lineups.get((match.id, match.home_team_id))
        away_lineup = lineups.get((match.id, match.away_team_id))
        row.update(_availability(home, home_lineup, "home"))
        row.update(_availability(away, away_lineup, "away"))
        row.update(_snapshot(home, "home", match.match_date, match.season))
        row.update(_snapshot(away, "away", match.match_date, match.season))
        row["elo_diff"] = home.elo - away.elo
        rows.append(row)

        if match.home_score is None or match.away_score is None:
            continue  # unplayed fixture: snapshot only, never update state

        # ---- update state AFTER snapshotting (leakage barrier) ----
        outcome_home = (
            0.5
            if match.home_score == match.away_score
            else float(match.home_score > match.away_score)
        )
        expected = _elo_expected(home.elo + ELO_HOME_ADVANTAGE, away.elo)
        home.elo += ELO_K * (outcome_home - expected)
        away.elo -= ELO_K * (outcome_home - expected)

        home.recent.append((outcome_home, match.home_score, match.away_score))
        away.recent.append((1.0 - outcome_home, match.away_score, match.home_score))
        home.season_wins += outcome_home
        away.season_wins += 1.0 - outcome_home
        home.season_games += 1
        away.season_games += 1
        home.last_match_date = away.last_match_date = match.match_date
        home.last_season = away.last_season = match.season
        for state, lineup in ((home, home_lineup), (away, away_lineup)):
            if lineup is not None and len(lineup) >= MIN_LINEUP:
                state.last_lineup = lineup
                state.lineup_history.append(lineup)

    data = pd.DataFrame(rows)
    # Home-minus-away differences: half the width, less collinearity. With
    # ~1200 training matches the tree model overfits the raw pairs (first
    # run: XGB 0.663 test log loss vs 0.653 for its own Elo input).
    for name in (
        "season_win_rate",
        "rest_days",
        "win_rate_5",
        "win_rate_10",
        "margin_5",
        "margin_10",
        "points_for_5",
        "points_against_5",
        "returning_share",
        "regulars_available",
    ):
        data[f"{name}_diff"] = data[f"home_{name}"] - data[f"away_{name}"]
    return data


FEATURE_COLUMNS = [
    "elo_expected_home",
    "elo_diff",
    "round_number",
    "season_win_rate_diff",
    "rest_days_diff",
    "win_rate_5_diff",
    "win_rate_10_diff",
    "margin_5_diff",
    "margin_10_diff",
    "points_for_5_diff",
    "points_against_5_diff",
    "home_games_played",
    # travel (city-level): kept after walk-forward A/B — pooled 2022-26 log
    # loss 0.6384 vs 0.6397 without, improvement stable across seeds
    "travel_km_diff",
    "home_at_home",
    # lineup availability: kept after walk-forward A/B — improved pooled log
    # loss on all 5 seeds tried (mean -0.0028), biggest gains in 2025/2026
    # where official team lists also feed the serving path
    "returning_share_diff",
    "regulars_available_diff",
]
