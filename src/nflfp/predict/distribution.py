"""Outcome distributions from held-out residuals.

A projection is not a number. The choice between two players projected for 11
points is entirely about their shapes, and shapes differ sharply by position:
at 50%+ snaps, tight ends finish under five points 48.5% of the time against
10.1% for running backs.

Method
------
Empirical residual quantiles, fitted on **out-of-fold** predictions and applied
to new ones. For a projection of ``x`` from a player at position ``p``, the
distribution is ``x + Q`` where ``Q`` is the observed distribution of
``actual - predicted`` for similar past projections.

Chosen over a parametric family because weekly scoring is not normal — it is
right-skewed with a hard floor near zero, so a Gaussian interval puts the floor
below zero and understates the ceiling. Chosen over quantile regression because
the data does not yet justify the extra machinery: with 44 observations above 30
projected points, a flexible model would mostly fit noise and present it
confidently. This is the deliberately simpler, more honest option.

Binning: the resolution / sample size / stability tradeoff
----------------------------------------------------------
Residual spread scales with projection size, so residuals must be conditioned on
it. That creates a direct tension:

* **Too few bins** and a 35-point projection shares a bucket with an 18-point
  one. This was the phase-3a failure: the top bucket pooled everything above 18,
  and boom probabilities in the 0.9-1.0 band stated 94% and delivered 17%.
* **Too many bins** and each holds a handful of observations, so its quantiles
  are noise — which reads as precision and is worse than coarseness, because
  nothing signals that the number is unreliable.

Resolution is therefore chosen by **sample count, not by value**: bins are
equal-count (default 300 observations), so they are automatically narrow where
data is dense and wide where it is sparse. A position whose data cannot support
even one full bin falls back to a single pooled distribution, and the bin count
and occupancy are reported so the tradeoff stays visible rather than implied.

Extrapolation is refused. A projection beyond the range seen in training uses
the topmost bin's residuals and is flagged ``extrapolated``, because the honest
statement about a 40-point projection is "we have never seen one" rather than a
confident interval.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Published percentiles. P10/P50/P90 are also exposed as floor/median/ceiling.
PERCENTILES: tuple[float, ...] = (0.10, 0.25, 0.50, 0.75, 0.90)

#: Absolute thresholds. A manager asks "will this leave me short?", and that
#: question does not move because the model was optimistic.
BUST_THRESHOLD = 5.0
BOOM_THRESHOLD = 20.0

#: Minimum observations per residual bin. Below this, quantile estimates wobble
#: enough that added resolution is a net loss.
MIN_BIN_SAMPLES = 300


def quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile of an already-sorted sequence."""
    if not sorted_values:
        raise ValueError("cannot take a quantile of an empty sequence")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = q * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


