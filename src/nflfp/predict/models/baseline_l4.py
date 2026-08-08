"""The baseline every other model has to beat.

"Last four games" is what a human does by eye and what most public projections
amount to. Measured over 2019-2025 it achieves:

===========  =====  ======  ===========
position     r      MAE     sd(actual)
===========  =====  ======  ===========
QB           0.487  6.57    9.20
RB           0.572  4.53    7.56
WR           0.519  4.26    6.77
TE           0.474  3.31    5.14
===========  =====  ======  ===========

Shipping a model that does not beat this would be worse than shipping nothing,
because it would carry the authority of a model without the accuracy. So it is
registered as a real model, backtested by the same harness, and reported
alongside every candidate.

Expressed in component space
----------------------------
It would be simpler to return ``fp_half_ppr_l4`` directly, but this returns
lagged *components* and lets the scoring bridge derive points. Two reasons:
it makes the baseline directly comparable to component models rather than a
special case in the harness, and — because scoring is linear in the components —
it must reproduce the points-space average exactly. That equivalence is an
end-to-end check on the whole component/scoring path, and it is asserted in the
tests.

Cold start
----------
12.9% of Week 1 rows and ~1-2% of later rows have no usage history, mostly
rookies and returns from injury. Those get a positional prior fitted from the
training data instead of a hole in the slate, flagged in ``explain`` so nothing
downstream mistakes a prior for a projection.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from statistics import median

from ..base import ComponentPrediction, FeatureRow, empty_components
from ..scoring_bridge import COMPONENT_TO_COLUMN

logger = logging.getLogger(__name__)


class BaselineL4:
    """Projects each component as its trailing 4-game average."""

    name = "baseline_l4"
    version = "1.0.0"
    algorithm = "baseline"

    def __init__(self) -> None:
        #: position -> component -> prior, fitted in `fit`.
        self._priors: dict[str, dict[str, float]] = {}

    # -- training ----------------------------------------------------------

    def fit(self, rows: Sequence[FeatureRow]) -> None:
        """Fit positional priors for players with no history.

        The averaging model itself has nothing to learn — the lagged columns are
        already computed. What needs fitting is the cold-start fallback, and it
        must be fitted on *training* rows only, or it leaks.

        Medians rather than means: weekly fantasy scoring is right-skewed, and a
        mean prior would systematically over-project the replacement-level
        player it is meant to describe.
        """
        by_position: dict[str, list[FeatureRow]] = {}
        for row in rows:
            by_position.setdefault(str(row["position"]), []).append(row)

        self._priors = {}
        for position, position_rows in by_position.items():
            priors: dict[str, float] = {}
            for component, column in COMPONENT_TO_COLUMN.items():
                values = [
                    float(r[f"{column}_actual"])
                    for r in position_rows
                    if r.get(f"{column}_actual") is not None
                ]
                priors[component] = median(values) if values else 0.0
            self._priors[position] = priors

        logger.info(
            "fitted cold-start priors for %s from %d row(s)",
            ", ".join(sorted(self._priors)), len(rows),
        )

    # -- inference ---------------------------------------------------------

    def predict(self, rows: Sequence[FeatureRow]) -> list[ComponentPrediction]:
        """One prediction per row, in input order."""
        return [self._predict_one(row) for row in rows]

    def _predict_one(self, row: FeatureRow) -> ComponentPrediction:
        position = str(row["position"])
        components = empty_components()

        # A player is "known" if they have any lagged history at all. Using the
        # points average as the probe rather than a single component avoids
        # treating a genuine zero (a healthy WR with no carries) as missing.
        known = row.get("fp_half_ppr_l4") is not None
        source = "history" if known else "positional_prior"
        prior = self._priors.get(position, {})

        for component, column in COMPONENT_TO_COLUMN.items():
            if known:
                value = row.get(f"{column}_l4")
                components[component] = 0.0 if value is None else float(value)
            else:
                components[component] = prior.get(component, 0.0)

        return ComponentPrediction(
            player_id=str(row["player_id"]),
            season=int(row["season"]),
            week=int(row["week"]),
            position=position,
            components=components,
            explain={
                "source": source,
                "games_in_window": row.get("games_played_season"),
                "snap_pct_l4": row.get("snap_pct_l4"),
            },
        )

    def params(self) -> dict:
        """Fitted priors, sufficient to reproduce the model with the code."""
        return {
            "window": 4,
            "cold_start": "positional median of actual components",
            "priors": self._priors,
        }
