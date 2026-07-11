"""Ingest cached raw pages into the database.

Usage:
    python -m genpicks.ingest --seasons 2016-2026                # RLP (default)
    python -m genpicks.ingest --source nrl --seasons 2016-2026   # NRL.com
    python -m genpicks.ingest --source asb --seasons 2016-2026   # closing odds
    python -m genpicks.ingest --source nrl-teamlists --seasons 2026  # team lists
    python -m genpicks.ingest --source oddsapi                   # odds snapshots

Reads only from data/raw/ (never the network). Match pages the backfill has
not downloaded yet are skipped and picked up on the next run — ingest and
backfill can run at the same time. Ingest RLP before NRL for any given
season: the NRL loader reconciles against RLP-created matches and players.
"""

import argparse
import logging
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from genpicks.config import get_settings
from genpicks.db.models import PlayerMatchStats
from genpicks.ingest.asb_loader import load_asb_odds
from genpicks.ingest.nrl_loader import NrlContext, load_nrl_match, load_team_list
from genpicks.ingest.oddsapi_loader import OddsContext, load_odds_events
from genpicks.ingest.resolve import Resolver
from genpicks.ingest.rlp_loader import load_match_detail, load_season_rows
from genpicks.scrape import asb, nrl, oddsapi, rlp
from genpicks.scrape.backfill import parse_seasons

logger = logging.getLogger(__name__)


def ingest_season(
    session: Session, raw_root: Path, season: int, resolver: Resolver | None = None
) -> tuple[int, int, int]:
    """Returns (matches upserted, detail pages ingested, detail pages missing)."""
    season_file = raw_root / rlp.season_results_cache_path(season)
    if not season_file.exists():
        logger.warning("season %d: results page not in raw store, skipping", season)
        return 0, 0, 0

    rows = rlp.parse_season_results(season_file.read_text(encoding="utf-8"), season)
    if resolver is None:
        resolver = Resolver(session, rlp.SOURCE).warm()
    matches = load_season_rows(session, rows, resolver)

    # the season's existing stats rows in one round trip, keyed per match
    stats_by_match: dict[int, dict[int, PlayerMatchStats]] = {}
    for stats in session.scalars(
        select(PlayerMatchStats).where(
            PlayerMatchStats.match_id.in_([m.id for m in matches.values()])
        )
    ):
        stats_by_match.setdefault(stats.match_id, {})[stats.player_id] = stats

    ingested = missing = 0
    for source_key, match in matches.items():
        match_file = raw_root / rlp.match_cache_path(source_key)
        if not match_file.exists():
            missing += 1
            continue
        detail = rlp.parse_match(match_file.read_text(encoding="utf-8"), source_key)
        load_match_detail(session, match, detail, resolver, stats_by_match.get(match.id, {}))
        ingested += 1
    return len(matches), ingested, missing


def ingest_nrl_season(session: Session, raw_root: Path, season: int) -> tuple[int, int, int]:
    """Returns (fixtures attached, skipped/unreconciled, not yet downloaded)."""
    draw_dir = raw_root / f"nrl/draws/{season}"
    if not draw_dir.exists():
        logger.warning("season %d: no NRL draw files in raw store, skipping", season)
        return 0, 0, 0

    ctx = NrlContext(session, season)
    attached = skipped = missing = 0
    for draw_file in sorted(draw_dir.glob("round-*.json")):
        page = nrl.parse_draw(draw_file.read_text(encoding="utf-8"))
        for fixture in page.fixtures:
            if not fixture.is_played:
                continue
            match_file = raw_root / nrl.match_cache_path(fixture.match_centre_path)
            if not match_file.exists():
                missing += 1
                continue
            detail = nrl.parse_match(match_file.read_text(encoding="utf-8"))
            if load_nrl_match(session, season, fixture, detail, ctx):
                attached += 1
            else:
                skipped += 1
    return attached, skipped, missing


