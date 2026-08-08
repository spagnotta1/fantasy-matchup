"""Calibration analysis.

Why more than one metric
------------------------
Expected Calibration Error is sample-weighted, so a handful of catastrophically
overconfident predictions barely move it. Measured in phase 3a, boom
probabilities scored **ECE 0.006** — apparently excellent — while the 0.9-1.0
band stated 94% and delivered 17%. Those are exactly the projections a user acts
on.

So this module reports, and never collapses to, a single number:

* :func:`expected_calibration_error` — sample-weighted average gap. Answers
  "is the typical probability about right?"
* :func:`max_calibration_error` — worst adequately-sampled bin. Answers "is any
  confident claim badly wrong?" **Both are required.** Neither replaces the other.
* :func:`interval_coverage` — do stated 80% intervals contain 80% of outcomes?
* :func:`by_projection_range` — the high end evaluated on its own, since that is
  where pooling hides failure.
* :func:`by_position` — reported where sample size justifies it.

Binning
-------
Probability bins are fixed-width because the question is about the probability
scale itself; but every bin carries its count, and
:func:`max_calibration_error` ignores bins too small to distinguish error from
noise. Reporting a 100% gap from three observations would be worse than
reporting nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: Bins below this size are excluded from max error — three coin flips are not
#: evidence of miscalibration.
MIN_BIN_FOR_MAX = 30

#: Reporting bands for projection magnitude. The top band is open-ended and is
#: the one that matters: it is where phase 3a failed.
PROJECTION_BANDS: tuple[tuple[float, float], ...] = (
    (0.0, 5.0), (5.0, 10.0), (10.0, 15.0),
    (15.0, 20.0), (20.0, 25.0), (25.0, 30.0), (30.0, float("inf")),
)


@dataclass
class CalibrationBin:
    """One probability bin: what was claimed against what happened."""

    lower: float
    upper: float
    count: int
    mean_predicted: float
    observed_rate: float

    @property
    def error(self) -> float:
        return abs(self.mean_predicted - self.observed_rate)

    @property
    def reliable(self) -> bool:
        return self.count >= MIN_BIN_FOR_MAX


def calibration_report(
    predicted_probabilities: Sequence[float],
    outcomes: Sequence[bool],
    bins: int = 10,
) -> list[CalibrationBin]:
    """Bin stated probabilities and compare against observed rates."""
    if len(predicted_probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must be the same length")

    grouped: dict[int, list[tuple[float, bool]]] = {}
    for probability, outcome in zip(predicted_probabilities, outcomes):
        index = min(int(probability * bins), bins - 1)
        grouped.setdefault(index, []).append((probability, outcome))

    return [
        CalibrationBin(
            lower=index / bins,
            upper=(index + 1) / bins,
            count=len(pairs),
            mean_predicted=sum(p for p, _ in pairs) / len(pairs),
            observed_rate=sum(1 for _, o in pairs if o) / len(pairs),
        )
        for index, pairs in sorted(grouped.items())
    ]


def expected_calibration_error(report: Sequence[CalibrationBin]) -> float:
    """Sample-weighted mean gap between stated and observed probability.

    **Never read alone.** Being sample-weighted, it rates a model excellent when
    its rare confident predictions are catastrophically wrong. Always pair with
    :func:`max_calibration_error`.
    """
    total = sum(b.count for b in report)
    if not total:
        return 0.0
    return sum(b.count * b.error for b in report) / total


def max_calibration_error(
    report: Sequence[CalibrationBin], min_count: int = MIN_BIN_FOR_MAX
) -> float:
    """Worst gap among adequately-sampled bins.

    The metric that catches confident nonsense. Retained deliberately: ECE does
    not substitute for it, and it must not be removed.
    """
    eligible = [b.error for b in report if b.count >= min_count]
    return max(eligible) if eligible else 0.0


def weighted_calibration_error(report: Sequence[CalibrationBin]) -> float:
    """ECE re-weighted toward confident bins.

    A middle ground: still an average, but it weights a bin by how strong a
    claim it makes (``|p - 0.5|``), so being wrong at 0.95 costs far more than
    being wrong at 0.55. Reported alongside the other two rather than instead
    of them.
    """
    weights = [b.count * (abs(b.mean_predicted - 0.5) + 0.1) for b in report]
    total = sum(weights)
    if not total:
        return 0.0
    return sum(w * b.error for w, b in zip(weights, report)) / total


@dataclass
class CoverageResult:
    """Whether a stated interval contains the stated share of outcomes."""

    label: str
    nominal: float
    observed: float
    n: int
    mean_width: float

    @property
    def gap(self) -> float:
        return self.observed - self.nominal

    @property
    def verdict(self) -> str:
        if abs(self.gap) <= 0.03:
            return "calibrated"
        return "too narrow" if self.gap < 0 else "too wide"

    def __str__(self) -> str:
        return (
            f"{self.label:<10} nominal={self.nominal:.2f} observed={self.observed:.3f} "
            f"({self.verdict:<11}) width={self.mean_width:5.1f} n={self.n:,}"
        )


def interval_coverage(
    bounds: Sequence[tuple[float, float]],
    actuals: Sequence[float],
    nominal: float,
    label: str,
) -> CoverageResult:
    """Fraction of actuals inside the given intervals.

    Reported with mean width, because coverage alone is gameable: an interval of
    0 to 100 achieves perfect coverage and says nothing. Width is what
    distinguishes a sharp calibrated forecast from a vacuous one.
    """
    if len(bounds) != len(actuals):
        raise ValueError("bounds and actuals must be the same length")
    if not bounds:
        return CoverageResult(label, nominal, 0.0, 0, 0.0)

    inside = sum(1 for (low, high), a in zip(bounds, actuals) if low <= a <= high)
    width = sum(high - low for low, high in bounds) / len(bounds)
    return CoverageResult(label, nominal, inside / len(bounds), len(bounds), width)


@dataclass
class RangeCalibration:
    """Point and distribution quality within one projection band."""

    label: str
    n: int
    mean_predicted: float
    mean_actual: float
    bias: float
    mae: float
    coverage_80: float
    mean_p90: float
    exceed_p90_rate: float

    @property
    def reliable(self) -> bool:
        """Whether the band has enough data to draw a conclusion from."""
        return self.n >= MIN_BIN_FOR_MAX

    def __str__(self) -> str:
        flag = "" if self.reliable else "  (!! small sample)"
        return (
            f"{self.label:<9} n={self.n:>6,}  pred={self.mean_predicted:5.1f} "
            f"actual={self.mean_actual:5.1f}  bias={self.bias:+6.2f}  "
            f"MAE={self.mae:5.2f}  cov80={self.coverage_80:.3f}  "
            f">P90={self.exceed_p90_rate:.3f}{flag}"
        )


def by_projection_range(
    predicted: Sequence[float],
    actual: Sequence[float],
    p10: Sequence[float],
    p90: Sequence[float],
    bands: Sequence[tuple[float, float]] = PROJECTION_BANDS,
) -> list[RangeCalibration]:
    """Calibration within each projection band.

    The analysis phase 3a was missing. Pooling hides high-end failure because
    the high end is rare — 44 observations above 30 projected points against
    24,565 below 5 — so it must be evaluated on its own terms, with the sample
    size shown so a reader can judge how much to trust it.
    """
    results = []
    for low, high in bands:
        indices = [i for i, p in enumerate(predicted) if low <= p < high]
        if not indices:
            continue
        label = f"{low:.0f}-{high:.0f}" if high != float("inf") else f"{low:.0f}+"
        band_pred = [predicted[i] for i in indices]
        band_actual = [actual[i] for i in indices]
        errors = [band_pred[j] - band_actual[j] for j in range(len(indices))]
        inside = sum(
            1 for i in indices if p10[i] <= actual[i] <= p90[i]
        )
        above = sum(1 for i in indices if actual[i] > p90[i])
        results.append(
            RangeCalibration(
                label=label,
                n=len(indices),
                mean_predicted=sum(band_pred) / len(indices),
                mean_actual=sum(band_actual) / len(indices),
                bias=sum(errors) / len(indices),
                mae=sum(abs(e) for e in errors) / len(indices),
                coverage_80=inside / len(indices),
                mean_p90=sum(p90[i] for i in indices) / len(indices),
                exceed_p90_rate=above / len(indices),
            )
        )
    return results


def by_position(
    positions: Sequence[str],
    predicted: Sequence[float],
    actual: Sequence[float],
    p10: Sequence[float],
    p90: Sequence[float],
    min_samples: int = 200,
) -> dict[str, CoverageResult]:
    """Interval coverage per position, where the sample justifies reporting it."""
    grouped: dict[str, list[int]] = {}
    for index, position in enumerate(positions):
        grouped.setdefault(position, []).append(index)

    results = {}
    for position, indices in sorted(grouped.items()):
        if len(indices) < min_samples:
            continue
        results[position] = interval_coverage(
            [(p10[i], p90[i]) for i in indices],
            [actual[i] for i in indices],
            nominal=0.80,
            label=position,
        )
    return results


def by_sample_size(
    games_in_window: Sequence[float],
    predicted: Sequence[float],
    actual: Sequence[float],
    p10: Sequence[float],
    p90: Sequence[float],
) -> dict[str, CoverageResult]:
    """Coverage grouped by how much history the projection rests on.

    Answers whether thin-evidence projections are quietly overconfident — a
    distribution fitted mostly on well-established players can be too narrow for
    the rookie it is applied to.
    """
    grouped: dict[str, list[int]] = {}
    for index, games in enumerate(games_in_window):
        key = "no history" if not games else f"{int(games)} game(s)"
        grouped.setdefault(key, []).append(index)

    return {
        key: interval_coverage(
            [(p10[i], p90[i]) for i in indices],
            [actual[i] for i in indices],
            nominal=0.80,
            label=key,
        )
        for key, indices in sorted(grouped.items())
        if len(indices) >= 100
    }
