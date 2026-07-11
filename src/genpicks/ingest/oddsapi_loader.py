"""Load The Odds API snapshots into odds_snapshots.

One row per bookmaker per selection per snapshot, source "oddsapi", market
"h2h"; the bookmaker's key/title and the API's event id ride in `raw`.
Append-only across snapshots (each poll is a new captured_at), idempotent
per snapshot: a captured_at the table has already seen is skipped, so
ingest can replay the whole raw directory.

Reconciliation:
- teams: the exact quoted name becomes an (oddsapi, name) alias on first
  sight, seeded by full-name map with a nickname-containment fallback (the
  API's exact NRL naming is only observable with live data, and bookmaker
  display names drift).
- matches: (oddsapi, event id) via match_source_keys if seen before, else
  same-season teams + commence date within a day of match_date, retrying
  swapped home/away like the other loaders.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from genpicks.db.models import (
    MARKET_H2H,
    Match,
    MatchSourceKey,
    OddsSnapshot,
    Team,
    TeamAlias,
)
from genpicks.ingest.nrl_loader import NICKNAME_TO_RLP_SLUG
from genpicks.scrape.oddsapi import SOURCE, OddsEvent

logger = logging.getLogger(__name__)

RLP_SOURCE = "rlp"

# best-guess full names (ASB-style); anything missed falls through to the
# nickname containment check below and still resolves
ODDSAPI_NAME_TO_RLP_SLUG = {
    "Brisbane Broncos": "brisbane-broncos",
    "Canberra Raiders": "canberra-raiders",
    "Canterbury Bulldogs": "canterbury-bankstown-bulldogs",
    "Canterbury-Bankstown Bulldogs": "canterbury-bankstown-bulldogs",
    "Cronulla Sharks": "cronulla-sutherland-sharks",
    "Cronulla-Sutherland Sharks": "cronulla-sutherland-sharks",
    "Cronulla Sutherland Sharks": "cronulla-sutherland-sharks",  # live-observed
    "Dolphins": "dolphins",
    "Redcliffe Dolphins": "dolphins",
    "Gold Coast Titans": "gold-coast-titans",
    "Manly Sea Eagles": "manly-warringah-sea-eagles",
    "Manly Warringah Sea Eagles": "manly-warringah-sea-eagles",
    "Melbourne Storm": "melbourne",
    "New Zealand Warriors": "warriors",
    "Newcastle Knights": "newcastle-knights",
    "North Queensland Cowboys": "north-queensland-cowboys",
    "North QLD Cowboys": "north-queensland-cowboys",
    "Parramatta Eels": "parramatta-eels",
    "Penrith Panthers": "penrith-panthers",
    "South Sydney Rabbitohs": "south-sydney-rabbitohs",
    "St George Illawarra Dragons": "st-george-illawarra-dragons",
    "St George Dragons": "st-george-illawarra-dragons",
    "Sydney Roosters": "sydney-roosters",
    "Wests Tigers": "wests-tigers",
}

# longest first so "Sea Eagles" wins before any shorter accidental hit
_NICKNAMES = sorted(NICKNAME_TO_RLP_SLUG, key=len, reverse=True)


def _utc_key(value: datetime) -> datetime:
    """Naive-UTC form for set membership: Postgres returns aware datetimes,
    SQLite naive ones (written as UTC), and the two must compare equal."""
    return value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)


class OddsContext:
    """Run-scoped lookups: replaying a raw directory of N snapshots must not
    pay one existence-check round trip per file."""

    def __init__(self, session: Session) -> None:
        self.seen_captured_at: set[datetime] = {
            _utc_key(value)
            for value in session.scalars(
                select(OddsSnapshot.captured_at).where(OddsSnapshot.source == SOURCE).distinct()
            )
        }
        self.team_alias: dict[str, int] = {}
        self.rlp_team_alias: dict[str, int] = {}
        for alias in session.scalars(
            select(TeamAlias).where(TeamAlias.source.in_([SOURCE, RLP_SOURCE]))
        ):
            table = self.team_alias if alias.source == SOURCE else self.rlp_team_alias
            table[alias.alias] = alias.team_id
        self.match_key: dict[str, int] = {
            key.source_key: key.match_id
            for key in session.scalars(
                select(MatchSourceKey).where(MatchSourceKey.source == SOURCE)
            )
        }
        # identity-map priming (weak references — must stay pinned here)
        self._teams: list[Team] = list(session.scalars(select(Team)))


def load_odds_events(
    session: Session, events: list[OddsEvent], captured_at, ctx: OddsContext | None = None
) -> tuple[int, int, int]:
    """Returns (snapshot rows added, events matched, events unmatched)."""
    ctx = ctx if ctx is not None else OddsContext(session)
    if _utc_key(captured_at) in ctx.seen_captured_at:
        return 0, 0, 0
    ctx.seen_captured_at.add(_utc_key(captured_at))

    rows = matched = unmatched = 0
    for event in events:
        match = _resolve_match(session, ctx, event)
        if match is None:
            unmatched += 1
            continue
        matched += 1
        for price in event.prices:
            team = _resolve_team(session, ctx, price.selection_name)
            session.add(
                OddsSnapshot(
                    source=SOURCE,
                    market=MARKET_H2H,
                    match_id=match.id,
                    team_id=team.id if team is not None else None,
                    player_id=None,
                    selection_name=price.selection_name,
                    price_decimal=price.price_decimal,
                    captured_at=captured_at,
                    raw={
                        "bookmaker": price.bookmaker,
                        "title": price.title,
                        "last_update": price.last_update,
                        "event_id": event.event_id,
                    },
                )
            )
            rows += 1
    session.flush()
    return rows, matched, unmatched


def _resolve_team(session: Session, ctx: OddsContext, name: str) -> Team | None:
    if name == "Draw":
        return None  # a real selection, priced, but not a team
    team_id = ctx.team_alias.get(name)
    if team_id is not None:
        return session.get(Team, team_id)

    slug = ODDSAPI_NAME_TO_RLP_SLUG.get(name)
    if slug is None:
        slug = next(
            (NICKNAME_TO_RLP_SLUG[nick] for nick in _NICKNAMES if nick in name),
            None,
        )
        if slug is not None:
            logger.warning(
                "oddsapi team %r resolved by nickname only — add it to ODDSAPI_NAME_TO_RLP_SLUG",
                name,
            )
    if slug is None:
        logger.warning("no mapping for oddsapi team %r", name)
        return None
    team_id = ctx.rlp_team_alias.get(slug)
    if team_id is None:
        logger.warning("team %r not ingested from RLP yet", slug)
        return None
    session.add(TeamAlias(team_id=team_id, alias=name, source=SOURCE))
    ctx.team_alias[name] = team_id
    return session.get(Team, team_id)


def _resolve_match(session: Session, ctx: OddsContext, event: OddsEvent) -> Match | None:
    known = ctx.match_key.get(event.event_id)
    if known is not None:
        return session.get(Match, known)
    if event.commence_time is None:
        return None
    commence = event.commence_time

    home = _resolve_team(session, ctx, event.home_team)
    away = _resolve_team(session, ctx, event.away_team)
    if home is None or away is None:
        return None

    def find(home_id: int, away_id: int) -> list[Match]:
        return [
            m
            for m in session.scalars(
                select(Match).where(
                    Match.season == commence.year,
                    Match.home_team_id == home_id,
                    Match.away_team_id == away_id,
                )
            )
            if m.match_date is not None and abs(m.match_date - commence.date()) <= timedelta(days=1)
        ]

    candidates = find(home.id, away.id) or find(away.id, home.id)
    if len(candidates) != 1:
        logger.warning(
            "oddsapi event %s (%s v %s, %s): %d canonical candidates, skipping",
            event.event_id,
            event.home_team,
            event.away_team,
            event.commence_time,
            len(candidates),
        )
        return None
    match = candidates[0]
    session.add(MatchSourceKey(match_id=match.id, source=SOURCE, source_key=event.event_id))
    ctx.match_key[event.event_id] = match.id
    return match
