"""API endpoint tests against a seeded in-memory database."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genpicks.api.main import app, get_session
from genpicks.db.models import Base, Match, Player, Prediction, Team, Venue

TODAY = date.today()


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection: in-memory DB survives
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with Session(engine) as session:
        session.add_all([Team(id=1, name="Alpha"), Team(id=2, name="Beta")])
        session.add(Venue(id=1, name="Big Stadium"))
        session.add(Player(id=1, full_name="Flash Winger"))
        session.add_all(
            [
                # settled match with a correct home prediction
                Match(id=1, season=2026, round="1", match_date=TODAY - timedelta(days=30),
                      home_team_id=1, away_team_id=2, home_score=20, away_score=10,
                      venue_id=1, source="t", source_key="m1"),
                # upcoming fixture
                Match(id=2, season=2026, round="20", match_date=TODAY + timedelta(days=3),
                      home_team_id=2, away_team_id=1, venue_id=1,
                      source="t", source_key="m2"),
            ]
        )
        now = datetime.now(timezone.utc)
        session.add_all(
            [
                Prediction(model_version="v_test", match_id=1, market="h2h",
                           team_id=1, probability=0.7, generated_at=now),
                Prediction(model_version="v_test", match_id=1, market="h2h",
                           team_id=2, probability=0.3, generated_at=now),
                Prediction(model_version="v_test", match_id=2, market="h2h",
                           team_id=2, probability=0.55, generated_at=now),
                Prediction(model_version="v_test", match_id=2, market="h2h",
                           team_id=1, probability=0.45, generated_at=now),
                Prediction(model_version="v_test", match_id=2, market="anytime_try",
                           team_id=1, player_id=1, probability=0.42, generated_at=now),
                Prediction(model_version="v_test", match_id=2, market="first_try",
                           team_id=1, player_id=1, probability=0.08, generated_at=now),
            ]
        )
        session.commit()

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_upcoming_lists_fixture_with_probabilities(client):
    body = client.get("/matches/upcoming").json()
    assert len(body) == 1
    fixture = body[0]
    assert fixture["match_id"] == 2
    assert fixture["home_team"] == "Beta"
    assert fixture["venue"] == "Big Stadium"
    probs = fixture["win_probabilities"]
    assert probs["home"]["probability"] == 0.55
    assert probs["home"]["implied_odds"] == round(1 / 0.55, 2)
    assert probs["away"]["probability"] == 0.45
    assert probs["model_version"] == "v_test"


def test_match_markets(client):
    body = client.get("/matches/2/markets").json()
    assert body["h2h"]["home"]["probability"] == 0.55
    assert body["anytime_try"][0] == {
        "player": "Flash Winger",
        "team": "Alpha",
        "probability": 0.42,
        "implied_odds": round(1 / 0.42, 2),
    }
    assert body["first_try"][0]["probability"] == 0.08
    assert client.get("/matches/999/markets").status_code == 404


def test_track_record_scores_settled_predictions(client):
    body = client.get("/track-record").json()
    assert body["v_test"]["settled"] == 1
    assert body["v_test"]["accuracy"] == 1.0
    assert 0 < body["v_test"]["log_loss"] < 1
