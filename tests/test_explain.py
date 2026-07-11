"""Factor grouping: every feature accounted for, arithmetic honest."""

import numpy as np
import pytest

from genpicks.ml.explain import FACTOR_GROUPS, build_explanation
from genpicks.ml.features import FEATURE_COLUMNS


def test_factor_groups_cover_feature_columns_exactly():
    grouped = [name for _, _, names in FACTOR_GROUPS for name in names]
    assert sorted(grouped) == sorted(FEATURE_COLUMNS)
    assert len(grouped) == len(set(grouped))  # no feature in two groups


def test_build_explanation_groups_and_ranks():
    features = ["elo_expected_home", "elo_diff", "rest_days_diff"]
    groups = [g for g in FACTOR_GROUPS if g[0] in ("strength", "rest")]
    # strength: 0.3 + 0.2 = 0.5 toward home; rest: -0.25 toward away; bias 0.4
    contribs = np.array([0.3, 0.2, -0.25, 0.4])
    payload = build_explanation(features, contribs, groups=groups)

    assert payload["bias"] == pytest.approx(0.4)
    strength, rest = payload["factors"]  # sorted by |logit|
    assert strength["factor"] == "strength"
    assert strength["logit"] == pytest.approx(0.5)
    assert strength["share"] == pytest.approx(0.5 / 0.75, abs=1e-3)
    assert rest["logit"] == pytest.approx(-0.25)
    assert sum(f["share"] for f in payload["factors"]) == pytest.approx(1.0)


def test_build_explanation_rejects_ungrouped_features():
    features = FEATURE_COLUMNS + ["mystery_feature"]
    contribs = np.zeros(len(features) + 1)
    with pytest.raises(ValueError, match="mystery_feature"):
        build_explanation(features, contribs)


def test_build_explanation_full_feature_set_round_trip():
    rng = np.random.default_rng(3)
    contribs = rng.normal(size=len(FEATURE_COLUMNS) + 1)
    payload = build_explanation(FEATURE_COLUMNS, contribs)
    assert len(payload["factors"]) == len(FACTOR_GROUPS)
    total_logit = sum(f["logit"] for f in payload["factors"]) + payload["bias"]
    assert total_logit == pytest.approx(float(contribs.sum()), abs=1e-3)
