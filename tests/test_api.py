"""API endpoint tests against a seeded in-memory database."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genpicks.api.main import app, get_session
from genpicks.config import get_settings
from genpicks.db.models import (
    Base,
    Match,
    OddsSnapshot,
    Player,
    Prediction,
    Team,
    User,
    Venue,
)

TODAY = date.today()

INTERNAL_KEY = "test-internal-key"
SUBSCRIBED = {"X-Internal-Key": INTERNAL_KEY, "X-User-Id": "1"}
FREE_USER = {"X-Internal-Key": INTERNAL_KEY, "X-User-Id": "2"}


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
        session.add_all(
            [
                Player(id=1, full_name="Flash Winger"),
                Player(id=2, full_name="Late Callup"),
            ]
        )
        session.add_all(
            [
                # settled match with a correct home prediction
                Match(
                    id=1,
                    season=2026,
                    round="1",
                    match_date=TODAY - timedelta(days=30),
                    home_team_id=1,
                    away_team_id=2,
                    home_score=20,
                    away_score=10,
                    venue_id=1,
                    source="t",
                    source_key="m1",
                ),
                # upcoming fixture
                Match(
                    id=2,
                    season=2026,
                    round="20",
                    match_date=TODAY + timedelta(days=3),
                    home_team_id=2,
                    away_team_id=1,
                    venue_id=1,
                    source="t",
                    source_key="m2",
                ),
            ]
        )
        now = datetime.now(UTC)
        session.add_all(
            [
                User(
                    id=1,
                    github_id="100",
                    name="Paying Punter",
                    created_at=now,
                    subscription_status="active",
                ),
                User(id=2, github_id="200", name="Free Fan", created_at=now),
            ]
        )
        session.add_all(
            [
                Prediction(
                    model_version="v_test",
                    match_id=1,
                    market="h2h",
                    team_id=1,
                    probability=0.7,
                    generated_at=now,
                ),
                Prediction(
                    model_version="v_test",
                    match_id=1,
                    market="h2h",
                    team_id=2,
                    probability=0.3,
                    generated_at=now,
                ),
                Prediction(
                    model_version="v_test",
                    match_id=2,
                    market="h2h",
                    team_id=2,
                    probability=0.55,
                    generated_at=now,
                ),
                Prediction(
                    model_version="v_test",
                    match_id=2,
                    market="h2h",
                    team_id=1,
                    probability=0.45,
                    generated_at=now,
                ),
                # projected-lineup generation, superseded by the official one
                # below: only the newest generation may be served
                Prediction(
                    model_version="v_test",
                    match_id=2,
                    market="anytime_try",
                    team_id=1,
                    player_id=1,
                    probability=0.42,
                    generated_at=now - timedelta(hours=2),
                    lineup_source="projected",
                ),
                Prediction(
                    model_version="v_test",
                    match_id=2,
                    market="first_try",
                    team_id=1,
                    player_id=1,
                    probability=0.08,
                    generated_at=now - timedelta(hours=2),
                    lineup_source="projected",
                ),
                Prediction(
                    model_version="v_test",
                    match_id=2,
                    market="anytime_try",
                    team_id=1,
                    player_id=1,
                    probability=0.5,
                    generated_at=now,
                    lineup_source="official",
                ),
                Prediction(
                    model_version="v_test",
                    match_id=2,
                    market="anytime_try",
                    team_id=1,
                    player_id=2,
                    probability=0.3,
                    generated_at=now,
                    lineup_source="official",
                ),
                Prediction(
                    model_version="v_test",
                    match_id=2,
                    market="first_try",
                    team_id=1,
                    player_id=1,
                    probability=0.1,
                    generated_at=now,
                    lineup_source="official",
                ),
            ]
        )
        session.add_all(
            [
                # stale snapshot that must not be served
                OddsSnapshot(
                    source="oddsapi",
                    market="h2h",
                    match_id=2,
                    team_id=2,
                    selection_name="Beta",
                    price_decimal=1.9,
                    captured_at=now - timedelta(hours=6),
                    raw={"bookmaker": "tab", "title": "TAB"},
                ),
                # newest snapshot: two bookmakers, best price per team wins
                OddsSnapshot(
                    source="oddsapi",
                    market="h2h",
                    match_id=2,
                    team_id=2,
                    selection_name="Beta",
                    price_decimal=1.8,
                    captured_at=now,
                    raw={"bookmaker": "tab", "title": "TAB"},
                ),
                OddsSnapshot(
                    source="oddsapi",
                    market="h2h",
                    match_id=2,
                    team_id=2,
                    selection_name="Beta",
                    price_decimal=1.85,
                    captured_at=now,
                    raw={"bookmaker": "sportsbet", "title": "SportsBet"},
                ),
                OddsSnapshot(
                    source="oddsapi",
                    market="h2h",
                    match_id=2,
                    team_id=1,
                    selection_name="Alpha",
                    price_decimal=2.1,
                    captured_at=now,
                    raw={"bookmaker": "tab", "title": "TAB"},
                ),
            ]
        )
        session.commit()

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    settings = get_settings()
    previous_key = settings.internal_api_key
    settings.internal_api_key = INTERNAL_KEY
    yield TestClient(app)
    settings.internal_api_key = previous_key
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


def test_match_markets_serve_newest_generation_only(client):
    body = client.get("/matches/2/markets", headers=SUBSCRIBED).json()
    assert body["h2h"]["home"]["probability"] == 0.55
    assert body["try_markets_locked"] is False
    assert body["anytime_try"][0] == {
        "player": "Flash Winger",
        "team": "Alpha",
        "probability": 0.5,
        "implied_odds": round(1 / 0.5, 2),
    }
    # the superseded projected generation (0.42 / 0.08) is not served
    assert [e["probability"] for e in body["anytime_try"]] == [0.5, 0.3]
    assert [e["probability"] for e in body["first_try"]] == [0.1]
    assert body["lineup_source"] == "official"
    assert client.get("/matches/999/markets").status_code == 404


def test_try_markets_locked_without_entitled_viewer(client):
    # anonymous, free signed-in user, wrong key, unknown user: all locked
    for headers in (
        {},
        FREE_USER,
        {"X-Internal-Key": "wrong", "X-User-Id": "1"},
        {"X-Internal-Key": INTERNAL_KEY, "X-User-Id": "999"},
    ):
        body = client.get("/matches/2/markets", headers=headers).json()
        assert body["try_markets_locked"] is True
        assert body["anytime_try"] is None
        assert body["first_try"] is None
        # free content and the unlock teaser still served
        assert body["h2h"]["home"]["probability"] == 0.55
        assert body["try_market_counts"] == {"anytime_try": 2, "first_try": 1}


def test_user_sync_upserts_and_reports_subscription(client):
    unauthorized = client.post(
        "/internal/users/sync",
        json={"github_id": "300"},
        headers={"X-Internal-Key": "wrong"},
    )
    assert unauthorized.status_code == 401

    created = client.post(
        "/internal/users/sync",
        json={"github_id": "300", "email": "new@x.com", "name": "New User"},
        headers={"X-Internal-Key": INTERNAL_KEY},
    ).json()
    assert created["subscription_active"] is False

    # same github id: updates the profile, keeps the row
    updated = client.post(
        "/internal/users/sync",
        json={"github_id": "300", "email": "renamed@x.com", "name": "Renamed"},
        headers={"X-Internal-Key": INTERNAL_KEY},
    ).json()
    assert updated["user_id"] == created["user_id"]

    subscribed = client.post(
        "/internal/users/sync",
        json={"github_id": "100"},
        headers={"X-Internal-Key": INTERNAL_KEY},
    ).json()
    assert subscribed["user_id"] == 1
    assert subscribed["subscription_active"] is True


def test_market_odds_serve_newest_snapshot_best_price(client):
    for body in (
        client.get("/matches/2/markets").json(),
        client.get("/matches/upcoming").json()[0],
    ):
        odds = body["market_odds"]
        # match 2 has Beta at home; best of 1.8 (TAB) / 1.85 (SportsBet),
        # the stale 1.9 snapshot is not served
        assert odds["home"] == {"price": 1.85, "bookmaker": "SportsBet"}
        assert odds["away"] == {"price": 2.1, "bookmaker": "TAB"}
        assert odds["bookmakers"] == 2


def test_track_record_scores_settled_predictions(client):
    body = client.get("/track-record").json()
    assert body["v_test"]["settled"] == 1
    assert body["v_test"]["accuracy"] == 1.0
    assert 0 < body["v_test"]["log_loss"] < 1
