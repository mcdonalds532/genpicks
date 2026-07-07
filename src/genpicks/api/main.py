"""FastAPI app.

Run locally:
    .venv/Scripts/uvicorn genpicks.api.main:app --reload

Endpoints:
    GET /health
    GET /matches/upcoming            fixtures with win probs + implied odds
    GET /matches/{match_id}/markets  all markets for one match
    GET /track-record                settled h2h predictions vs results
"""

import math
from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from genpicks.config import get_settings
from genpicks.db.models import (
    MARKET_ANYTIME_TRY,
    MARKET_FIRST_TRY,
    MARKET_H2H,
    Match,
    Player,
    Prediction,
    Team,
    Venue,
)

app = FastAPI(title="GenPicks", version="0.1.0")

_engine = None
_session_factory = None


def get_session():
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(get_settings().database_url)
        _session_factory = sessionmaker(_engine)
    with _session_factory() as session:
        yield session


def implied_odds(probability: float) -> float | None:
    return round(1.0 / probability, 2) if probability > 0.01 else None


def _latest_h2h(session: Session, match_ids: list[int]) -> dict[int, list[Prediction]]:
    """Newest h2h prediction pair per match (latest model_version wins)."""
    rows = session.scalars(
        select(Prediction)
        .where(Prediction.match_id.in_(match_ids), Prediction.market == MARKET_H2H)
        .order_by(Prediction.generated_at)
    )
    latest: dict[tuple[int, int], Prediction] = {}
    for p in rows:
        latest[(p.match_id, p.team_id)] = p
    grouped: dict[int, list[Prediction]] = {}
    for (match_id, _), p in latest.items():
        grouped.setdefault(match_id, []).append(p)
    return grouped


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/matches/upcoming")
def upcoming_matches(limit: int = 20, session: Session = Depends(get_session)):
    matches = list(
        session.scalars(
            select(Match)
            .where(Match.home_score.is_(None), Match.match_date >= date.today())
            .order_by(Match.match_date, Match.kickoff_utc)
            .limit(limit)
        )
    )
    teams = {t.id: t.name for t in session.scalars(select(Team))}
    venues = {v.id: v.name for v in session.scalars(select(Venue))}
    h2h = _latest_h2h(session, [m.id for m in matches])

    out = []
    for m in matches:
        entry = {
            "match_id": m.id,
            "season": m.season,
            "round": m.round,
            "date": m.match_date.isoformat(),
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "home_team": teams.get(m.home_team_id),
            "away_team": teams.get(m.away_team_id),
            "venue": venues.get(m.venue_id),
            "win_probabilities": None,
        }
        if m.id in h2h:
            probs = {
                ("home" if p.team_id == m.home_team_id else "away"): {
                    "probability": round(p.probability, 4),
                    "implied_odds": implied_odds(p.probability),
                }
                for p in h2h[m.id]
            }
            probs["model_version"] = h2h[m.id][0].model_version
            entry["win_probabilities"] = probs
        out.append(entry)
    return out


@app.get("/matches/{match_id}/markets")
def match_markets(match_id: int, top: int = 10,
                  session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if match is None:
        raise HTTPException(404, "match not found")
    teams = {t.id: t.name for t in session.scalars(select(Team))}
    players = {p.id: p.full_name for p in session.scalars(select(Player))}

    predictions = list(
        session.scalars(
            select(Prediction)
            .where(Prediction.match_id == match_id)
            .order_by(Prediction.generated_at)
        )
    )
    if not predictions:
        raise HTTPException(404, "no predictions for this match")

    def player_market(market: str):
        latest: dict[int, Prediction] = {}
        for p in predictions:
            if p.market == market and p.player_id is not None:
                latest[p.player_id] = p
        ranked = sorted(latest.values(), key=lambda p: -p.probability)[:top]
        return [
            {
                "player": players.get(p.player_id),
                "team": teams.get(p.team_id),
                "probability": round(p.probability, 4),
                "implied_odds": implied_odds(p.probability),
            }
            for p in ranked
        ]

    h2h = _latest_h2h(session, [match_id]).get(match_id, [])
    return {
        "match_id": match_id,
        "home_team": teams.get(match.home_team_id),
        "away_team": teams.get(match.away_team_id),
        "date": match.match_date.isoformat() if match.match_date else None,
        "h2h": {
            ("home" if p.team_id == match.home_team_id else "away"): {
                "probability": round(p.probability, 4),
                "implied_odds": implied_odds(p.probability),
            }
            for p in h2h
        },
        "anytime_try": player_market(MARKET_ANYTIME_TRY),
        "first_try": player_market(MARKET_FIRST_TRY),
        "lineup_note": "player markets use lineups projected from each team's "
                       "most recent match until official team lists are ingested",
    }


@app.get("/track-record")
def track_record(session: Session = Depends(get_session)):
    """Settled home-side h2h predictions vs actual results, per model version."""
    rows = session.execute(
        select(Prediction, Match)
        .join(Match, Match.id == Prediction.match_id)
        .where(
            Prediction.market == MARKET_H2H,
            Prediction.team_id == Match.home_team_id,
            Match.home_score.is_not(None),
        )
    ).all()
    by_version: dict[str, list[tuple[float, int]]] = {}
    for prediction, match in rows:
        if match.home_score == match.away_score:
            continue
        outcome = int(match.home_score > match.away_score)
        by_version.setdefault(prediction.model_version, []).append(
            (prediction.probability, outcome)
        )
    return {
        version: {
            "settled": len(pairs),
            "accuracy": round(
                sum((p > 0.5) == bool(y) for p, y in pairs) / len(pairs), 4
            ),
            "log_loss": round(
                -sum(
                    y * math.log(max(p, 1e-9)) + (1 - y) * math.log(max(1 - p, 1e-9))
                    for p, y in pairs
                ) / len(pairs),
                4,
            ),
        }
        for version, pairs in by_version.items()
        if pairs
    }
