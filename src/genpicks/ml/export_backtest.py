"""Export the held-out backtest as static JSON for the track-record page.

Usage:
    python -m genpicks.ml.export_backtest
    python -m genpicks.ml.export_backtest --out web/src/data/backtest.json

Replays the exact evaluation train.py ran on the held-out test seasons —
same saved booster, same Platt calibration from report.json, same de-vigged
closing-odds benchmark — but keeps the per-match rows instead of collapsing
them to aggregates, so the frontend can draw cumulative log loss over time
and a calibration plot without a database round trip. The backtest only
changes on retrain, so the JSON is committed next to the model artifacts.

Refuses to write unless its aggregate log losses reproduce report.json to
four decimals: the published chart can never drift from the published model.
"""

import argparse
import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from genpicks.config import get_settings
from genpicks.db.models import Team
from genpicks.ml.features import FEATURE_COLUMNS, build_match_dataset
from genpicks.ml.predict import latest_model_dir
from genpicks.ml.train import load_closing_probs

logger = logging.getLogger(__name__)


def log_loss_mean(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def build_rows(engine, model_dir: Path) -> tuple[dict, pd.DataFrame]:
    report = json.loads((model_dir / "report.json").read_text(encoding="utf-8"))
    booster = xgb.Booster()
    booster.load_model(model_dir / "model.json")
    platt = report["calibrator_platt"]

    data = build_match_dataset(engine)
    test = data[data["season"].isin(report["splits"]["test"]) & data["home_win"].notna()].copy()
    test = test.sort_values(["match_date", "match_id"])

    raw = booster.predict(
        xgb.DMatrix(test[FEATURE_COLUMNS].astype(float), feature_names=FEATURE_COLUMNS),
        iteration_range=(0, report["best_iteration"] + 1),
    )
    clipped = np.clip(raw, 1e-6, 1 - 1e-6)
    logit = np.log(clipped / (1 - clipped))
    test["p_model"] = 1.0 / (1.0 + np.exp(-(platt["coef"] * logit + platt["intercept"])))

    market = load_closing_probs(engine, test["match_id"].tolist())
    test = test.merge(market, on="match_id", how="left")
    return report, test


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--models-root", type=Path, default=Path("data/models"))
    parser.add_argument("--out", type=Path, default=Path("web/src/data/backtest.json"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    engine = create_engine(args.database_url or get_settings().database_url)
    model_dir = latest_model_dir(args.models_root, "match_winner_")
    report, test = build_rows(engine, model_dir)

    with Session(engine) as session:
        team_names = dict(session.execute(select(Team.id, Team.name)).tuples().all())

    y = test["home_win"].astype(int).to_numpy()
    with_market = test[test["market_home_prob"].notna()]
    reproduced = {
        "model": log_loss_mean(y, test["p_model"].to_numpy()),
        "market": log_loss_mean(
            with_market["home_win"].astype(int).to_numpy(),
            with_market["market_home_prob"].to_numpy(),
        ),
    }
    published = {
        "model": report["test_all"]["model_calibrated"]["log_loss"],
        "market": report["test_with_market_odds"]["market_closing"]["log_loss"],
    }
    for key, value in reproduced.items():
        if not math.isclose(value, published[key], abs_tol=5e-5):
            raise SystemExit(
                f"{key} log loss {value:.6f} does not reproduce report.json "
                f"{published[key]:.6f} — refusing to export a chart that "
                "disagrees with the published model"
            )
    logger.info(
        "reproduced report.json: model %.4f, market %.4f over %d matches",
        reproduced["model"],
        reproduced["market"],
        len(test),
    )

    payload = {
        "model_version": report["model_version"],
        "splits": report["splits"],
        "matches": [
            {
                "date": row.match_date.isoformat(),
                "season": int(row.season),
                "home": team_names.get(row.home_team_id),
                "away": team_names.get(row.away_team_id),
                "p_model": round(float(row.p_model), 4),
                "p_market": (
                    None if pd.isna(row.market_home_prob) else round(float(row.market_home_prob), 4)
                ),
                "home_win": int(row.home_win),
            }
            for row in test.itertuples()
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    logger.info("wrote %d matches to %s", len(payload["matches"]), args.out)


if __name__ == "__main__":
    main()
