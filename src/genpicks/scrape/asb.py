"""aussportsbetting.com historical NRL odds spreadsheet.

This source is NOT fetched automatically: the site sits behind a Cloudflare
browser challenge and its robots.txt restricts automated collection. The
user downloads https://www.aussportsbetting.com/historical_data/nrl.xlsx in
a browser and saves it to data/raw/asb/nrl.xlsx; this module only parses.

File layout (verified 2026-07-06): sheet "Data", header on row 2, newest
match first, one row per match back to 2009. h2h, line and totals markets
with open/min/max/close each. Their notes say the surveyed closing price is
Pinnacle until 2018-04-02, bet365 until 2024-04-28, BlueBet after — worth
citing when benchmarking the model against these closes.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

import openpyxl

SOURCE = "asb"
DEFAULT_PATH = "asb/nrl.xlsx"


@dataclass(frozen=True)
class AsbMatchOdds:
    date: date
    kickoff_local: time | None
    home_name: str
    away_name: str
    venue_name: str | None
    home_score: int | None
    away_score: int | None
    is_playoff: bool
    home_odds_close: float | None
    away_odds_close: float | None
    home_odds_avg: float | None  # "Home Odds": bookmaker survey average
    away_odds_avg: float | None
    draw_odds_avg: float | None  # no close published for the draw
    raw: dict  # every named column, JSON-safe


def parse_workbook(path: Path) -> list[AsbMatchOdds]:
    workbook = openpyxl.load_workbook(path, read_only=True)
    sheet = workbook["Data"]
    rows = sheet.iter_rows(min_row=2, values_only=True)
    header = next(rows)
    columns = {name: i for i, name in enumerate(header) if name}

    parsed = []
    for row in rows:
        if row[columns["Date"]] is None or row[columns["Home Team"]] is None:
            continue
        get = lambda name: row[idx] if (idx := columns.get(name)) is not None else None
        parsed.append(
            AsbMatchOdds(
                date=get("Date").date(),
                kickoff_local=get("Kick-off (local)"),
                home_name=str(get("Home Team")).strip(),
                away_name=str(get("Away Team")).strip(),
                venue_name=get("Venue"),
                home_score=get("Home Score"),
                away_score=get("Away Score"),
                is_playoff=get("Play Off Game?") == "Y",
                home_odds_close=_number(get("Home Odds Close")),
                away_odds_close=_number(get("Away Odds Close")),
                home_odds_avg=_number(get("Home Odds")),
                away_odds_avg=_number(get("Away Odds")),
                draw_odds_avg=_number(get("Draw Odds")),
                raw={
                    name: _json_safe(row[i])
                    for name, i in columns.items()
                    if row[i] is not None
                },
            )
        )
    workbook.close()
    return parsed


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _json_safe(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value
