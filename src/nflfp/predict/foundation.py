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

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from .calibration import COVERAGE_TOLERANCE

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


#: Seasons :data:`BASELINE_BAR` was measured over.
BASELINE_SEASONS = (2023, 2024, 2025)

#: ``baseline_l4`` over 2023-25: 54 weeks, 17,666 predictions. Nothing ships
#: without beating this.
#:
#: These numbers are a property of *those three seasons*, not of the baseline:
#: over 2019-2025 the same model scores RB 4.50 and WR 4.24 against 4.26 and
#: 4.05 here, because the earlier seasons are harder to project. Comparing a
#: model measured on other seasons against this record compares seasons, not
#: models. Evaluations therefore measure ``baseline_l4`` on the seasons they
#: evaluate and pass it to :func:`meets_acceptance`; this record is the
#: fallback for a caller that evaluates exactly :data:`BASELINE_SEASONS`.
BASELINE_BAR: tuple[PositionBar, ...] = (
    PositionBar("QB", 1_991, 6.63, 8.44, +0.29, 0.465, 0.454),
    PositionBar("RB", 4_584, 4.26, 6.10, +0.04, 0.606, 0.671),
    PositionBar("TE", 3_694, 3.18, 4.52, +0.02, 0.493, 0.532),
    PositionBar("WR", 7_397, 4.05, 5.74, +0.08, 0.539, 0.602),
)


#: Games in a full trailing window. A projection made on fewer rests on a
#: "short history", which is the one property of a single projection that was
#: measured to change how much its range can be trusted.
FULL_WINDOW_GAMES = 4


@dataclass(frozen=True)
class ShortHistoryCoverage:
    """P10-P90 coverage for projections made on a short history.

    One cell per scoring profile and position, over every held-out projection
    whose player had fewer than :data:`FULL_WINDOW_GAMES` games in the trailing
    window (including none).
    """

    profile: str
    position: str
    n: int
    coverage_p10_p90: float


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

    #: The same P10-P90 coverage for projections made on a short history, by
    #: scoring profile and position. This is the measurement behind the "short
    #: history" caveat a reader sees beside a range: the caveat is raised for
    #: exactly the cells :func:`undercovered_short_history` returns, and for no
    #: others.
    short_history_coverage: tuple[ShortHistoryCoverage, ...] = field(default_factory=tuple)


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
    # The frozen model on the frozen harness over the frozen seasons, once per
    # league profile that has recorded outcomes to score against
    # (`ppr_te_premium` has no `fp_*_actual` column, so it has no measurement).
    # 2,868 of the 38,061 held-out distributions rest on a short history; the
    # other 35,193 cover 0.803-0.805 in every profile. Method and the reading
    # of these cells: docs/simulation-readiness.md, "Range evidence".
    short_history_coverage=(
        ShortHistoryCoverage("standard", "QB", 309, 0.718),
        ShortHistoryCoverage("standard", "RB", 775, 0.750),
        ShortHistoryCoverage("standard", "TE", 596, 0.790),
        ShortHistoryCoverage("standard", "WR", 1_188, 0.817),
        ShortHistoryCoverage("half_ppr", "QB", 309, 0.718),
        ShortHistoryCoverage("half_ppr", "RB", 775, 0.795),
        ShortHistoryCoverage("half_ppr", "TE", 596, 0.777),
        ShortHistoryCoverage("half_ppr", "WR", 1_188, 0.801),
        ShortHistoryCoverage("ppr", "QB", 309, 0.718),
        ShortHistoryCoverage("ppr", "RB", 775, 0.787),
        ShortHistoryCoverage("ppr", "TE", 596, 0.779),
        ShortHistoryCoverage("ppr", "WR", 1_188, 0.780),
    ),
)


