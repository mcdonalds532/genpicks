"""Train the team try-rate model and evaluate the derived try-scorer markets.

Usage:
    python -m genpicks.ml.train_tries

Pipeline: XGBoost Poisson regression for expected team tries (lambda), then
player shares from tries.py, then the derived markets:

    P(anytime, p) = 1 - exp(-lambda_team * share_p)
    P(first, p)   = lambda_team / (lambda_home + lambda_away) * share_p

Evaluated on the held-out test seasons:
- team lambda: Poisson deviance and MAE vs league-mean and rolling-form
  baselines
- anytime try: log loss + reliability vs a position-prior-only baseline
- first try scorer: mean -log P(actual scorer), top-1/top-3 hit rate vs a
  uniform-lineup baseline, on matches with verified try order
"""

import argparse
import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import log_loss
from sqlalchemy import create_engine

from genpicks.config import get_settings
from genpicks.ml.tries import (
    TEAM_FEATURES,
    build_share_dataset,
    build_team_try_dataset,
    load_try_data,
    position_priors,
)
from genpicks.scrape.backfill import parse_seasons

logger = logging.getLogger(__name__)

XGB_PARAMS = {
    "objective": "count:poisson",
    "eval_metric": "poisson-nloglik",
    "max_depth": 2,
    "learning_rate": 0.02,
    "subsample": 0.8,
    "colsample_bytree": 0.9,
    "min_child_weight": 20,
    "reg_lambda": 2.0,
    "seed": 42,
}


