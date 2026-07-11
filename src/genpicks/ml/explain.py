"""Group per-feature SHAP contributions into named, human-readable factors.

XGBoost's pred_contribs gives one log-odds contribution per feature plus a
bias term. Individual features are too granular to show a reader (five form
columns say one thing), so they are summed into stable factor groups here at
generation time and stored on the prediction row — the API serves, never
computes.

Contributions live in the raw model's logit space. Platt calibration scales
every contribution by the same positive coefficient, so the signs and the
relative shares shown to the reader are unaffected by it.

The payload on the h2h home-team row:

    {"factors": [{"factor": "strength", "label": "Team strength",
                  "logit": 0.41, "share": 0.55}, ...],   # sorted, all groups
     "bias": 0.33}

Positive logit pushes toward the home side, negative toward the away side;
share is the factor's fraction of total absolute contribution.
"""

from typing import Any

import numpy as np

# Every FEATURE_COLUMNS entry must belong to exactly one group — the test
# suite fails the build otherwise, so a new feature can't silently ship
# without a place in the story.
FACTOR_GROUPS: list[tuple[str, str, list[str]]] = [
    ("strength", "Team strength", ["elo_expected_home", "elo_diff"]),
    (
        "form",
        "Recent form",
        [
            "season_win_rate_diff",
            "win_rate_5_diff",
            "win_rate_10_diff",
            "margin_5_diff",
            "margin_10_diff",
            "points_for_5_diff",
            "points_against_5_diff",
        ],
    ),
    ("rest", "Rest advantage", ["rest_days_diff"]),
    ("stage", "Season stage", ["round_number", "home_games_played"]),
    ("travel", "Travel and venue", ["travel_km_diff", "home_at_home"]),
    (
        "availability",
        "Lineup availability",
        ["returning_share_diff", "regulars_available_diff"],
    ),
]


def build_explanation(
    feature_names: list[str],
    contribs: np.ndarray,
    groups: list[tuple[str, str, list[str]]] | None = None,
) -> dict:
    """One match's contribution row (features + trailing bias) -> payload."""
    by_feature = dict(zip(feature_names, (float(c) for c in contribs[:-1]), strict=True))
    factors: list[dict[str, Any]] = [
        {
            "factor": key,
            "label": label,
            "logit": round(sum(by_feature.pop(name) for name in names), 4),
        }
        for key, label, names in (groups if groups is not None else FACTOR_GROUPS)
    ]
    if by_feature:
        raise ValueError(f"features without a factor group: {sorted(by_feature)}")
    total = sum(abs(f["logit"]) for f in factors) or 1.0
    for factor in factors:
        factor["share"] = round(abs(factor["logit"]) / total, 4)
    factors.sort(key=lambda f: -abs(f["logit"]))
    return {"factors": factors, "bias": round(float(contribs[-1]), 4)}
