"""Model registry.

Same pattern as the provider and job registries: a small explicit dict of
factories, readable in one screen. Registering by *factory* rather than
instance matters here — the backtest harness needs a fresh, unfitted model for
every walk-forward fold, and handing it a shared instance would let one fold's
training leak into another's evaluation.

Estimators that need optional dependencies register only when those are
importable, exactly as feature views skip when ``raw_pbp`` is absent. That keeps
the API and ETL images free of a 150MB gradient-boosting wheel they never use.
"""

from __future__ import annotations

import logging
from typing import Callable

from .base import Model
from .models.baseline_l4 import BaselineL4
from .models.shrinkage import ShrinkageModel

logger = logging.getLogger(__name__)

MODELS: dict[str, Callable[[], Model]] = {
    "baseline_l4": BaselineL4,
    "shrinkage_eb": ShrinkageModel,
}


class UnknownModelError(KeyError):
    """The requested model is not registered."""


def register(name: str, factory: Callable[[], Model]) -> None:
    """Add a model factory, refusing to silently replace one."""
    if name in MODELS:
        raise ValueError(f"model {name!r} is already registered")
    MODELS[name] = factory


def get_model_factory(name: str) -> Callable[[], Model]:
    """Look up a factory by name.

    Raises:
        UnknownModelError: naming the models that *are* available, since the
            usual cause is an optional dependency not being installed.
    """
    try:
        return MODELS[name]
    except KeyError:
        raise UnknownModelError(
            f"unknown model {name!r}; registered: {sorted(MODELS)}"
        ) from None


def available() -> list[str]:
    return sorted(MODELS)
