"""Phase 6C: are the outcome curve's tail factors right at the *lineup* level?

The question
------------
:mod:`nflfp.services.distributions` reconstructs a player's distribution from
five stored percentiles and assumes the two tails, extending them over
``LOWER_TAIL_FACTOR`` and ``UPPER_TAIL_FACTOR`` multiples of the nearest
interior segment. Those two numbers were chosen from the shape of a *player's*
week. Nothing the product sells is a player's week: a start/sit call, a win
probability and a projected team total are all statements about a **sum of
seven curves**, and a tail assumption that is harmless for one player compounds
seven times when they are added.

Phase 6B measured the symptom without being able to act on it — the team total's
80% interval covered 82–83% of realised totals in both of its arms, which is a
property of the marginals, not of the correlation structure it was testing. This
module is the instrument that turns that observation into a decision.

What is measured, and against what
----------------------------------
The panel (:mod:`nflfp.correlation.panel`) is reused unchanged: 38,061
player-weeks, each one carrying the distribution a deployment would have
published *before* that week kicked off, plus what the player actually scored.
The leakage boundary is therefore inherited rather than re-argued — see that
module — and this phase adds one of its own: **factors are chosen on one set of
seasons and reported on another**, and the two never overlap.

Three levels, because they can disagree:

* **player** — coverage at each stored knot, CRPS, and the gap between the
  curve's implied mean and the stored calibrated one. Note that knot coverage is
  *invariant* to the tail factors by construction: the factors move mass below
  P10 and above P90 and cannot move the knots themselves. It is measured anyway,
  as the guard that a candidate has not been accepted for lineup reasons while
  quietly breaking the thing the calibration actually validated.
* **lineup** — the realised team total against the simulated one: knot
  calibration, 80% and 90% interval coverage, CRPS, and the PIT of the realised
  total within its own simulated distribution.
* **matchup** — win probability against the realised winner: Brier, log loss,
  ECE and maximum calibration error. Maximum calibration error is not optional
  and is not replaceable by ECE; see :mod:`nflfp.predict.calibration`.

Why the tails can be re-scored without re-simulating
----------------------------------------------------
A grid search over 36 candidate configurations, each one re-simulating thousands
of matchups, is hours of work for an answer that a decomposition gives exactly.
The uniforms a sampler draws do not depend on the tail factors — that is true of
the independent sampler and of the Gaussian copula alike — and the curve is
piecewise-linear with the factors entering **only** the two outer segments. So
for a fixed draw ``u``:

* ``0.10 <= u <= 0.90`` — the sampled value is independent of both factors;
* ``u < 0.10`` — the value is ``p10 - g(L) * (1 - u/0.10)``, where ``g`` is the
  lower gap, a function of the player and ``L`` alone;
* ``u > 0.90`` — the value is ``p90 + U * (p90 - p75) * (u - 0.90)/0.10``, exactly
  linear in ``U``.

:class:`LineupDraws` precomputes the parts that do not move once, and produces a
team total for any ``(L, U)`` in a single cheap pass. This is an optimisation and
not a second model: ``tests/test_tail_calibration.py`` asserts it reproduces the
production path — :meth:`OutcomeCurve.from_percentiles` at those factors, sampled
by :func:`nflfp.services.simulation.simulate` — to floating-point tolerance. If
that test ever fails, this module is wrong and the production path is right.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_left
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from statistics import mean

from ..correlation.evaluate import (
    LINEUP_SHAPE,
    STARTABLE_FLOOR,
    SyntheticMatchup,
    synthesise_matchups,
)
from ..correlation.model import CorrelationMode, CorrelationModel
from ..correlation.panel import Panel, PanelRow
from ..correlation.sampler import RosterMember, Sampler, build_sampler
from ..predict.calibration import (
    CalibrationBin,
    calibration_report,
    expected_calibration_error,
    max_calibration_error,
)
from ..predict.distribution import crps
from ..services.distributions import (
    HARD_FLOOR,
    LOWER_TAIL_FACTOR,
    UPPER_TAIL_FACTOR,
    OutcomeCurve,
)
from ..services.simulation import SCORING_PRECISION

#: The probability of the lowest and highest stored knots. Named because the
#: decomposition below is a statement about exactly these two boundaries.
LOWER_KNOT = 0.10
UPPER_KNOT = 0.90

#: Grid resolution for a player's own CRPS. The curve is piecewise-linear, so a
#: midpoint grid this fine is exact to well under a hundredth of a point — and
#: unlike a Monte Carlo estimate it is deterministic, which a metric that decides
#: a production constant has to be.
PLAYER_CRPS_POINTS = 512

#: Seasons candidates are chosen on. Nothing reported as a final result comes
#: from these weeks.
TUNING_SEASONS: tuple[int, ...] = (2022, 2023)

#: Seasons the chosen candidate is reported on. Never used for selection.
HELDOUT_SEASONS: tuple[int, ...] = (2024, 2025)

#: Bins for every PIT histogram in this module.
PIT_BINS = 10

#: Which conditional buckets one lineup belongs to. Pluggable because Phase 6C
#: and Phase 6D ask different questions of the same sweep: 6C splits by
#: projection band and stacking, 6D by what dependence the drawn lineup actually
#: contains. See :func:`_strata_keys` for the default.
StrataKeys = Callable[["LineupDraws", SyntheticMatchup], tuple[str, ...]]


@dataclass(frozen=True, order=True)
class TailFactors:
    """One candidate configuration of the two free parameters."""

    lower: float
    upper: float

    @classmethod
    def incumbent(cls) -> "TailFactors":
        """Whatever production currently ships. Read, never hard-coded."""
        return cls(lower=LOWER_TAIL_FACTOR, upper=UPPER_TAIL_FACTOR)

    @property
    def is_incumbent(self) -> bool:
        return self == TailFactors.incumbent()

    def as_pair(self) -> tuple[float, float]:
        return (self.lower, self.upper)

    def __str__(self) -> str:
        return f"L={self.lower:.2f}/U={self.upper:.2f}"


def build_curve(row: PanelRow, factors: TailFactors) -> OutcomeCurve:
    """A panel row's curve under a candidate configuration.

    Goes through :meth:`OutcomeCurve.from_percentiles`, so a candidate is
    evaluated on the reconstruction production would perform, not on a copy of
    it that could drift.
    """
    return row.curve(factors.as_pair())


# ---------------------------------------------------------------------------
# The decomposition
# ---------------------------------------------------------------------------


def lower_gap(p10: float, p25: float, lower_factor: float) -> float:
    """How far below P10 the curve reaches, as a positive distance.

    Mirrors ``_extend_tails`` exactly, including both clamps: the hard floor at
    :data:`~nflfp.services.distributions.HARD_FLOOR`, and the refusal to place
    the q=0 knot *above* P10 for a player whose stored P10 is already below the
    floor. Returned as a gap rather than as a value because the gap is what the
    decomposition multiplies.
    """
    value = min(p10, max(HARD_FLOOR, p10 - (p25 - p10) * lower_factor))
    return p10 - value


def upper_gap(p75: float, p90: float, upper_factor: float) -> float:
    """How far above P90 the curve reaches, as a positive distance."""
    return max(0.0, (p90 - p75) * upper_factor)


@dataclass
class LineupDraws:
    """One lineup's sampled totals, factorised into fixed and tail-dependent parts.

    Built from a matrix of uniforms — one row per iteration, one column per
    player — and then queried for any candidate configuration. The uniforms are
    drawn once and shared across every candidate, which is what makes the grid
    comparison *paired*: two configurations differ by their tails and by nothing
    else, exactly as the two arms of the Phase 6B backtest differed only by
    their sampler.
    """

    #: The whole total at ``lower=upper=0`` — the curve truncated at its stored
    #: knots. Every candidate is this plus its two tail contributions.
    base: list[float]
    #: Coefficient of ``upper``: the tail is exactly linear in it.
    upper_coefficient: list[float]
    #: Lower-tail draws, flattened. ``lower_index[k]`` is the player whose gap
    #: applies and ``lower_weight[k]`` how much of it, for the draws belonging to
    #: iteration ``t`` — ``lower_offset[t] : lower_offset[t + 1]``.
    lower_index: list[int]
    lower_weight: list[float]
    lower_offset: list[int]
    #: ``(p10, p25)`` per player, for evaluating the lower gap once per candidate.
    knees: list[tuple[float, float]]
    #: Sum of the stored calibrated means. The centre a total is compared against.
    projection_sum: float
    #: What the lineup actually scored.
    actual: float
    #: Players in the lineup, for the size and composition breakdowns.
    size: int
    #: The lineup itself, in draw order. Carried so a stratum function can ask
    #: what the lineup *is* — which players share a team, which share a game —
    #: rather than being limited to what the matchup generator was told to make.
    #: References, not copies; this costs a pointer per player.
    rows: tuple[PanelRow, ...] = ()

    def totals(self, factors: TailFactors) -> list[float]:
        """Team totals under one candidate, in iteration order.

        Iteration order, not sorted: a matchup pairs the two lineups draw by
        draw, and sorting here would silently decouple them.
        """
        gaps = [
            lower_gap(p10, p25, factors.lower) for p10, p25 in self.knees
        ]
        upper = factors.upper
        base = self.base
        coefficient = self.upper_coefficient
        index = self.lower_index
        weight = self.lower_weight
        offset = self.lower_offset

        out = [0.0] * len(base)
        for t in range(len(base)):
            total = base[t] + upper * coefficient[t]
            for k in range(offset[t], offset[t + 1]):
                total -= gaps[index[k]] * weight[k]
            out[t] = total
        return out


def draw_lineup(
    rows: Sequence[PanelRow],
    uniforms: Sequence[Sequence[float]],
    columns: Sequence[int],
) -> LineupDraws:
    """Factorise one lineup's draws.

    Args:
        rows: The lineup, in draw order.
        uniforms: ``iterations x players`` uniforms for the whole matchup.
        columns: Which column of ``uniforms`` belongs to each row.
    """
    knees = [(row.p10, row.p25) for row in rows]
    # The interior knots, as the quantile function sees them.
    interior = [
        ((0.10, row.p10), (0.25, row.p25), (0.50, row.p50),
         (0.75, row.p75), (0.90, row.p90))
        for row in rows
    ]
    spread_up = [row.p90 - row.p75 for row in rows]

    base: list[float] = []
    upper_coefficient: list[float] = []
    lower_index: list[int] = []
    lower_weight: list[float] = []
    lower_offset: list[int] = [0]

    for draw in uniforms:
        total = 0.0
        coefficient = 0.0
        for position, column in enumerate(columns):
            u = draw[column]
            if u < LOWER_KNOT:
                # Truncated value is P10; the candidate subtracts from there.
                total += interior[position][0][1]
                lower_index.append(position)
                lower_weight.append(1.0 - u / LOWER_KNOT)
            elif u > UPPER_KNOT:
                total += interior[position][-1][1]
                coefficient += spread_up[position] * (u - UPPER_KNOT) / (
                    1.0 - UPPER_KNOT
                )
            else:
                total += _interior_quantile(interior[position], u)
        base.append(total)
        upper_coefficient.append(coefficient)
        lower_offset.append(len(lower_index))

    return LineupDraws(
        base=base,
        upper_coefficient=upper_coefficient,
        lower_index=lower_index,
        lower_weight=lower_weight,
        lower_offset=lower_offset,
        knees=knees,
        projection_sum=sum(row.expected for row in rows),
        actual=sum(row.actual for row in rows),
        size=len(rows),
        rows=tuple(rows),
    )


def _interior_quantile(
    knots: Sequence[tuple[float, float]], u: float
) -> float:
    """Piecewise-linear interpolation between the stored knots.

    The same arithmetic :meth:`OutcomeCurve.quantile` performs, restricted to the
    segments no tail factor can move.
    """
    for (p_low, v_low), (p_high, v_high) in zip(knots, knots[1:]):
        if u <= p_high:
            span = p_high - p_low
            if span <= 0.0:  # pragma: no cover - stored knots are distinct
                return v_high
            return v_low + (v_high - v_low) * (u - p_low) / span
    return knots[-1][1]  # pragma: no cover - guarded by the caller


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def percentile(sorted_values: Sequence[float], probability: float) -> float:
    """Linear-interpolated percentile of a sorted sample.

    Deliberately the same definition as
    :func:`nflfp.services.simulation._percentile` (NumPy/R type 7), so a P10
    reported here is the P10 the product would report. The equivalence is
    asserted in the tests rather than left to a comment.
    """
    if not sorted_values:
        raise ValueError("cannot take a percentile of an empty sample")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = probability * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return float(
        sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight
    )


def pit_of(sorted_values: Sequence[float], actual: float) -> float:
    """Where an outcome fell inside its own simulated distribution."""
    position = bisect_left(sorted_values, actual)
    return min(0.9999, max(0.0001, position / len(sorted_values)))


#: The quantiles a distribution is checked at. The three interior ones catch a
#: shift that the two outer ones would miss.
KNOT_PROBABILITIES: tuple[float, ...] = (0.10, 0.25, 0.50, 0.75, 0.90)


@dataclass
class DistributionMetrics:
    """How well a set of distributions matched the outcomes they predicted."""

    label: str
    n: int = 0
    #: Observed share of outcomes at or below each nominal quantile. A
    #: well-calibrated P10 is exceeded downward 10% of the time.
    knot_coverage: tuple[float, ...] = ()
    coverage_80: float = 0.0
    coverage_90: float = 0.0
    mean_width_80: float = 0.0
    mean_width_90: float = 0.0
    crps: float = 0.0
    #: PIT histogram, and its total absolute deviation from uniform. The
    #: full-shape calibration measure — coverage only checks two thresholds.
    pit: tuple[float, ...] = ()
    pit_divergence: float = 0.0
    #: Mean of the distribution's own mean minus the sum of stored projections,
    #: absolute and as a share. This is the Phase 6A 4% gap, measured.
    mean_drift: float = 0.0
    mean_drift_share: float = 0.0
    mean_actual: float = 0.0
    mean_predicted: float = 0.0

    @property
    def coverage_error(self) -> float:
        """Mean absolute miss across the two nominal intervals."""
        return (abs(self.coverage_80 - 0.80) + abs(self.coverage_90 - 0.90)) / 2.0

    @property
    def knot_error(self) -> float:
        """Mean absolute miss across the five nominal quantiles."""
        if not self.knot_coverage:
            return 0.0
        return mean(
            abs(observed - nominal)
            for observed, nominal in zip(self.knot_coverage, KNOT_PROBABILITIES)
        )

    def __str__(self) -> str:
        knots = " ".join(f"{value:.3f}" for value in self.knot_coverage)
        return (
            f"{self.label:<22} n={self.n:>6,}  knots[{knots}]  "
            f"cov80={self.coverage_80:.4f}  cov90={self.coverage_90:.4f}  "
            f"CRPS={self.crps:.4f}  PITdiv={self.pit_divergence:.4f}  "
            f"drift={self.mean_drift:+.3f} ({self.mean_drift_share:+.2%})"
        )


@dataclass(frozen=True)
class PairedDelta:
    """One metric's paired difference between two configurations.

    Every cell of a sweep is scored on the **same lineups and the same draws**,
    so the per-observation difference isolates the tail configuration and
    nothing else. That pairing is what makes a difference of 0.007 in CRPS
    readable at all: unpaired, the standard deviation of a lineup's CRPS across
    2,876 lineups is around 7 points, so the standard error on its mean is ~0.13
    — twenty times the difference being looked for. Paired, the same difference
    is measured against the standard error of the *difference*, which is two
    orders of magnitude smaller.
    """

    metric: str
    n: int
    #: Candidate minus incumbent. The sign convention is stated per metric in
    #: the report, because "lower is better" is true of CRPS and false of
    #: coverage.
    delta: float
    standard_error: float

    @property
    def t_statistic(self) -> float:
        return self.delta / self.standard_error if self.standard_error else 0.0

    @property
    def significant(self) -> bool:
        """Two standard errors from zero. A sanity gate, not a hypothesis test."""
        return abs(self.t_statistic) >= 2.0

    def __str__(self) -> str:
        verdict = "significant" if self.significant else "indistinguishable from zero"
        return (
            f"{self.metric:<26} delta={self.delta:+.6f}  "
            f"se={self.standard_error:.6f}  t={self.t_statistic:+7.2f}  "
            f"n={self.n:,}  ({verdict})"
        )


def paired_delta(
    metric: str, incumbent: Sequence[float], candidate: Sequence[float]
) -> PairedDelta:
    """Mean paired difference and its standard error.

    Raises:
        ValueError: if the two series are different lengths, which would mean
            the two configurations were not scored on the same observations and
            the pairing — the entire basis of the comparison — is not real.
    """
    if len(incumbent) != len(candidate):
        raise ValueError(
            f"{metric}: {len(incumbent)} incumbent observation(s) against "
            f"{len(candidate)} candidate; these are not paired"
        )
    differences = [b - a for a, b in zip(incumbent, candidate)]
    n = len(differences)
    if n < 2:
        return PairedDelta(metric=metric, n=n, delta=0.0, standard_error=0.0)
    average = mean(differences)
    variance = sum((d - average) ** 2 for d in differences) / (n - 1)
    return PairedDelta(
        metric=metric, n=n, delta=average, standard_error=(variance / n) ** 0.5
    )


@dataclass
class _DistributionAccumulator:
    """Streams one distribution family's scores. Bounded memory by design."""

    label: str
    n: int = 0
    below: list[int] = field(default_factory=lambda: [0] * len(KNOT_PROBABILITIES))
    inside_80: int = 0
    inside_90: int = 0
    width_80: float = 0.0
    width_90: float = 0.0
    crps_total: float = 0.0
    pit_counts: list[int] = field(default_factory=lambda: [0] * PIT_BINS)
    drift_total: float = 0.0
    projection_total: float = 0.0
    predicted_total: float = 0.0
    actual_total: float = 0.0
    #: Per-observation scores, kept only when a paired test will be run on them.
    #: Off by default: the grid has 36 cells and does not need 36 copies of
    #: three thousand floats to report a mean.
    series: dict[str, list[float]] | None = None

    def add(
        self,
        sorted_totals: Sequence[float],
        actual: float,
        projection_sum: float,
    ) -> None:
        self.n += 1
        for index, probability in enumerate(KNOT_PROBABILITIES):
            if actual <= percentile(sorted_totals, probability):
                self.below[index] += 1

        p05 = percentile(sorted_totals, 0.05)
        p10 = percentile(sorted_totals, 0.10)
        p90 = percentile(sorted_totals, 0.90)
        p95 = percentile(sorted_totals, 0.95)
        self.inside_80 += int(p10 <= actual <= p90)
        self.inside_90 += int(p05 <= actual <= p95)
        self.width_80 += p90 - p10
        self.width_90 += p95 - p05

        score = crps(sorted_totals, actual)
        self.crps_total += score
        pit = pit_of(sorted_totals, actual)
        self.pit_counts[min(int(pit * PIT_BINS), PIT_BINS - 1)] += 1

        if self.series is not None:
            self.series["crps"].append(score)
            self.series["inside_80"].append(float(p10 <= actual <= p90))
            self.series["inside_90"].append(float(p05 <= actual <= p95))
            # Distance from the middle of the distribution. A calibrated
            # forecast puts this uniform on [0, 0.5], so its mean is 0.25 and a
            # paired shift in it is a paired shift in dispersion.
            self.series["pit_centrality"].append(abs(pit - 0.5))
            self.series["width_80"].append(p90 - p10)

        predicted = sum(sorted_totals) / len(sorted_totals)
        self.predicted_total += predicted
        self.projection_total += projection_sum
        self.drift_total += predicted - projection_sum
        self.actual_total += actual

    def result(self) -> DistributionMetrics:
        if not self.n:
            return DistributionMetrics(label=self.label)
        n = self.n
        pit = tuple(count / n for count in self.pit_counts)
        return DistributionMetrics(
            label=self.label,
            n=n,
            knot_coverage=tuple(count / n for count in self.below),
            coverage_80=self.inside_80 / n,
            coverage_90=self.inside_90 / n,
            mean_width_80=self.width_80 / n,
            mean_width_90=self.width_90 / n,
            crps=self.crps_total / n,
            pit=pit,
            pit_divergence=sum(abs(share - 1.0 / PIT_BINS) for share in pit),
            mean_drift=self.drift_total / n,
            mean_drift_share=(
                self.drift_total / self.projection_total
                if self.projection_total
                else 0.0
            ),
            mean_actual=self.actual_total / n,
            mean_predicted=self.predicted_total / n,
        )


