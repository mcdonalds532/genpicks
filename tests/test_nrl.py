"""NRL.com parser and loader tests against real saved JSON.

The 2025 fixtures are the same real match as the RLP fixtures (the Vegas
opener, Raiders v Warriors), so the ingest test exercises genuine
cross-source reconciliation: RLP creates the canonical rows, then the NRL
loader must attach to them without creating duplicates.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from genpicks.db.models import (
    Base,
    MatchSourceKey,
    Player,
    PlayerAlias,
    PlayerMatchStats,
    TeamListEntry,
    TryEvent,
)
from genpicks.ingest.nrl_loader import load_nrl_match, load_team_list
from genpicks.ingest.rlp_loader import load_match_detail, load_season_rows
from genpicks.scrape import nrl, rlp

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def draw():
    return nrl.parse_draw((FIXTURES / "nrl-draw-2025-round-1.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def vegas_detail():
    return nrl.parse_match(
        (FIXTURES / "nrl-match-2025-raiders-v-warriors.json").read_text(encoding="utf-8")
    )


# -- parsers -----------------------------------------------------------------


def test_parse_draw(draw):
    assert len(draw.fixtures) == 8
    assert draw.round_numbers[0] == 1 and len(draw.round_numbers) >= 27
    f = draw.fixtures[0]
    assert f.match_centre_path == "/draw/nrl-premiership/2025/round-1/raiders-v-warriors/"
    assert f.kickoff_utc == datetime(2025, 3, 2, 0, 0, tzinfo=UTC)
    assert (f.home_nickname, f.home_score) == ("Raiders", 30)
    assert (f.away_nickname, f.away_score) == ("Warriors", 8)
    assert f.is_played
    assert (f.venue_name, f.venue_city) == ("Allegiant Stadium", "Las Vegas")


def test_parse_match_2025(vegas_detail):
    d = vegas_detail
    assert d.match_id == "20251110110"
    assert d.start_time_utc == datetime(2025, 3, 2, 0, 0, tzinfo=UTC)
    assert len(d.squads) == 36  # 18-player squads listed per side
    assert len(d.player_stats) == 36
    # timeline tries arrive in scoring order with times: 5 + 2 = 7 tries
    assert len(d.tries) == 7
    seconds = [t.game_seconds for t in d.tries]
    assert seconds == sorted(seconds)
    assert all(t.player_id is not None and t.team_id is not None for t in d.tries)

    weekes = next(s for s in d.player_stats if s.player_id == 507846)
    assert weekes.stats["allRunMetres"] == 128
    assert weekes.stats["minutesPlayed"] == 80


def test_parse_match_2016_has_same_shape():
    d = nrl.parse_match(
        (FIXTURES / "nrl-match-2016-eels-v-broncos.json").read_text(encoding="utf-8")
    )
    assert d.match_id == "20161110110"
    assert d.start_time_utc == datetime(2016, 3, 3, 9, 5, tzinfo=UTC)
    assert len(d.tries) == 4
    assert d.player_stats and "tacklesMade" in d.player_stats[0].stats


def test_cache_path_from_match_centre_url():
    assert (
        nrl.match_cache_path("/draw/nrl-premiership/2016/round-1/eels-v-broncos/")
        == "nrl/matches/2016/round-1/eels-v-broncos.json"
    )
    assert (
        nrl.teamlist_cache_path("/draw/nrl-premiership/2026/round-19/wests-tigers-v-warriors/")
        == "nrl/teamlists/2026/round-19/wests-tigers-v-warriors.json"
    )


# -- cross-source ingest -----------------------------------------------------


@pytest.fixture()
def session_with_rlp_data():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        html = (FIXTURES / "rlp-nrl-2025-results.html").read_text(encoding="utf-8")
        matches = load_season_rows(session, rlp.parse_season_results(html, 2025))
        detail = rlp.parse_match(
            (FIXTURES / "rlp-match-103171.html").read_text(encoding="utf-8"), "103171"
        )
        load_match_detail(session, matches["103171"], detail)
        session.commit()
        yield session, matches["103171"]


def test_nrl_attaches_to_rlp_match(session_with_rlp_data, draw, vegas_detail):
    session, match = session_with_rlp_data
    players_before = session.scalar(select(func.count()).select_from(Player))

    assert load_nrl_match(session, 2025, draw.fixtures[0], vegas_detail)
    session.commit()

    # reconciled onto the existing match, recorded in match_source_keys
    key = session.scalar(select(MatchSourceKey).where(MatchSourceKey.source == "nrl"))
    assert key.match_id == match.id
    assert key.source_key == "20251110110"

    # UTC kickoff filled; local date unchanged (Vegas: UTC date differs)
    session.refresh(match)
    assert match.kickoff_utc is not None
    assert match.kickoff_utc.date() == date(2025, 3, 2)
    assert match.match_date == date(2025, 3, 1)

    # no duplicate players: every NRL squad member matched an RLP appearance
    players_after = session.scalar(select(func.count()).select_from(Player))
    assert players_after == players_before

    # stats filled onto the RLP-created rows
    kris = session.scalar(
        select(PlayerAlias).where(PlayerAlias.source == "rlp", PlayerAlias.alias == "28599")
    )
    kris_nrl = session.scalar(
        select(PlayerAlias).where(PlayerAlias.source == "nrl", PlayerAlias.alias == "504148")
    )
    assert kris_nrl is not None and kris_nrl.player_id == kris.player_id
    kris_stats = session.scalar(
        select(PlayerMatchStats).where(
            PlayerMatchStats.match_id == match.id,
            PlayerMatchStats.player_id == kris.player_id,
        )
    )
    assert kris_stats.tries == 2
    assert kris_stats.minutes_played is not None
    assert kris_stats.run_metres is not None
    assert kris_stats.tackles is not None

    # try events rebuilt with scoring order; first try is Sebastian Kris
    events = list(
        session.scalars(
            select(TryEvent).where(TryEvent.match_id == match.id).order_by(TryEvent.scoring_order)
        )
    )
    assert [e.scoring_order for e in events] == [1, 2, 3, 4, 5, 6, 7]
    assert events[0].player_id == kris.player_id
    assert events[0].minute == 5  # 316 gameSeconds
    home_tries = sum(1 for e in events if e.team_id == match.home_team_id)
    assert home_tries == 5


def test_incomplete_timeline_keeps_rlp_tries_and_skips_try_order(
    session_with_rlp_data, draw, vegas_detail
):
    # Old NRL.com feeds can miss tries (observed in 2017). If the timeline
    # doesn't account for every RLP try, keep RLP counts and write no order.
    import dataclasses

    session, match = session_with_rlp_data
    crippled = dataclasses.replace(vegas_detail, tries=vegas_detail.tries[:-1])
    assert load_nrl_match(session, 2025, draw.fixtures[0], crippled)
    session.commit()

    assert session.scalar(select(func.count()).select_from(TryEvent)) == 0
    kris = session.scalar(
        select(PlayerAlias).where(PlayerAlias.source == "rlp", PlayerAlias.alias == "28599")
    )
    kris_stats = session.scalar(
        select(PlayerMatchStats).where(
            PlayerMatchStats.match_id == match.id,
            PlayerMatchStats.player_id == kris.player_id,
        )
    )
    assert kris_stats.tries == 2  # RLP scoresheet value untouched
    assert kris_stats.run_metres is not None  # other stats still merged

    # a later run with the full timeline heals the match
    assert load_nrl_match(session, 2025, draw.fixtures[0], vegas_detail)
    session.commit()
    assert session.scalar(select(func.count()).select_from(TryEvent)) == 7


def test_team_list_resolves_known_players_and_replaces_on_reingest(
    session_with_rlp_data, draw, vegas_detail
):
    session, match = session_with_rlp_data
    fixture = draw.fixtures[0]

    # before any NRL played-match ingest, no (nrl, playerId) aliases exist:
    # every entry lands unresolved, and no Player rows are invented
    players_before = session.scalar(select(func.count()).select_from(Player))
    assert load_team_list(session, 2025, fixture, vegas_detail)
    session.commit()
    entries = list(session.scalars(select(TeamListEntry)))
    assert len(entries) == 36
    assert all(e.player_id is None for e in entries)
    assert all(e.player_name for e in entries)
    assert session.scalar(select(func.count()).select_from(Player)) == players_before
    # positions are stored in the canonical (RLP) vocabulary
    positions = {e.position for e in entries}
    assert "Wing" in positions and "Winger" not in positions
    assert "Bench" in positions and "Interchange" not in positions

    # once the played-match ingest has created the aliases, a re-ingest
    # replaces the entries wholesale and resolves everyone who took the
    # field (non-playing reserves never get aliases, so they stay null)
    assert load_nrl_match(session, 2025, fixture, vegas_detail)
    assert load_team_list(session, 2025, fixture, vegas_detail)
    session.commit()
    entries = list(session.scalars(select(TeamListEntry)))
    assert len(entries) == 36  # replaced, not appended
    played = {s.player_id for s in vegas_detail.player_stats if s.stats.get("minutesPlayed")}
    assert sum(e.player_id is not None for e in entries) == len(played)
    assert {e.match_id for e in entries} == {match.id}
    kris = session.scalar(
        select(PlayerAlias).where(PlayerAlias.source == "nrl", PlayerAlias.alias == "504148")
    )
    assert any(e.player_id == kris.player_id and e.jersey_number for e in entries)


def test_debut_without_rlp_appearance_adopts_existing_same_name_player(
    session_with_rlp_data, draw, vegas_detail
):
    # NRL shows real minutes for a player RLP's scoresheet skipped (reserve
    # who came on). If a same-name player already exists with no nrl alias
    # (RLP credited them in another match), claim it instead of duplicating.
    import dataclasses

    from genpicks.scrape.nrl import NrlPlayerStats, NrlSquadPlayer

    session, match = session_with_rlp_data
    existing = Player(full_name="Totally Newman")
    session.add(existing)
    session.commit()

    detail = dataclasses.replace(
        vegas_detail,
        squads=vegas_detail.squads
        + [
            NrlSquadPlayer(
                side="home",
                player_id=999001,
                first_name="Totally",
                last_name="Newman",
                position="Interchange",
                number=None,
            )
        ],
        player_stats=vegas_detail.player_stats
        + [
            NrlPlayerStats(
                side="home",
                player_id=999001,
                stats={"playerId": 999001, "minutesPlayed": 11},
            )
        ],
    )
    players_before = session.scalar(select(func.count()).select_from(Player))
    assert load_nrl_match(session, 2025, draw.fixtures[0], detail)
    session.commit()

    assert session.scalar(select(func.count()).select_from(Player)) == players_before
    alias = session.scalar(
        select(PlayerAlias).where(PlayerAlias.source == "nrl", PlayerAlias.alias == "999001")
    )
    assert alias.player_id == existing.id


def test_nrl_ingest_is_idempotent(session_with_rlp_data, draw, vegas_detail):
    session, match = session_with_rlp_data
    assert load_nrl_match(session, 2025, draw.fixtures[0], vegas_detail)
    session.commit()
    counts_first = (
        session.scalar(select(func.count()).select_from(Player)),
        session.scalar(select(func.count()).select_from(TryEvent)),
        session.scalar(select(func.count()).select_from(PlayerMatchStats)),
        session.scalar(select(func.count()).select_from(MatchSourceKey)),
    )
    assert load_nrl_match(session, 2025, draw.fixtures[0], vegas_detail)
    session.commit()
    counts_second = (
        session.scalar(select(func.count()).select_from(Player)),
        session.scalar(select(func.count()).select_from(TryEvent)),
        session.scalar(select(func.count()).select_from(PlayerMatchStats)),
        session.scalar(select(func.count()).select_from(MatchSourceKey)),
    )
    assert counts_first == counts_second


def test_unchanged_try_events_are_not_rewritten(session_with_rlp_data, draw, vegas_detail):
    # a weekly replay recomputes identical events for every settled match;
    # a delete+reinsert would show up as fresh autoincrement ids
    session, match = session_with_rlp_data
    assert load_nrl_match(session, 2025, draw.fixtures[0], vegas_detail)
    session.commit()
    ids_first = session.scalars(select(TryEvent.id).order_by(TryEvent.id)).all()
    assert load_nrl_match(session, 2025, draw.fixtures[0], vegas_detail)
    session.commit()
    assert session.scalars(select(TryEvent.id).order_by(TryEvent.id)).all() == ids_first
