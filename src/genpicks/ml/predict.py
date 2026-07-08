"""Generate predictions for upcoming fixtures and append them to the DB.

Usage:
    python -m genpicks.ml.predict            # all future fixtures
    python -m genpicks.ml.predict --days 10

Loads the newest saved match-winner and try-scorer artifacts from
data/models/, scores every unplayed fixture, and appends rows to the
predictions table (append-only by design: a (model_version, match, market)
combination is written at most once, so re-runs only add what's missing).

Lineups for the try markets come from ingested official team lists when a
match has them for both sides (lineup_source="official"); otherwise they are
projected from each team's most recent played match ("projected"). A
projected generation is superseded by appending an official one once team
lists arrive — rows are never updated — and readers take the newest
generation per market. First-try probabilities are conditional on a try
being scored and normalised per match.
"""

import argparse
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import xgboost as xgb
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from genpicks.config import get_settings
from genpicks.db.models import (
    MARKET_ANYTIME_TRY,
    MARKET_FIRST_TRY,
    MARKET_H2H,
    Match,
    Prediction,
    TeamListEntry,
)
from genpicks.ml.features import FEATURE_COLUMNS, build_match_dataset
from genpicks.ml.tries import (
    TEAM_FEATURES,
    build_team_try_dataset,
    current_shares,
    load_try_data,
    position_priors,
)

logger = logging.getLogger(__name__)


def latest_model_dir(models_root: Path, prefix: str) -> Path:
    dirs = sorted(d for d in models_root.iterdir() if d.name.startswith(prefix))
    if not dirs:
        raise FileNotFoundError(f"no {prefix}* under {models_root} — train first")
    return dirs[-1]


def existing_keys(session: Session, model_version: str) -> set[tuple[int, str]]:
    return set(
        session.execute(
            select(Prediction.match_id, Prediction.market).where(
                Prediction.model_version == model_version
            )
        )
    )


def predict_h2h(session, engine, models_root: Path, upcoming_ids: set[int]) -> int:
    model_dir = latest_model_dir(models_root, "match_winner_")
    report = json.loads((model_dir / "report.json").read_text(encoding="utf-8"))
    version = report["model_version"]
    platt = report["calibrator_platt"]
    booster = xgb.Booster()
    booster.load_model(model_dir / "model.json")

    data = build_match_dataset(engine, include_unplayed=True)
    rows = data[data["match_id"].isin(upcoming_ids)]
    if rows.empty:
        return 0
    raw = booster.predict(
        xgb.DMatrix(rows[FEATURE_COLUMNS].astype(float), feature_names=FEATURE_COLUMNS)
    )
    logit = np.log(np.clip(raw, 1e-6, 1 - 1e-6) / (1 - np.clip(raw, 1e-6, 1 - 1e-6)))
    prob_home = 1.0 / (1.0 + np.exp(-(platt["coef"] * logit + platt["intercept"])))

    done = existing_keys(session, version)
    now = datetime.now(timezone.utc)
    written = 0
    for row, p in zip(rows.itertuples(), prob_home):
        if (row.match_id, MARKET_H2H) in done:
            continue
        for team_id, prob in ((row.home_team_id, float(p)),
                              (row.away_team_id, float(1 - p))):
            session.add(
                Prediction(
                    model_version=version, match_id=row.match_id, market=MARKET_H2H,
                    team_id=team_id, probability=prob, generated_at=now,
                )
            )
        written += 1
    logger.info("h2h (%s): %d matches written", version, written)
    return written


def official_lineups(
    session: Session, match_ids: set[int]
) -> dict[tuple[int, int], list[tuple[int, str | None]]]:
    """Usable official lineups keyed by (match_id, team_id).

    Jerseys 1-17 are the matchday side; higher numbers and unnumbered names
    are cover players. A lineup is usable when at least 13 of its players
    resolved to canonical ids (unresolved debutants are simply absent — their
    try share is diffuse anyway with no appearance history).
    """
    lineups: dict[tuple[int, int], list[tuple[int, str | None]]] = {}
    for entry in session.scalars(
        select(TeamListEntry).where(
            TeamListEntry.match_id.in_(match_ids),
            TeamListEntry.player_id.is_not(None),
        )
    ):
        if entry.jersey_number is None or entry.jersey_number > 17:
            continue
        lineups.setdefault((entry.match_id, entry.team_id), []).append(
            (entry.player_id, entry.position)
        )
    return {key: lineup for key, lineup in lineups.items() if len(lineup) >= 13}