@dataclass
class MatchupMetrics:
    """Win-probability quality for one configuration."""

    label: str
    n: int = 0
    brier: float = 0.0
    log_loss: float = 0.0
    ece: float = 0.0
    max_calibration_error: float = 0.0
    extreme_share: float = 0.0
    calibration: tuple[CalibrationBin, ...] = ()
    #: CRPS of the simulated score differential against the realised one, and
    #: the share of realised margins inside the simulated 80% band. A win
    #: probability is a threshold statistic; these two say whether the whole
    #: differential distribution is right.
    margin_crps: float = 0.0
    margin_coverage_80: float = 0.0

    def __str__(self) -> str:
        return (
            f"{self.label:<22} n={self.n:>6,}  Brier={self.brier:.5f}  "
            f"logloss={self.log_loss:.5f}  ECE={self.ece:.4f}  "
            f"maxCE={self.max_calibration_error:.4f}  "
            f"marginCRPS={self.margin_crps:.4f}  "
            f"marginCov80={self.margin_coverage_80:.4f}"
        )


@dataclass
class _MatchupAccumulator:
    label: str
    probabilities: list[float] = field(default_factory=list)
    outcomes: list[bool] = field(default_factory=list)
    margin_crps_total: float = 0.0
    margin_inside_80: int = 0
    series: dict[str, list[float]] | None = None
    #: Probability floor inside the logarithm only. A simulation legitimately
    #: returns 0.000; log(0) would make one matchup infinite and hide the rest.
    iterations: int = 1

    def add(
        self,
        win_probability: float,
        team_a_won: bool,
        sorted_margins: Sequence[float],
        actual_margin: float,
    ) -> None:
        self.probabilities.append(win_probability)
        self.outcomes.append(team_a_won)
        score = crps(sorted_margins, actual_margin)
        inside = float(
            percentile(sorted_margins, 0.10)
            <= actual_margin
            <= percentile(sorted_margins, 0.90)
        )
        self.margin_crps_total += score
        self.margin_inside_80 += int(inside)
        if self.series is not None:
            self.series["brier"].append((win_probability - float(team_a_won)) ** 2)
            self.series["margin_crps"].append(score)
            self.series["margin_inside_80"].append(inside)

    def result(self) -> MatchupMetrics:
        n = len(self.probabilities)
        if not n:
            return MatchupMetrics(label=self.label)
        floor = 1.0 / self.iterations
        report = calibration_report(self.probabilities, self.outcomes)
        return MatchupMetrics(
            label=self.label,
            n=n,
            brier=mean(
                (p - float(o)) ** 2
                for p, o in zip(self.probabilities, self.outcomes)
            ),
            log_loss=-mean(
                math.log(max(floor, min(1.0 - floor, p if o else 1.0 - p)))
                for p, o in zip(self.probabilities, self.outcomes)
            ),
            ece=expected_calibration_error(report),
            max_calibration_error=max_calibration_error(report),
            extreme_share=sum(
                1 for p in self.probabilities if p < 0.05 or p > 0.95
            ) / n,
            calibration=tuple(report),
            margin_crps=self.margin_crps_total / n,
            margin_coverage_80=self.margin_inside_80 / n,
        )