def poisson_deviance(y: np.ndarray, mu: np.ndarray) -> float:
    mu = np.clip(mu, 1e-9, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.where(y > 0, y * np.log(y / mu), 0.0)
    return float(2.0 * np.mean(term - (y - mu)))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--train-seasons", default="2016-2021")
    parser.add_argument("--val-seasons", default="2022-2023")
    parser.add_argument("--test-seasons", default="2024-2026")
    parser.add_argument("--out", type=Path, default=Path("data/models"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    train_seasons = set(parse_seasons(args.train_seasons))
    val_seasons = set(parse_seasons(args.val_seasons))
    test_seasons = set(parse_seasons(args.test_seasons))

    engine = create_engine(args.database_url or get_settings().database_url)
    data = load_try_data(engine)
    team_rows = build_team_try_dataset(data)
    logger.info("team try rows: %d", len(team_rows))

    split = {
        "train": team_rows[team_rows["season"].isin(train_seasons)],
        "val": team_rows[team_rows["season"].isin(val_seasons)],
        "test": team_rows[team_rows["season"].isin(test_seasons)],
    }

    def dmatrix(frame, with_label=True):
        return xgb.DMatrix(
            frame[TEAM_FEATURES].astype(float),
            label=frame["tries"].to_numpy() if with_label else None,
            feature_names=TEAM_FEATURES,
        )

    booster = xgb.train(
        XGB_PARAMS,
        dmatrix(split["train"]),
        num_boost_round=4000,
        evals=[(dmatrix(split["val"]), "val")],
        early_stopping_rounds=200,
        verbose_eval=False,
    )
    logger.info("team model best iteration: %d", booster.best_iteration)

    test_team = split["test"].copy()
    test_team["lam"] = booster.predict(
        dmatrix(test_team, with_label=False),
        iteration_range=(0, booster.best_iteration + 1),
    )
    y = test_team["tries"].to_numpy().astype(float)
    league_mean = float(split["train"]["tries"].mean())
    rolling = test_team["tries_for_10"].fillna(league_mean).to_numpy()

    team_report = {
        "model": {
            "deviance": poisson_deviance(y, test_team["lam"].to_numpy()),
            "mae": float(np.abs(y - test_team["lam"]).mean()),
        },
        "league_mean": {
            "deviance": poisson_deviance(y, np.full_like(y, league_mean)),
            "mae": float(np.abs(y - league_mean).mean()),
        },
        "rolling_form_10": {
            "deviance": poisson_deviance(y, rolling),
            "mae": float(np.abs(y - rolling).mean()),
        },
        "n": int(len(y)),
        "league_mean_tries": league_mean,
    }

    # ---- player shares ----------------------------------------------------
    priors, fallback = position_priors(data, train_seasons)
    shares = build_share_dataset(data, priors, fallback)
    lam_by_team = test_team.set_index(["match_id", "team_id"])["lam"].to_dict()

    test_shares = shares[
        shares["match_id"].isin(set(test_team["match_id"]))
    ].copy()
    test_shares["lam"] = [
        lam_by_team.get((m, t), np.nan)
        for m, t in zip(test_shares["match_id"], test_shares["team_id"])
    ]
    test_shares = test_shares[test_shares["lam"].notna()].copy()

    # prior-only baseline uses the same lambda but position priors as shares,
    # renormalised within each lineup
    prior_total = test_shares.groupby(["match_id", "team_id"])["prior"].transform("sum")
    test_shares["share_prior_only"] = test_shares["prior"] / prior_total

    y_any = test_shares["scored_anytime"].to_numpy().astype(int)
    p_model = 1.0 - np.exp(-test_shares["lam"] * test_shares["share"])
    p_prior = 1.0 - np.exp(-test_shares["lam"] * test_shares["share_prior_only"])
    anytime_report = {
        "model": {"log_loss": float(log_loss(y_any, p_model)),
                  "base_rate": float(y_any.mean()), "n": int(len(y_any))},
        "position_prior_only": {"log_loss": float(log_loss(y_any, p_prior))},
        "reliability": [
            {
                "bin": f"{lo:.2f}-{hi:.2f}",
                "n": int(mask.sum()),
                "predicted": float(p_model[mask].mean()),
                "actual": float(y_any[mask].mean()),
            }
            for lo, hi in [(0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4),
                           (0.4, 0.5), (0.5, 1.0)]
            if (mask := (p_model >= lo) & (p_model < hi)).sum() >= 30
        ],
    }

    # ---- first try scorer --------------------------------------------------
    lam_sum = test_team.groupby("match_id")["lam"].sum().to_dict()
    test_shares["p_first"] = (
        test_shares["lam"] / test_shares["match_id"].map(lam_sum)
    ) * test_shares["share"]

    hits1 = hits3 = 0
    logs_model, logs_uniform = [], []
    for match_id, group in test_shares.groupby("match_id"):
        actual = data.first_scorers.get(match_id)
        if actual is None or actual not in set(group["player_id"]):
            continue
        probs = group.set_index("player_id")["p_first"]
        probs = probs / probs.sum()  # condition on someone scoring first
        ranked = probs.sort_values(ascending=False)
        hits1 += int(ranked.index[0] == actual)
        hits3 += int(actual in ranked.index[:3])
        logs_model.append(-np.log(max(probs[actual], 1e-9)))
        logs_uniform.append(-np.log(1.0 / len(group)))
    n_first = len(logs_model)
    first_report = {
        "n_matches": n_first,
        "model": {
            "mean_neg_log_prob": float(np.mean(logs_model)),
            "top1_hit_rate": hits1 / n_first,
            "top3_hit_rate": hits3 / n_first,
        },
        "uniform_lineup": {
            "mean_neg_log_prob": float(np.mean(logs_uniform)),
            "top1_expected": float(np.mean([1 / 34])),
        },
    }

    report = {
        "model_version": f"try_scorer_v0.1_{date.today():%Y%m%d}",
        "splits": {"train": sorted(train_seasons), "val": sorted(val_seasons),
                   "test": sorted(test_seasons)},
        "team_try_rate_test": team_report,
        "anytime_try_test": anytime_report,
        "first_try_test": first_report,
        "position_priors": {k: round(v, 4) for k, v in sorted(
            priors.items(), key=lambda kv: -kv[1])},
        "feature_importance_gain": {
            k: round(v, 2)
            for k, v in sorted(
                booster.get_score(importance_type="gain").items(),
                key=lambda kv: -kv[1],
            )
        },
    }

    out_dir = args.out / report["model_version"]
    out_dir.mkdir(parents=True, exist_ok=True)
    booster.save_model(out_dir / "team_try_model.json")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("saved to %s", out_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
