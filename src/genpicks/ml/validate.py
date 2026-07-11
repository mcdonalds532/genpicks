"""Walk-forward (rolling-origin) validation of the match-winner model.

Usage:
    python -m genpicks.ml.validate
    python -m genpicks.ml.validate --eval-seasons 2022-2026 --out data/models/walkforward.json

The published artifact is trained once on a fixed split, which leaves a fair
question open: was that one split lucky? This answers it by refitting the
model once per evaluated season using only information available before it —
boost on seasons up to S-2, early-stop and Platt-calibrate on season S-1,
score season S out of sample — exactly the procedure a yearly retrain would
follow in production. fit_fold is shared with train.py, so a season's
walk-forward number and the artifact's test number differ only in what data
the model saw, never in how it was trained.

Reports per-season and pooled metrics against the same de-vigged closing-odds
benchmark train.py uses, plus the Elo-only baseline. Also the gate for new
features: run once on main, once on the candidate, compare pooled log loss.
"""

import argparse
import json
import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

from genpicks.config import get_settings
from genpicks.ml.features import FEATURE_COLUMNS, build_match_dataset
from genpicks.ml.train import fit_fold, load_closing_probs, metrics
from genpicks.scrape.backfill import parse_seasons

logger = logging.getLogger(__name__)


def walk_forward(
    data: pd.DataFrame,
    eval_seasons: list[int],
    feature_columns: list[str] = FEATURE_COLUMNS,
) -> pd.DataFrame:
    """Out-of-sample calibrated probabilities for every eval-season match.

    Returns the eval rows of `data` with columns p_model (calibrated) and
    fold_best_iteration added. Raises if an eval season lacks at least two
    earlier seasons (one to boost on, one to calibrate on).
    """
    scored = []
    for season in sorted(eval_seasons):
        train = data[data["season"] <= season - 2]
        val = data[data["season"] == season - 1]
        test = data[data["season"] == season].copy()
        if train.empty or val.empty:
            raise ValueError(f"season {season} lacks history: need seasons <= {season - 1}")
        if test.empty:
            logger.warning("season %d: no decided matches, skipping", season)
            continue
        fold = fit_fold(train, val, test, feature_columns)
        test["p_model"] = fold["test_prob"]
        test["fold_best_iteration"] = fold["best_iteration"]
        scored.append(test)
        logger.info(
            "season %d: trained on %d (<=%d), calibrated on %d (%d), scored %d",
            season,
            len(train),
            season - 2,
            len(val),
            season - 1,
            len(test),
        )
    return pd.concat(scored, ignore_index=True)


def evaluate(scored: pd.DataFrame, market: pd.DataFrame) -> dict:
    """Per-season and pooled metrics for walk-forward output vs the market."""
    scored = scored.merge(market, on="match_id", how="left")

    def block(frame: pd.DataFrame) -> dict:
        y = frame["home_win"].to_numpy()
        with_market = frame[frame["market_home_prob"].notna()]
        y_market = with_market["home_win"].to_numpy()
        market_block: dict = {"n": int(len(with_market))}
        if len(with_market):  # a season can lack odds coverage entirely
            market_block["model"] = metrics(y_market, with_market["p_model"].to_numpy())
            market_block["market_closing"] = metrics(
                y_market, with_market["market_home_prob"].to_numpy()
            )
        return {
            "all": {
                "model": metrics(y, frame["p_model"].to_numpy()),
                "elo_only": metrics(y, frame["elo_expected_home"].to_numpy()),
            },
            "with_market_odds": market_block,
        }

    return {
        "pooled": block(scored),
        "per_season": {
            int(season): block(frame) for season, frame in scored.groupby("season")
        },
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--eval-seasons", default="2022-2026")
    parser.add_argument("--out", type=Path, default=None, help="also write the report as JSON")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    engine = create_engine(args.database_url or get_settings().database_url)
    data = build_match_dataset(engine)
    data = data[data["home_win"].notna()].copy()
    data["home_win"] = data["home_win"].astype(int)

    eval_seasons = parse_seasons(args.eval_seasons)
    scored = walk_forward(data, eval_seasons)
    market = load_closing_probs(engine, scored["match_id"].tolist())

    report = {
        "eval_seasons": sorted(eval_seasons),
        "feature_columns": FEATURE_COLUMNS,
        "folds_best_iteration": {
            int(season): int(frame["fold_best_iteration"].iloc[0])
            for season, frame in scored.groupby("season")
        },
    }
    report.update(evaluate(scored, market))

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("wrote %s", args.out)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