# ---------------------------------------------------------------------------
# Player level
# ---------------------------------------------------------------------------


@dataclass
class PlayerMetrics:
    """Player-level calibration under one configuration.

    Knot coverage here is invariant to the tail factors and is expected to be
    identical across candidates. It is reported because "the candidate did not
    touch what Layer 3b validated" is a claim that should be measured rather
    than asserted from the algebra.
    """

    label: str
    n: int
    knot_coverage: tuple[float, ...]
    crps: float
    #: Mean of ``curve.mean() - stored expected``, in points and as a share.
    #: The player-level half of the Phase 6A gap.
    mean_drift: float
    mean_drift_share: float
    #: ``(position, n, CRPS)``. Reported because one global pair of factors is
    #: only defensible if the error it leaves behind is not strongly positional.
    by_position: tuple[tuple[str, int, float], ...] = ()

    @property
    def knot_error(self) -> float:
        return mean(
            abs(observed - nominal)
            for observed, nominal in zip(self.knot_coverage, KNOT_PROBABILITIES)
        )

    def __str__(self) -> str:
        knots = " ".join(f"{value:.3f}" for value in self.knot_coverage)
        return (
            f"{self.label:<22} n={self.n:>6,}  knots[{knots}]  "
            f"CRPS={self.crps:.4f}  drift={self.mean_drift:+.3f} "
            f"({self.mean_drift_share:+.2%})"
        )


