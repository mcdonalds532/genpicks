"""NRL.com draw and match-centre JSON endpoints.

NRL.com is a JS app, but two unauthenticated JSON endpoints carry everything
we need (verified working for 2016 and 2025):

- /draw/data?competition=111&season=Y&round=N — fixtures for one round, with
  UTC kickoff, stable numeric teamIds, and each fixture's matchCentreUrl.
- <matchCentreUrl>data — full match detail: squads with jersey numbers and
  stable playerIds, ~50 stat columns per player, and an event timeline whose
  Try events carry gameSeconds + playerId, i.e. scoring order and minute
  (the exact data rugbyleagueproject.org lacks).

Caveats:
- venue names are RETROACTIVELY the current sponsor name (a 2016 match says
  "CommBank Stadium" which did not exist then). Never trust them for
  historical naming; RLP is the honest source there.
- team/player/match ids are NRL.com's own; reconciliation to canonical rows
  happens in ingest, not here.
- attendance is sometimes 0 where RLP has a real crowd figure.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

SOURCE = "nrl"
BASE_URL = "https://www.nrl.com"
COMPETITION_NRL = 111

JSON_HEADERS = {"Accept": "application/json"}


def draw_url(season: int, round_number: int) -> str:
    return (
        f"{BASE_URL}/draw/data?competition={COMPETITION_NRL}&season={season}&round={round_number}"
    )


def draw_cache_path(season: int, round_number: int) -> str:
    return f"nrl/draws/{season}/round-{round_number:02d}.json"


def match_data_url(match_centre_path: str) -> str:
    return f"{BASE_URL}{match_centre_path.rstrip('/')}/data"


def match_cache_path(match_centre_path: str) -> str:
    """ "/draw/nrl-premiership/2016/round-1/eels-v-broncos/" ->
    "nrl/matches/2016/round-1/eels-v-broncos.json"."""
    m = re.search(r"/(\d{4})/([^/]+)/([^/]+)/?$", match_centre_path)
    if m is None:
        raise ValueError(f"unrecognised match centre path: {match_centre_path}")
    return f"nrl/matches/{m.group(1)}/{m.group(2)}/{m.group(3)}.json"


def teamlist_cache_path(match_centre_path: str) -> str:
    """Pre-match snapshot of the same endpoint as match_cache_path, stored
    apart from it: the pre-game payload (squads, no stats/timeline) must never
    sit where the played-match ingest expects full-time data."""
    return match_cache_path(match_centre_path).replace("nrl/matches/", "nrl/teamlists/", 1)


# --------------------------------------------------------------------------
# Draw (fixtures for one round)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NrlFixture:
    match_centre_path: str
    round_title: str
    match_state: str  # "FullTime", "Upcoming", ...
    match_mode: str  # "Post", "Pre", "Live"
    kickoff_utc: datetime | None
    venue_name: str | None
    venue_city: str | None
    home_team_id: int
    home_nickname: str
    home_score: int | None
    away_team_id: int
    away_nickname: str
    away_score: int | None

    @property
    def is_played(self) -> bool:
        return self.match_mode == "Post"


@dataclass(frozen=True)
class DrawPage:
    fixtures: list[NrlFixture]
    round_numbers: list[int]  # all rounds the season offers, from filterRounds


def parse_draw(raw_json: str) -> DrawPage:
    data = json.loads(raw_json)
    fixtures = [_parse_fixture(f) for f in data.get("fixtures", []) if f.get("type") == "Match"]
    round_numbers = sorted(
        value
        for item in data.get("filterRounds", [])
        if isinstance(value := item.get("value"), int)
    )
    return DrawPage(fixtures=fixtures, round_numbers=round_numbers)


def _parse_fixture(f: dict) -> NrlFixture:
    home, away = f.get("homeTeam", {}), f.get("awayTeam", {})
    return NrlFixture(
        match_centre_path=f["matchCentreUrl"],
        round_title=f.get("roundTitle", ""),
        match_state=f.get("matchState", ""),
        match_mode=f.get("matchMode", ""),
        kickoff_utc=_parse_utc(f.get("clock", {}).get("kickOffTimeLong")),
        venue_name=f.get("venue"),
        venue_city=f.get("venueCity"),
        home_team_id=home["teamId"],
        home_nickname=home.get("nickName", ""),
        home_score=home.get("score"),
        away_team_id=away["teamId"],
        away_nickname=away.get("nickName", ""),
        away_score=away.get("score"),
    )


# --------------------------------------------------------------------------
# Match centre detail
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NrlSquadPlayer:
    side: str  # "home" | "away"
    player_id: int
    first_name: str
    last_name: str
    position: str | None
    number: int | None


@dataclass(frozen=True)
class NrlPlayerStats:
    side: str
    player_id: int
    stats: dict  # the source's full stat dict, verbatim


@dataclass(frozen=True)
class NrlTryEvent:
    game_seconds: int | None
    player_id: int | None  # None for penalty tries / unattributed
    team_id: int | None


@dataclass(frozen=True)
class NrlMatchDetail:
    match_id: str
    match_state: str
    start_time_utc: datetime | None
    venue_name: str | None
    venue_city: str | None
    attendance: int | None
    home_team_id: int | None
    away_team_id: int | None
    squads: list[NrlSquadPlayer] = field(default_factory=list)
    player_stats: list[NrlPlayerStats] = field(default_factory=list)
    tries: list[NrlTryEvent] = field(default_factory=list)  # in scoring order


def parse_match(raw_json: str) -> NrlMatchDetail:
    data = json.loads(raw_json)
    home, away = data.get("homeTeam", {}), data.get("awayTeam", {})

    squads = [
        NrlSquadPlayer(
            side=side,
            player_id=p["playerId"],
            first_name=p.get("firstName", ""),
            last_name=p.get("lastName", ""),
            position=p.get("position"),
            number=p.get("number"),
        )
        for side, team in (("home", home), ("away", away))
        for p in team.get("players", [])
    ]

    stats_by_side = (data.get("stats") or {}).get("players") or {}
    player_stats = [
        NrlPlayerStats(side=side, player_id=row["playerId"], stats=row)
        for side, key in (("home", "homeTeam"), ("away", "awayTeam"))
        for row in stats_by_side.get(key) or []
    ]

    try_events = sorted(
        (
            NrlTryEvent(
                game_seconds=e.get("gameSeconds"),
                player_id=e.get("playerId"),
                team_id=e.get("teamId"),
            )
            for e in data.get("timeline") or []
            if "try" in str(e.get("type", "")).lower()
        ),
        key=lambda t: (t.game_seconds is None, t.game_seconds),
    )

    return NrlMatchDetail(
        match_id=str(data["matchId"]),
        match_state=data.get("matchState", ""),
        start_time_utc=_parse_utc(data.get("startTime")),
        venue_name=data.get("venue"),
        venue_city=data.get("venueCity"),
        attendance=data.get("attendance"),
        home_team_id=home.get("teamId"),
        away_team_id=away.get("teamId"),
        squads=squads,
        player_stats=player_stats,
        tries=try_events,
    )


def _parse_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