def newest_try_generation(session: Session, model_version: str) -> dict[int, str | None]:
    """match_id -> lineup_source of the newest try-market generation."""
    newest: dict[int, str | None] = {}
    for match_id, lineup_source in session.execute(
        select(Prediction.match_id, Prediction.lineup_source)
        .where(
            Prediction.model_version == model_version,
            Prediction.market == MARKET_ANYTIME_TRY,
        )
        .order_by(Prediction.generated_at)
    ):
        newest[match_id] = lineup_source
    return newest


def predict_tries(session, engine, models_root: Path, upcoming_ids: set[int]) -> int:
    model_dir = latest_model_dir(models_root, "try_scorer_")
    report = json.loads((model_dir / "report.json").read_text(encoding="utf-8"))
    version = report["model_version"]
    booster = xgb.Booster()
    booster.load_model(model_dir / "team_try_model.json")

    data = load_try_data(engine, include_unplayed=True)
    team_rows = build_team_try_dataset(data)
    team_rows = team_rows[team_rows["match_id"].isin(upcoming_ids)].copy()
    if team_rows.empty:
        return 0
    team_rows["lam"] = booster.predict(
        xgb.DMatrix(team_rows[TEAM_FEATURES].astype(float), feature_names=TEAM_FEATURES)
    )

    priors, fallback = position_priors(
        data, set(report["splits"]["train"]) | set(report["splits"]["val"])
    )

    # projected lineup: the team's most recent played match
    played = data.matches[data.matches["played"]]
    apps = data.appearances
    last_match: dict[int, int] = {}
    for match in played.itertuples():  # chronological
        last_match[match.home_team_id] = match.match_id
        last_match[match.away_team_id] = match.match_id

    newest = newest_try_generation(session, version)
    official = official_lineups(session, upcoming_ids)
    now = datetime.now(timezone.utc)
    lam_sum = team_rows.groupby("match_id")["lam"].sum().to_dict()
    written = {"official": 0, "projected": 0}
    for match_id, group in team_rows.groupby("match_id"):
        team_ids = [team.team_id for team in group.itertuples()]
        basis = (
            "official"
            if all((match_id, team_id) in official for team_id in team_ids)
            else "projected"
        )
        # a projected generation is superseded once official lists arrive;
        # an official one is final, and re-runs never duplicate a basis
        prev = newest.get(match_id, "none")
        if prev in (basis, "official"):
            continue
        entries = []  # (team_id, player_id, share, lam)
        for team in group.itertuples():
            lineup = official.get((match_id, team.team_id))
            if lineup is None:
                source_match = last_match.get(team.team_id)
                if source_match is None:
                    continue
                lineup_rows = apps[
                    (apps["match_id"] == source_match)
                    & (apps["team_id"] == team.team_id)
                ]
                lineup = list(zip(lineup_rows["player_id"], lineup_rows["position"]))
            shares = current_shares(data, priors, fallback, lineup)
            total = sum(shares.values()) or 1.0
            for player_id, share_raw in shares.items():
                entries.append((team.team_id, player_id, share_raw / total, team.lam))
        for team_id, player_id, share, lam in entries:
            p_any = 1.0 - float(np.exp(-lam * share))
            p_first = float(lam / lam_sum[match_id] * share)
            session.add(
                Prediction(
                    model_version=version, match_id=match_id,
                    market=MARKET_ANYTIME_TRY, team_id=team_id,
                    player_id=player_id, probability=p_any, generated_at=now,
                    lineup_source=basis,
                )
            )
            session.add(
                Prediction(
                    model_version=version, match_id=match_id,
                    market=MARKET_FIRST_TRY, team_id=team_id,
                    player_id=player_id, probability=p_first, generated_at=now,
                    lineup_source=basis,
                )
            )
        written[basis] += 1
    logger.info(
        "try markets (%s): %d matches written from official lists, %d projected",
        version, written["official"], written["projected"],
    )
    return sum(written.values())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--models-root", type=Path, default=Path("data/models"))
    parser.add_argument("--days", type=int, default=None,
                        help="only fixtures within N days (default: all)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    engine = create_engine(args.database_url or get_settings().database_url)
    with Session(engine) as session:
        query = select(Match.id, Match.match_date).where(
            Match.home_score.is_(None), Match.match_date >= date.today()
        )
        rows = session.execute(query).all()
        if args.days is not None:
            rows = [r for r in rows if (r.match_date - date.today()).days <= args.days]
        upcoming = {r.id for r in rows}
        logger.info("upcoming fixtures to score: %d", len(upcoming))

        predict_h2h(session, engine, args.models_root, upcoming)
        predict_tries(session, engine, args.models_root, upcoming)
        session.commit()


if __name__ == "__main__":
    main()
