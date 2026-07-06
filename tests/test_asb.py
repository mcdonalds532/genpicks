"""ASB spreadsheet parser and odds-loader tests.

The workbook fixture is synthesized with the real file's exact header
layout (sheet "Data", junk row 1, header row 2, newest first). The Vegas
opener row uses the Sydney date (2025-03-02) while the canonical match_date
is the venue-local 2025-03-01 — exercising the ±1 day reconciliation.
"""

from datetime import date, datetime, time
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from genpicks.db.models import Base, OddsSnapshot
from genpicks.ingest.asb_loader import load_asb_odds
from genpicks.ingest.rlp_loader import load_season_rows
from genpicks.scrape import asb, rlp

FIXTURES = Path(__file__).parent / "fixtures"

HEADER = [
    "Date", "Kick-off (local)", "Home Team", "Away Team", "Venue",
    "Home Score", "Away Score", "Play Off Game?", "Over Time?",
    "Home Odds", "Draw Odds", "Away Odds", "Bookmakers Surveyed",
    "Home Odds Open", "Home Odds Min", "Home Odds Max", "Home Odds Close",
    "Away Odds Open", "Away Odds Min", "Away Odds Max", "Away Odds Close",
    "Notes",
]

VEGAS_ROW = [
    datetime(2025, 3, 2), time(11, 0), "Canberra Raiders", "New Zealand Warriors",
    "Allegiant Stadium", 30, 8, None, None,
    2.32, 21.0, 1.62, 11,
    2.40, 2.25, 2.45, 2.30,
    1.55, 1.55, 1.66, 1.63,
    None,
]

UNKNOWN_ROW = [
    datetime(2025, 3, 2), time(14, 0), "Canberra Raiders", "New Zealand Warriors",
    "Somewhere", 0, 0, None, None,
    2.0, 21.0, 2.0, 11,
    2.0, 2.0, 2.0, 2.0,
    2.0, 2.0, 2.0, 2.0,
    None,
]


@pytest.fixture(scope="module")
def workbook_path(tmp_path_factory):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["junk banner row"])
    ws.append(HEADER)
    ws.append(VEGAS_ROW)
    old = list(VEGAS_ROW)
    old[0] = datetime(2015, 3, 7)  # outside requested seasons
    ws.append(old)
    path = tmp_path_factory.mktemp("asb") / "nrl.xlsx"
    wb.save(path)
    return path


def test_parse_workbook(workbook_path):
    rows = asb.parse_workbook(workbook_path)
    assert len(rows) == 2
    row = rows[0]
    assert row.date == date(2025, 3, 2)
    assert (row.home_name, row.away_name) == ("Canberra Raiders", "New Zealand Warriors")
    assert row.home_odds_close == 2.30
    assert row.away_odds_close == 1.63
    assert row.draw_odds_avg == 21.0
    assert row.raw["Home Odds Close"] == 2.30
    assert row.raw["Date"] == "2025-03-02T00:00:00"  # JSON-safe


def test_odds_attach_to_canonical_match(workbook_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        html = (FIXTURES / "rlp-nrl-2025-results.html").read_text(encoding="utf-8")
        matches = load_season_rows(session, rlp.parse_season_results(html, 2025))
        session.commit()
        vegas = matches["103171"]

        rows = asb.parse_workbook(workbook_path)
        loaded, unmatched = load_asb_odds(session, rows, {2025})
        session.commit()
        assert (loaded, unmatched) == (1, 0)  # 2015 row filtered by season

        snapshots = list(
            session.scalars(
                select(OddsSnapshot).where(OddsSnapshot.match_id == vegas.id)
            )
        )
        by_selection = {s.selection_name: s for s in snapshots}
        assert float(by_selection["Canberra Raiders"].price_decimal) == 2.30
        assert by_selection["Canberra Raiders"].team_id == vegas.home_team_id
        assert float(by_selection["New Zealand Warriors"].price_decimal) == 1.63
        assert by_selection["Draw"].team_id is None
        assert by_selection["Canberra Raiders"].raw["Venue"] == "Allegiant Stadium"

        # idempotent: re-running replaces, not duplicates
        load_asb_odds(session, rows, {2025})
        session.commit()
        total = session.scalar(select(func.count()).select_from(OddsSnapshot))
        assert total == 3


def test_unmatched_row_is_counted_not_loaded(workbook_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        # no RLP data ingested at all -> nothing can reconcile
        rows = asb.parse_workbook(workbook_path)
        loaded, unmatched = load_asb_odds(session, rows, {2025})
        assert (loaded, unmatched) == (0, 1)
        assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 0