def undercovered_short_history() -> dict[tuple[str, str], float]:
    """Short-history cells whose range was measured to hold too few outcomes.

    Keyed ``(profile, position)``, valued with the coverage measured there.
    "Too few" is the line the backtest report itself draws
    (:data:`~nflfp.predict.calibration.COVERAGE_TOLERANCE` below nominal), so a
    caveat shown to a user and the verdict printed in a report cannot disagree.

    For the frozen model that is quarterbacks in every profile (0.718, one
    measurement seen three times: a quarterback's points do not depend on the
    reception format) and running backs under standard scoring (0.750). The
    other eight cells sit between 0.777 and 0.817 and are deliberately absent —
    a caveat the measurement does not support is the same failure as a missing
    one.
    """
    return {
        (cell.profile, cell.position): cell.coverage_p10_p90
        for cell in VALIDATION.short_history_coverage
        if VALIDATION.nominal_p10_p90 - cell.coverage_p10_p90 > COVERAGE_TOLERANCE
    }


@dataclass(frozen=True)
class LineupCoverage:
    """How often a simulated lineup total's interval held the realised total.

    Measured at the lineup level, with every player drawn independently, on
    held-out historical lineups. This is the number that says what ignoring
    correlation costs, and it is why a caveat about correlated players may not
    claim the interval is too narrow.
    """

    profile: str
    lineups: int
    matchups: int
    nominal_80: float
    coverage_80: float
    nominal_90: float
    coverage_90: float


