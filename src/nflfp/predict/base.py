"""Prediction engine contracts.

The layer boundary, restated as types: a model receives rows from
``feat_training_dataset`` and returns *components*. It never sees a database
session, never calls a provider, and never computes fantasy points itself —
points come from :mod:`nflfp.predict.scoring_bridge`, which applies the same
:class:`~nflfp.scoring.ScoringRules` that scored the training targets.

That constraint is what makes a model swappable. Anything obeying
:class:`Model` can be registered, backtested against the same harness, and
compared on the same metrics, whether it is a four-line average or a gradient
booster.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

#: One row of ``feat_training_dataset``.
FeatureRow = Mapping[str, object]

#: Positions the engine projects. Kickers and defences score under entirely
#: different rules and are out of scope until they have their own features.
POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")


@dataclass
class ComponentPrediction:
    """A model's output for one player-week: projected stat components.

    Scoring-agnostic by construction, matching what ``projections`` stores. The
    keys of :attr:`components` are :data:`nflfp.scoring.COMPONENT_FIELDS`.
    """

    player_id: str
    season: int
    week: int
    position: str
    components: dict[str, float] = field(default_factory=dict)
    #: Free-form provenance: which branch produced this, what was missing.
    #: Persisted to ``projections.features`` so a thin projection can explain
    #: itself months later.
    explain: dict[str, object] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.player_id, self.season, self.week)


@runtime_checkable
class Model(Protocol):
    """A component-space projection model.

    Implementations must be **deterministic**: the same training rows and the
    same prediction rows must produce identical output. A backtest of a
    non-deterministic model measures noise, and a projection that changes when
    regenerated cannot be explained to a user.
    """

    name: str
    version: str
    algorithm: str

    def fit(self, rows: Sequence[FeatureRow]) -> None:
        """Learn from completed player-weeks.

        Args:
            rows: Training rows, every one with actual components populated.
                The caller guarantees these all precede the prediction week —
                see :mod:`nflfp.predict.dataset`.
        """
        ...

    def predict(self, rows: Sequence[FeatureRow]) -> list[ComponentPrediction]:
        """Project components for the given player-weeks.

        Must return one prediction per input row, in input order, including for
        players with no usable history — a slate with holes is worse than one
        with low-confidence entries, because the hole is invisible downstream.
        """
        ...

    def params(self) -> dict:
        """Fitted parameters, for `model_runs.params`.

        Must be JSON-serialisable and sufficient, with the code, to reproduce
        the model. This is what makes a projection auditable after the fact.
        """
        ...


def empty_components() -> dict[str, float]:
    """A zeroed component vector.

    The starting point for every prediction, so a model that declines to
    project a stat yields 0.0 rather than a missing key that would later be
    read as a silent None.
    """
    from ..scoring import COMPONENT_FIELDS

    return {field_name: 0.0 for field_name in COMPONENT_FIELDS}
