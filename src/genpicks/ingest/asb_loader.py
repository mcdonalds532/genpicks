"""Load aussportsbetting closing odds into odds_snapshots.

One snapshot row per selection (home, away, draw) per match, source "asb",
market "h2h". The price is the closing odds where published (the draw only
has a survey average). captured_at approximates the close with the match's
UTC kickoff when known, else midnight UTC on the match date. The full
spreadsheet row rides along in `raw`, so line/totals markets are recoverable
later without re-reading the file.

Idempotent: a match's asb h2h snapshots are deleted and rebuilt on re-run.
Matches are reconciled by season + teams + date (±1 day: the sheet uses the
Sydney date, match_date is venue-local, e.g. Las Vegas).
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from genpicks.db.models import MARKET_H2H, Match, OddsSnapshot, Team, TeamAlias
from genpicks.scrape.asb import SOURCE, AsbMatchOdds

logger = logging.getLogger(__name__)

RLP_SOURCE = "rlp"

ASB_NAME_TO_RLP_SLUG = {
    "Brisbane Broncos": "brisbane-broncos",
    "Canberra Raiders": "canberra-raiders",
    "Canterbury Bulldogs": "canterbury-bankstown-bulldogs",
    "Cronulla Sharks": "cronulla-sutherland-sharks",
    "Dolphins": "dolphins",
    "Gold Coast Titans": "gold-coast-titans",
    "Manly Sea Eagles": "manly-warringah-sea-eagles",
    "Melbourne Storm": "melbourne",
    "New Zealand Warriors": "warriors",
    "Newcastle Knights": "newcastle-knights",
    "North QLD Cowboys": "north-queensland-cowboys",
    "Parramatta Eels": "parramatta-eels",
    "Penrith Panthers": "penrith-panthers",
    "South Sydney Rabbitohs": "south-sydney-rabbitohs",
    "St George Dragons": "st-george-illawarra-dragons",
    "Sydney Roosters": "sydney-roosters",
    "Wests Tigers": "wests-tigers",
}


def load_asb_odds(session: Session, rows: list[AsbMatchOdds], seasons: set[int]) -> tuple[int, int]:
    """Returns (matches with odds loaded, rows that found no match)."""
    loaded = unmatched = 0
    for row in rows:
        if row.date.year not in seasons:
            continue
        match = _resolve_match(session, row)
        if match is None:
            unmatched += 1
            continue
        _replace_snapshots(session, match, row)
        loaded += 1
    session.flush()
    return loaded, unmatched


def _resolve_team(session: Session, asb_name: str) -> Team | None:
    existing = session.scalar(
        select(TeamAlias).where(TeamAlias.source == SOURCE, TeamAlias.alias == asb_name)
    )
    if existing is not None:
        return session.get(Team, existing.team_id)
    slug = ASB_NAME_TO_RLP_SLUG.get(asb_name)
    if slug is None:
        logger.warning("no RLP slug mapping for ASB team %r", asb_name)
        return None
    rlp_alias = session.scalar(
        select(TeamAlias).where(TeamAlias.source == RLP_SOURCE, TeamAlias.alias == slug)
    )
    if rlp_alias is None:
        logger.warning("team %r not ingested from RLP yet", slug)
        return None
    session.add(TeamAlias(team_id=rlp_alias.team_id, alias=asb_name, source=SOURCE))
    session.flush()
    return session.get(Team, rlp_alias.team_id)


def _resolve_match(session: Session, row: AsbMatchOdds) -> Match | None:
    home = _resolve_team(session, row.home_name)
    away = _resolve_team(session, row.away_name)
    if home is None or away is None:
        return None
    candidates = [
        m
        for m in session.scalars(
            select(Match).where(
                Match.season == row.date.year,
                Match.home_team_id == home.id,
                Match.away_team_id == away.id,
            )
        )
        if m.match_date is not None and abs(m.match_date - row.date) <= timedelta(days=1)
    ]
    if len(candidates) != 1:
        logger.warning(
            "ASB row %s %s v %s: %d canonical candidates, skipping",
            row.date,
            row.home_name,
            row.away_name,
            len(candidates),
        )
        return None
    return candidates[0]


def _replace_snapshots(session: Session, match: Match, row: AsbMatchOdds) -> None:
    session.execute(
        delete(OddsSnapshot).where(
            OddsSnapshot.match_id == match.id,
            OddsSnapshot.source == SOURCE,
            OddsSnapshot.market == MARKET_H2H,
        )
    )
    captured_at = match.kickoff_utc or datetime.combine(row.date, datetime.min.time(), tzinfo=UTC)
    selections = [
        (row.home_name, match.home_team_id, row.home_odds_close or row.home_odds_avg),
        (row.away_name, match.away_team_id, row.away_odds_close or row.away_odds_avg),
        ("Draw", None, row.draw_odds_avg),
    ]
    for selection_name, team_id, price in selections:
        if price is None:
            continue
        session.add(
            OddsSnapshot(
                source=SOURCE,
                market=MARKET_H2H,
                match_id=match.id,
                team_id=team_id,
                player_id=None,
                selection_name=selection_name,
                price_decimal=price,
                captured_at=captured_at,
                raw=row.raw,
            )
        )