def player_metrics(
    rows: Sequence[PanelRow],
    factors: TailFactors,
    *,
    label: str | None = None,
    points: int = PLAYER_CRPS_POINTS,
) -> PlayerMetrics:
    """Score every player-week against its own published distribution."""
    step = 1.0 / points
    below = [0] * len(KNOT_PROBABILITIES)
    crps_total = 0.0
    drift_total = 0.0
    expected_total = 0.0
    per_position: dict[str, list[float]] = {}

    for row in rows:
        curve = build_curve(row, factors)
        sample = [curve.quantile((i + 0.5) * step) for i in range(points)]
        score = crps(sample, row.actual)
        crps_total += score
        per_position.setdefault(row.position, []).append(score)

        stored = (row.p10, row.p25, row.p50, row.p75, row.p90)
        for index, knot in enumerate(stored):
            if row.actual <= knot:
                below[index] += 1

        implied = sum(sample) / points
        drift_total += implied - row.expected
        expected_total += row.expected

    n = max(1, len(rows))
    return PlayerMetrics(
        label=label or f"player {factors}",
        n=len(rows),
        knot_coverage=tuple(count / n for count in below),
        crps=crps_total / n,
        mean_drift=drift_total / n,
        mean_drift_share=drift_total / expected_total if expected_total else 0.0,
        by_position=tuple(
            (position, len(scores), sum(scores) / len(scores))
            for position, scores in sorted(per_position.items())
        ),
    )


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


