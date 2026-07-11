"""rugbyleagueproject.org (RLP) URL scheme and HTML parsers.

Parsers are pure functions over saved HTML from data/raw/rlp/. They keep
source strings verbatim (team names, player names as displayed) and expose
RLP's stable numeric ids for matches, venues and players — those ids, not
the display names, are what ingestion should key aliases on.

Format notes, verified identical on the 2016 and 2025 season pages:

- The results page is one <table class="list">. Round header rows are a
  single <th colspan="11">; the first such row holds the competition <h3>.
- The date column only names the month when it changes ("Mar 1", then "6"),
  so parsing carries the current month forward. Year comes from the season.
- Score cells are empty for unplayed matches.
- Match pages have four sections tagged data-section=match_info /
  match_stats / match_scoresheet / match_teams. The scoresheet lists per-
  player totals only — RLP has NO try order or minute data, so try_events
  scoring_order cannot be sourced here.
- In the scoresheet a blank count next to a try scorer means 1.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from bs4 import BeautifulSoup, Tag

SOURCE = "rlp"
BASE_URL = "https://www.rugbyleagueproject.org"

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_FINALS_ROUNDS = {
    "Qualif Final": "QF",
    "Elim Final": "EF",
    "Elim Qualif": "EF",  # 2023 finals week 1 variant
    "Semi Final": "SF",
    "Prelim Final": "PF",
    "Grand Final": "GF",
}


def season_results_url(season: int) -> str:
    return f"{BASE_URL}/seasons/nrl-{season}/results.html"


def season_results_cache_path(season: int) -> str:
    return f"rlp/seasons/nrl-{season}-results.html"


def match_url(match_id: str) -> str:
    return f"{BASE_URL}/matches/{match_id}"


def match_cache_path(match_id: str) -> str:
    return f"rlp/matches/{match_id}.html"


# --------------------------------------------------------------------------
# Season results page
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SeasonMatchRow:
    source_key: str  # RLP numeric match id
    season: int
    round: str  # "1".."27", "QF", "EF", "SF", "PF", "GF"
    date: date | None
    kickoff_local: str | None  # verbatim, e.g. "Sat 4:00pm"
    home_name: str
    home_slug: str  # e.g. "canberra-raiders", stable across seasons
    away_name: str
    away_slug: str
    home_score: int | None
    away_score: int | None
    venue_id: str | None  # RLP numeric venue id
    venue_name: str | None  # verbatim sponsor name, e.g. "Allegiant"
    crowd: int | None


def normalize_round(label: str) -> str:
    """ "Round 5 - Multicultural Round" -> "5"; "Grand Final" -> "GF"."""
    base = label.split(" - ")[0].strip()
    if base in _FINALS_ROUNDS:
        return _FINALS_ROUNDS[base]
    m = re.fullmatch(r"Round (\d+)", base)
    if m:
        return m.group(1)
    return base


def parse_season_results(html: str, season: int) -> list[SeasonMatchRow]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="list")
    if table is None:
        raise ValueError(f"no results table found for season {season}")

    rows: list[SeasonMatchRow] = []
    current_round: str | None = None
    current_month: int | None = None

    for tr in table.find_all("tr"):
        header = _round_header(tr)
        if header is not None:
            current_round = normalize_round(header)
            continue

        tds = tr.find_all("td", recursive=False)
        if len(tds) != 11:
            continue
        match_link = tr.find("a", href=re.compile(r"^/matches/(\d+)$"))
        if match_link is None or current_round is None:
            continue

        match_date, current_month = _parse_row_date(_text(tds[1]), season, current_month)
        home_name, home_slug = _team_cell(tds[3])
        away_name, away_slug = _team_cell(tds[5])
        venue_id, venue_name = _venue_cell(tds[8])

        rows.append(
            SeasonMatchRow(
                source_key=str(match_link["href"]).rsplit("/", 1)[-1],
                season=season,
                round=current_round,
                date=match_date,
                kickoff_local=_text(tds[2]) or None,
                home_name=home_name,
                home_slug=home_slug,
                away_name=away_name,
                away_slug=away_slug,
                home_score=_int_or_none(_text(tds[4])),
                away_score=_int_or_none(_text(tds[6])),
                venue_id=venue_id,
                venue_name=venue_name,
                crowd=_int_or_none(_text(tds[9])),
            )
        )
    return rows


def _round_header(tr: Tag) -> str | None:
    """Text of a round header row, or None for any other row.

    Header rows are a lone <th colspan="11">; the competition title row looks
    the same but wraps an <h3>.
    """
    ths = tr.find_all("th", recursive=False)
    if len(ths) != 1 or not ths[0].get("colspan") or tr.find("td"):
        return None
    if ths[0].find("h3"):
        return None
    text = ths[0].get_text(" ", strip=True)
    return text or None


def _parse_row_date(
    raw: str, season: int, current_month: int | None
) -> tuple[date | None, int | None]:
    m = re.fullmatch(r"([A-Za-z]{3})\s+(\d{1,2})", raw)
    if m:
        month = _MONTHS.get(m.group(1).lower())
        if month is None:
            return None, current_month
        return date(season, month, int(m.group(2))), month
    if raw.isdigit() and current_month is not None:
        return date(season, current_month, int(raw)), current_month
    return None, current_month


def _team_cell(td: Tag) -> tuple[str, str]:
    link = td.find("a", href=re.compile(r"^/seasons/.+/summary\.html$"))
    if link is None:
        return _text(td), ""
    slug = str(link["href"]).split("/")[-2]
    return link.get_text(strip=True), slug


def _venue_cell(td: Tag) -> tuple[str | None, str | None]:
    link = td.find("a", href=re.compile(r"^/venues/(\d+)$"))
    if link is None:
        name = _text(td)
        return None, name or None
    return str(link["href"]).rsplit("/", 1)[-1], link.get_text(strip=True)


# --------------------------------------------------------------------------
# Match detail page
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoresheetEntry:
    stat: str  # section title verbatim: "Tries", "Goals", "Field Goals", ...
    side: str  # "home" | "away"
    player_id: str  # RLP numeric player id
    player_name: str  # verbatim, e.g. "Sebastian KRIS"
    raw_value: str  # verbatim cell, e.g. "2", "5/6", ""
    count: int | None  # tries: blank means 1; other stats: int if unambiguous


@dataclass(frozen=True)
class Appearance:
    side: str  # "home" | "away"
    player_id: str
    player_name: str
    jersey: int | None
    position: str  # abbr title verbatim, e.g. "Fullback", "Interchange"


@dataclass(frozen=True)
class MatchDetail:
    source_key: str
    status: str | None
    date: date | None
    kickoff_local: str | None  # verbatim, e.g. "4:00pm (local time)"
    venue_id: str | None
    venue_name: str | None
    venue_city: str | None
    crowd: int | None
    halftime: tuple[int, int] | None  # (home, away)
    scoresheet: list[ScoresheetEntry] = field(default_factory=list)
    appearances: list[Appearance] = field(default_factory=list)


def parse_match(html: str, match_id: str) -> MatchDetail:
    soup = BeautifulSoup(html, "lxml")
    info = _parse_info_rows(soup.find("tbody", id="match_info"))
    venue_id, venue_name, venue_city = info.get("_venue", (None, None, None))
    stats = _parse_stat_rows(soup.find("tbody", id="match_stats"))

    return MatchDetail(
        source_key=match_id,
        status=info.get("Status"),
        date=_parse_long_date(info.get("Date", "")),
        kickoff_local=info.get("Kick Off"),
        venue_id=venue_id,
        venue_name=venue_name,
        venue_city=venue_city,
        crowd=_int_or_none(info.get("Crowd", "")),
        halftime=stats.get("Halftime Score"),
        scoresheet=_parse_scoresheet(soup.find("tbody", id="match_scoresheet")),
        appearances=_parse_teams(soup.find("tbody", id="match_teams")),
    )


def _parse_info_rows(tbody: Tag | None) -> dict:
    info: dict = {}
    if tbody is None:
        return info
    for tr in tbody.find_all("tr"):
        th, td = tr.find("th"), tr.find("td")
        if th is None or td is None:
            continue
        label = th.get_text(" ", strip=True)
        info[label] = td.get_text(" ", strip=True)
        if label == "Venue":
            link = td.find("a", href=re.compile(r"^/venues/(\d+)$"))
            city_match = re.search(r"\(([^)]+)\)\s*$", td.get_text(" ", strip=True))
            info["_venue"] = (
                str(link["href"]).rsplit("/", 1)[-1] if link else None,
                link.get_text(strip=True) if link else None,
                city_match.group(1) if city_match else None,
            )
    return info


def _parse_stat_rows(tbody: Tag | None) -> dict[str, tuple[int, int]]:
    stats: dict[str, tuple[int, int]] = {}
    if tbody is None:
        return stats
    for tr in tbody.find_all("tr"):
        th = tr.find("th", class_="left")
        tds = tr.find_all("td")
        if th is None or len(tds) < 2:
            continue
        home = _int_or_none(tds[0].get_text(strip=True))
        away = _int_or_none(tds[-1].get_text(strip=True))
        if home is not None and away is not None:
            stats[th.get_text(" ", strip=True)] = (home, away)
    return stats


def _parse_scoresheet(tbody: Tag | None) -> list[ScoresheetEntry]:
    entries: list[ScoresheetEntry] = []
    if tbody is None:
        return entries
    stat: str | None = None
    for tr in tbody.find_all("tr"):
        abbr = tr.find("abbr")
        if abbr is not None and abbr.get("title"):
            stat = str(abbr["title"])
        if stat is None:
            continue
        tds = tr.find_all("td")
        if len(tds) != 4:  # player, count, count, player around the centre th
            continue
        for side, player_td, value_td in (
            ("home", tds[0], tds[1]),
            ("away", tds[3], tds[2]),
        ):
            entry = _scoresheet_entry(stat, side, player_td, value_td)
            if entry is not None:
                entries.append(entry)
    return entries


def _scoresheet_entry(
    stat: str, side: str, player_td: Tag, value_td: Tag
) -> ScoresheetEntry | None:
    link = player_td.find("a", href=re.compile(r"^/players/(\d+)$"))
    if link is None:
        return None
    raw_value = value_td.get_text(strip=True).replace("\xa0", "")
    count = _int_or_none(raw_value)
    if stat == "Tries" and count is None and raw_value == "":
        count = 1
    return ScoresheetEntry(
        stat=stat,
        side=side,
        player_id=str(link["href"]).rsplit("/", 1)[-1],
        player_name=link.get_text(" ", strip=True),
        raw_value=raw_value,
        count=count,
    )


def _parse_teams(tbody: Tag | None) -> list[Appearance]:
    appearances: list[Appearance] = []
    if tbody is None:
        return appearances
    for tr in tbody.find_all("tr"):
        abbr = tr.find("abbr")
        tds = tr.find_all("td")
        if abbr is None or not abbr.get("title") or len(tds) != 4:
            continue
        position = str(abbr["title"])
        for side, player_td, jersey_td in (
            ("home", tds[0], tds[1]),
            ("away", tds[3], tds[2]),
        ):
            link = player_td.find("a", href=re.compile(r"^/players/(\d+)$"))
            if link is None:
                continue
            appearances.append(
                Appearance(
                    side=side,
                    player_id=str(link["href"]).rsplit("/", 1)[-1],
                    player_name=link.get_text(" ", strip=True),
                    jersey=_int_or_none(jersey_td.get_text(strip=True)),
                    position=position,
                )
            )
    return appearances


def _parse_long_date(raw: str) -> date | None:
    """ "Saturday, 1st March, 2025" -> date(2025, 3, 1)."""
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(\d{4})", raw)
    if m is None:
        return None
    month = _MONTHS.get(m.group(2).lower())
    if month is None:
        return None
    return date(int(m.group(3)), month, int(m.group(1)))


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _text(td: Tag) -> str:
    return td.get_text(" ", strip=True).replace("\xa0", "").strip()


def _int_or_none(raw: str | None) -> int | None:
    if raw is None:
        return None
    cleaned = raw.replace(",", "").replace("\xa0", "").strip()
    return int(cleaned) if cleaned.isdigit() else None
