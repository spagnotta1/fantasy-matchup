"""Prediction engine.

Transforms the feature layer's output into weekly projections. Its boundaries,
which the rest of the system depends on:

* it reads ``feat_training_dataset`` and nothing below it — no ``raw_*``, no
  provider calls, no snapshot joins;
* it predicts **components**, and points are derived by the same
  :class:`~nflfp.scoring.ScoringRules` that scored the training targets, so one
  model serves every league format and training and inference cannot disagree
  about what a point is;
* it runs offline. The API reads projections it has already written and never
  invokes a model in a request.

**Phase 3b is frozen.** ``shrinkage_eb`` is the validated foundation the rest of
the application is built on, and :mod:`nflfp.predict.foundation` records what it
was measured to do — interval coverage, calibration error, conditional bias —
along with the criteria a successor must clear on the same walk-forward harness.
Registering a new model is encouraged; replacing the foundation means re-earning
those numbers, not merely passing the tests.
"""

from __future__ import annotations

from .backtest import BacktestResult, Prediction, compare, run_backtest
from .base import POSITIONS, ComponentPrediction, Model
from .dataset import Split, assert_no_leakage, load_rows, split_by_position, walk_forward
from .calibration import (
    calibration_report,
    expected_calibration_error,
    max_calibration_error,
    weighted_calibration_error,
)
from .distribution import PointDistribution, ResidualDistribution, crps, pinball_loss
from .features import AVAILABLE_FEATURES, FEATURE_VERSION, assert_available
from .foundation import (
    ACCEPTANCE,
    FROZEN_MODEL,
    VALIDATION,
    foundation_summary,
    meets_acceptance,
)
from .registry import MODELS, available, get_model_factory
from .scoring_bridge import actual_components, score_components

__all__ = [
    "ACCEPTANCE",
    "FROZEN_MODEL",
    "VALIDATION",
    "foundation_summary",
    "meets_acceptance",
    "BacktestResult",
    "ComponentPrediction",
    "MODELS",
    "Model",
    "POSITIONS",
    "PointDistribution",
    "ResidualDistribution",
    "Split",
    "actual_components",
    "assert_no_leakage",
    "available",
    "AVAILABLE_FEATURES",
    "FEATURE_VERSION",
    "assert_available",
    "calibration_report",
    "crps",
    "max_calibration_error",
    "pinball_loss",
    "weighted_calibration_error",
    "compare",
    "Prediction",
    "expected_calibration_error",
    "get_model_factory",
    "load_rows",
    "run_backtest",
    "score_components",
    "split_by_position",
    "walk_forward",
]