@dataclass
class FactorResult:
    """Everything one candidate scored over one period."""

    factors: TailFactors
    lineup: DistributionMetrics
    matchup: MatchupMetrics
    #: Lineup metrics restricted to a stratum — projection band, stacking.
    strata: dict[str, DistributionMetrics] = field(default_factory=dict)
    #: Per-observation scores, present only when the sweep was asked for them.
    #: The input to :func:`paired_delta`.
    lineup_series: dict[str, list[float]] = field(default_factory=dict)
    matchup_series: dict[str, list[float]] = field(default_factory=dict)


@dataclass
class SweepResult:
    """A whole grid, over one period, from one set of draws."""

    period: str
    seasons: tuple[int, ...]
    weeks: int
    lineups: int
    matchups: int
    iterations: int
    results: dict[TailFactors, FactorResult]
    duration_seconds: float = 0.0

    def best(self) -> TailFactors:
        """The selection rule, stated once and applied mechanically.

        **Primary: lineup-total PIT divergence.** The full shape of the team
        total's calibration, not two thresholds of it — a candidate can hit 80%
        coverage exactly while being wrong everywhere in between.

        **Tie-break: lineup CRPS.** PIT divergence is blind to sharpness: a
        distribution can be perfectly uniform in PIT and needlessly wide. CRPS
        is a proper score and punishes that, so it breaks ties within the noise
        band of the primary metric.
        """
        candidates = sorted(
            self.results.values(),
            key=lambda r: (round(r.lineup.pit_divergence, 4), r.lineup.crps),
        )
        return candidates[0].factors


