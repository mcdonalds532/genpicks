"""Attach NRL.com match-centre data to canonical matches.

RLP created the canonical match/team/player rows; this loader reconciles
NRL.com's own ids onto them and fills what RLP cannot:

- matches.kickoff_utc (NRL.com serves real UTC kickoff times)
- player_match_stats: minutes, run metres, line/tackle breaks, tackles,
  missed tackles, offloads, errors, try assists (and tries, cross-checked)
- try_events: scoring order and minute from the match timeline

Reconciliation:
- teams: NRL teamId alias if seen before, else nickname -> RLP slug seed map.
- matches: NRL matchId via match_source_keys if seen before, else same
  season + teams + kickoff date within a day of match_date (UTC date can
  differ from local date, e.g. Las Vegas).
- players: NRL playerId alias if seen before, else matched inside the
  reconciled match against RLP appearances by full name, falling back to
  jersey number; else a same-name player unclaimed by any nrl row (a debut
  RLP only credits in a later match); else a new Player row. Requires the
  RLP detail for the match to be ingested first to avoid duplicate players.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from genpicks.db.models import (
    Match,
    MatchSourceKey,
    Player,
    PlayerAlias,
    PlayerMatchStats,
    Team,
    TeamAlias,
    TeamListEntry,
    TryEvent,
)
from genpicks.ingest.resolve import adopt_orphan_player
from genpicks.scrape.nrl import SOURCE, NrlFixture, NrlMatchDetail

logger = logging.getLogger(__name__)

RLP_SOURCE = "rlp"

# NRL.com nickname -> RLP team slug (every club active 2016-2026)
NICKNAME_TO_RLP_SLUG = {
    "Broncos": "brisbane-broncos",
    "Raiders": "canberra-raiders",
    "Bulldogs": "canterbury-bankstown-bulldogs",
    "Sharks": "cronulla-sutherland-sharks",
    "Dolphins": "dolphins",
    "Titans": "gold-coast-titans",
    "Sea Eagles": "manly-warringah-sea-eagles",
    "Storm": "melbourne",
    "Knights": "newcastle-knights",
    "Cowboys": "north-queensland-cowboys",
    "Eels": "parramatta-eels",
    "Panthers": "penrith-panthers",
    "Rabbitohs": "south-sydney-rabbitohs",
    "Dragons": "st-george-illawarra-dragons",
    "Roosters": "sydney-roosters",
    "Warriors": "warriors",
    "Wests Tigers": "wests-tigers",
}

# NRL.com position label -> the canonical vocabulary RLP established in
# player_match_stats (which the try-share position priors were computed on).
# Labels not listed pass through unchanged (Fullback, Centre, Halfback,
# Hooker, Lock, Reserve).
NRL_POSITION_TO_CANONICAL = {
    "Winger": "Wing",
    "Prop": "Front row",
    "2nd Row": "Second row",
    "Five-Eighth": "Five-eighth",
    "Interchange": "Bench",
}


def canonical_position(nrl_position: str | None) -> str | None:
    if nrl_position is None:
        return None
    return NRL_POSITION_TO_CANONICAL.get(nrl_position, nrl_position)


# NRL.com stat name -> player_match_stats column. Tries are deliberately
# absent: they are handled through the timeline-vs-RLP reconciliation below,
# because old NRL.com stat feeds are incomplete (observed: a 2017 match whose
# RLP scoresheet has 10 tries, NRL timeline 7, NRL stats table 5).
STAT_COLUMNS = {
    "minutesPlayed": "minutes_played",
    "tryAssists": "try_assists",
    "lineBreaks": "line_breaks",
    "tackleBreaks": "tackle_breaks",
    "allRunMetres": "run_metres",
    "tacklesMade": "tackles",
    "missedTackles": "missed_tackles",
    "offloads": "offloads",
    "errors": "errors",
}


def load_nrl_match(
    session: Session, season: int, fixture: NrlFixture, detail: NrlMatchDetail
) -> bool:
    """Attach one NRL match's data; returns False if it cannot be reconciled."""
    home_team = _resolve_team(session, fixture.home_team_id, fixture.home_nickname)
    away_team = _resolve_team(session, fixture.away_team_id, fixture.away_nickname)
    if home_team is None or away_team is None:
        return False

    match = _resolve_match(session, season, detail, fixture, home_team, away_team)
    if match is None:
        return False

    if detail.start_time_utc is not None:
        match.kickoff_utc = detail.start_time_utc

    side_team = {"home": home_team, "away": away_team}
    players = _resolve_players(session, match, detail, side_team)

    timeline_ok = _timeline_reconciles(session, match, detail, home_team, away_team)
    _load_player_stats(session, match, detail, side_team, players, timeline_ok)
    if timeline_ok:
        _load_try_events(session, match, detail, home_team, away_team, players)
    else:
        # an incomplete timeline would silently corrupt scoring_order
        session.execute(delete(TryEvent).where(TryEvent.match_id == match.id))
    session.flush()
    return True


