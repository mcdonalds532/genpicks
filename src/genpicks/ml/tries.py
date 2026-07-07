"""Try-scorer modelling: team try rates and player try shares.

Decomposition (per the project design: derived, not directly classified):

- team try count in a match ~ Poisson(lambda_team), lambda from a count
  model over pre-match form features
- each of the team's tries goes to player p with probability share_p
  (multinomial thinning), so player tries ~ Poisson(lambda * share_p) and
      P(anytime try) = 1 - exp(-lambda * share_p)
- competing Poisson processes give
      P(team scores first) = lambda_team / (lambda_home + lambda_away)
      P(first try = p)     = P(team first) * share_p

share_p is empirical-Bayes: the player's trailing try share over their last
SHARE_WINDOW appearances, shrunk toward a position prior by SHARE_ALPHA
pseudo-tries. Shares are renormalised over the actual lineup so each team's
shares sum to one.

Both dataset builders are single chronological passes that snapshot state
before updating it with the match result — same leakage barrier as
features.py.
"""

from collections import deque
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from genpicks.db.models import Match, PlayerMatchStats, TryEvent
from genpicks.ml.features import _round_number

SHARE_WINDOW = 25  # appearances of player history
SHARE_ALPHA = 12.0  # pseudo team-tries of shrinkage toward the position prior

TEAM_FEATURES = [
    "is_home",
    "round_number",
    "tries_for_5", "tries_for_10",
    "tries_against_5", "tries_against_10",
    "opp_tries_for_5", "opp_tries_for_10",
    "opp_tries_against_5", "opp_tries_against_10",
    "season_tries_per_game",
]


# --------------------------------------------------------------------------
# Load the flat tables once
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TryData:
    matches: pd.DataFrame  # played matches, chronological
    appearances: pd.DataFrame  # player_match_stats with tries + position
    first_scorers: dict[int, int]  # match_id -> player_id of try #1


def load_try_data(engine: Engine, include_unplayed: bool = False) -> TryData:
    with Session(engine) as session:
        query = (
            select(Match)
            .where(Match.match_date.is_not(None))
            .order_by(Match.match_date, Match.kickoff_utc, Match.id)
        )
        if not include_unplayed:
            query = query.where(Match.home_score.is_not(None))
        matches = pd.DataFrame(
            [
                {
                    "match_id": m.id,
                    "season": m.season,
                    "round_number": _round_number(m.round),
                    "match_date": m.match_date,
                    "home_team_id": m.home_team_id,
                    "away_team_id": m.away_team_id,
                    "played": m.home_score is not None,
                }
                for m in session.scalars(query)
            ]
        )
        appearances = pd.read_sql(
            select(
                PlayerMatchStats.match_id,
                PlayerMatchStats.player_id,
                PlayerMatchStats.team_id,
                PlayerMatchStats.position,
                PlayerMatchStats.tries,
            ).where(PlayerMatchStats.tries.is_not(None)),
            session.connection(),
        )
        first_scorers = {
            match_id: player_id
            for match_id, player_id in session.execute(
                select(TryEvent.match_id, TryEvent.player_id).where(
                    TryEvent.scoring_order == 1, TryEvent.player_id.is_not(None)
                )
            )
        }
    return TryData(matches=matches, appearances=appearances, first_scorers=first_scorers)


# --------------------------------------------------------------------------
# Team try-rate dataset (two rows per match: one per team)
# --------------------------------------------------------------------------


@dataclass
class _TeamTryState:
    scored: deque = field(default_factory=lambda: deque(maxlen=10))
    conceded: deque = field(default_factory=lambda: deque(maxlen=10))
    season_tries: int = 0
    season_games: int = 0
    last_season: int | None = None


def _avg(values, window):
    values = list(values)[-window:]
    return sum(values) / len(values) if values else None


def build_team_try_dataset(data: TryData) -> pd.DataFrame:
    """One row per team per played match; target `tries`, features pre-match."""
    team_tries = (
        data.appearances.groupby(["match_id", "team_id"])["tries"].sum().to_dict()
    )
    states: dict[int, _TeamTryState] = {}
    rows = []
    for match in data.matches.itertuples():
        sides = (
            (match.home_team_id, match.away_team_id, 1),
            (match.away_team_id, match.home_team_id, 0),
        )
        for team_id, opp_id, is_home in sides:
            team = states.setdefault(team_id, _TeamTryState())
            opp = states.setdefault(opp_id, _TeamTryState())
            for state in (team, opp):
                if state.last_season is not None and state.last_season != match.season:
                    state.season_tries = 0
                    state.season_games = 0
            rows.append(
                {
                    "match_id": match.match_id,
                    "season": match.season,
                    "team_id": team_id,
                    "is_home": is_home,
                    "round_number": match.round_number,
                    "tries_for_5": _avg(team.scored, 5),
                    "tries_for_10": _avg(team.scored, 10),
                    "tries_against_5": _avg(team.conceded, 5),
                    "tries_against_10": _avg(team.conceded, 10),
                    "opp_tries_for_5": _avg(opp.scored, 5),
                    "opp_tries_for_10": _avg(opp.scored, 10),
                    "opp_tries_against_5": _avg(opp.conceded, 5),
                    "opp_tries_against_10": _avg(opp.conceded, 10),
                    "season_tries_per_game": (
                        team.season_tries / team.season_games
                        if team.season_games
                        else None
                    ),
                    "tries": (
                        team_tries.get((match.match_id, team_id), 0)
                        if match.played
                        else None
                    ),
                }
            )
        if not match.played:
            continue  # unplayed fixture: snapshot only, never update state

        # ---- update AFTER both teams' rows are snapshotted ----
        home_tries = team_tries.get((match.match_id, match.home_team_id), 0)
        away_tries = team_tries.get((match.match_id, match.away_team_id), 0)
        home_state = states[match.home_team_id]
        away_state = states[match.away_team_id]
        home_state.scored.append(home_tries)
        home_state.conceded.append(away_tries)
        away_state.scored.append(away_tries)
        away_state.conceded.append(home_tries)
        home_state.season_tries += home_tries
        away_state.season_tries += away_tries
        home_state.season_games += 1
        away_state.season_games += 1
        home_state.last_season = away_state.last_season = match.season

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Player try shares
# --------------------------------------------------------------------------