def run_sweep(
    panel: Panel,
    *,
    grid: Sequence[TailFactors],
    seasons: Sequence[int],
    period: str,
    matchups_per_week: int = 40,
    iterations: int = 2_000,
    seed: int = 20260801,
    stack_share: float = 0.35,
    opponent_share: float = 0.0,
    duel_share: float = 0.0,
    lineup_shape: Sequence[tuple[str, tuple[str, ...]]] = LINEUP_SHAPE,
    sampler_for: Callable[[Sequence[RosterMember], int, int], Sampler] | None = None,
    weeks_filter: Callable[[int, int], bool] | None = None,
    matchup_filter: Callable[[SyntheticMatchup], bool] | None = None,
    strata: bool = False,
    strata_keys: StrataKeys | None = None,
    collect_series: bool = False,
    progress: Callable[[str], None] | None = None,
) -> SweepResult:
    """Score every candidate on the same synthesised matchups and draws.

    One set of lineups, one set of uniforms, every candidate scored against
    them. That pairing is the whole design: a difference between two cells of
    the grid is the tail configuration and nothing else — not a different
    lineup, not a different draw, not a different week.

    Args:
        panel: The historical panel.
        grid: Candidate configurations.
        seasons: Seasons to evaluate. Selection and reporting use disjoint sets.
        period: A label for the report.
        matchups_per_week: Synthesised matchups per week; each yields two
            lineups, so the lineup sample is twice this.
        iterations: Monte Carlo draws per lineup.
        seed: Base seed. The lineup draw and the uniform draw are both derived
            from it, so the whole sweep is reproducible.
        stack_share: Share of lineups built around a QB stack.
        opponent_share: Share of lineups built around a QB and a skill player on
            the opposing sideline. Zero — the Phase 6B and 6C behaviour — leaves
            the generator's random stream untouched.
        duel_share: Share of matchups whose two quarterbacks face each other.
            Also zero by default, and also short-circuited.
        lineup_shape: Slots to fill. Varying this is how the lineup-size
            sensitivity in the report is produced.
        sampler_for: Builds the sampler for one matchup's roster. ``None`` is
            the independent sampler — the production behaviour.
        weeks_filter: Restricts which weeks are evaluated, used to align the
            independent arms with the correlated ones, which have no fitted
            structure for their first weeks.
        matchup_filter: Restricts which *matchups* are scored, so a population
            defined by the drawn lineups — "the two quarterbacks face each
            other" — can be reported with the full metric set rather than only
            as a lineup-level stratum. Applied before any draw, so a filtered
            sweep costs only the matchups it keeps.
        strata: Whether to accumulate the conditional breakdowns. Off during a
            grid search, where they would triple the cost for numbers only the
            baseline and the candidate need.
        strata_keys: Which buckets a lineup belongs to. Defaults to Phase 6C's
            projection band and stacking split; Phase 6D passes a finer one that
            reads the drawn lineup's composition.
        collect_series: Whether to keep per-observation scores for a paired
            test. Off during a grid search for the same reason.
    """
    import time

    started = time.monotonic()
    accumulators = {
        factors: (
            _DistributionAccumulator(
                label=f"lineup {factors}",
                series=(
                    {
                        key: []
                        for key in (
                            "crps", "inside_80", "inside_90", "pit_centrality",
                            "width_80",
                        )
                    }
                    if collect_series else None
                ),
            ),
            _MatchupAccumulator(
                label=f"matchup {factors}",
                iterations=iterations,
                series=(
                    {key: [] for key in ("brier", "margin_crps", "margin_inside_80")}
                    if collect_series else None
                ),
            ),
            {} if strata else None,
        )
        for factors in grid
    }

    weeks = 0
    lineups = 0
    matchups = 0
    for season, week in panel.weeks(seasons):
        if weeks_filter is not None and not weeks_filter(season, week):
            continue
        rows = panel.week(season, week)
        drawn = list(
            synthesise_matchups(
                rows,
                season=season,
                week=week,
                count=matchups_per_week,
                stack_share=stack_share,
                opponent_share=opponent_share,
                duel_share=duel_share,
                shape=lineup_shape,
                seed=seed + season * 100 + week,
            )
        )
        if matchup_filter is not None:
            drawn = [matchup for matchup in drawn if matchup_filter(matchup)]
        if not drawn:
            continue
        weeks += 1

        for matchup in drawn:
            outcome = _score_matchup(
                matchup,
                grid=grid,
                accumulators=accumulators,
                iterations=iterations,
                seed=seed + hash((season, week, matchup.index)) % 1_000_003,
                sampler_for=sampler_for,
                lineup_shape=lineup_shape,
                strata_keys=strata_keys or _strata_keys,
            )
            if outcome:
                matchups += 1
                lineups += 2
        if progress and weeks % 6 == 0:
            progress(f"    {period}: {weeks} week(s), {matchups:,} matchup(s)")

    results = {}
    for factors, (lineup, matchup, stratum) in accumulators.items():
        results[factors] = FactorResult(
            factors=factors,
            lineup=lineup.result(),
            matchup=matchup.result(),
            strata=(
                {key: value.result() for key, value in sorted(stratum.items())}
                if stratum is not None
                else {}
            ),
            lineup_series=lineup.series or {},
            matchup_series=matchup.series or {},
        )

    return SweepResult(
        period=period,
        seasons=tuple(seasons),
        weeks=weeks,
        lineups=lineups,
        matchups=matchups,
        iterations=iterations,
        results=results,
        duration_seconds=time.monotonic() - started,
    )


