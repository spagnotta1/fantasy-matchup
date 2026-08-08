"""Walk-forward backtesting with held-out residual distributions.

The temporal scheme
-------------------
For each week ``N`` in the evaluation range:

.. code-block:: text

    weeks < N ────────────► fit base model ────► predict week N
        │                                              │
        │ residuals accumulated from earlier            │
        │ weeks, each produced by a model               ▼
        └── that had not seen its own week ──► fit residual model
                                                        │
                                                        ▼
                                              distribution for week N
                                                        │
                                                        ▼
                                          evaluated against week N actuals

The residual model for week ``N`` is fitted **only** on residuals from weeks
strictly before ``N``, and each of those residuals came from a base model
trained before *its* own week. So every residual is out-of-fold twice over:
out-of-fold with respect to the base model that produced it, and in the past
with respect to the week it is used to describe.

This is what phase 3a lacked. There, residuals were fitted on the same
predictions they were then scored against, which flatters interval width — the
model has already seen those outcomes. The numbers below are what a deployment
would actually have produced.

A burn-in is unavoidable: the earliest weeks have no residual history to fit on,
so their distributions are not evaluated. Point accuracy is still measured from
the first week.

What is available at prediction time
------------------------------------
For a projection generated on the Thursday before week ``N``: every completed
game through week ``N-1``, the schedule, and the feature contract in
:mod:`nflfp.predict.features`. Nothing from week ``N`` itself, and no market or
weather column — see that module for the measurement behind the exclusion.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import mean

from ..scoring import PROFILES
from .calibration import (
    CoverageResult,
    RangeCalibration,
    by_position,
    by_projection_range,
    by_sample_size,
    calibration_report,
    expected_calibration_error,
    interval_coverage,
    max_calibration_error,
    weighted_calibration_error,
)
from .dataset import assert_no_leakage, walk_forward
from .distribution import (
    BOOM_THRESHOLD,
    BUST_THRESHOLD,
    PointDistribution,
    ResidualDistribution,
    crps,
    pinball_loss,
)
from .scoring_bridge import score_components

logger = logging.getLogger(__name__)

DEFAULT_PROFILE = "half_ppr"

#: Residual observations required before a distribution is fitted at all.
MIN_RESIDUALS_TO_FIT = 2000


@dataclass
class Prediction:
    """One backtested prediction, its distribution, and the outcome."""

    player_id: str
    season: int
    week: int
    position: str
    predicted: float
    actual: float
    games_in_window: float = 0.0
    distribution: PointDistribution | None = None
    crps: float | None = None

    @property
    def error(self) -> float:
        return self.predicted - self.actual


@dataclass
class PositionMetrics:
    """Point accuracy for one position."""

    position: str
    n: int
    mae: float
    rmse: float
    bias: float
    pearson: float
    spearman: float

    def __str__(self) -> str:
        return (
            f"{self.position:<3} n={self.n:>6,}  MAE={self.mae:5.2f}  "
            f"RMSE={self.rmse:5.2f}  bias={self.bias:+5.2f}  "
            f"r={self.pearson:.3f}  rho={self.spearman:.3f}"
        )


@dataclass
class BacktestResult:
    """Everything one backtest produced."""

    model_name: str
    model_version: str
    profile: str
    weeks: int
    predictions: list[Prediction] = field(default_factory=list)
    by_position: dict[str, PositionMetrics] = field(default_factory=dict)
    calibration_ece: dict[str, float] = field(default_factory=dict)
    calibration_max: dict[str, float] = field(default_factory=dict)
    calibration_weighted: dict[str, float] = field(default_factory=dict)
    coverage: list[CoverageResult] = field(default_factory=list)
    coverage_by_position: dict[str, CoverageResult] = field(default_factory=dict)
    coverage_by_sample_size: dict[str, CoverageResult] = field(default_factory=dict)
    ranges: list[RangeCalibration] = field(default_factory=list)
    mean_crps: float | None = None
    mean_pinball: float | None = None
    duration_seconds: float = 0.0

    @property
    def scored(self) -> list[Prediction]:
        """Predictions that carry a held-out distribution."""
        return [p for p in self.predictions if p.distribution is not None]

    def as_metrics(self) -> dict:
        """JSON-serialisable summary for ``model_runs.metrics``."""
        return {
            "profile": self.profile,
            "weeks": self.weeks,
            "n": len(self.predictions),
            "n_with_distribution": len(self.scored),
            "by_position": {
                position: {
                    "n": m.n, "mae": round(m.mae, 4), "rmse": round(m.rmse, 4),
                    "bias": round(m.bias, 4), "pearson": round(m.pearson, 4),
                    "spearman": round(m.spearman, 4),
                }
                for position, m in sorted(self.by_position.items())
            },
            "calibration_ece": {k: round(v, 4) for k, v in self.calibration_ece.items()},
            "calibration_max": {k: round(v, 4) for k, v in self.calibration_max.items()},
            "calibration_weighted": {
                k: round(v, 4) for k, v in self.calibration_weighted.items()
            },
            "coverage": {
                c.label: {"nominal": c.nominal, "observed": round(c.observed, 4),
                          "width": round(c.mean_width, 3), "n": c.n}
                for c in self.coverage
            },
            "projection_ranges": [
                {"band": r.label, "n": r.n, "bias": round(r.bias, 3),
                 "coverage_80": round(r.coverage_80, 3), "reliable": r.reliable}
                for r in self.ranges
            ],
            "mean_crps": round(self.mean_crps, 4) if self.mean_crps is not None else None,
            "mean_pinball": (
                round(self.mean_pinball, 4) if self.mean_pinball is not None else None
            ),
            "duration_seconds": round(self.duration_seconds, 1),
        }

    def report(self) -> str:
        lines = [
            f"{self.model_name} v{self.model_version} — {self.profile}, "
            f"{self.weeks} week(s), {len(self.predictions):,} prediction(s), "
            f"{len(self.scored):,} with held-out distribution, "
            f"{self.duration_seconds:.1f}s",
            "=" * 88,
            "POINT ACCURACY",
        ]
        lines.extend("  " + str(self.by_position[p]) for p in sorted(self.by_position))

        if self.coverage:
            lines += ["", "INTERVAL COVERAGE (held out)"]
            lines.extend("  " + str(c) for c in self.coverage)
        if self.mean_crps is not None:
            lines.append(f"  mean CRPS={self.mean_crps:.3f}  mean pinball={self.mean_pinball:.3f}")

        if self.calibration_ece:
            lines += ["", "PROBABILITY CALIBRATION"]
            for key in sorted(self.calibration_ece):
                lines.append(
                    f"  {key:<5} ECE={self.calibration_ece[key]:.3f}  "
                    f"max={self.calibration_max[key]:.3f}  "
                    f"weighted={self.calibration_weighted[key]:.3f}"
                )
            lines.append("  (ECE is sample-weighted and hides rare confident errors; read max too)")

        if self.ranges:
            lines += ["", "BY PROJECTION RANGE — the high end evaluated on its own"]
            lines.extend("  " + str(r) for r in self.ranges)

        if self.coverage_by_position:
            lines += ["", "COVERAGE BY POSITION (nominal 0.80)"]
            lines.extend("  " + str(c) for c in self.coverage_by_position.values())

        if self.coverage_by_sample_size:
            lines += ["", "COVERAGE BY EVIDENCE (nominal 0.80)"]
            lines.extend("  " + str(c) for c in self.coverage_by_sample_size.values())

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) < 2:
        return float("nan")
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else float("nan")


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks, ties shared — required for a correct Spearman."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    return _pearson(_ranks(xs), _ranks(ys))


def _metrics(position: str, predictions: Sequence[Prediction]) -> PositionMetrics:
    predicted = [p.predicted for p in predictions]
    actual = [p.actual for p in predictions]
    errors = [p.error for p in predictions]
    return PositionMetrics(
        position=position,
        n=len(predictions),
        mae=mean(abs(e) for e in errors),
        rmse=(mean(e * e for e in errors)) ** 0.5,
        bias=mean(errors),
        pearson=_pearson(predicted, actual),
        spearman=_spearman(predicted, actual),
    )


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------

def run_backtest(
    model_factory,
    rows: Sequence[dict],
    *,
    test_seasons: Sequence[int],
    profile: str = DEFAULT_PROFILE,
    fit_distribution: bool = True,
    min_residuals: int = MIN_RESIDUALS_TO_FIT,
) -> BacktestResult:
    """Walk forward, refitting the model and the residual distribution weekly.

    Args:
        model_factory: Zero-argument callable returning a fresh model. A factory
            rather than an instance so each fold trains from scratch.
        rows: Completed player-weeks.
        test_seasons: Seasons to evaluate.
        profile: Scoring profile to evaluate against.
        fit_distribution: Fit and evaluate held-out distributions.
        min_residuals: Residual history required before distributions are
            produced. Earlier weeks still contribute point accuracy.

    Returns:
        Point accuracy, coverage, calibration and per-range analysis.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown scoring profile {profile!r}")

    started = time.monotonic()
    actual_column = f"fp_{profile}_actual"
    predictions: list[Prediction] = []
    # Residuals from *earlier* weeks only. This list is the held-out sample.
    residual_history: list[tuple[str, float, float]] = []
    weeks = 0

    for split in walk_forward(rows, test_seasons=test_seasons):
        assert_no_leakage(split)

        model = model_factory()
        model.fit(split.train)

        # Fit the distribution on residuals from strictly earlier weeks. Doing
        # this *before* the current week's residuals are appended is what makes
        # the evaluation honest.
        distribution = None
        if fit_distribution and len(residual_history) >= min_residuals:
            distribution = ResidualDistribution().fit(residual_history)

        week_predictions: list[Prediction] = []
        for row, prediction in zip(split.test, model.predict(split.test)):
            actual = row.get(actual_column)
            if actual is None:
                continue
            points = score_components(
                prediction.components, position=prediction.position
            )[profile]

            entry = Prediction(
                player_id=prediction.player_id,
                season=prediction.season,
                week=prediction.week,
                position=prediction.position,
                predicted=points,
                actual=float(actual),
                games_in_window=float(row.get("games_in_window_l4") or 0),
            )
            if distribution is not None:
                try:
                    entry.distribution = distribution.apply(entry.position, points)
                    entry.crps = crps(
                        distribution.sample_quantiles(entry.position, points), entry.actual
                    )
                except ValueError:
                    pass  # position not represented in the history yet
            week_predictions.append(entry)

        predictions.extend(week_predictions)
        residual_history.extend(
            (p.position, p.predicted, p.actual) for p in week_predictions
        )
        weeks += 1
        if weeks % 20 == 0:
            logger.info("backtested %d week(s), %d prediction(s)", weeks, len(predictions))

    prototype = model_factory()
    result = BacktestResult(
        model_name=prototype.name,
        model_version=prototype.version,
        profile=profile,
        weeks=weeks,
        predictions=predictions,
        duration_seconds=time.monotonic() - started,
    )

    grouped: dict[str, list[Prediction]] = {}
    for prediction in predictions:
        grouped.setdefault(prediction.position, []).append(prediction)
    result.by_position = {
        position: _metrics(position, group) for position, group in grouped.items()
    }

    if result.scored:
        _evaluate_distributions(result)

    logger.info(
        "backtest complete: %d prediction(s), %d with distribution",
        len(predictions), len(result.scored),
    )
    return result