@dataclass
class PointDistribution:
    """The published outcome distribution for one projection and profile.

    Shaped for the future Monte Carlo simulation engine: it exposes percentiles
    and a standard deviation directly, so a simulator never has to reconstruct
    a distribution from ``expected +/- some percentage``.
    """

    #: The model's raw output, kept for lineage and debugging.
    predicted_points: float
    #: The mean of the held-out outcome distribution — the **calibrated**
    #: expectation, and the number that should be shown and simulated from.
    #:
    #: These differ, and the difference is the point of the distribution. A raw
    #: shrunk projection is conditionally biased (measured: -1.2 to -1.6 points
    #: in the 5-15 band) because shrinkage trades bias for variance. Adding back
    #: the empirical mean residual for projections of this size removes that
    #: bias without touching the shape.
    expected_points: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    standard_deviation: float
    confidence: float
    boom_probability: float
    bust_probability: float
    boom_threshold: float = BOOM_THRESHOLD
    bust_threshold: float = BUST_THRESHOLD
    #: Observations behind this distribution — the honesty flag.
    sample_size: int = 0
    #: True when the projection exceeded anything seen in fitting.
    extrapolated: bool = False

    def __post_init__(self) -> None:
        ordered = [self.p10, self.p25, self.p50, self.p75, self.p90]
        if ordered != sorted(ordered):
            raise ValueError(f"percentiles out of order: {ordered}")
        for name, value in (
            ("boom_probability", self.boom_probability),
            ("bust_probability", self.bust_probability),
            ("confidence", self.confidence),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {value}")

    # Aliases kept because Layer 1's schema and the API speak this language.
    @property
    def floor_points(self) -> float:
        return self.p10

    @property
    def median_points(self) -> float:
        return self.p50

    @property
    def ceiling_points(self) -> float:
        return self.p90

    def as_dict(self) -> dict:
        return {
            "predicted": self.predicted_points,
            "expected": self.expected_points,
            "p10": self.p10, "p25": self.p25, "p50": self.p50,
            "p75": self.p75, "p90": self.p90,
            "sd": self.standard_deviation,
            "boom": self.boom_probability, "bust": self.bust_probability,
            "sample_size": self.sample_size, "extrapolated": self.extrapolated,
        }


@dataclass
class _Bin:
    """Residuals for one (position, projection range)."""

    lower: float
    upper: float
    residuals: list[float]

    @property
    def count(self) -> int:
        return len(self.residuals)


@dataclass
class ResidualDistribution:
    """Equal-count empirical residual quantiles, per position.

    Fit on out-of-fold predictions only. Fitting on in-sample predictions
    understates spread, because the model has already seen those outcomes.
    """

    min_bin_samples: int = MIN_BIN_SAMPLES
    max_bins: int = 12
    _bins: dict[str, list[_Bin]] = field(default_factory=dict)
    _pooled: dict[str, list[float]] = field(default_factory=dict)
    #: Largest projection actually seen while fitting, per position. This is
    #: what ``extrapolated`` is measured against -- not a bin edge. The top bin
    #: is open-ended by construction (``upper`` is ``+inf``), so comparing
    #: against the *second* bin's upper edge flags every projection in the top
    #: bin, which for equal-count bins is 1/``max_bins`` of the board.
    _max_predicted: dict[str, float] = field(default_factory=dict)

    def fit(self, samples: Sequence[tuple[str, float, float]]) -> "ResidualDistribution":
        """Fit from ``(position, predicted_points, actual_points)`` triples."""
        by_position: dict[str, list[tuple[float, float]]] = {}
        for position, predicted, actual in samples:
            by_position.setdefault(position, []).append((predicted, actual))

        self._bins, self._pooled, self._max_predicted = {}, {}, {}
        for position, pairs in by_position.items():
            pairs.sort(key=lambda pair: pair[0])
            self._pooled[position] = sorted(actual - predicted for predicted, actual in pairs)
            self._bins[position] = self._make_bins(pairs)
            # pairs is sorted by predicted, so the last one is the fitted ceiling.
            self._max_predicted[position] = float(pairs[-1][0])

        logger.info(
            "fitted residual distribution: %s",
            ", ".join(
                f"{position}={len(bins)} bin(s)" for position, bins in sorted(self._bins.items())
            ),
        )
        return self

    def _make_bins(self, pairs: Sequence[tuple[float, float]]) -> list[_Bin]:
        """Split sorted (predicted, actual) pairs into equal-count bins.

        Equal-count rather than equal-width: bins end up narrow where
        projections are dense and wide where they are sparse, which is exactly
        the resolution/stability tradeoff resolved in the data's favour.
        """
        n = len(pairs)
        bin_count = max(1, min(self.max_bins, n // self.min_bin_samples))
        if bin_count <= 1:
            return [
                _Bin(
                    lower=float("-inf"), upper=float("inf"),
                    residuals=sorted(a - p for p, a in pairs),
                )
            ]

        size = n // bin_count
        bins: list[_Bin] = []
        for index in range(bin_count):
            start = index * size
            stop = n if index == bin_count - 1 else (index + 1) * size
            chunk = pairs[start:stop]
            bins.append(
                _Bin(
                    lower=float("-inf") if index == 0 else chunk[0][0],
                    upper=float("inf") if index == bin_count - 1 else chunk[-1][0],
                    residuals=sorted(a - p for p, a in chunk),
                )
            )
        return bins

    def _select(self, position: str, predicted: float) -> tuple[list[float], bool]:
        """Residuals for this projection, plus whether we extrapolated.

        ``extrapolated`` means what the module docstring says it means: this
        projection is larger than anything seen while fitting, so the topmost
        bin's residuals are being reused outside the range that produced them.
        It is deliberately *not* "landed in the top bin" -- the top bin holds
        1/``max_bins`` of the training data by construction, so that reading
        flagged roughly 8% of every position's board as an extrapolation and
        drained the meaning out of a flag that reaches the user.
        """
        ceiling = self._max_predicted.get(position)
        extrapolated = ceiling is not None and predicted > ceiling

        bins = self._bins.get(position)
        if not bins:
            return self._pooled.get(position, []), extrapolated

        uppers = [b.upper for b in bins[:-1]]
        index = bisect_right(uppers, predicted)
        chosen = bins[min(index, len(bins) - 1)]
        return chosen.residuals, extrapolated

    def apply(self, position: str, predicted_points: float) -> PointDistribution:
        """Build the outcome distribution around a point projection.

        Raises:
            ValueError: if nothing was fitted for `position`.
        """
        residuals, extrapolated = self._select(position, predicted_points)
        if not residuals:
            raise ValueError(f"no fitted residuals for position {position!r}")

        # Clamp at zero: a fantasy score below zero is possible but vanishingly
        # rare, and a negative floor is not something a manager can act on.
        values = [max(0.0, predicted_points + r) for r in residuals]
        values.sort()

        percentiles = [quantile(values, q) for q in PERCENTILES]
        # Guard against a clamp inverting the order at the very bottom.
        percentiles = sorted(percentiles)

        mean_value = sum(values) / len(values)
        variance = sum((v - mean_value) ** 2 for v in values) / max(len(values) - 1, 1)

        return PointDistribution(
            predicted_points=predicted_points,
            expected_points=mean_value,
            p10=percentiles[0], p25=percentiles[1], p50=percentiles[2],
            p75=percentiles[3], p90=percentiles[4],
            standard_deviation=variance ** 0.5,
            confidence=_confidence(percentiles[0], percentiles[4], predicted_points),
            boom_probability=sum(1 for v in values if v >= BOOM_THRESHOLD) / len(values),
            bust_probability=sum(1 for v in values if v <= BUST_THRESHOLD) / len(values),
            sample_size=len(residuals),
            extrapolated=extrapolated,
        )

    def sample_quantiles(self, position: str, predicted_points: float) -> list[float]:
        """The full empirical outcome set, for Monte Carlo sampling.

        The simulation engine draws from this rather than assuming a shape.
        """
        residuals, _ = self._select(position, predicted_points)
        return sorted(max(0.0, predicted_points + r) for r in residuals)

    def describe(self) -> dict:
        """Bin structure and occupancy, so the tradeoff stays inspectable."""
        return {
            position: [
                {"lower": b.lower, "upper": b.upper, "n": b.count} for b in bins
            ]
            for position, bins in sorted(self._bins.items())
        }


def _confidence(p10: float, p90: float, predicted: float) -> float:
    """0-1, higher when the outcome band is tight relative to the projection.

    Explicitly *not* a claim about accuracy — it reports how wide the historical
    error band is for this kind of projection, scaled so that a 3-point spread
    means something different on a 4-point player than an 18-point one.
    """
    scale = max(predicted, 4.0)
    return max(0.0, min(1.0, 1.0 - ((p90 - p10) / (2.0 * scale))))


# ---------------------------------------------------------------------------
# probabilistic scoring
# ---------------------------------------------------------------------------

def crps(sorted_outcomes: Sequence[float], actual: float) -> float:
    """Continuous Ranked Probability Score for an empirical distribution.

    Lower is better; it reduces to absolute error for a point forecast, so a
    sharp *and* correct distribution beats a vague one and both beat a confident
    wrong one. Preferred over negative log likelihood here because NLL needs a
    density — an empirical quantile set has none, and forcing one on it would
    mean assuming the parametric shape this module deliberately avoids. NLL also
    goes infinite the first time an outcome lands outside the support, which for
    an empirical distribution is a property of the sample, not of the forecast.

    Computed as the mean absolute error of the empirical sample minus half its
    mean pairwise spread — the standard energy-form identity.
    """
    n = len(sorted_outcomes)
    if n == 0:
        raise ValueError("cannot score an empty distribution")

    mean_absolute = sum(abs(value - actual) for value in sorted_outcomes) / n
    # Sum of pairwise |xi - xj| in O(n) using the sorted order.
    weighted = 0.0
    for index, value in enumerate(sorted_outcomes):
        weighted += value * (2 * index - n + 1)
    mean_spread = (2.0 * weighted) / (n * n)
    return mean_absolute - 0.5 * mean_spread


def pinball_loss(predicted_quantile: float, actual: float, q: float) -> float:
    """Quantile (pinball) loss — the proper scoring rule for one percentile.

    Asymmetric on purpose: a P90 that is too low is penalised more than one that
    is too high, which is what makes it measure the quantile rather than the mean.
    """
    delta = actual - predicted_quantile
    return q * delta if delta >= 0 else (q - 1) * delta
