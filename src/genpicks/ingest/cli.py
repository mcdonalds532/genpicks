"""Ingest cached raw pages into the database.

Usage:
    python -m genpicks.ingest --seasons 2016-2026                # RLP (default)
    python -m genpicks.ingest --source nrl --seasons 2016-2026   # NRL.com
    python -m genpicks.ingest --source asb --seasons 2016-2026   # closing odds

Reads only from data/raw/ (never the network). Match pages the backfill has
not downloaded yet are skipped and picked up on the next run — ingest and
backfill can run at the same time. Ingest RLP before NRL for any given
season: the NRL loader reconciles against RLP-created matches and players.
"""

import argparse
import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from genpicks.config import get_settings
from genpicks.scrape import asb, nrl, rlp
from genpicks.scrape.backfill import parse_seasons
from genpicks.ingest.asb_loader import load_asb_odds
from genpicks.ingest.nrl_loader import load_nrl_match
from genpicks.ingest.rlp_loader import load_match_detail, load_season_rows

logger = logging.getLogger(__name__)


def ingest_season(session: Session, raw_root: Path, season: int) -> tuple[int, int, int]:
    """Returns (matches upserted, detail pages ingested, detail pages missing)."""
    season_file = raw_root / rlp.season_results_cache_path(season)
    if not season_file.exists():
        logger.warning("season %d: results page not in raw store, skipping", season)
        return 0, 0, 0

    rows = rlp.parse_season_results(season_file.read_text(encoding="utf-8"), season)
    matches = load_season_rows(session, rows)

    ingested = missing = 0
    for source_key, match in matches.items():
        match_file = raw_root / rlp.match_cache_path(source_key)
        if not match_file.exists():
            missing += 1
            continue
        detail = rlp.parse_match(match_file.read_text(encoding="utf-8"), source_key)
        load_match_detail(session, match, detail)
        ingested += 1
    return len(matches), ingested, missing


def ingest_nrl_season(
    session: Session, raw_root: Path, season: int
) -> tuple[int, int, int]:
    """Returns (fixtures attached, skipped/unreconciled, not yet downloaded)."""
    draw_dir = raw_root / f"nrl/draws/{season}"
    if not draw_dir.exists():
        logger.warning("season %d: no NRL draw files in raw store, skipping", season)
        return 0, 0, 0

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
            if load_nrl_match(session, season, fixture, detail):
                attached += 1
            else:
                skipped += 1
    return attached, skipped, missing


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("rlp", "nrl", "asb"), default="rlp")
    parser.add_argument("--seasons", required=True, help='e.g. "2016-2026"')
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--database-url", default=None,
                        help="defaults to GENPICKS_DATABASE_URL / settings")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    engine = create_engine(args.database_url or get_settings().database_url)
    with Session(engine) as session:
        if args.source == "asb":
            workbook = args.raw_root / asb.DEFAULT_PATH
            if not workbook.exists():
                parser.error(
                    f"{workbook} not found — download "
                    "https://www.aussportsbetting.com/historical_data/nrl.xlsx "
                    "in a browser and save it there"
                )
            rows = asb.parse_workbook(workbook)
            loaded, unmatched = load_asb_odds(
                session, rows, set(parse_seasons(args.seasons))
            )
            session.commit()
            logger.info("asb: odds for %d matches loaded, %d rows unmatched",
                        loaded, unmatched)
            return
        for season in parse_seasons(args.seasons):
            if args.source == "nrl":
                attached, skipped, missing = ingest_nrl_season(
                    session, args.raw_root, season
                )
                session.commit()
                logger.info(
                    "season %d: %d NRL matches attached, %d unreconciled, %d not yet downloaded",
                    season, attached, skipped, missing,
                )
            else:
                upserted, ingested, missing = ingest_season(
                    session, args.raw_root, season
                )
                session.commit()
                logger.info(
                    "season %d: %d matches upserted, %d detail pages ingested, %d not yet downloaded",
                    season, upserted, ingested, missing,
                )


if __name__ == "__main__":
    main()
