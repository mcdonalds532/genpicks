"""Train and evaluate the match-winner model.

Usage:
    python -m genpicks.ml.train
    python -m genpicks.ml.train --test-seasons 2024-2026

Time-based split (never shuffled): train on the earliest seasons, use the
validation seasons for early stopping and isotonic calibration, hold out the
most recent seasons as the test set. Draws are dropped (a handful per
season) and the target is P(home win).

The report benchmarks against the aussportsbetting closing odds, de-vigged
two-way: implied_home = (1/home) / (1/home + 1/away). Market comparison
rows are restricted to test matches that have closing odds.
"""

import argparse
import json
import logging
from datetime import date
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from genpicks.config import get_settings
from genpicks.db.models import MARKET_H2H, Match, OddsSnapshot
from genpicks.ml.features import FEATURE_COLUMNS, build_match_dataset
from genpicks.scrape.backfill import parse_seasons

logger = logging.getLogger(__name__)

XGB_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "max_depth": 2,
    "learning_rate": 0.02,
    "subsample": 0.8,
    "colsample_bytree": 0.9,
    "min_child_weight": 20,
    "reg_lambda": 2.0,
    "seed": 42,
}
NUM_ROUNDS = 4000
EARLY_STOPPING = 200


def load_closing_probs(engine, match_ids: list[int]) -> pd.DataFrame:
    """De-vigged two-way implied home probability per match from ASB closes."""
    with Session(engine) as session:
        rows = session.execute(
            select(
                OddsSnapshot.match_id,
                OddsSnapshot.team_id,
                OddsSnapshot.price_decimal,
                Match.home_team_id,
            )
            .join(Match, Match.id == OddsSnapshot.match_id)
            .where(
                OddsSnapshot.source == "asb",
                OddsSnapshot.market == MARKET_H2H,
                OddsSnapshot.team_id.is_not(None),
                OddsSnapshot.match_id.in_(match_ids),
            )
        ).all()
    prices: dict[int, dict[str, float]] = {}
    for match_id, team_id, price, home_team_id in rows:
        side = "home" if team_id == home_team_id else "away"
        prices.setdefault(match_id, {})[side] = float(price)
    records = [
        {
            "match_id": match_id,
            "market_home_prob": (1 / p["home"]) / (1 / p["home"] + 1 / p["away"]),
        }
        for match_id, p in prices.items()
        if "home" in p and "away" in p and p["home"] > 1 and p["away"] > 1
    ]
    return pd.DataFrame(records)


def metrics(y_true: np.ndarray, prob: np.ndarray) -> dict:
    return {
        "log_loss": float(log_loss(y_true, prob, labels=[0, 1])),
        "brier": float(brier_score_loss(y_true, prob)),
        "accuracy": float(((prob > 0.5) == y_true).mean()),
        "n": int(len(y_true)),
    }


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def fit_fold(
    train: pd.DataFrame,
    val: pd.DataFrame,
    test: pd.DataFrame,
    feature_columns: list[str] = FEATURE_COLUMNS,
) -> dict:
    """Boost on train, early-stop + Platt-calibrate on val, score test.

    The one training procedure, shared by the artifact build (fixed split)
    and walk-forward validation so their numbers are comparable by
    construction. Returns the booster, calibrator params, and calibrated
    test probabilities aligned with test's row order.
    """

    def xy(frame):
        return frame[feature_columns].astype(float), frame["home_win"].to_numpy()

    x_train, y_train = xy(train)
    x_val, y_val = xy(val)

    dtrain = xgb.DMatrix(x_train, label=y_train, feature_names=feature_columns)
    dval = xgb.DMatrix(x_val, label=y_val, feature_names=feature_columns)
    dtest = xgb.DMatrix(test[feature_columns].astype(float), feature_names=feature_columns)

    booster = xgb.train(
        XGB_PARAMS,
        dtrain,
        num_boost_round=NUM_ROUNDS,
        evals=[(dtrain, "train"), (dval, "val")],
        early_stopping_rounds=EARLY_STOPPING,
        verbose_eval=False,
    )
    iteration_range = (0, booster.best_iteration + 1)
    val_prob = booster.predict(dval, iteration_range=iteration_range)
    test_prob = booster.predict(dtest, iteration_range=iteration_range)

    # Platt scaling on the validation set: isotonic needs more than ~400
    # points to help (first run it cost 0.035 log loss); a two-parameter
    # sigmoid on the logit cannot overfit that way.
    calibrator = LogisticRegression(C=1e6)
    calibrator.fit(_logit(val_prob), y_val)
    test_prob_cal = calibrator.predict_proba(_logit(test_prob))[:, 1]

    return {
        "booster": booster,
        "best_iteration": int(booster.best_iteration),
        "platt": {
            "coef": float(calibrator.coef_[0][0]),
            "intercept": float(calibrator.intercept_[0]),
        },
        "test_prob_raw": test_prob,
        "test_prob": test_prob_cal,
    }


