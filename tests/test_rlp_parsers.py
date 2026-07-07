"""Parser tests against real saved RLP pages (2025 season, match 103171).

The fixtures are unmodified downloads, so these tests pin the exact markup
the site serves; if RLP changes format, these fail before bad data lands.
"""

from datetime import date
from pathlib import Path

import pytest

from genpicks.scrape import rlp

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def season_rows():
    html = (FIXTURES / "rlp-nrl-2025-results.html").read_text(encoding="utf-8")
    return rlp.parse_season_results(html, 2025)


@pytest.fixture(scope="module")
def match_detail():
    html = (FIXTURES / "rlp-match-103171.html").read_text(encoding="utf-8")
    return rlp.parse_match(html, "103171")


def test_season_covers_all_rounds_and_finals(season_rows):
    rounds = {row.round for row in season_rows}
    assert {str(n) for n in range(1, 28)} <= rounds
    assert {"QF", "EF", "SF", "PF", "GF"} <= rounds
    # 2025: 27 rounds with byes plus 9 finals
    assert len(season_rows) == 213
    # every match has a unique numeric source key
    keys = {row.source_key for row in season_rows}
    assert len(keys) == len(season_rows)
    assert all(key.isdigit() for key in keys)


def test_season_first_row_vegas_opener(season_rows):
    row = season_rows[0]
    assert row.source_key == "103171"
    assert row.round == "1"
    assert row.date == date(2025, 3, 1)
    assert row.kickoff_local == "Sat 4:00pm"
    assert (row.home_name, row.home_slug) == ("Canberra", "canberra-raiders")
    assert (row.away_name, row.away_slug) == ("Warriors", "warriors")
    assert (row.home_score, row.away_score) == (30, 8)
    assert (row.venue_id, row.venue_name) == ("1290", "Allegiant")
    assert row.crowd == 45209


def test_season_month_carries_forward(season_rows):
    # Second Vegas match shows only "1" in the date column; the month must
    # carry forward from the previous row.
    assert season_rows[1].source_key == "103172"
    assert season_rows[1].date == date(2025, 3, 1)
    # All rows in a completed season have dates and scores.
    assert all(row.date is not None for row in season_rows)
    assert all(row.home_score is not None for row in season_rows)


def test_season_dates_are_monotonic_within_rounds(season_rows):
    # Guards the month carry-forward logic across the whole season: matches
    # in round order should never jump backwards by more than a bye weekend.
    dates = [row.date for row in season_rows]
    for previous, current in zip(dates, dates[1:]):
        assert (current - previous).days > -8


def test_match_info(match_detail):
    d = match_detail
    assert d.status == "Completed"
    assert d.date == date(2025, 3, 1)
    assert d.kickoff_local == "4:00pm (local time)"
    assert (d.venue_id, d.venue_name, d.venue_city) == ("1290", "Allegiant", "Las Vegas")
    assert d.crowd == 45209
    assert d.halftime == (16, 4)


def test_match_try_scorers(match_detail):
    tries = {
        (e.side, e.player_name): e.count
        for e in match_detail.scoresheet
        if e.stat == "Tries"
    }
    assert tries == {
        ("home", "Sebastian KRIS"): 2,
        ("home", "Xavier SAVAGE"): 2,
        ("home", "Matthew TIMOKO"): 1,  # blank cell means one try
        ("away", "Kurt CAPEWELL"): 1,
        ("away", "Roger TUIVASA-SHECK"): 1,
    }
    # try counts must reconcile with the final score: 30-8 with 5 and 0/2 goals
    home_tries = sum(c for (side, _), c in tries.items() if side == "home")
    away_tries = sum(c for (side, _), c in tries.items() if side == "away")
    assert (home_tries, away_tries) == (5, 2)


def test_match_appearances(match_detail):
    home = [a for a in match_detail.appearances if a.side == "home"]
    away = [a for a in match_detail.appearances if a.side == "away"]
    # 13 starters + bench per side; every appearance has a numeric player id
    assert len(home) >= 17 and len(away) >= 17
    assert all(a.player_id.isdigit() for a in match_detail.appearances)

    fullback = next(a for a in home if a.position == "Fullback")
    assert fullback.player_name == "Kaeo WEEKES"
    assert fullback.jersey == 1
    assert fullback.player_id == "33751"


def test_normalize_round():
    assert rlp.normalize_round("Round 1") == "1"
    assert rlp.normalize_round("Round 5 - Multicultural Round") == "5"
    assert rlp.normalize_round("Qualif Final") == "QF"
    assert rlp.normalize_round("Elim Qualif") == "EF"  # 2023 finals variant
    assert rlp.normalize_round("Grand Final") == "GF"