def _score_matchup(
    matchup: SyntheticMatchup,
    *,
    grid: Sequence[TailFactors],
    accumulators: dict,
    iterations: int,
    seed: int,
    sampler_for: Callable[[Sequence[RosterMember], int, int], Sampler] | None,
    lineup_shape: Sequence[tuple[str, tuple[str, ...]]],
    strata_keys: "StrataKeys",
) -> bool:
    """Draw once, score every candidate against the same draws."""
    rows = (*matchup.team_a, *matchup.team_b)
    members = [
        RosterMember(position=r.position, team=r.team, game_id=r.game_id)
        for r in rows
    ]
    sampler = (
        sampler_for(members, matchup.season, matchup.week)
        if sampler_for is not None
        else build_sampler(members, mode=CorrelationMode.INDEPENDENT)
    )

    rng = random.Random(seed)
    uniforms = [sampler.draw(rng) for _ in range(iterations)]

    split = len(matchup.team_a)
    draws_a = draw_lineup(matchup.team_a, uniforms, range(split))
    draws_b = draw_lineup(
        matchup.team_b, uniforms, range(split, split + len(matchup.team_b))
    )

    if round(draws_a.actual, SCORING_PRECISION) == round(
        draws_b.actual, SCORING_PRECISION
    ):
        # A realised tie has no winner to score a win probability against.
        return False

    team_a_won = draws_a.actual > draws_b.actual
    actual_margin = draws_a.actual - draws_b.actual

    for factors in grid:
        lineup_accumulator, matchup_accumulator, stratum = accumulators[factors]
        totals_a = draws_a.totals(factors)
        totals_b = draws_b.totals(factors)

        wins_a = 0
        decided = 0
        margins = [0.0] * iterations
        for index in range(iterations):
            a, b = totals_a[index], totals_b[index]
            margins[index] = a - b
            scored_a = round(a, SCORING_PRECISION)
            scored_b = round(b, SCORING_PRECISION)
            if scored_a != scored_b:
                decided += 1
                if scored_a > scored_b:
                    wins_a += 1
        margins.sort()
        totals_a.sort()
        totals_b.sort()

        lineup_accumulator.add(totals_a, draws_a.actual, draws_a.projection_sum)
        lineup_accumulator.add(totals_b, draws_b.actual, draws_b.projection_sum)
        matchup_accumulator.add(
            wins_a / iterations, team_a_won, margins, actual_margin
        )

        if stratum is not None:
            for draws, totals in ((draws_a, totals_a), (draws_b, totals_b)):
                for key in strata_keys(draws, matchup):
                    accumulator = stratum.get(key)
                    if accumulator is None:
                        accumulator = _DistributionAccumulator(label=key)
                        stratum[key] = accumulator
                    accumulator.add(totals, draws.actual, draws.projection_sum)
    return True


