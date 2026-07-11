"""Walk-forward harness tests: fold boundaries and out-of-sample discipline."""

import numpy as np
import pandas as pd
import pytest

from genpicks.ml.validate import evaluate, walk_forward

FEATURES = ["f1", "f2"]


def synthetic_seasons(seasons: list[int], per_season: int = 30) -> pd.DataFrame:
    """f1 drives the outcome, f2 is noise — enough signal to fit on."""
    rng = np.random.default_rng(7)
    rows = []
    match_id = 0
    for season in seasons:
        for _ in range(per_season):
            f1 = rng.normal()
            rows.append(
                {
                    "match_id": (match_id := match_id + 1),
                    "season": season,
                    "f1": f1,
                    "f2": rng.normal(),
                    "home_win": int(rng.random() < 1 / (1 + np.exp(-2 * f1))),
                    "elo_expected_home": 0.58,
                }
            )
    return pd.DataFrame(rows)


def test_walk_forward_scores_only_eval_seasons():
    data = synthetic_seasons([2019, 2020, 2021, 2022])
    scored = walk_forward(data, [2021, 2022], feature_columns=FEATURES)
    assert sorted(scored["season"].unique()) == [2021, 2022]
    assert len(scored) == 60
    assert scored["p_model"].between(0, 1).all()
    # each fold trained: best_iteration recorded per season
    assert set(scored["fold_best_iteration"].groupby(scored["season"]).nunique()) == {1}


def test_walk_forward_requires_two_prior_seasons():
    data = synthetic_seasons([2020, 2021])
    with pytest.raises(ValueError, match="lacks history"):
        walk_forward(data, [2021], feature_columns=FEATURES)


def test_evaluate_pools_and_splits_by_season():
    data = synthetic_seasons([2019, 2020, 2021, 2022])
    scored = walk_forward(data, [2021, 2022], feature_columns=FEATURES)
    market = pd.DataFrame(
        {"match_id": scored["match_id"].iloc[:10], "market_home_prob": [0.6] * 10}
    )
    report = evaluate(scored, market)
    assert report["pooled"]["all"]["model"]["n"] == 60
    assert report["pooled"]["with_market_odds"]["n"] == 10
    assert set(report["per_season"]) == {2021, 2022}
    # a fold must never see its own season: pooled log loss is finite and sane
    assert 0 < report["pooled"]["all"]["model"]["log_loss"] < 2
