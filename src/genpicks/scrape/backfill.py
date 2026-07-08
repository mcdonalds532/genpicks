"""Download raw source pages into data/raw/.

Usage:
    python -m genpicks.scrape --seasons 2016-2025                # RLP (default)
    python -m genpicks.scrape --source nrl --seasons 2016-2025   # NRL.com JSON
    python -m genpicks.scrape --source nrl-teamlists --seasons 2026  # team lists
    python -m genpicks.scrape --seasons 2025 --limit 5           # smoke test
    python -m genpicks.scrape --seasons 2025 --skip-matches

Already-cached pages are skipped, so an interrupted backfill just resumes.
At the default 2s between requests a full 10-season backfill (~2000 match
pages per source) takes a bit over an hour of network time on the first run.
"""

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from genpicks.scrape import nrl, rlp
from genpicks.scrape.fetch import Fetcher

logger = logging.getLogger(__name__)


def parse_seasons(spec: str) -> list[int]:
    """"2016-2025" or "2019" or "2019,2021" -> list of years."""
    seasons: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            seasons.extend(range(int(start), int(end) + 1))
        else:
            seasons.append(int(part))
    return seasons


def backfill_season(
    fetcher: Fetcher, season: int, *, skip_matches: bool, limit: int | None, force: bool
) -> tuple[int, int]:
    """Returns (matches on results page, match pages fetched or cached)."""
    html = fetcher.get(
        rlp.season_results_url(season),
        rlp.season_results_cache_path(season),
        force=force,
    )
    rows = rlp.parse_season_results(html, season)
    logger.info("season %d: %d matches on results page", season, len(rows))

    if skip_matches:
        return len(rows), 0
    fetched = 0
    for row in rows if limit is None else rows[:limit]:
        fetcher.get(
            rlp.match_url(row.source_key),
            rlp.match_cache_path(row.source_key),
            force=force,
        )
        fetched += 1
    return len(rows), fetched


def backfill_nrl_season(
    fetcher: Fetcher, season: int, *, skip_matches: bool, limit: int | None, force: bool
) -> tuple[int, int]:
    """Fetch every round's draw JSON, then every played match's detail JSON.

    Unplayed fixtures (matchMode != "Post") are skipped: their detail pages
    change until full time, so caching them now would freeze a pre-game
    snapshot. Returns (played fixtures seen, match files fetched or cached).
    """
    first = nrl.parse_draw(
        fetcher.get(nrl.draw_url(season, 1), nrl.draw_cache_path(season, 1), force=force)
    )
    rounds = first.round_numbers or [1]
    logger.info("season %d: rounds %d..%d", season, rounds[0], rounds[-1])

    played: list[nrl.NrlFixture] = []
    for round_number in rounds:
        if round_number == 1:
            page = first
        else:
            page = nrl.parse_draw(
                fetcher.get(
                    nrl.draw_url(season, round_number),
                    nrl.draw_cache_path(season, round_number),
                    force=force,
                )
            )
        played.extend(f for f in page.fixtures if f.is_played)
    logger.info("season %d: %d played fixtures", season, len(played))

    if skip_matches:
        return len(played), 0
    fetched = 0
    for fixture in played if limit is None else played[:limit]:
        fetcher.get(
            nrl.match_data_url(fixture.match_centre_path),
            nrl.match_cache_path(fixture.match_centre_path),
            force=force,
        )
        fetched += 1
    return len(played), fetched


def backfill_nrl_teamlists(
    fetcher: Fetcher, season: int, *, horizon_days: int = 8
) -> tuple[int, int]:
    """Fetch team lists (pre-match match-centre data) for upcoming fixtures.

    Uses the season's cached draw files to find rounds that still have
    unplayed fixtures, force-refetches those draws (kickoffs and match modes
    go stale), and snapshots every Pre fixture kicking off within
    horizon_days. Always force-fetches: team lists change during the week.
    Returns (upcoming fixtures in horizon, team list files fetched).
    """
    draw_dir = fetcher.raw_root / f"nrl/draws/{season}"
    if not draw_dir.exists():
        logger.warning(
            "season %d: no cached draw files — run the nrl backfill first", season
        )
        return 0, 0

    pending_rounds = []
    for draw_file in sorted(draw_dir.glob("round-*.json")):
        page = nrl.parse_draw(draw_file.read_text(encoding="utf-8"))
        if any(not f.is_played for f in page.fixtures):
            pending_rounds.append(int(draw_file.stem.split("-")[1]))

    horizon = datetime.now(timezone.utc) + timedelta(days=horizon_days)
    upcoming = fetched = 0
    for round_number in pending_rounds:
        page = nrl.parse_draw(
            fetcher.get(
                nrl.draw_url(season, round_number),
                nrl.draw_cache_path(season, round_number),
                force=True,
            )
        )
        in_horizon = [
            f
            for f in page.fixtures
            if f.match_mode == "Pre"
            and f.kickoff_utc is not None
            and f.kickoff_utc <= horizon
        ]
        upcoming += len(in_horizon)
        if not in_horizon:
            break  # rounds are chronological; nothing further is in horizon
        for fixture in in_horizon:
            fetcher.get(
                nrl.match_data_url(fixture.match_centre_path),
                nrl.teamlist_cache_path(fixture.match_centre_path),
                force=True,
            )
            fetched += 1
    return upcoming, fetched


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("rlp", "nrl", "nrl-teamlists"),
                        default="rlp")
    parser.add_argument("--seasons", required=True, help='e.g. "2016-2025" or "2025"')
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--skip-matches", action="store_true",
                        help="only fetch season/draw pages")
    parser.add_argument("--limit", type=int, default=None,
                        help="max match pages per season (smoke tests)")
    parser.add_argument("--force", action="store_true",
                        help="refetch even if cached")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.source == "nrl-teamlists":
        fetcher = Fetcher(args.raw_root, headers=nrl.JSON_HEADERS)
        for season in parse_seasons(args.seasons):
            upcoming, fetched = backfill_nrl_teamlists(fetcher, season)
            logger.info("season %d: team lists for %d/%d upcoming fixtures",
                        season, fetched, upcoming)
        return
    if args.source == "nrl":
        fetcher = Fetcher(args.raw_root, headers=nrl.JSON_HEADERS)
        backfill = backfill_nrl_season
    else:
        fetcher = Fetcher(args.raw_root)
        backfill = backfill_season
    for season in parse_seasons(args.seasons):
        total, fetched = backfill(
            fetcher,
            season,
            skip_matches=args.skip_matches,
            limit=args.limit,
            force=args.force,
        )
        logger.info("season %d done: %d/%d match pages in raw store",
                    season, fetched, total)


if __name__ == "__main__":
    main()
