"""Load parsed RLP pages into the clean schema.

Idempotent: matches upsert on (source, source_key), stats upsert on
(match_id, player_id). Re-ingesting the same or refreshed raw files updates
in place and never duplicates.

What RLP can and cannot fill:
- matches: everything except kickoff_utc (needs venue timezone mapping).
- player_match_stats: position, jersey_number and tries only; tries default
  to 0 for anyone who appeared in a completed match without a scoresheet
  entry. NRL.com will fill the remaining stat columns later.
- try_events: nothing — RLP has no try order, so that table stays empty
  until a source with scoring order exists.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from genpicks.db.models import Match, PlayerMatchStats
from genpicks.ingest.resolve import Resolver
from genpicks.scrape.rlp import SOURCE, MatchDetail, SeasonMatchRow

logger = logging.getLogger(__name__)


def load_season_rows(session: Session, rows: list[SeasonMatchRow]) -> dict[str, Match]:
    """Upsert one season's matches; returns matches keyed by source_key."""
    resolver = Resolver(session, SOURCE)
    loaded: dict[str, Match] = {}
    for row in rows:
        # Resolve entities before creating the Match: resolver queries
        # autoflush the session, and a pending Match without team ids yet
        # would violate NOT NULL.
        home_team_id = resolver.team(row.home_slug, row.home_name).id
        away_team_id = resolver.team(row.away_slug, row.away_name).id
        venue_id = resolver.venue(row.venue_id, row.venue_name).id if row.venue_id else None

        match = session.scalar(
            select(Match).where(Match.source == SOURCE, Match.source_key == row.source_key)
        )
        if match is None:
            match = Match(source=SOURCE, source_key=row.source_key)
            session.add(match)

        match.season = row.season
        match.round = row.round
        match.match_date = row.date
        match.home_team_id = home_team_id
        match.away_team_id = away_team_id
        match.venue_id = venue_id
        match.home_score = row.home_score
        match.away_score = row.away_score
        loaded[row.source_key] = match
    session.flush()
    return loaded


def load_match_detail(session: Session, match: Match, detail: MatchDetail) -> int:
    """Upsert per-player rows for one match; returns the number of rows."""
    resolver = Resolver(session, SOURCE)
    completed = (detail.status or "").lower() == "completed"

    if detail.venue_city and detail.venue_id is not None and match.venue_id is not None:
        venue = resolver.venue(detail.venue_id, detail.venue_name, detail.venue_city)
        if venue.id != match.venue_id:
            logger.warning(
                "match %s: detail venue %s disagrees with results-page venue",
                match.source_key,
                detail.venue_id,
            )

    tries: dict[str, int] = {}
    for entry in detail.scoresheet:
        if entry.stat == "Tries" and entry.count is not None:
            tries[entry.player_id] = tries.get(entry.player_id, 0) + entry.count

    existing = {
        stats.player_id: stats
        for stats in session.scalars(
            select(PlayerMatchStats).where(PlayerMatchStats.match_id == match.id)
        )
    }

    count = 0
    seen_player_ids: set[int] = set()
    for appearance in detail.appearances:
        player = resolver.player(appearance.player_id, appearance.player_name)
        if player.id in seen_player_ids:
            continue  # defensive: one row per player per match
        seen_player_ids.add(player.id)

        stats = existing.get(player.id)
        if stats is None:
            stats = PlayerMatchStats(match_id=match.id, player_id=player.id)
            session.add(stats)

        stats.team_id = match.home_team_id if appearance.side == "home" else match.away_team_id
        stats.position = appearance.position
        stats.jersey_number = appearance.jersey
        stats.tries = tries.get(appearance.player_id, 0 if completed else None)
        count += 1
    session.flush()
    return count