def calibration_table(y_true: np.ndarray, prob: np.ndarray, bins: int = 10) -> list:
    table = []
    edges = np.linspace(0, 1, bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (prob >= lo) & (prob < hi if hi < 1 else prob <= hi)
        if mask.sum() >= 10:
            table.append(
                {
                    "bin": f"{lo:.1f}-{hi:.1f}",
                    "n": int(mask.sum()),
                    "predicted": float(prob[mask].mean()),
                    "actual": float(y_true[mask].mean()),
                }
            )
    return table


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--train-seasons", default="2016-2021")
    parser.add_argument("--val-seasons", default="2022-2023")
    parser.add_argument("--test-seasons", default="2024-2026")
    parser.add_argument("--out", type=Path, default=Path("data/models"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    engine = create_engine(args.database_url or get_settings().database_url)
    data = build_match_dataset(engine)
    data = data[data["home_win"].notna()].copy()
    data["home_win"] = data["home_win"].astype(int)
    logger.info("dataset: %d decided matches, %d features", len(data), len(FEATURE_COLUMNS))

    splits = {
        name: data[data["season"].isin(parse_seasons(spec))]
        for name, spec in (
            ("train", args.train_seasons),
            ("val", args.val_seasons),
            ("test", args.test_seasons),
        )
    }
    for name, frame in splits.items():
        logger.info("%s: %d matches (%s)", name, len(frame), sorted(frame["season"].unique()))

    fold = fit_fold(splits["train"], splits["val"], splits["test"])
    booster = fold["booster"]
    logger.info("best iteration: %d", fold["best_iteration"])

    y_train = splits["train"]["home_win"].to_numpy()
    y_test = splits["test"]["home_win"].to_numpy()
    test_prob = fold["test_prob_raw"]
    test_prob_cal = fold["test_prob"]

    test = splits["test"].copy()
    test["model_prob"] = test_prob
    test["model_prob_cal"] = test_prob_cal

    market = load_closing_probs(engine, test["match_id"].tolist())
    with_market = test.merge(market, on="match_id", how="inner")
    y_market = with_market["home_win"].to_numpy()

    report = {
        "model_version": f"match_winner_v0.1_{date.today():%Y%m%d}",
        "splits": {k: sorted(int(s) for s in v["season"].unique()) for k, v in splits.items()},
        "best_iteration": fold["best_iteration"],
        "test_all": {
            "model_raw": metrics(y_test, test_prob),
            "model_calibrated": metrics(y_test, test_prob_cal),
            "elo_only": metrics(y_test, splits["test"]["elo_expected_home"].to_numpy()),
            "always_home_0.58": metrics(y_test, np.full(len(y_test), y_train.mean())),
        },
        "test_with_market_odds": {
            "n": int(len(with_market)),
            "model_calibrated": metrics(y_market, with_market["model_prob_cal"].to_numpy()),
            "market_closing": metrics(y_market, with_market["market_home_prob"].to_numpy()),
        },
        "calibration_test": calibration_table(y_test, test_prob_cal),
        "feature_importance_gain": {
            k: round(v, 2)
            for k, v in sorted(
                cast(dict[str, float], booster.get_score(importance_type="gain")).items(),
                key=lambda kv: -kv[1],
            )
        },
    }

    out_dir = args.out / report["model_version"]
    out_dir.mkdir(parents=True, exist_ok=True)
    booster.save_model(out_dir / "model.json")
    report["calibrator_platt"] = fold["platt"]
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("saved model + report to %s", out_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