def _evaluate_distributions(result: BacktestResult) -> None:
    """Coverage, calibration and per-range analysis over the scored subset."""
    scored = result.scored
    actual = [p.actual for p in scored]
    # Evaluated against the *calibrated* expectation, not the raw model output.
    # The raw shrunk value is conditionally biased by construction; the
    # distribution's mean is what the system actually publishes and simulates
    # from, so it is what must be held to account.
    predicted = [p.distribution.expected_points for p in scored]
    p10 = [p.distribution.p10 for p in scored]
    p25 = [p.distribution.p25 for p in scored]
    p75 = [p.distribution.p75 for p in scored]
    p90 = [p.distribution.p90 for p in scored]

    result.coverage = [
        interval_coverage(list(zip(p10, p90)), actual, 0.80, "P10-P90"),
        interval_coverage(list(zip(p25, p75)), actual, 0.50, "P25-P75"),
    ]

    result.ranges = by_projection_range(predicted, actual, p10, p90)
    result.coverage_by_position = by_position(
        [p.position for p in scored], predicted, actual, p10, p90
    )
    result.coverage_by_sample_size = by_sample_size(
        [p.games_in_window for p in scored], predicted, actual, p10, p90
    )

    for label, threshold, above in (
        ("boom", BOOM_THRESHOLD, True),
        ("bust", BUST_THRESHOLD, False),
    ):
        probabilities = [
            p.distribution.boom_probability if above else p.distribution.bust_probability
            for p in scored
        ]
        outcomes = [
            (p.actual >= threshold) if above else (p.actual <= threshold) for p in scored
        ]
        report = calibration_report(probabilities, outcomes)
        result.calibration_ece[label] = expected_calibration_error(report)
        result.calibration_max[label] = max_calibration_error(report)
        result.calibration_weighted[label] = weighted_calibration_error(report)

    scored_crps = [p.crps for p in scored if p.crps is not None]
    if scored_crps:
        result.mean_crps = mean(scored_crps)

    losses = []
    for prediction in scored:
        band = prediction.distribution
        for value, q in ((band.p10, 0.10), (band.p25, 0.25), (band.p50, 0.50),
                         (band.p75, 0.75), (band.p90, 0.90)):
            losses.append(pinball_loss(value, prediction.actual, q))
    if losses:
        result.mean_pinball = mean(losses)


def compare(results: Sequence[BacktestResult]) -> str:
    """Side-by-side MAE and Spearman, so 'did it beat the baseline?' is one read."""
    positions = sorted({p for r in results for p in r.by_position})
    lines = [f"{'model':<24} " + "  ".join(f"{p:>14}" for p in positions), "-" * 90]
    for result in results:
        cells = []
        for position in positions:
            metrics = result.by_position.get(position)
            cells.append(
                f"{metrics.mae:5.2f}/{metrics.spearman:.3f}" if metrics else " " * 11
            )
        lines.append(f"{result.model_name:<24} " + "  ".join(f"{c:>14}" for c in cells))
    lines += ["", "cells are MAE/Spearman — lower MAE and higher Spearman are better"]
    return "\n".join(lines)