def position_priors(
    data: TryData, train_seasons: set[int]
) -> tuple[dict[str, float], float]:
    """Prior try share per position from training seasons only.

    Returns ({position: share of a team's tries}, fallback share).
    Share = (position tries per player-game) / (team tries per game).
    """
    train_ids = set(
        data.matches[data.matches["season"].isin(train_seasons)]["match_id"]
    )
    apps = data.appearances[data.appearances["match_id"].isin(train_ids)]
    team_games = apps.groupby(["match_id", "team_id"]).ngroups
    if team_games == 0:
        return {}, 0.0
    team_tries_per_game = apps["tries"].sum() / team_games

    priors = {}
    for position, group in apps.groupby(apps["position"].fillna("Unknown")):
        tries_per_player_game = group["tries"].sum() / len(group)
        priors[position] = tries_per_player_game / team_tries_per_game
    fallback = (apps["tries"].sum() / len(apps)) / team_tries_per_game
    return priors, fallback


@dataclass
class _PlayerShareState:
    history: deque = field(default_factory=lambda: deque(maxlen=SHARE_WINDOW))
    # each item: (player_tries, team_tries) for one appearance


def build_share_dataset(
    data: TryData, priors: dict[str, float], fallback_prior: float
) -> pd.DataFrame:
    """One row per appearance: pre-match share estimate + outcomes.

    share_raw = (sum player tries + alpha * prior * mean team tries)
              / (sum team tries in those games + alpha * mean team tries)
    collapsing to the position prior with no history and to the empirical
    share with lots of it.
    """
    team_tries = (
        data.appearances.groupby(["match_id", "team_id"])["tries"].sum().to_dict()
    )
    mean_team_tries = (
        sum(team_tries.values()) / len(team_tries) if team_tries else 0.0
    )
    order = {m: i for i, m in enumerate(data.matches["match_id"])}
    apps = data.appearances.sort_values(
        "match_id", key=lambda s: s.map(order)
    )

    states: dict[int, _PlayerShareState] = {}
    rows = []
    current_match = None
    pending = []  # (state, player_tries, team_tries) applied after the match
    for app in apps.itertuples():
        if app.match_id != current_match:
            for state, p_tries, t_tries in pending:
                state.history.append((p_tries, t_tries))
            pending = []
            current_match = app.match_id

        state = states.setdefault(app.player_id, _PlayerShareState())
        prior = priors.get(app.position or "Unknown", fallback_prior)
        hist_player = sum(h[0] for h in state.history)
        hist_team = sum(h[1] for h in state.history)
        pseudo = SHARE_ALPHA * mean_team_tries
        share_raw = (
            (hist_player + prior * pseudo) / (hist_team + pseudo)
            if (hist_team + pseudo) > 0
            else prior
        )
        match_team_tries = team_tries.get((app.match_id, app.team_id), 0)
        rows.append(
            {
                "match_id": app.match_id,
                "player_id": app.player_id,
                "team_id": app.team_id,
                "position": app.position,
                "share_raw": share_raw,
                "prior": prior,
                "history_games": len(state.history),
                "tries": app.tries,
                "scored_anytime": app.tries > 0,
            }
        )
        pending.append((state, app.tries, match_team_tries))
    for state, p_tries, t_tries in pending:
        state.history.append((p_tries, t_tries))

    frame = pd.DataFrame(rows)
    # renormalise within each actual lineup so team shares sum to 1
    totals = frame.groupby(["match_id", "team_id"])["share_raw"].transform("sum")
    frame["share"] = frame["share_raw"] / totals
    return frame


def current_shares(
    data: TryData,
    priors: dict[str, float],
    fallback_prior: float,
    lineup: list[tuple[int, str | None]],  # (player_id, position)
) -> dict[int, float]:
    """Raw share estimate per player as of now (all played history).

    Same formula as build_share_dataset but evaluated after the last played
    match, for serving. Caller renormalises over the lineup.
    """
    team_tries = (
        data.appearances.groupby(["match_id", "team_id"])["tries"].sum().to_dict()
    )
    mean_team_tries = sum(team_tries.values()) / len(team_tries) if team_tries else 0.0
    pseudo = SHARE_ALPHA * mean_team_tries
    order = {m: i for i, m in enumerate(data.matches["match_id"])}
    apps = data.appearances.sort_values("match_id", key=lambda s: s.map(order))

    shares = {}
    for player_id, position in lineup:
        history = apps[apps["player_id"] == player_id].tail(SHARE_WINDOW)
        hist_player = int(history["tries"].sum())
        hist_team = sum(
            team_tries.get((m, t), 0)
            for m, t in zip(history["match_id"], history["team_id"])
        )
        prior = priors.get(position or "Unknown", fallback_prior)
        shares[player_id] = (
            (hist_player + prior * pseudo) / (hist_team + pseudo)
            if (hist_team + pseudo) > 0
            else prior
        )
    return shares
