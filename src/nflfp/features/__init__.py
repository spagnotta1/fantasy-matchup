"""Feature engineering.

The layer between the ETL and the prediction engine. Its job is to turn
warehouse rows into a clean, model-ready dataset so that feature logic lives
here — versioned, documented, tested, and shared by training and inference —
rather than inside model code where it silently forks between the two.

The contract with everything above:

* the prediction engine reads ``feat_training_dataset`` and nothing below it;
* every column is computed from information available **before kickoff**;
* generation is deterministic and reproducible — the same warehouse state
  produces the same feature values, so a backtest means something.

Import order below is dependency order: defence and context views must be
registered before the usage module's ``feat_training_dataset`` references them.
"""

from __future__ import annotations

from .base import REGISTRY, FeatureRegistry, FeatureView, lagged_window

# Registration happens at import. Order matters — see the module docstring.
from . import defense as _defense  # noqa: E402,F401  (registers defensive views)
from . import context as _context  # noqa: E402,F401  (registers game context)
from . import usage as _usage      # noqa: E402,F401  (registers usage + dataset)

from .build import (  # noqa: E402
    BuildResult,
    available_relations,
    build_features,
    drop_features,
    refresh_features,
)

__all__ = [
    "BuildResult",
    "FeatureRegistry",
    "FeatureView",
    "REGISTRY",
    "available_relations",
    "build_features",
    "drop_features",
    "lagged_window",
    "refresh_features",
]
