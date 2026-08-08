"""The frozen prediction foundation, and the bar a successor has to clear.

Phase 3b is **frozen**. ``shrinkage_eb`` is the validated model the application
is built on, and the numbers below are the ones it actually produced on a
walk-forward backtest — not targets, not aspirations, measurements. Everything
above this module (the business layer, the API, the UI) is built against these
guarantees, so changing the model means re-earning them rather than merely
passing the tests.

Why freeze at all
-----------------
A projection product has two failure modes and only one of them is visible. A
model that crashes gets fixed on Sunday morning. A model that quietly gets 8%
worse ships, renders beautifully, and costs people their week. Freezing means
the shipped foundation has a written, machine-readable description of what it
was measured to do, so "is the new model actually better?" is a question with a
procedure rather than an opinion.

What "frozen" does and does not mean
------------------------------------
It does **not** mean the model is finished, and it does not stop anyone
registering a new one. It means:

* ``shrinkage_eb`` stays registered and reproducible at this version;
* :data:`VALIDATION` records what it measured, so drift is detectable;
* a challenger is promoted only by clearing :data:`ACCEPTANCE`, on the same
  walk-forward harness, over the same seasons — a model evaluated any other way
  has not been compared to this one, it has been compared to nothing.

The API surfaces this at ``/meta/model``, because a client showing projections
is entitled to know what produced them and how well it was shown to work.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The model the application is built on.
FROZEN_MODEL = "shrinkage_eb"

#: The phase that produced it. Bump only when a new foundation is frozen.
FOUNDATION_PHASE = "3b"

#: Seasons the walk-forward evaluation covered.
VALIDATION_SEASONS = (2019, 2020, 2021, 2022, 2023, 2024, 2025)


@dataclass(frozen=True)
class PositionBar:
    """The naive bar for one position, from ``baseline_l4``.

    "Last four games" is what a human does by eye. A model that does not beat
    it is worse than shipping nothing, because it carries the authority of a
    model without the accuracy — so these are floors, not goals.
    """

    position: str
    n: int
    mae: float
    rmse: float
    bias: float
    correlation: float
    spearman: float


#: ``baseline_l4`` over 2023-25: 54 weeks, 17,666 predictions. Nothing ships
#: without beating this.
BASELINE_BAR: tuple[PositionBar, ...] = (
    PositionBar("QB", 1_991, 6.63, 8.44, +0.29, 0.465, 0.454),
    PositionBar("RB", 4_584, 4.26, 6.10, +0.04, 0.606, 0.671),
    PositionBar("TE", 3_694, 3.18, 4.52, +0.02, 0.493, 0.532),
    PositionBar("WR", 7_397, 4.05, 5.74, +0.08, 0.539, 0.602),
)


@dataclass(frozen=True)
class ValidationRecord:
    """What the frozen model was measured to do.

    Every field here came from a run of ``python -m nflfp.predict backtest``
    and ``calibration``; none was chosen. The interval and calibration numbers
    are the load-bearing ones, because the whole product is built on
    distributions rather than point estimates.
    """

    model: str
    phase: str
    seasons: tuple[int, ...]
    held_out_distributions: int

    coverage_p10_p90: float
    nominal_p10_p90: float
    width_p10_p90: float
    coverage_p25_p75: float
    nominal_p25_p75: float
    width_p25_p75: float

    crps: float
    pinball_loss: float

    boom_calibration_ece: float
    boom_calibration_max: float
    bust_calibration_ece: float
    bust_calibration_max: float

    #: Largest absolute conditional bias across projection bands with a usable
    #: sample. The headline result of 3b: the raw four-game average was -14.1
    #: at the top of the range.
    max_conditional_bias: float

    calibration_method: str
    notes: tuple[str, ...] = field(default_factory=tuple)


#: The frozen record. Reproduce with:
#:
#:     python -m nflfp.predict backtest shrinkage_eb --seasons 2022 2023 2024 2025
#:     python -m nflfp.predict calibration shrinkage_eb
VALIDATION = ValidationRecord(
    model=FROZEN_MODEL,
    phase=FOUNDATION_PHASE,
    seasons=VALIDATION_SEASONS,
    held_out_distributions=38_061,
    coverage_p10_p90=0.803,
    nominal_p10_p90=0.80,
    width_p10_p90=13.2,
    coverage_p25_p75=0.507,
    nominal_p25_p75=0.50,
    width_p25_p75=6.7,
    crps=2.927,
    pinball_loss=1.440,
    boom_calibration_ece=0.001,
    boom_calibration_max=0.130,
    bust_calibration_ece=0.006,
    bust_calibration_max=0.014,
    max_conditional_bias=0.10,
    calibration_method="heldout_residual_quantiles_v1",
    notes=(
        "Market features are excluded. Correlation with the lagged baseline's "
        "residual measured -0.039 to +0.021 across positions over 2019-2025, "
        "and nflverse's spread_line is a settled close for played games but a "
        "live capture for upcoming ones — two different objects.",
        "Weather features are excluded for the same reason: history carries "
        "observations, upcoming games carry forecasts.",
        "Projections beyond the fitted residual range are flagged "
        "`extrapolated` rather than given a confident interval.",
        "Kickers and defences are out of scope; they score under different "
        "rules and have no features. See nflfp.services.positions.",
    ),
)


@dataclass(frozen=True)
class AcceptanceCriteria:
    """What a challenger must demonstrate before it replaces the foundation.

    Deliberately stated as *tolerances against the frozen record* rather than
    as absolute numbers. A successor that improves point accuracy while
    quietly widening its intervals or decalibrating its boom probabilities is
    not an improvement — it is a trade, and it has to be made on purpose.
    """

    #: Interval coverage must stay within this of nominal. 3b achieved 0.003.
    max_coverage_error: float = 0.02

    #: Worst well-sampled calibration bin. 3b achieved 0.130 on boom.
    max_calibration_error: float = 0.15

    #: Conditional bias in every projection band with a usable sample.
    max_conditional_bias: float = 0.25

    #: A challenger must not be worse than the frozen model on CRPS, which is
    #: the single metric that scores the whole distribution rather than a
    #: summary of it.
    max_crps: float = 2.927

    #: And it must still beat the naive bar per position, on MAE.
    must_beat_baseline: bool = True

    #: Evaluated on the same harness. A random split is not a comparison.
    requires_walk_forward: bool = True


ACCEPTANCE = AcceptanceCriteria()


def foundation_summary() -> dict:
    """A JSON-serialisable description of the frozen foundation.

    Served by the API at ``/meta/model`` so a client can display — and a
    reviewer can audit — what produced the numbers on screen.
    """
    return {
        "model": VALIDATION.model,
        "phase": VALIDATION.phase,
        "frozen": True,
        "calibration_method": VALIDATION.calibration_method,
        "validation": {
            "seasons": list(VALIDATION.seasons),
            "held_out_distributions": VALIDATION.held_out_distributions,
            "interval_coverage": {
                "p10_p90": {
                    "observed": VALIDATION.coverage_p10_p90,
                    "nominal": VALIDATION.nominal_p10_p90,
                    "mean_width": VALIDATION.width_p10_p90,
                },
                "p25_p75": {
                    "observed": VALIDATION.coverage_p25_p75,
                    "nominal": VALIDATION.nominal_p25_p75,
                    "mean_width": VALIDATION.width_p25_p75,
                },
            },
            "crps": VALIDATION.crps,
            "pinball_loss": VALIDATION.pinball_loss,
            "calibration": {
                "boom": {
                    "ece": VALIDATION.boom_calibration_ece,
                    "max": VALIDATION.boom_calibration_max,
                },
                "bust": {
                    "ece": VALIDATION.bust_calibration_ece,
                    "max": VALIDATION.bust_calibration_max,
                },
            },
            "max_conditional_bias": VALIDATION.max_conditional_bias,
        },
        "baseline_bar": [
            {
                "position": bar.position,
                "n": bar.n,
                "mae": bar.mae,
                "rmse": bar.rmse,
                "bias": bar.bias,
                "correlation": bar.correlation,
                "spearman": bar.spearman,
            }
            for bar in BASELINE_BAR
        ],
        "acceptance": {
            "max_coverage_error": ACCEPTANCE.max_coverage_error,
            "max_calibration_error": ACCEPTANCE.max_calibration_error,
            "max_conditional_bias": ACCEPTANCE.max_conditional_bias,
            "max_crps": ACCEPTANCE.max_crps,
            "must_beat_baseline": ACCEPTANCE.must_beat_baseline,
            "requires_walk_forward": ACCEPTANCE.requires_walk_forward,
        },
        "excluded_inputs": list(VALIDATION.notes),
    }


def meets_acceptance(
    *,
    coverage_p10_p90: float,
    max_calibration_error: float,
    max_conditional_bias: float,
    crps: float,
) -> tuple[bool, tuple[str, ...]]:
    """Check a challenger's measurements against :data:`ACCEPTANCE`.

    Args:
        coverage_p10_p90: Observed P10-P90 interval coverage.
        max_calibration_error: Worst well-sampled calibration bin.
        max_conditional_bias: Largest absolute bias across projection bands.
        crps: Continuous ranked probability score, lower better.

    Returns:
        ``(passed, reasons)``. ``reasons`` lists every failure, not just the
        first — a model that misses on three counts should be told so once.
    """
    failures: list[str] = []

    coverage_error = abs(coverage_p10_p90 - VALIDATION.nominal_p10_p90)
    if coverage_error > ACCEPTANCE.max_coverage_error:
        failures.append(
            f"P10-P90 coverage {coverage_p10_p90:.3f} is {coverage_error:.3f} from "
            f"nominal {VALIDATION.nominal_p10_p90:.2f}; "
            f"limit {ACCEPTANCE.max_coverage_error:.2f}"
        )
    if max_calibration_error > ACCEPTANCE.max_calibration_error:
        failures.append(
            f"worst calibration bin {max_calibration_error:.3f} exceeds "
            f"{ACCEPTANCE.max_calibration_error:.2f}"
        )
    if max_conditional_bias > ACCEPTANCE.max_conditional_bias:
        failures.append(
            f"conditional bias {max_conditional_bias:.3f} exceeds "
            f"{ACCEPTANCE.max_conditional_bias:.2f} points"
        )
    if crps > ACCEPTANCE.max_crps:
        failures.append(
            f"CRPS {crps:.3f} is worse than the frozen foundation's "
            f"{ACCEPTANCE.max_crps:.3f}"
        )

    return (not failures, tuple(failures))