def ingest_nrl_teamlists(session: Session, raw_root: Path, season: int) -> tuple[int, int]:
    """Returns (team lists loaded, skipped/unreconciled)."""
    draw_dir = raw_root / f"nrl/draws/{season}"
    if not draw_dir.exists():
        logger.warning("season %d: no NRL draw files in raw store, skipping", season)
        return 0, 0

    ctx = NrlContext(session, season)
    loaded = skipped = 0
    for draw_file in sorted(draw_dir.glob("round-*.json")):
        page = nrl.parse_draw(draw_file.read_text(encoding="utf-8"))
        for fixture in page.fixtures:
            if fixture.is_played:
                continue
            teamlist_file = raw_root / nrl.teamlist_cache_path(fixture.match_centre_path)
            if not teamlist_file.exists():
                continue
            detail = nrl.parse_match(teamlist_file.read_text(encoding="utf-8"))
            if load_team_list(session, season, fixture, detail, ctx):
                loaded += 1
            else:
                skipped += 1
    return loaded, skipped


def ingest_oddsapi(session: Session, raw_root: Path) -> tuple[int, int, int]:
    """Replay every snapshot the DB has not seen. Returns (rows, matched, unmatched)."""
    snapshot_dir = raw_root / f"oddsapi/{oddsapi.SPORT_KEY}"
    ctx = OddsContext(session)
    total_rows = total_matched = total_unmatched = 0
    for snapshot_file in sorted(snapshot_dir.glob("*.json")) if snapshot_dir.exists() else []:
        events = oddsapi.parse_snapshot(snapshot_file.read_text(encoding="utf-8"))
        rows, matched, unmatched = load_odds_events(
            session, events, oddsapi.captured_at_from_path(snapshot_file), ctx
        )
        total_rows += rows
        total_matched += matched
        total_unmatched += unmatched
    return total_rows, total_matched, total_unmatched


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", choices=("rlp", "nrl", "nrl-teamlists", "asb", "oddsapi"), default="rlp"
    )
    parser.add_argument("--seasons", default=None, help='e.g. "2016-2026" (not used by oddsapi)')
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--database-url", default=None, help="defaults to GENPICKS_DATABASE_URL / settings"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    engine = create_engine(args.database_url or get_settings().database_url)
    # expire_on_commit=False: the per-season commit must not expire the
    # prefetched entities — refreshing them would re-pay one round trip per
    # object, exactly what the prefetching exists to avoid. This process is
    # the only writer while it runs.
    with Session(engine, expire_on_commit=False) as session:
        if args.source == "oddsapi":
            rows, matched, unmatched = ingest_oddsapi(session, args.raw_root)
            session.commit()
            logger.info(
                "oddsapi: %d snapshot rows added (%d events matched, %d unmatched)",
                rows,
                matched,
                unmatched,
            )
            return
        if args.seasons is None:
            parser.error(f"--seasons is required for --source {args.source}")
        if args.source == "asb":
            workbook = args.raw_root / asb.DEFAULT_PATH
            if not workbook.exists():
                parser.error(
                    f"{workbook} not found — download "
                    "https://www.aussportsbetting.com/historical_data/nrl.xlsx "
                    "in a browser and save it there"
                )
            odds_rows = asb.parse_workbook(workbook)
            loaded, unmatched = load_asb_odds(session, odds_rows, set(parse_seasons(args.seasons)))
            session.commit()
            logger.info("asb: odds for %d matches loaded, %d rows unmatched", loaded, unmatched)
            return
        # one warmed resolver for the whole run: the alias cache carries
        # across seasons, so only genuinely new entities touch the wire
        rlp_resolver = Resolver(session, rlp.SOURCE).warm() if args.source == "rlp" else None
        for season in parse_seasons(args.seasons):
            if args.source == "nrl-teamlists":
                loaded, skipped = ingest_nrl_teamlists(session, args.raw_root, season)
                session.commit()
                logger.info("season %d: %d team lists loaded, %d skipped", season, loaded, skipped)
            elif args.source == "nrl":
                attached, skipped, missing = ingest_nrl_season(session, args.raw_root, season)
                session.commit()
                logger.info(
                    "season %d: %d NRL matches attached, %d unreconciled, %d not yet downloaded",
                    season,
                    attached,
                    skipped,
                    missing,
                )
            else:
                upserted, ingested, missing = ingest_season(
                    session, args.raw_root, season, rlp_resolver
                )
                session.commit()
                logger.info(
                    "season %d: %d matches upserted, %d detail pages ingested,"
                    " %d not yet downloaded",
                    season,
                    upserted,
                    ingested,
                    missing,
                )


if __name__ == "__main__":
    main()
