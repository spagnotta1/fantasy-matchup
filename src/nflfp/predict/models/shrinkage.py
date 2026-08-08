"""Empirical-Bayes shrinkage of lagged component averages.

The problem this solves
-----------------------
A 4-game average is an unbiased estimate of a player's *current* level, but a
*selected* extreme average is not a good forecast. Measured over 2016-2025,
half-PPR, comparing the plain 4-game average against what actually happened:

============  ===========  =======  ======
l4 projection  mean actual  bias     n
============  ===========  =======  ======
2.2            3.2          +0.98    24,565
7.3            7.4          +0.11    14,702
12.3           11.3         -0.93    8,838
17.1           14.7         -2.44    4,356
22.0           17.6         -4.37    1,499
26.9           19.3         -7.58    359
32.1           18.0         **-14.12**  44
============  ===========  =======  ======

A 32-point projection returns 18. That single fact explains the phase-3a
calibration failure: boom probabilities near 0.94 delivered 0.17, because the
point estimate feeding them was itself far too high. No amount of work on the
interval fixes a mis-centred distribution.

The method
----------
Standard empirical Bayes for a normal hierarchical model. For each position and
component, decompose observed variance into within-player (week to week noise)
and between-player (real talent spread):

.. code-block:: text

    shrunk = (n * player_mean + k * prior) / (n + k)
    k      = sigma^2_within / sigma^2_between

``k`` has a plain reading: **the number of games of evidence the prior is
worth.** A component where players differ a lot and are consistent week to week
gets a small ``k`` and little shrinkage; one that is mostly noise gets a large
``k`` and is pulled hard toward the positional prior. Nothing is hand-tuned —
``k`` is computed from the training fold and reported in ``params()``.

``sigma^2_between`` is corrected for sampling noise via the method of moments:
the variance of observed player means overstates true spread by roughly
``sigma^2_within / n_bar``, and subtracting that is what keeps ``k`` from being
biased toward zero (which would under-shrink exactly where shrinkage matters).

What is deliberately *not* modelled
-----------------------------------
Shrinkage strength could also vary by window sample size, role stability,
injury status and opponent. Measured, the sample-size effect on residual spread
is weak once projection level is controlled for — within a projection band,
residual SD is 4.32 (1 game) against 4.21 (4 games), and 6.07 against 6.27 in
the next band. That is not a signal worth a parameter.

So sample size enters only through ``n`` in the formula above, where it belongs
on first principles, and the rest are left out. A more elaborate scheme would
add configuration surface and the appearance of sophistication without evidence
that it helps.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import fmean

from ..base import ComponentPrediction, FeatureRow, empty_components
from ..features import FEATURE_VERSION, assert_available
from ..scoring_bridge import COMPONENT_TO_COLUMN

logger = logging.getLogger(__name__)

#: Components the model projects. 2-point conversions are excluded: they are
#: near-unpredictable and worth 2 points, so projecting them adds noise.
MODELLED_COMPONENTS: tuple[str, ...] = (
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "fumbles_lost_total",
)

#: Guardrails on the fitted k. A degenerate training fold (one player, or a
#: component nobody records) can otherwise produce k = 0 or k = inf.
MIN_K, MAX_K = 0.1, 40.0

#: Players with fewer than this many observations are excluded from the
#: variance decomposition — a within-player variance from two games is noise.
MIN_OBSERVATIONS_PER_PLAYER = 4


@dataclass
class ShrinkageParams:
    """Fitted constants for one position and component."""

    k: float
    prior: float
    sigma_within: float
    sigma_between: float
    players: int

    def as_dict(self) -> dict:
        return {
            "k": round(self.k, 4),
            "prior": round(self.prior, 4),
            "sigma_within": round(self.sigma_within, 4),
            "sigma_between": round(self.sigma_between, 4),
            "players": self.players,
        }


@dataclass
class ShrinkageModel:
    """Component projections with empirical-Bayes shrinkage toward a positional prior."""

    name: str = "shrinkage_eb"
    version: str = "1.0.0"
    algorithm: str = "baseline"
    #: Extra prior weight, in games. 0.0 uses pure empirical Bayes; raising it
    #: shrinks harder everywhere. Exposed for configurability and swept in the
    #: tests, but the default is the un-tuned statistical answer.
    extra_prior_games: float = 0.0
    _params: dict[tuple[str, str], ShrinkageParams] = field(default_factory=dict)

    #: Declared so the feature contract can be enforced. See predict/features.py.
    required_features: tuple[str, ...] = (
        "games_in_window_l4",
        "fp_half_ppr_l4",
    )

    def __post_init__(self) -> None:
        # Fails loudly if a future edit introduces a feature that would not
        # exist at prediction time.
        assert_available(self.required_features)

    # -- training ----------------------------------------------------------

    def fit(self, rows: Sequence[FeatureRow]) -> None:
        """Decompose variance per (position, component) and derive k.

        Fitted on *actual* component outcomes in the training fold, which is
        the right sample: k describes how noisy a component genuinely is, and
        that is a property of the game, not of any projection.
        """
        by_position: dict[str, list[FeatureRow]] = {}
        for row in rows:
            by_position.setdefault(str(row["position"]), []).append(row)

        self._params = {}
        for position, position_rows in by_position.items():
            for component in MODELLED_COMPONENTS:
                column = f"{COMPONENT_TO_COLUMN[component]}_actual"
                per_player: dict[str, list[float]] = {}
                for row in position_rows:
                    value = row.get(column)
                    if value is not None:
                        per_player.setdefault(str(row["player_id"]), []).append(float(value))

                params = _decompose(per_player)
                if params is not None:
                    self._params[(position, component)] = params

        logger.info(
            "fitted shrinkage for %d (position, component) pair(s) from %d row(s)",
            len(self._params), len(rows),
        )

    # -- inference ---------------------------------------------------------

    def predict(self, rows: Sequence[FeatureRow]) -> list[ComponentPrediction]:
        return [self._predict_one(row) for row in rows]

    def _predict_one(self, row: FeatureRow) -> ComponentPrediction:
        position = str(row["position"])
        components = empty_components()

        has_history = row.get("fp_half_ppr_l4") is not None
        raw_n = row.get("games_in_window_l4")
        n = float(raw_n) if has_history and raw_n is not None else 0.0

        weights: dict[str, float] = {}
        for component in MODELLED_COMPONENTS:
            column = COMPONENT_TO_COLUMN[component]
            params = self._params.get((position, component))
            if params is None:
                components[component] = 0.0
                continue

            observed = row.get(f"{column}_l4")
            if observed is None or n <= 0:
                # No history at all: the prior *is* the projection.
                components[component] = params.prior
                weights[component] = 0.0
                continue

            k = params.k + self.extra_prior_games
            weight = n / (n + k)
            components[component] = weight * float(observed) + (1.0 - weight) * params.prior
            weights[component] = weight

        return ComponentPrediction(
            player_id=str(row["player_id"]),
            season=int(row["season"]),
            week=int(row["week"]),
            position=position,
            components=components,
            explain={
                "source": "history" if has_history else "positional_prior",
                "games_in_window": n,
                "feature_version": FEATURE_VERSION,
                # The headline shrinkage weight, so a projection can say how
                # much of it was the player and how much was the prior.
                "shrink_weight": round(fmean(weights.values()), 4) if weights else 0.0,
            },
        )

    def params(self) -> dict:
        return {
            "method": "empirical_bayes",
            "formula": "(n * player_mean + k * prior) / (n + k), k = var_within / var_between",
            "extra_prior_games": self.extra_prior_games,
            "feature_version": FEATURE_VERSION,
            "fitted": {
                f"{position}.{component}": params.as_dict()
                for (position, component), params in sorted(self._params.items())
            },
        }


def _decompose(per_player: dict[str, list[float]]) -> ShrinkageParams | None:
    """Split observed variance into within- and between-player components.

    Returns None when the sample cannot support the decomposition — better no
    shrinkage parameter than one derived from three observations.
    """
    usable = {
        player: values
        for player, values in per_player.items()
        if len(values) >= MIN_OBSERVATIONS_PER_PLAYER
    }
    if len(usable) < 10:
        return None

    means = {player: fmean(values) for player, values in usable.items()}
    prior = fmean(means.values())

    within = []
    for player, values in usable.items():
        centre = means[player]
        within.append(
            sum((v - centre) ** 2 for v in values) / (len(values) - 1)
        )
    sigma_within = fmean(within)

    grand = fmean(means.values())
    observed_between = fmean((m - grand) ** 2 for m in means.values())
    mean_n = fmean(len(v) for v in usable.values())

    # The observed spread of player means includes sampling noise. Removing it
    # is what stops k being biased low, which would under-shrink precisely
    # where shrinkage matters most.
    sigma_between = observed_between - (sigma_within / mean_n)
    if sigma_between <= 1e-9:
        # Everything is noise: shrink as hard as the guardrail allows.
        return ShrinkageParams(MAX_K, prior, sigma_within, 0.0, len(usable))

    k = min(max(sigma_within / sigma_between, MIN_K), MAX_K)
    return ShrinkageParams(k, prior, sigma_within, sigma_between, len(usable))
