"""Travel feature tests: geography table coverage and feature wiring."""

import math
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from genpicks.db.models import Base, Match, Team, Venue
from genpicks.ml.features import build_match_dataset
from genpicks.ml.geo import CITY_COORDS, TEAM_HOME_CITY, haversine_km, travel_km


def test_haversine_known_distances():
    # Sydney-Auckland is ~2,156 km great-circle
    assert haversine_km(CITY_COORDS["Sydney"], CITY_COORDS["Auckland"]) == pytest.approx(
        2156, rel=0.02
    )
    assert haversine_km(CITY_COORDS["Sydney"], CITY_COORDS["Sydney"]) == 0.0


def test_every_home_city_has_coordinates():
    missing = [c for c in TEAM_HOME_CITY.values() if c not in CITY_COORDS]
    assert missing == []


def test_travel_km_unknowns_are_nan_not_errors():
    assert math.isnan(travel_km("Expansion Team 2030", "Sydney"))
    assert math.isnan(travel_km("Warriors", "Atlantis"))
    assert math.isnan(travel_km("Warriors", None))


@pytest.fixture()
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Team(id=1, name="Warriors"),
                Team(id=2, name="North Queensland Cowboys"),
                Venue(id=1, name="Go Media", city="Auckland"),
                Venue(id=2, name="Allegiant", city="Las Vegas"),
                Venue(id=3, name="Mystery Ground", city=None),
            ]
        )
        session.add_all(
            [
                # Warriors host the Cowboys in Auckland: true home game
                Match(
                    season=2025,
                    round="1",
                    match_date=date(2025, 3, 8),
                    home_team_id=1,
                    away_team_id=2,
                    venue_id=1,
                    home_score=20,
                    away_score=10,
                    source="t",
                    source_key="m1",
                ),
                # "home" in Las Vegas: both sides travel, nobody is at home
                Match(
                    season=2025,
                    round="2",
                    match_date=date(2025, 3, 15),
                    home_team_id=1,
                    away_team_id=2,
                    venue_id=2,
                    home_score=10,
                    away_score=20,
                    source="t",
                    source_key="m2",
                ),
                # unknown venue city: features degrade to NaN, never raise
                Match(
                    season=2025,
                    round="3",
                    match_date=date(2025, 3, 22),
                    home_team_id=2,
                    away_team_id=1,
                    venue_id=3,
                    home_score=14,
                    away_score=12,
                    source="t",
                    source_key="m3",
                ),
            ]
        )
        session.commit()
    return engine


def test_travel_features(engine):
    data = build_match_dataset(engine)
    home_game, vegas, unknown = data.iloc[0], data.iloc[1], data.iloc[2]

    assert home_game["home_travel_km"] == 0.0
    assert home_game["away_travel_km"] == pytest.approx(3346, rel=0.02)  # Townsville-Auckland
    assert home_game["home_at_home"] == 1.0
    assert home_game["travel_km_diff"] < -2000

    assert vegas["home_travel_km"] > 10000
    assert vegas["home_at_home"] == 0.0

    assert math.isnan(unknown["home_travel_km"])
    assert math.isnan(unknown["home_at_home"])
