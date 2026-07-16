"""FastAPI app.

Run locally:
    .venv/Scripts/uvicorn genpicks.api.main:app --reload

Endpoints:
    GET /health
    GET /matches/upcoming            fixtures with win probs + implied odds
    GET /matches/{match_id}/markets  all markets for one match; try markets
                                     require an entitled internal caller
    GET /track-record                settled h2h predictions vs results
    POST /internal/users/sync        upsert a user on OAuth sign-in
                                     (Next.js server only, shared key)
    POST /internal/billing/checkout  Stripe hosted-checkout URL (billing.py)
    POST /webhooks/stripe            subscription lifecycle (billing.py)
"""

import math
from datetime import UTC, date, datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from genpicks.api.billing import router as billing_router
from genpicks.api.deps import get_session, is_internal
from genpicks.api.observability import setup_observability
from genpicks.config import get_settings
from genpicks.db.models import (
    MARKET_ANYTIME_TRY,
    MARKET_FIRST_TRY,
    MARKET_H2H,
    Match,
    OddsSnapshot,
    Player,
    Prediction,
    Team,
    User,
    Venue,
)

LIVE_ODDS_SOURCE = "oddsapi"

app = FastAPI(title="GenPicks", version="0.1.0")
setup_observability(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in get_settings().cors_origins.split(",") if origin.strip()
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(billing_router)


def implied_odds(probability: float) -> float | None:
    return round(1.0 / probability, 2) if probability > 0.01 else None


def _latest_h2h(session: Session, match_ids: list[int]) -> dict[int, list[Prediction]]:
    """Newest h2h prediction pair per match (latest model_version wins)."""
    rows = session.scalars(
        select(Prediction)
        .where(Prediction.match_id.in_(match_ids), Prediction.market == MARKET_H2H)
        .order_by(Prediction.generated_at)
    )
    latest: dict[tuple[int, int | None], Prediction] = {}
    for p in rows:
        latest[(p.match_id, p.team_id)] = p
    grouped: dict[int, list[Prediction]] = {}
    for (match_id, _), p in latest.items():
        grouped.setdefault(match_id, []).append(p)
    return grouped


def _latest_market_odds(session: Session, match_ids: list[int]) -> dict[int, dict]:
    """Per match: the newest live-odds snapshot, condensed to the best
    (highest) decimal price per team across bookmakers."""
    rows = list(
        session.scalars(
            select(OddsSnapshot).where(
                OddsSnapshot.match_id.in_(match_ids),
                OddsSnapshot.source == LIVE_ODDS_SOURCE,
                OddsSnapshot.market == MARKET_H2H,
            )
        )
    )
    newest: dict[int | None, datetime] = {}
    for row in rows:
        if row.match_id not in newest or row.captured_at > newest[row.match_id]:
            newest[row.match_id] = row.captured_at
    out: dict[int, dict] = {}
    for row in rows:
        if row.match_id is None or row.team_id is None or row.captured_at != newest[row.match_id]:
            continue
        entry = out.setdefault(
            row.match_id, {"captured_at": row.captured_at.isoformat(), "teams": {}}
        )
        best = entry["teams"].get(row.team_id)
        if best is None or float(row.price_decimal) > best["price"]:
            entry["teams"][row.team_id] = {
                "price": float(row.price_decimal),
                "bookmaker": (row.raw or {}).get("title"),
            }
        entry["bookmakers"] = len(
            {
                (r.raw or {}).get("bookmaker")
                for r in rows
                if r.match_id == row.match_id and r.captured_at == newest[row.match_id]
            }
        )
    return out


def _sided_odds(odds: dict | None, match: Match) -> dict | None:
    if odds is None:
        return None
    return {
        "home": odds["teams"].get(match.home_team_id),
        "away": odds["teams"].get(match.away_team_id),
        "bookmakers": odds.get("bookmakers", 0),
        "captured_at": odds["captured_at"],
    }


def _viewer_subscribed(session: Session, internal_key: str | None, user_id: str | None) -> bool:
    if not is_internal(internal_key) or not user_id:
        return False
    try:
        user = session.get(User, int(user_id))
    except ValueError:
        return False
    return user is not None and user.subscription_status == "active"


class UserSyncPayload(BaseModel):
    github_id: str
    email: str | None = None
    name: str | None = None
    avatar_url: str | None = None


@app.post("/internal/users/sync")
def sync_user(
    payload: UserSyncPayload,
    x_internal_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    """Upsert a user on OAuth sign-in; profile fields refresh every call."""
    if not is_internal(x_internal_key):
        raise HTTPException(401, "invalid internal key")
    user = session.scalar(select(User).where(User.github_id == payload.github_id))
    if user is None:
        user = User(
            github_id=payload.github_id,
            created_at=datetime.now(UTC),
        )
        session.add(user)
    user.email = payload.email
    user.name = payload.name
    user.avatar_url = payload.avatar_url
    session.commit()
    return {
        "user_id": user.id,
        "subscription_active": user.subscription_status == "active",
    }


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
    teams: dict[int | None, str] = {t.id: t.name for t in session.scalars(select(Team))}
    venues: dict[int | None, str] = {v.id: v.name for v in session.scalars(select(Venue))}
    h2h = _latest_h2h(session, [m.id for m in matches])
    market_odds = _latest_market_odds(session, [m.id for m in matches])

    out = []
    for m in matches:
        entry = {
            "match_id": m.id,
            "season": m.season,
            "round": m.round,
            "date": m.match_date.isoformat() if m.match_date else None,
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "home_team": teams.get(m.home_team_id),
            "away_team": teams.get(m.away_team_id),
            "venue": venues.get(m.venue_id),
            "win_probabilities": None,
            "market_odds": _sided_odds(market_odds.get(m.id), m),
        }
        if m.id in h2h:
            probs: dict[str, Any] = {
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
def match_markets(
    match_id: int,
    top: int = 10,
    x_internal_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    match = session.get(Match, match_id)
    if match is None:
        raise HTTPException(404, "match not found")
    teams: dict[int | None, str] = {t.id: t.name for t in session.scalars(select(Team))}
    players: dict[int | None, str] = {p.id: p.full_name for p in session.scalars(select(Player))}

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
        """Rows of the newest generation only: a projected-lineup generation
        is superseded wholesale once official team lists arrive, and stale
        players must not survive the changeover."""
        rows = [p for p in predictions if p.market == market and p.player_id is not None]
        if not rows:
            return [], None
        newest = max(p.generated_at for p in rows)
        current = [p for p in rows if p.generated_at == newest]
        ranked = sorted(current, key=lambda p: -p.probability)[:top]
        return [
            {
                "player": players.get(p.player_id),
                "team": teams.get(p.team_id),
                "probability": round(p.probability, 4),
                "implied_odds": implied_odds(p.probability),
            }
            for p in ranked
        ], current[0].lineup_source

    anytime, anytime_source = player_market(MARKET_ANYTIME_TRY)
    first, first_source = player_market(MARKET_FIRST_TRY)
    # Try-scorer markets are the paid tier. The check lives here — not only
    # in the frontend — so a direct request to the public API can't bypass
    # the paywall: without the internal key + a subscribed user, the tables
    # are withheld and only their row counts are disclosed.
    locked = not _viewer_subscribed(session, x_internal_key, x_user_id)
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
        # grouped SHAP factors from the newest h2h generation (home row);
        # positive logit leans home, negative leans away
        "h2h_explanation": next(
            (p.explanation for p in h2h if p.team_id == match.home_team_id), None
        ),
        "anytime_try": None if locked else anytime,
        "first_try": None if locked else first,
        "try_markets_locked": locked,
        # row counts let the locked panel say what the subscription unlocks
        "try_market_counts": {"anytime_try": len(anytime), "first_try": len(first)},
        "market_odds": _sided_odds(_latest_market_odds(session, [match_id]).get(match_id), match),
        # "official": published team lists; "projected": each team's most
        # recent played lineup (team lists not out yet)
        "lineup_source": anytime_source or first_source,
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
    # newest generation only: a projected h2h prediction superseded by an
    # official-lineup one must not double-count the match
    newest: dict[tuple[str, int], tuple] = {}
    for prediction, match in rows:
        if match.home_score == match.away_score:
            continue
        key = (prediction.model_version, prediction.match_id)
        if key not in newest or prediction.generated_at > newest[key][0].generated_at:
            newest[key] = (prediction, match)
    by_version: dict[str, list[tuple[float, int]]] = {}
    for prediction, match in newest.values():
        outcome = int(match.home_score > match.away_score)
        by_version.setdefault(prediction.model_version, []).append(
            (prediction.probability, outcome)
        )
    return {
        version: {
            "settled": len(pairs),
            "accuracy": round(sum((p > 0.5) == bool(y) for p, y in pairs) / len(pairs), 4),
            "log_loss": round(
                -sum(
                    y * math.log(max(p, 1e-9)) + (1 - y) * math.log(max(1 - p, 1e-9))
                    for p, y in pairs
                )
                / len(pairs),
                4,
            ),
        }
        for version, pairs in by_version.items()
        if pairs
    }