def _timeline_reconciles(
    session: Session,
    match: Match,
    detail: NrlMatchDetail,
    home_team: Team,
    away_team: Team,
) -> bool:
    """True when the NRL timeline's per-team try totals agree with RLP's.

    RLP's curated scoresheet is the authority on try counts; the timeline is
    only trusted (for try order and attribution) when it accounts for every
    try RLP knows about. With no RLP baseline there is nothing to check
    against, so the timeline is accepted as-is.
    """
    if not detail.tries:
        return False
    rlp_totals: dict[int, int] = {home_team.id: 0, away_team.id: 0}
    have_baseline = False
    for stats in session.scalars(
        select(PlayerMatchStats).where(PlayerMatchStats.match_id == match.id)
    ):
        if stats.tries is not None:
            have_baseline = True
            rlp_totals[stats.team_id] = rlp_totals.get(stats.team_id, 0) + stats.tries
    if not have_baseline:
        return True

    nrl_to_canonical = {
        detail.home_team_id: home_team.id,
        detail.away_team_id: away_team.id,
    }
    timeline_totals = {home_team.id: 0, away_team.id: 0}
    for try_event in detail.tries:
        team_id = nrl_to_canonical.get(try_event.team_id)
        if team_id is not None:
            timeline_totals[team_id] += 1
    if timeline_totals != rlp_totals:
        logger.warning(
            "match %s: timeline tries %s disagree with RLP %s — keeping RLP counts, "
            "skipping try order",
            match.source_key, timeline_totals, rlp_totals,
        )
        return False
    return True


# -- teams -------------------------------------------------------------------


def _resolve_team(session: Session, nrl_team_id: int, nickname: str) -> Team | None:
    alias = str(nrl_team_id)
    existing = session.scalar(
        select(TeamAlias).where(TeamAlias.source == SOURCE, TeamAlias.alias == alias)
    )
    if existing is not None:
        return session.get(Team, existing.team_id)

    slug = NICKNAME_TO_RLP_SLUG.get(nickname)
    if slug is None:
        logger.warning("no RLP slug mapping for NRL team %r (%s)", nickname, alias)
        return None
    rlp_alias = session.scalar(
        select(TeamAlias).where(TeamAlias.source == RLP_SOURCE, TeamAlias.alias == slug)
    )
    if rlp_alias is None:
        logger.warning("team %r not ingested from RLP yet", slug)
        return None
    session.add(TeamAlias(team_id=rlp_alias.team_id, alias=alias, source=SOURCE))
    if nickname:
        session.add(TeamAlias(team_id=rlp_alias.team_id, alias=nickname, source=SOURCE))
    session.flush()
    return session.get(Team, rlp_alias.team_id)


# -- matches -----------------------------------------------------------------


def _resolve_match(
    session: Session,
    season: int,
    detail: NrlMatchDetail,
    fixture: NrlFixture,
    home_team: Team,
    away_team: Team,
) -> Match | None:
    known = session.scalar(
        select(MatchSourceKey).where(
            MatchSourceKey.source == SOURCE,
            MatchSourceKey.source_key == detail.match_id,
        )
    )
    if known is not None:
        return session.get(Match, known.match_id)

    kickoff = detail.start_time_utc or fixture.kickoff_utc

    def find(home_id: int, away_id: int) -> list[Match]:
        found = session.scalars(
            select(Match).where(
                Match.season == season,
                Match.home_team_id == home_id,
                Match.away_team_id == away_id,
            )
        )
        return [
            m
            for m in found
            if kickoff is None
            or (
                m.match_date is not None
                and abs(m.match_date - kickoff.date()) <= timedelta(days=1)
            )
        ]

    candidates = find(home_team.id, away_team.id)
    if not candidates:
        # sources disagree on the designated home side at neutral venues
        # (observed: the 2016 Grand Final)
        candidates = find(away_team.id, home_team.id)
        if candidates:
            logger.info(
                "NRL match %s: home/away designation differs from RLP",
                detail.match_id,
            )
    if len(candidates) != 1:
        logger.warning(
            "NRL match %s (%s v %s, %s): %d canonical candidates, skipping",
            detail.match_id,
            fixture.home_nickname,
            fixture.away_nickname,
            kickoff,
            len(candidates),
        )
        return None

    match = candidates[0]
    session.add(
        MatchSourceKey(match_id=match.id, source=SOURCE, source_key=detail.match_id)
    )
    session.flush()
    return match


