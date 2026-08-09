"""Reconstructing a projected outcome distribution from its stored percentiles.

Why this exists
---------------
``projection_points`` stores five percentiles, a mean, a standard deviation and
two tail probabilities. Every interesting fantasy question — "who should I
start?", "what are the odds this lineup clears 120?", "is the gap between WR14
and WR15 real?" — is a question about *distributions*, not about the point
estimate. :func:`nflfp.predict.persist.load_distribution` already says as much:
"a simulator never reconstructs one from ``expected +/- some percentage``."

This module is the honest reconstruction. It builds a piecewise-linear quantile
function through the stored knots, which has three properties that matter:

* it **passes through the stored percentiles exactly**, so a reconstructed P90
  is the P90 the calibration measured, not an approximation of it;
* it is **monotone**, so a CDF derived from it can never go backwards;
* it makes **no distributional assumption**. Layer 3b chose empirical residual
  quantiles over a Gaussian specifically because weekly fantasy scoring is
  right-skewed with a hard floor near zero, and fitting a normal here would
  throw that away at the last step.

The tails are the assumption
----------------------------
Below P10 and above P90 there is nothing stored, so something must be assumed.
The tails are extended linearly to zero and one over a multiple of the nearest
interior segment, wider on the right than the left because the underlying
distribution is right-skewed — a receiver's ceiling week is further from their
P90 than their disaster week is from their P10.

Those multiples (:data:`LOWER_TAIL_FACTOR`, :data:`UPPER_TAIL_FACTOR`) are the
only free parameters in this module and they are named, not buried. They move
20% of the probability mass in total, and head-to-head comparisons are
dominated by the interior, which is why a coarse tail is tolerable here and
would not be if this were pricing an outright ceiling bet.

:meth:`OutcomeCurve.from_percentiles` accepts the two factors as keyword
arguments defaulting to the constants, so an evaluation harness can build a
curve under candidate factors **through this same code path** rather than
through a parallel reimplementation of it. The defaults are the production
configuration; passing anything else is an experiment and is the caller's to
declare. See ``docs/simulation-readiness.md``, Phase 6C.

Independence
------------
:func:`probability_beats` assumes the two outcomes are independent. That is
close to true for players in different games and **wrong for teammates**, whose
scoring shares one offence's plays, and for players facing each other. The
function reports the assumption rather than silently applying it; see
``correlation_warning``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

#: How far below P10 the distribution is assumed to reach, as a multiple of the
#: P10-P25 segment. Smaller than the upper factor because zero is a near-hard
#: floor on fantasy scoring.
#:
#: Phase 6C measured this at the lineup level and recommended **1.0**, which was
#: approved and applied in Phase 6D. It is barely identified either way:
#: :data:`HARD_FLOOR` clamps the lower extension for most startable players, so
#: the calibration surface is nearly flat along this axis — 1.0 is the middle of
#: an underdetermined direction rather than an argmin. Was 1.5 through Phases
#: 6A–6C. See ``docs/simulation-readiness.md``.
LOWER_TAIL_FACTOR = 1.0

#: How far above P90 the distribution is assumed to reach, as a multiple of the
#: P75-P90 segment. Larger because the distribution is right-skewed: the ceiling
#: is genuinely long.
#:
#: This is the load-bearing one. Phase 6C found that 2.5 over-disperses a
#: seven-player sum — the team total's 80% interval covered 82.2% of realised
#: totals against a nominal 80% — and recommended **2.0**, which was approved and
#: applied in Phase 6D. Both held-out and tuning surfaces put the calibration
#: basin at 2.0 regardless of the lower factor. Was 2.5 through Phases 6A–6C;
#: ``tests/test_tail_calibration.py`` pins the shipped values so the next change
#: is also deliberate.
#:
#: This is a **calibration** improvement and not a winner-prediction one. Brier,
#: log loss and score-differential CRPS all moved in its favour and none of them
#: significantly; the claim it is approved on is interval calibration.
UPPER_TAIL_FACTOR = 2.0

#: Fantasy scoring can go negative (interceptions, fumbles) but not far. The
#: lower tail is clamped here so a wide interval cannot imply an impossible
#: outcome.
HARD_FLOOR = -6.0

#: Quadrature resolution for :func:`probability_beats`. 512 points puts the
#: discretisation error near 1e-3 — an order of magnitude below the calibration
#: error the distributions themselves report (max 0.130 for boom), so refining
#: it further would be measuring the grid rather than the football.
INTEGRATION_POINTS = 512

#: The stored percentile knots, in order.
_KNOT_PROBABILITIES: tuple[float, ...] = (0.10, 0.25, 0.50, 0.75, 0.90)


@dataclass(frozen=True)
class OutcomeCurve:
    """A monotone piecewise-linear quantile function for one player-week.

    Construct with :meth:`from_percentiles`; the raw constructor exists for
    tests that want a deliberately odd shape.

    Attributes:
        knots: ``(probability, points)`` pairs sorted by probability, spanning
            0.0 to 1.0 inclusive after tail extension.
        expected: The stored calibrated mean, when there was one. Kept
            separately from :meth:`mean` because the two answer different
            questions: this is what the calibration measured, that is what this
            reconstruction implies. They should agree closely, and a large gap
            is a signal the reconstruction is being asked to do too much.
        extrapolated: Propagated from storage — the projection exceeded
            anything seen when the residual distribution was fitted.
        samples: Held-out residuals behind the distribution. A curve built from
            40 observations is not the same claim as one built from 4,000, and
            callers that aggregate curves should weight by this.
    """

    knots: tuple[tuple[float, float], ...]
    expected: float | None = None
    extrapolated: bool = False
    samples: int | None = None

    def __post_init__(self) -> None:
        if len(self.knots) < 2:
            raise ValueError("an outcome curve needs at least two knots")
        probabilities = [p for p, _ in self.knots]
        if probabilities != sorted(probabilities):
            raise ValueError("knot probabilities must be non-decreasing")
        values = [v for _, v in self.knots]
        if values != sorted(values):
            raise ValueError(
                "knot values must be non-decreasing; a ceiling below a floor is "
                "not a distribution"
            )

    # -- construction -------------------------------------------------------

    @classmethod
    def from_percentiles(
        cls,
        *,
        p10: float | None,
        p25: float | None = None,
        median: float | None,
        p75: float | None = None,
        p90: float | None,
        expected: float | None = None,
        extrapolated: bool = False,
        samples: int | None = None,
        lower_tail_factor: float = LOWER_TAIL_FACTOR,
        upper_tail_factor: float = UPPER_TAIL_FACTOR,
    ) -> "OutcomeCurve | None":
        """Build a curve from stored percentiles.

        The quartiles are optional: the database permits a three-point summary
        (P10/P50/P90) and older rows may carry only that. The floor, median and
        ceiling are not optional, because with fewer than three knots the
        "distribution" is a straight line and every question asked of it is
        really a question about the point estimate.

        Args:
            lower_tail_factor: How far below the lowest stored knot the curve
                reaches, as a multiple of the adjacent segment. Defaults to the
                production constant; overriding it is how the Phase 6C
                evaluation measures a candidate configuration without a second
                implementation of the reconstruction.
            upper_tail_factor: The same, above the highest stored knot.

        Returns:
            The curve, or ``None`` when there is not enough stored to build one
            — a missing distribution is a normal state (an unpublished week, a
            model that declined to project), and forcing callers into a
            try/except for it would put error handling on the common path.
        """
        supplied = [
            (probability, value)
            for probability, value in (
                (0.10, p10), (0.25, p25), (0.50, median), (0.75, p75), (0.90, p90)
            )
            if value is not None
        ]
        if len(supplied) < 3:
            return None

        values = [v for _, v in supplied]
        if values != sorted(values):
            # The database's CHECK constraints make this unreachable for stored
            # rows. It is still checked, because this constructor is also fed by
            # tests and by any future writer that has not been added to the
            # schema yet, and a silently reversed curve would produce confident
            # nonsense rather than an error.
            raise ValueError(f"percentiles are not ordered: {values}")

        return cls(
            knots=_extend_tails(
                supplied,
                lower_factor=lower_tail_factor,
                upper_factor=upper_tail_factor,
            ),
            expected=expected,
            extrapolated=extrapolated,
            samples=samples,
        )

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> "OutcomeCurve | None":
        """Build a curve from a ``projection_points`` row mapping.

        Accepts the column names as stored, so a repository result can be handed
        over without an intermediate translation step that would only be one
        more place for a typo to change a projection.
        """
        return cls.from_percentiles(
            p10=_as_float(row.get("floor_points")),
            p25=_as_float(row.get("p25_points")),
            median=_as_float(row.get("median_points")),
            p75=_as_float(row.get("p75_points")),
            p90=_as_float(row.get("ceiling_points")),
            expected=_as_float(row.get("expected_points")),
            extrapolated=bool(row.get("extrapolated") or False),
            samples=_as_int(row.get("distribution_samples")),
        )

    # -- evaluation ---------------------------------------------------------

    @property
    def lower(self) -> float:
        """Smallest outcome the curve admits."""
        return self.knots[0][1]

    @property
    def upper(self) -> float:
        """Largest outcome the curve admits."""
        return self.knots[-1][1]

    def quantile(self, probability: float) -> float:
        """The outcome at a given cumulative probability.

        Args:
            probability: In [0, 1]. Values outside are clamped rather than
                rejected: quadrature grids legitimately land on the endpoints,
                and raising there would make every caller defensive.
        """
        q = min(1.0, max(0.0, float(probability)))
        knots = self.knots
        if q <= knots[0][0]:
            return knots[0][1]
        for (p_low, v_low), (p_high, v_high) in zip(knots, knots[1:]):
            if q <= p_high:
                span = p_high - p_low
                if span <= 0:
                    return v_high
                return v_low + (v_high - v_low) * (q - p_low) / span
        return knots[-1][1]

    def cdf(self, points: float) -> float:
        """``P(outcome <= points)``.

        The inverse of :meth:`quantile` over the same piecewise-linear shape,
        so ``cdf(quantile(q)) == q`` wherever the curve is strictly increasing.
        Over a flat segment — a player whose P10 and P25 are both zero — the
        inverse is not unique and this returns the *highest* probability
        consistent with the value, which is the reading that makes
        ``P(points >= x)`` conservative.
        """
        x = float(points)
        knots = self.knots
        if x < knots[0][1]:
            return 0.0
        if x >= knots[-1][1]:
            return 1.0
        result = 0.0
        for (p_low, v_low), (p_high, v_high) in zip(knots, knots[1:]):
            if x >= v_high:
                result = p_high
                continue
            if x >= v_low:
                span = v_high - v_low
                if span <= 0:
                    result = max(result, p_high)
                else:
                    result = max(result, p_low + (p_high - p_low) * (x - v_low) / span)
                break
        return min(1.0, max(0.0, result))

    def probability_at_least(self, points: float) -> float:
        """``P(outcome >= points)`` — the shape of a boom probability."""
        return 1.0 - self.cdf(points)

    def probability_at_most(self, points: float) -> float:
        """``P(outcome <= points)`` — the shape of a bust probability."""
        return self.cdf(points)

    def mean(self, *, points: int = INTEGRATION_POINTS) -> float:
        """The mean implied by this reconstruction.

        Computed by midpoint quadrature over the quantile function, which is
        exact for a piecewise-linear curve given enough points. Compare against
        :attr:`expected` to see how much the tail assumption is contributing.
        """
        step = 1.0 / points
        return sum(self.quantile((i + 0.5) * step) for i in range(points)) * step

    def interval(self, lower: float = 0.10, upper: float = 0.90) -> tuple[float, float]:
        """A central interval, defaulting to the stored P10-P90."""
        if not 0.0 <= lower < upper <= 1.0:
            raise ValueError(f"invalid interval bounds: ({lower}, {upper})")
        return (self.quantile(lower), self.quantile(upper))


def _extend_tails(
    supplied: Sequence[tuple[float, float]],
    *,
    lower_factor: float = LOWER_TAIL_FACTOR,
    upper_factor: float = UPPER_TAIL_FACTOR,
) -> tuple[tuple[float, float], ...]:
    """Add q=0 and q=1 knots so the curve spans the whole probability range.

    The extension is linear over a multiple of the nearest interior segment.
    When that segment has zero width — a player whose P10 and P25 are both zero
    — there is no slope to extend, so the tail is flat and the curve simply
    stops there. That is the right answer: a distribution with no observed
    spread at the bottom should not be given an imaginary one.

    A factor of zero is legitimate and means "do not extend": the curve reaches
    its stored knot at q=0 or q=1 and no further, which is the boundary case a
    parameter search has to be able to evaluate.
    """
    knots = list(supplied)

    lowest_p, lowest_v = knots[0]
    _, next_v = knots[1]
    lower_span = (next_v - lowest_v) * lower_factor
    lower_value = max(HARD_FLOOR, lowest_v - lower_span)
    lower_value = min(lower_value, lowest_v)
    if lowest_p > 0.0:
        knots.insert(0, (0.0, lower_value))

    highest_p, highest_v = knots[-1]
    _, prev_v = knots[-2]
    upper_span = (highest_v - prev_v) * upper_factor
    upper_value = max(highest_v, highest_v + upper_span)
    if highest_p < 1.0:
        knots.append((1.0, upper_value))

    return tuple(knots)


# ---------------------------------------------------------------------------
# Head to head
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeadToHead:
    """The result of comparing two outcome curves.

    ``win_probability`` is ``P(a > b)`` under independence. ``expected_margin``
    is ``E[a] - E[b]``, and the two can disagree in direction: a player with a
    higher mean but a fatter left tail can be more likely to lose the week. That
    disagreement is the entire reason distributions are stored, so it is
    surfaced as :attr:`mean_and_odds_disagree` rather than resolved silently.
    """

    win_probability: float
    expected_margin: float
    #: True when the two curves are known to share an offence or a game, making
    #: the independence assumption behind ``win_probability`` unsafe.
    correlated: bool = False

    @property
    def mean_and_odds_disagree(self) -> bool:
        """The higher mean is not the more likely winner."""
        if self.expected_margin == 0.0:
            return False
        return (self.expected_margin > 0) != (self.win_probability > 0.5)

    @property
    def correlation_warning(self) -> str | None:
        """Human-readable caveat when independence does not hold."""
        if not self.correlated:
            return None
        return (
            "these players share a game, so their outcomes are correlated; the "
            "head-to-head probability assumes independence and will be too "
            "confident"
        )


def probability_beats(
    a: OutcomeCurve,
    b: OutcomeCurve,
    *,
    margin: float = 0.0,
    points: int = INTEGRATION_POINTS,
) -> float:
    """``P(a > b + margin)`` under independence.

    Evaluated as ``E_u[ F_b(Q_a(u) - margin) ]`` over a uniform midpoint grid —
    "for each possible outcome of ``a``, how much of ``b``'s mass falls below
    it?" — in one pass, with no sampling, and therefore **deterministic**. A
    Monte Carlo
    estimate would be simpler to write and would make the same comparison
    return a different answer on every request, which is not an acceptable
    property of a start/sit recommendation.

    Args:
        a: The curve being asked about.
        b: The curve it is measured against.
        margin: Points ``a`` must win by. A positive margin answers "is this
            worth the roster move?" rather than "who is better?".
        points: Quadrature resolution.

    Returns:
        A probability in [0, 1].
    """
    if points < 2:
        raise ValueError("need at least two quadrature points")
    step = 1.0 / points
    total = 0.0
    for index in range(points):
        outcome_a = a.quantile((index + 0.5) * step)
        total += b.cdf(outcome_a - margin)
    return min(1.0, max(0.0, total * step))


def compare(
    a: OutcomeCurve,
    b: OutcomeCurve,
    *,
    margin: float = 0.0,
    correlated: bool = False,
) -> HeadToHead:
    """Compare two outcome curves.

    The expected margin uses each curve's stored :attr:`~OutcomeCurve.expected`
    when available and falls back to the reconstruction's own mean. Stored is
    preferred because it is the number the calibration actually measured — the
    reconstruction's mean depends on the tail assumption, and the stored one
    does not.
    """
    mean_a = a.expected if a.expected is not None else a.mean()
    mean_b = b.expected if b.expected is not None else b.mean()
    return HeadToHead(
        win_probability=probability_beats(a, b, margin=margin),
        expected_margin=mean_a - mean_b,
        correlated=correlated,
    )


def probability_total_at_least(
    curves: Sequence[OutcomeCurve], threshold: float
) -> float:
    """``P(sum of outcomes >= threshold)`` for a set of players.

    A normal approximation, and deliberately so — this is a sum of several
    independent right-skewed variables, and the central limit theorem is doing
    real work by the time a lineup has six or more players. The individual
    curves are *not* approximated anywhere else in this module; only their sum
    is, and only because an exact convolution of piecewise-linear curves would
    cost far more than the accuracy is worth for a lineup-level number.

    Independence is the load-bearing assumption
    ------------------------------------------
    Variances are summed in quadrature, which is only valid for uncorrelated
    outcomes. A real fantasy lineup is not uncorrelated: teammates divide one
    offence's plays, and any two players in the same game share pace and script.
    The error is concentrated in the **spread**, not the centre — the total
    stays about right while the interval comes out too narrow, which makes the
    floor and the ceiling the least trustworthy numbers this function produces.

    Callers assembling a lineup should pair this with
    :func:`nflfp.services.rosters.lineup_caveats`, which reports exactly which
    players break the assumption. Correcting for it needs a fitted correlation
    structure; see ``docs/simulation-readiness.md``.

    Returns ``0.0`` for an empty roster and for a degenerate sum, rather than
    dividing by a zero standard deviation.
    """
    if not curves:
        return 0.0
    mean = sum(c.expected if c.expected is not None else c.mean() for c in curves)
    # SD of each curve from its own reconstruction, then summed in quadrature.
    variance = 0.0
    for curve in curves:
        spread = (curve.quantile(0.90) - curve.quantile(0.10)) / 2.563103  # z(0.9)-z(0.1)
        variance += spread * spread
    if variance <= 0.0:
        return 1.0 if mean >= threshold else 0.0
    z = (threshold - mean) / math.sqrt(variance)
    return 1.0 - _standard_normal_cdf(z)


def _standard_normal_cdf(z: float) -> float:
    """Φ(z), via the error function in the standard library."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _as_float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _as_int(value: object) -> int | None:
    return None if value is None else int(value)  # type: ignore[arg-type]