#: Projection-sum bands for the conditional breakdown. A seven-player half-PPR
#: lineup drawn from startable players projects to about 73 points, and these
#: split that into roughly equal thirds. They are *measured* boundaries: the
#: first version of this constant assumed a ~100-point lineup, put 2,872 of
#: 2,876 observations in one bucket, and answered nothing.
PROJECTION_BANDS: tuple[tuple[float, float], ...] = (
    (0.0, 66.0), (66.0, 79.0), (79.0, float("inf")),
)


def _strata_keys(draws: LineupDraws, matchup: SyntheticMatchup) -> tuple[str, ...]:
    """Which conditional buckets one lineup belongs to.

    Lineup size is deliberately absent: every lineup in one sweep has the same
    shape, so it would restate the overall row. The size question is answered by
    running the sweep again at a different shape.
    """
    band = next(
        f"projection {low:.0f}-{high:.0f}"
        for low, high in PROJECTION_BANDS
        if low <= draws.projection_sum < high
    )
    return (band, "stacked" if matchup.stacked else "unstacked")


# ---------------------------------------------------------------------------
# Correlated arms
# ---------------------------------------------------------------------------


def correlated_sampler_factory(
    models: dict[tuple[int, int], CorrelationModel | None],
) -> Callable[[Sequence[RosterMember], int, int], Sampler]:
    """A ``sampler_for`` that applies each week's own prior-fitted structure.

    Refuses to fall back to independence for a week with no model, for the same
    reason :func:`nflfp.correlation.build_sampler` does: an arm that silently
    became its own control is worse than one that fails.
    """

    def factory(
        members: Sequence[RosterMember], season: int, week: int
    ) -> Sampler:
        model = models.get((season, week))
        if model is None:
            raise ValueError(
                f"no correlation structure fitted before {season}w{week}; "
                "filter these weeks out rather than simulating them"
            )
        return build_sampler(
            members, mode=CorrelationMode.GAME_ENVIRONMENT, model=model
        )

    return factory


def weeks_with_models(
    models: dict[tuple[int, int], CorrelationModel | None],
) -> Callable[[int, int], bool]:
    """A ``weeks_filter`` keeping only weeks a correlated arm can simulate."""

    def keep(season: int, week: int) -> bool:
        return models.get((season, week)) is not None

    return keep


def startable_rows(panel: Panel, seasons: Sequence[int]) -> tuple[PanelRow, ...]:
    """The player-weeks a lineup can draw from, for the player-level metrics.

    Restricted to the startable floor because that is the population the lineup
    numbers are built from — scoring the whole panel would report calibration
    dominated by players no manager would start, and the two are not the same
    distribution.
    """
    wanted = set(seasons)
    return tuple(
        row
        for row in panel.rows
        if row.season in wanted and row.expected >= STARTABLE_FLOOR
    )


def default_grid(
    *,
    lower: Iterable[float] = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5),
    upper: Iterable[float] = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0),
) -> tuple[TailFactors, ...]:
    """The search grid.

    Centred on the Phase 6A-6C configuration (1.5, 2.5) and extended a full unit
    either side in both directions, at a 0.5 step. Two properties are
    deliberate. The grid **contains whatever production ships** — (1.5, 2.5) when
    Phase 6C searched it, (1.0, 2.0) since Phase 6D approved the recalibration —
    so the baseline is a cell of the same experiment rather than a separate run.
    And it **reaches zero on the lower factor**,
    because "do not extend the tail at all" is a real hypothesis given Phase 6B
    found the summed distribution over-dispersed, and a search that could not
    express it would be answering a narrower question than the one asked.

    Thirty-six cells against ~2,900 lineup observations per period is roughly
    eighty observations per cell — coarse enough to resist the overfitting a
    finer grid would invite, and the report reads the *surface* rather than the
    argmin for the same reason.
    """
    return tuple(
        TailFactors(lower=low, upper=high) for low in lower for high in upper
    )