#: The independent sampler at the shipped tail factors, over every held-out
#: matchup. Source: docs/simulation-readiness.md, "Phase 6D", "All held-out
#: matchups". Any sentence shown to a user about what independence costs a
#: lineup total quotes these, and the tests pin it to them. Half-PPR only: it
#: is the one profile Phase 6D scored (see that section's limitations), so the
#: figure is quoted as a measurement of the sampler, not re-derived per profile.
LINEUP_INDEPENDENCE = LineupCoverage(
    profile="half_ppr",
    lineups=2_878,
    matchups=1_439,
    nominal_80=0.800,
    coverage_80=0.7943,
    nominal_90=0.900,
    coverage_90=0.8919,
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
    #: summary of it. Compared at :data:`CRPS_DECIMALS`, the precision the
    #: record was taken at.
    max_crps: float = 2.927

    #: And it must still beat the naive bar per position, on MAE.
    must_beat_baseline: bool = True

    #: Evaluated on the same harness. A random split is not a comparison.
    requires_walk_forward: bool = True


ACCEPTANCE = AcceptanceCriteria()

#: Decimal places :attr:`AcceptanceCriteria.max_crps` is recorded to. A run
#: scoring 2.9271 has tied the frozen 2.927, not lost to it: the record cannot
#: tell the two apart, and failing the incumbent on the fourth decimal of its
#: own number is a rounding artefact, not a finding.
CRPS_DECIMALS = 3


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
                "p10_p90_short_history": [
                    {
                        "profile": cell.profile,
                        "position": cell.position,
                        "n": cell.n,
                        "observed": cell.coverage_p10_p90,
                    }
                    for cell in VALIDATION.short_history_coverage
                ],
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
        "baseline_bar_seasons": list(BASELINE_SEASONS),
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
    mae_by_position: Mapping[str, float] | None = None,
    baseline_mae_by_position: Mapping[str, float] | None = None,
    walk_forward: bool | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Check a challenger's measurements against :data:`ACCEPTANCE`.

    All six criteria are enforced here. Two of them used to be declared on
    :class:`AcceptanceCriteria` and read by nothing: ``must_beat_baseline`` and
    ``requires_walk_forward`` were documented as required, reported in
    :func:`foundation_summary`, and never checked — so a challenger with a
    per-position MAE worse than ``baseline_l4``, or one evaluated on a random
    split, passed. Both now **fail closed**: absent evidence is a failure, not
    a pass, because the whole point of the freeze is that a successor is
    compared to this model rather than to nothing.

    Args:
        coverage_p10_p90: Observed P10-P90 interval coverage.
        max_calibration_error: Worst well-sampled calibration bin.
        max_conditional_bias: Largest absolute bias across projection bands.
        crps: Continuous ranked probability score, lower better.
        mae_by_position: Per-position MAE, which must beat ``baseline_l4`` at
            every position. Required while ``ACCEPTANCE.must_beat_baseline`` is
            set; omitting it is a failure.
        baseline_mae_by_position: ``baseline_l4``'s per-position MAE measured on
            the *same seasons* as ``mae_by_position``. When given, it is the
            bar. When omitted, :data:`BASELINE_BAR` is used, which is only a
            like-for-like comparison for an evaluation of
            :data:`BASELINE_SEASONS`.
        walk_forward: Whether the measurements came from a walk-forward
            harness. Required while ``ACCEPTANCE.requires_walk_forward`` is set;
            neither ``False`` nor ``None`` passes.

    Returns:
        ``(passed, reasons)``. ``reasons`` lists every failure, not just the
        first — a model that misses on three counts should be told so once.
    """
    failures: list[str] = []

    # NaN compares False against every limit, so without this a measurement
    # that failed to compute would pass every check it is the input to. A
    # non-finite value is reported here and skipped by its own comparison
    # below, so every *other* failure is still reported alongside it.
    for label, value in (
        ("P10-P90 coverage", coverage_p10_p90),
        ("worst calibration bin", max_calibration_error),
        ("conditional bias", max_conditional_bias),
        ("CRPS", crps),
    ):
        if value is None or not math.isfinite(value):
            failures.append(
                f"{label} is {value!r}, not a measurement; the criterion fails closed"
            )
    def measured(value: float | None) -> bool:
        return value is not None and math.isfinite(value)

    coverage_error = (
        abs(coverage_p10_p90 - VALIDATION.nominal_p10_p90) if measured(coverage_p10_p90) else 0.0
    )
    if coverage_error > ACCEPTANCE.max_coverage_error:
        failures.append(
            f"P10-P90 coverage {coverage_p10_p90:.3f} is {coverage_error:.3f} from "
            f"nominal {VALIDATION.nominal_p10_p90:.2f}; "
            f"limit {ACCEPTANCE.max_coverage_error:.2f}"
        )
    if measured(max_calibration_error) and max_calibration_error > ACCEPTANCE.max_calibration_error:
        failures.append(
            f"worst calibration bin {max_calibration_error:.3f} exceeds "
            f"{ACCEPTANCE.max_calibration_error:.2f}"
        )
    if measured(max_conditional_bias) and max_conditional_bias > ACCEPTANCE.max_conditional_bias:
        failures.append(
            f"conditional bias {max_conditional_bias:.3f} exceeds "
            f"{ACCEPTANCE.max_conditional_bias:.2f} points"
        )
    if measured(crps) and round(crps, CRPS_DECIMALS) > ACCEPTANCE.max_crps:
        failures.append(
            f"CRPS {crps:.3f} is worse than the frozen foundation's "
            f"{ACCEPTANCE.max_crps:.3f}"
        )

    if ACCEPTANCE.must_beat_baseline:
        if mae_by_position is None:
            failures.append(
                "per-position MAE was not supplied, so 'beats baseline_l4' "
                "could not be checked; the criterion fails closed"
            )
        else:
            if baseline_mae_by_position is None:
                bar_by_position = {bar.position: bar.mae for bar in BASELINE_BAR}
                source = f"recorded {BASELINE_SEASONS[0]}-{BASELINE_SEASONS[-1]}"
            else:
                bar_by_position = dict(baseline_mae_by_position)
                source = "same seasons"
            for bar in BASELINE_BAR:
                observed = mae_by_position.get(bar.position)
                baseline = bar_by_position.get(bar.position)
                if observed is None:
                    failures.append(
                        f"no MAE reported for {bar.position}; the bar covers "
                        "every position and a challenger clears all of them or "
                        "none"
                    )
                elif baseline is None or not math.isfinite(baseline):
                    failures.append(
                        f"no baseline_l4 MAE for {bar.position}; the criterion "
                        "fails closed"
                    )
                elif not math.isfinite(observed) or observed >= baseline:
                    failures.append(
                        f"{bar.position} MAE {observed:.3f} does not beat "
                        f"baseline_l4's {baseline:.3f} ({source})"
                    )

    if ACCEPTANCE.requires_walk_forward and walk_forward is not True:
        failures.append(
            "evaluation was not walk-forward"
            if walk_forward is False
            else "walk-forward evaluation was not attested; the criterion "
            "fails closed"
        )

    return (not failures, tuple(failures))
