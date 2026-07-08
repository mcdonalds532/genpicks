"""The Odds API (the-odds-api.com) — live NRL match-winner prices.

Chosen over the originally planned direct TAB/Betfair polling because both
geo-block non-Australian IPs; The Odds API aggregates the same Australian
bookmakers (region "au") and works from anywhere. One h2h request for one
region costs 1 credit of the free tier's 500/month.

Unlike the fixture sources this is not cache-first: every poll is a new
timestamped snapshot under data/raw/oddsapi/, and ingest replays whichever
snapshots the database has not seen. The API key rides in the query string,
so requests are made here (never through Fetcher) and URLs are never logged.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from genpicks.scrape.fetch import FetchError, USER_AGENT

SOURCE = "oddsapi"
SPORT_KEY = "rugbyleague_nrl"
BASE_URL = "https://api.the-odds-api.com/v4"

_STAMP = "%Y%m%dT%H%M%SZ"


def odds_url(api_key: str) -> str:
    return (
        f"{BASE_URL}/sports/{SPORT_KEY}/odds"
        f"?apiKey={api_key}&regions=au&markets=h2h"
        "&oddsFormat=decimal&dateFormat=iso"
    )


def snapshot_cache_path(captured_at: datetime) -> str:
    return f"oddsapi/{SPORT_KEY}/{captured_at.strftime(_STAMP)}.json"


def captured_at_from_path(path: Path) -> datetime:
    return datetime.strptime(path.stem, _STAMP).replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class BookmakerPrice:
    bookmaker: str  # the API's key, e.g. "tab", "sportsbet", "betfair_ex_au"
    title: str
    last_update: str | None
    selection_name: str  # team name as quoted, or "Draw"
    price_decimal: float


@dataclass(frozen=True)
class OddsEvent:
    event_id: str
    commence_time: datetime | None
    home_team: str
    away_team: str
    prices: list[BookmakerPrice]


def parse_snapshot(raw_json: str) -> list[OddsEvent]:
    events = []
    for event in json.loads(raw_json):
        prices = [
            BookmakerPrice(
                bookmaker=bookmaker["key"],
                title=bookmaker.get("title", bookmaker["key"]),
                last_update=bookmaker.get("last_update"),
                selection_name=outcome["name"],
                price_decimal=float(outcome["price"]),
            )
            for bookmaker in event.get("bookmakers", [])
            for market in bookmaker.get("markets", [])
            if market.get("key") == "h2h"
            for outcome in market.get("outcomes", [])
        ]
        events.append(
            OddsEvent(
                event_id=event["id"],
                commence_time=_parse_utc(event.get("commence_time")),
                home_team=event.get("home_team", ""),
                away_team=event.get("away_team", ""),
                prices=prices,
            )
        )
    return events


def poll(api_key: str, raw_root: Path) -> tuple[Path, int, int | None]:
    """One odds request, saved as a new snapshot.

    Returns (snapshot file, events in it, credits remaining this month).
    """
    # httpx logs full request URLs at INFO — that would print the api key
    logging.getLogger("httpx").setLevel(logging.WARNING)
    response = httpx.get(
        odds_url(api_key),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=30.0,
    )
    if response.status_code != 200:
        raise FetchError(
            f"The Odds API returned {response.status_code}: {response.text[:200]}"
        )
    captured_at = datetime.now(timezone.utc)
    target = raw_root / snapshot_cache_path(captured_at)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(response.text, encoding="utf-8")
    tmp.replace(target)
    remaining = response.headers.get("x-requests-remaining")
    return (
        target,
        len(json.loads(response.text)),
        int(float(remaining)) if remaining is not None else None,
    )


def _parse_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
