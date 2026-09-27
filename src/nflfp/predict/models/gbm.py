"""Gradient-boosted component projections: the first challenger to 3b.

Why this model
--------------
``shrinkage_eb`` projects each component as a shrunk trailing average. It uses
two things about a player — their recent level and how much of it to trust —
and nothing about the game in front of them. The feature layer already carries
more: snap and target share with their trends, opponent strength against the
position, pace, rest, home field. A gradient booster is the obvious way to ask
whether that information is worth anything *in component space*, and README
"Where this goes next" names it as the next comparison.

It is a challenger, not a replacement. It is promoted only if it clears
:data:`~nflfp.predict.foundation.ACCEPTANCE` on the same walk-forward harness
over the same seasons — see ``scripts/challenger_eval.py``. Until then it is
registered, backtestable and unpublished.

Design choices, fixed before evaluation
---------------------------------------
Every choice below was made before the first backtest and is not tuned against
the evaluation seasons. Tuning hyperparameters on 2019-2025 and then reporting
2019-2025 would be selection on the test set — the walk-forward harness would
still be honest fold by fold, but the model would not be.

* **One regressor per component, all positions pooled**, with position as
  one-hot columns. Pooling gives the rare components (a receiving TD for a QB)
  enough rows to fit; the trees split on position where it matters.
* **Poisson loss for counts** (touchdowns, receptions, interceptions, fumbles),
  **squared error for yards** (which can be negative). Both estimate the
  conditional *mean*, which is what the scoring bridge needs: points are linear
  in components, so the mean of the points is the points of the means.
* **Only :data:`~nflfp.predict.features.AVAILABLE_FEATURES`.** The contract is
  enforced in ``__post_init__`` exactly as it is for the frozen model.
* **Missing values stay missing.** A player with no history gets NaN usage
  features, and LightGBM routes NaN down a learned branch. That is a better
  cold start than a zero, which would read as "played and did nothing".
* **Deterministic.** ``deterministic=True``, a fixed thread count and fixed
  seeds, so the same training rows produce the same projections — the
  :class:`~nflfp.predict.base.Model` contract, and the reason a backtest can be
  run twice and compared.

The distribution is not this module's job. The backtest wraps whatever this
returns in the same held-out residual distribution it gives every model, so the
booster's intervals and boom probabilities are judged by exactly the machinery
that judged the incumbent's.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import lightgbm
import numpy as np

from ..base import POSITIONS, ComponentPrediction, FeatureRow, empty_components
from ..features import AVAILABLE_FEATURES, FEATURE_VERSION, assert_available
from ..scoring_bridge import COMPONENT_TO_COLUMN
from .shrinkage import MODELLED_COMPONENTS

logger = logging.getLogger(__name__)

#: Components scored as counts, fitted with a Poisson objective. Everything
#: else in MODELLED_COMPONENTS is a yardage total.
COUNT_COMPONENTS = frozenset(
    {
        "passing_tds",
        "passing_interceptions",
        "rushing_tds",
        "receptions",
        "receiving_tds",
        "fumbles_lost_total",
    }
)

#: Hyperparameters. Chosen a priori (see module docstring) — conservative
#: settings for ~60k noisy rows: shallow trees, a large minimum leaf, and row
#: and column subsampling. Seeds and threads are pinned for determinism.
HYPERPARAMETERS: dict[str, object] = {
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 200,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "feature_fraction": 0.8,
    "lambda_l2": 1.0,
    "seed": 20260926,
    "num_threads": 4,
    "deterministic": True,
    "force_row_wise": True,
    "verbose": -1,
}

#: Boosting rounds. Fixed, not early-stopped: early stopping needs a validation
#: split, and carving one out of each fold would be a second place for the
#: temporal boundary to be got wrong.
BOOSTING_ROUNDS = 300


def _as_float(value: object) -> float:
    """A feature value as a float, with NULL as NaN rather than zero."""
    if value is None:
        return math.nan
    if isinstance(value, (bool, int, float, Decimal)):
        return float(value)
    raise TypeError(f"unexpected feature value {value!r}")


@dataclass
class LightGBMComponents:
    """Per-component gradient boosting over the full available feature set."""

    name: str = "lightgbm_components"
    version: str = "1.0.0"
    algorithm: str = "lightgbm"
    required_features: tuple[str, ...] = AVAILABLE_FEATURES
    _models: dict[str, lightgbm.Booster] = field(default_factory=dict)
    _trained_rows: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert_available(self.required_features)

    # -- design matrix -----------------------------------------------------

    def _matrix(self, rows: Sequence[FeatureRow]) -> np.ndarray:
        """Features in a fixed column order, then one-hot position."""
        width = len(self.required_features) + len(POSITIONS)
        matrix = np.empty((len(rows), width), dtype=np.float64)
        for i, row in enumerate(rows):
            for j, name in enumerate(self.required_features):
                matrix[i, j] = _as_float(row.get(name))
            position = str(row["position"])
            for k, candidate in enumerate(POSITIONS):
                matrix[i, len(self.required_features) + k] = float(position == candidate)
        return matrix

    @property
    def _column_names(self) -> list[str]:
        return [*self.required_features, *(f"position_{p}" for p in POSITIONS)]

    # -- training ----------------------------------------------------------

    def fit(self, rows: Sequence[FeatureRow]) -> None:
        matrix = self._matrix(rows)
        self._models = {}
        self._trained_rows = {}
        for component in MODELLED_COMPONENTS:
            column = f"{COMPONENT_TO_COLUMN[component]}_actual"
            targets = np.array([_as_float(row.get(column)) for row in rows])
            known = ~np.isnan(targets)
            if known.sum() < 1000:
                # Too little to fit; predict() falls back to 0.0, the same
                # thing the frozen model does for a component it cannot fit.
                logger.warning("skipping %s: %d labelled row(s)", component, int(known.sum()))
                continue

            objective = "poisson" if component in COUNT_COMPONENTS else "regression"
            target = targets[known]
            if objective == "poisson":
                # Poisson needs non-negative labels. Counts are, by definition;
                # this only guards against a corrupt row.
                target = np.clip(target, 0.0, None)

            dataset = lightgbm.Dataset(
                matrix[known], label=target, feature_name=self._column_names,
                free_raw_data=True,
            )
            self._models[component] = lightgbm.train(
                {**HYPERPARAMETERS, "objective": objective},
                dataset,
                num_boost_round=BOOSTING_ROUNDS,
            )
            self._trained_rows[component] = int(known.sum())

        logger.info(
            "fitted %d component model(s) on %d row(s)", len(self._models), len(rows)
        )

    # -- inference ---------------------------------------------------------

    def predict(self, rows: Sequence[FeatureRow]) -> list[ComponentPrediction]:
        if not rows:
            return []
        matrix = self._matrix(rows)
        by_component = {
            component: model.predict(matrix)
            for component, model in self._models.items()
        }

        predictions = []
        for i, row in enumerate(rows):
            components = empty_components()
            for component, values in by_component.items():
                components[component] = float(values[i])
            has_history = row.get("fp_half_ppr_l4") is not None
            predictions.append(
                ComponentPrediction(
                    player_id=str(row["player_id"]),
                    season=int(row["season"]),
                    week=int(row["week"]),
                    position=str(row["position"]),
                    components=components,
                    explain={
                        # Not "positional_prior": with no history the booster
                        # still reads schedule and opponent columns, so saying
                        # the projection is a prior would be untrue.
                        "source": "history" if has_history else "no_history",
                        # 0.0 rather than NaN: `explain` is persisted as JSON,
                        # and NaN is not valid JSON.
                        "games_in_window": float(row.get("games_in_window_l4") or 0),
                        "feature_version": FEATURE_VERSION,
                    },
                )
            )
        return predictions

    def params(self) -> dict:
        return {
            "method": "lightgbm_per_component",
            "lightgbm_version": lightgbm.__version__,
            "hyperparameters": HYPERPARAMETERS,
            "boosting_rounds": BOOSTING_ROUNDS,
            "objectives": {
                component: "poisson" if component in COUNT_COMPONENTS else "regression"
                for component in MODELLED_COMPONENTS
            },
            "features": self._column_names,
            "feature_version": FEATURE_VERSION,
            "trained_rows": dict(sorted(self._trained_rows.items())),
        }