# -- players -----------------------------------------------------------------


def _resolve_players(
    session: Session,
    match: Match,
    detail: NrlMatchDetail,
    side_team: dict[str, Team],
) -> dict[int, Player]:
    """Map every squad member's NRL playerId to a canonical Player."""
    rlp_rows = _rlp_appearance_index(session, match)
    minutes = {
        s.player_id: s.stats.get("minutesPlayed") for s in detail.player_stats
    }
    resolved: dict[int, Player] = {}

    for squad_player in detail.squads:
        alias = str(squad_player.player_id)
        existing = session.scalar(
            select(PlayerAlias).where(
                PlayerAlias.source == SOURCE, PlayerAlias.alias == alias
            )
        )
        if existing is not None:
            resolved[squad_player.player_id] = session.get(Player, existing.player_id)
            continue

        team_id = side_team[squad_player.side].id
        full_name = f"{squad_player.first_name} {squad_player.last_name}".strip()
        player = rlp_rows.get((team_id, full_name.lower()))
        if player is None and squad_player.number is not None:
            player = rlp_rows.get((team_id, squad_player.number))
            if player is not None:
                logger.info(
                    "match %s: matched %r by jersey %d to %r",
                    match.source_key, full_name, squad_player.number, player.full_name,
                )
        if player is None:
            # NRL squads include non-playing reserves (the 18th man); RLP
            # lists only who took the field. Don't invent Player rows for
            # people with no game time.
            if not minutes.get(squad_player.player_id):
                continue
            # a debut RLP credits only in a later match may already exist as
            # an RLP-created player with no nrl alias — claim it, don't dup
            player = adopt_orphan_player(session, SOURCE, full_name)
        if player is None:
            player = Player(full_name=full_name)
            session.add(player)
            session.flush()
            if rlp_rows:  # RLP squad known, so this should have matched
                logger.warning(
                    "match %s: no RLP counterpart for %r (#%s), created new player",
                    match.source_key, full_name, squad_player.number,
                )
        session.add(PlayerAlias(player_id=player.id, alias=alias, source=SOURCE))
        session.flush()
        resolved[squad_player.player_id] = player
    return resolved


def _rlp_appearance_index(session: Session, match: Match) -> dict:
    """Existing stats rows keyed by (team_id, lowercased name) and (team_id, jersey)."""
    index: dict = {}
    rows = session.execute(
        select(PlayerMatchStats, Player)
        .join(Player, Player.id == PlayerMatchStats.player_id)
        .where(PlayerMatchStats.match_id == match.id)
    ).all()
    for stats, player in rows:
        index[(stats.team_id, player.full_name.lower())] = player
        if stats.jersey_number is not None:
            index.setdefault((stats.team_id, stats.jersey_number), player)
    return index


# -- stats and tries ---------------------------------------------------------


