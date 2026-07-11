"""The Odds API parser and loader tests against a saved snapshot shape.

The snapshot's second event lists Cronulla as the home side where the
canonical fixture has the Dolphins at home, exercising the swapped
home/away retry the other match reconcilers also need.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from genpicks.db.models import (
    Base,
    Match,
    MatchSourceKey,
    OddsSnapshot,
    Team,
    TeamAlias,
)
from genpicks.ingest.oddsapi_loader import _resolve_team, load_odds_events
from genpicks.scrape import oddsapi

FIXTURES = Path(__file__).parent / "fixtures"

CAPTURED_AT = datetime(2026, 7, 7, 21, 45, tzinfo=UTC)


@pytest.fixture(scope="module")
def events():
    return oddsapi.parse_snapshot(
        (FIXTURES / "oddsapi-nrl-snapshot.json").read_text(encoding="utf-8")
    )


def test_parse_snapshot(events):
    assert len(events) == 2
    tigers = events[0]
    assert tigers.event_id == "e1f0a9c2b3d4e5f60718293a4b5c6d7e"
    assert tigers.commence_time == datetime(2026, 7, 10, 10, 0, tzinfo=UTC)
    assert (tigers.home_team, tigers.away_team) == (
        "Wests Tigers",
        "New Zealand Warriors",
    )
    # 2 outcomes at sportsbet + 3 at tab (incl. the draw), flattened
    assert len(tigers.prices) == 5
    tab_draw = next(p for p in tigers.prices if p.bookmaker == "tab" and p.selection_name == "Draw")
    assert tab_draw.price_decimal == 41.0
    assert tab_draw.title == "TAB"


def test_snapshot_path_roundtrip(tmp_path):
    path = Path(oddsapi.snapshot_cache_path(CAPTURED_AT))
    assert path.as_posix() == "oddsapi/rugbyleague_nrl/20260707T214500Z.json"
    assert oddsapi.captured_at_from_path(path) == CAPTURED_AT


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        teams = {
            "wests-tigers": Team(name="Wests Tigers"),
            "warriors": Team(name="Warriors"),
            "dolphins": Team(name="Dolphins"),
            "cronulla-sutherland-sharks": Team(name="Cronulla Sutherland Sharks"),
        }
        session.add_all(teams.values())
        session.flush()
        session.add_all(
            TeamAlias(team_id=team.id, alias=slug, source="rlp") for slug, team in teams.items()
        )
        session.add_all(
            [
                Match(
                    id=1,
                    season=2026,
                    round="19",
                    match_date=date(2026, 7, 10),
                    home_team_id=teams["wests-tigers"].id,
                    away_team_id=teams["warriors"].id,
                    source="rlp",
                    source_key="m1",
                ),
                # canonical designation is Dolphins at home; the odds feed swaps it
                Match(
                    id=2,
                    season=2026,
                    round="19",
                    match_date=date(2026, 7, 11),
                    home_team_id=teams["dolphins"].id,
                    away_team_id=teams["cronulla-sutherland-sharks"].id,
                    source="rlp",
                    source_key="m2",
                ),
            ]
        )
        session.commit()
        yield session


def test_load_resolves_matches_and_keeps_every_price(session, events):
    rows, matched, unmatched = load_odds_events(session, events, CAPTURED_AT)
    session.commit()
    assert (rows, matched, unmatched) == (7, 2, 0)

    # both events recorded in match_source_keys, incl. the swapped one
    keys = {
        k.source_key: k.match_id
        for k in session.scalars(select(MatchSourceKey).where(MatchSourceKey.source == "oddsapi"))
    }
    assert keys["e1f0a9c2b3d4e5f60718293a4b5c6d7e"] == 1
    assert keys["a1b2c3d4e5f60718293a4b5c6d7e8f90"] == 2

    snapshots = list(session.scalars(select(OddsSnapshot)))
    assert all(s.source == "oddsapi" and s.market == "h2h" for s in snapshots)
    # SQLite hands back naive datetimes, so compare the wall-clock value
    assert {s.captured_at.replace(tzinfo=UTC) for s in snapshots} == {CAPTURED_AT}
    draw = next(s for s in snapshots if s.selection_name == "Draw")
    assert draw.team_id is None  # priced, kept, but not a team
    assert draw.raw["bookmaker"] == "tab"
    warriors_prices = sorted(
        float(s.price_decimal) for s in snapshots if s.selection_name == "New Zealand Warriors"
    )
    assert warriors_prices == [1.2, 1.22]


def test_reingesting_a_seen_snapshot_adds_nothing(session, events):
    assert load_odds_events(session, events, CAPTURED_AT)[0] == 7
    session.commit()
    assert load_odds_events(session, events, CAPTURED_AT) == (0, 0, 0)
    # a later poll is a new snapshot and appends
    later = datetime(2026, 7, 8, 9, 0, tzinfo=UTC)
    assert load_odds_events(session, events, later)[0] == 7
    session.commit()
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 14


def test_unknown_name_falls_back_to_nickname_containment(session, caplog):
    team = _resolve_team(session, "The Dolphins")
    assert team is not None and team.name == "Dolphins"
    # the exact string is now an alias, so next time it resolves silently
    alias = session.scalar(
        select(TeamAlias).where(TeamAlias.source == "oddsapi", TeamAlias.alias == "The Dolphins")
    )
    assert alias.team_id == team.id
    assert _resolve_team(session, "Some Rugby Club") is None
