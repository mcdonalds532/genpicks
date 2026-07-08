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
from datetime import timedelta

from sqlalchemy import exists, select
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


def load_odds_events(
    session: Session, events: list[OddsEvent], captured_at
) -> tuple[int, int, int]:
    """Returns (snapshot rows added, events matched, events unmatched)."""
    already = session.scalar(
        select(
            exists().where(
                OddsSnapshot.source == SOURCE,
                OddsSnapshot.captured_at == captured_at,
            )
        )
    )
    if already:
        return 0, 0, 0

    rows = matched = unmatched = 0
    for event in events:
        match = _resolve_match(session, event)
        if match is None:
            unmatched += 1
            continue
        matched += 1
        for price in event.prices:
            team = _resolve_team(session, price.selection_name)
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


def _resolve_team(session: Session, name: str) -> Team | None:
    if name == "Draw":
        return None  # a real selection, priced, but not a team
    existing = session.scalar(
        select(TeamAlias).where(TeamAlias.source == SOURCE, TeamAlias.alias == name)
    )
    if existing is not None:
        return session.get(Team, existing.team_id)

    slug = ODDSAPI_NAME_TO_RLP_SLUG.get(name)
    if slug is None:
        slug = next(
            (
                NICKNAME_TO_RLP_SLUG[nick]
                for nick in _NICKNAMES
                if nick in name
            ),
            None,
        )
        if slug is not None:
            logger.warning(
                "oddsapi team %r resolved by nickname only — add it to "
                "ODDSAPI_NAME_TO_RLP_SLUG", name,
            )
    if slug is None:
        logger.warning("no mapping for oddsapi team %r", name)
        return None
    rlp_alias = session.scalar(
        select(TeamAlias).where(TeamAlias.source == RLP_SOURCE, TeamAlias.alias == slug)
    )
    if rlp_alias is None:
        logger.warning("team %r not ingested from RLP yet", slug)
        return None
    session.add(TeamAlias(team_id=rlp_alias.team_id, alias=name, source=SOURCE))
    session.flush()
    return session.get(Team, rlp_alias.team_id)


def _resolve_match(session: Session, event: OddsEvent) -> Match | None:
    known = session.scalar(
        select(MatchSourceKey).where(
            MatchSourceKey.source == SOURCE,
            MatchSourceKey.source_key == event.event_id,
        )
    )
    if known is not None:
        return session.get(Match, known.match_id)
    if event.commence_time is None:
        return None

    home = _resolve_team(session, event.home_team)
    away = _resolve_team(session, event.away_team)
    if home is None or away is None:
        return None

    def find(home_id: int, away_id: int) -> list[Match]:
        return [
            m
            for m in session.scalars(
                select(Match).where(
                    Match.season == event.commence_time.year,
                    Match.home_team_id == home_id,
                    Match.away_team_id == away_id,
                )
            )
            if m.match_date is not None
            and abs(m.match_date - event.commence_time.date()) <= timedelta(days=1)
        ]

    candidates = find(home.id, away.id) or find(away.id, home.id)
    if len(candidates) != 1:
        logger.warning(
            "oddsapi event %s (%s v %s, %s): %d canonical candidates, skipping",
            event.event_id, event.home_team, event.away_team,
            event.commence_time, len(candidates),
        )
        return None
    match = candidates[0]
    session.add(
        MatchSourceKey(match_id=match.id, source=SOURCE, source_key=event.event_id)
    )
    session.flush()
    return match