def _load_player_stats(
    session: Session,
    match: Match,
    detail: NrlMatchDetail,
    side_team: dict[str, Team],
    players: dict[int, Player],
    timeline_ok: bool,
) -> None:
    timeline_tries: dict[int, int] = {}
    if timeline_ok:
        for try_event in detail.tries:
            if try_event.player_id is not None:
                timeline_tries[try_event.player_id] = (
                    timeline_tries.get(try_event.player_id, 0) + 1
                )
    existing = {
        stats.player_id: stats
        for stats in session.scalars(
            select(PlayerMatchStats).where(PlayerMatchStats.match_id == match.id)
        )
    }
    squad_by_id = {p.player_id: p for p in detail.squads}

    for stat_row in detail.player_stats:
        player = players.get(stat_row.player_id)
        if player is None:
            continue
        row = existing.get(player.id)
        if row is None:
            row = PlayerMatchStats(
                match_id=match.id,
                player_id=player.id,
                team_id=side_team[stat_row.side].id,
            )
            session.add(row)
            existing[player.id] = row

        squad_player = squad_by_id.get(stat_row.player_id)
        if squad_player is not None:
            if row.position is None:
                row.position = canonical_position(squad_player.position)
            if row.jersey_number is None:
                row.jersey_number = squad_player.number

        for source_name, column in STAT_COLUMNS.items():
            value = stat_row.stats.get(source_name)
            if value is not None:
                setattr(row, column, value)

        # tries: reconciled timeline > RLP scoresheet > NRL stats table
        if timeline_ok:
            row.tries = timeline_tries.get(stat_row.player_id, 0)
        elif row.tries is None:
            row.tries = stat_row.stats.get("tries")


# -- team lists (pre-match) ---------------------------------------------------


def load_team_list(
    session: Session, season: int, fixture: NrlFixture, detail: NrlMatchDetail
) -> bool:
    """Replace a match's team_list_entries with the published squads.

    Players resolve through their (nrl, playerId) alias only — anyone without
    one (a debutant) keeps player_id null rather than getting a Player row
    invented here, because played-match ingest owns player creation and would
    otherwise produce a duplicate once RLP ingests the match.
    Returns False if the match cannot be reconciled or no squads are listed.
    """
    if not detail.squads:
        return False
    home_team = _resolve_team(session, fixture.home_team_id, fixture.home_nickname)
    away_team = _resolve_team(session, fixture.away_team_id, fixture.away_nickname)
    if home_team is None or away_team is None:
        return False
    match = _resolve_match(session, season, detail, fixture, home_team, away_team)
    if match is None:
        return False

    # upcoming fixtures have no played-match ingest to fill their kickoff
    if detail.start_time_utc is not None:
        match.kickoff_utc = detail.start_time_utc

    aliases = {
        alias.alias: alias.player_id
        for alias in session.scalars(
            select(PlayerAlias).where(
                PlayerAlias.source == SOURCE,
                PlayerAlias.alias.in_(
                    [str(p.player_id) for p in detail.squads]
                ),
            )
        )
    }
    side_team = {"home": home_team, "away": away_team}
    captured_at = datetime.now(timezone.utc)

    session.execute(delete(TeamListEntry).where(TeamListEntry.match_id == match.id))
    unresolved = 0
    for squad_player in detail.squads:
        player_id = aliases.get(str(squad_player.player_id))
        if player_id is None:
            unresolved += 1
        session.add(
            TeamListEntry(
                match_id=match.id,
                team_id=side_team[squad_player.side].id,
                player_id=player_id,
                player_name=(
                    f"{squad_player.first_name} {squad_player.last_name}".strip()
                ),
                position=canonical_position(squad_player.position),
                jersey_number=squad_player.number,
                source=SOURCE,
                captured_at=captured_at,
            )
        )
    if unresolved:
        logger.info(
            "match %s team list: %d/%d players have no appearance history yet",
            match.source_key, unresolved, len(detail.squads),
        )
    session.flush()
    return True


def _load_try_events(
    session: Session,
    match: Match,
    detail: NrlMatchDetail,
    home_team: Team,
    away_team: Team,
    players: dict[int, Player],
) -> None:
    """Rebuild the match's try events from the timeline (idempotent)."""
    if not detail.tries:
        return
    nrl_team_to_canonical = {
        detail.home_team_id: home_team.id,
        detail.away_team_id: away_team.id,
    }
    session.execute(delete(TryEvent).where(TryEvent.match_id == match.id))
    for order, try_event in enumerate(detail.tries, start=1):
        team_id = nrl_team_to_canonical.get(try_event.team_id)
        if team_id is None:
            logger.warning(
                "match %s try %d: unknown NRL team id %s",
                match.source_key, order, try_event.team_id,
            )
            continue
        player = players.get(try_event.player_id)
        session.add(
            TryEvent(
                match_id=match.id,
                team_id=team_id,
                player_id=player.id if player is not None else None,
                scoring_order=order,
                minute=(
                    try_event.game_seconds // 60
                    if try_event.game_seconds is not None
                    else None
                ),
            )
        )
