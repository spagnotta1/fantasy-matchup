"""Fitting the correlation structure, without letting the future in.

The estimation sample
---------------------
Every ordered pair of players in the same game, in the same week, from the
:mod:`~nflfp.correlation.panel` — each represented by their **normal score**,
the outcome mapped through their own published distribution and then through
the inverse normal CDF. A correlation of normal scores is the parameter a
Gaussian copula consumes, and it is invariant to the shape of the marginal, so a
quarterback and a tight end contribute on the same scale despite scoring in
different units with different skew.

Conditioning on the startable population
----------------------------------------
Correlation between two players is not a constant — it rises sharply with how
much they are projected for. Measured on the same panel:

===============  =========  =========  ==========
projection floor  QB-WR same  QB-QB opp  n (QB-WR)
===============  =========  =========  ==========
0                    +0.132     +0.142      19,149
4                    +0.188     +0.139      12,628
6                    +0.236     +0.143       8,382
8                    +0.285     +0.162       5,119
10                   +0.312     +0.165       3,101
===============  =========  =========  ==========

The reason is mechanical. A player projected for two points is mostly a
question of whether he plays at all, and that is idiosyncratic; a player
projected for fifteen is a question of how the offence goes, and that is shared.
The game-level effect (``QB-QB opp``) barely moves, which is what one would
expect of an effect that is about the game rather than about the players.

A simulated lineup contains starters, so the estimate must be conditioned on
starters. :data:`PROJECTION_FLOOR` is 6.0 — high enough to be the startable
population, low enough that the headline cells still rest on thousands of pairs.
It is deliberately **below** the level of a typical starter, which makes the
fitted correlations an understatement for the players a real lineup holds. That
is the conservative direction: this phase's stated risk is a model that is
confidently wrong, and a correlation that is too small errs toward the Phase 6A
behaviour rather than away from it.

Walk-forward, for the same reason Layer 3 is
--------------------------------------------
:func:`walk_forward_models` fits the structure applied to week ``N`` on pairs
from weeks strictly before ``N`` — the panel's own marginals are already
out-of-fold, so a correlation fitted this way is out-of-fold twice, exactly as
:mod:`nflfp.predict.backtest` describes for the distributions.

It is cheap because the fit consumes **sufficient statistics** rather than
pairs: each cell accumulates counts and moments, so advancing a week adds one
week of pairs to a running total instead of re-scanning history. A season of
weekly refits costs about as much as one full-history fit.
"""

from __future__ import annotations

import itertools
import logging
import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from .model import (
    CORRELATION_MODEL_VERSION,
    EXCLUDED_CELLS,
    POSITIONS,
    CellEstimate,
    CorrelationMode,
    CorrelationModel,
    EstimationReport,
    PositionLoading,
)
from .panel import Panel, PanelScore, score_panel

logger = logging.getLogger(__name__)

#: Projected points a player must reach to enter the estimation sample. See the
#: module docstring for the measurement behind the number.
PROJECTION_FLOOR = 6.0

#: A cell below this many pairs is carried for reporting but given no weight in
#: the fit. Two hundred pairs put the standard error near 0.07, which is wider
#: than every effect being estimated except the quarterback ones.
MIN_CELL_PAIRS = 200

#: Weeks of history required before a fitted structure is produced at all.
#: Below this the walk-forward estimate is noise and the caller gets ``None``,
#: which the evaluation treats as "run independent", not as "assume zero".
MIN_WEEKS_TO_FIT = 34


@dataclass
class _Cell:
    """Running moments for one (position, position, relation) cell.

    Pearson correlation from raw sums. The numerical objection to this form —
    catastrophic cancellation when the mean is far from zero — does not apply
    here: these are normal scores, so the mean is within a few hundredths of
    zero and the sums of squares are the same order as the counts.
    """

    n: int = 0
    sum_x: float = 0.0
    sum_y: float = 0.0
    sum_xx: float = 0.0
    sum_yy: float = 0.0
    sum_xy: float = 0.0

    def add(self, x: float, y: float) -> None:
        self.n += 1
        self.sum_x += x
        self.sum_y += y
        self.sum_xx += x * x
        self.sum_yy += y * y
        self.sum_xy += x * y

    def merge(self, other: "_Cell") -> None:
        self.n += other.n
        self.sum_x += other.sum_x
        self.sum_y += other.sum_y
        self.sum_xx += other.sum_xx
        self.sum_yy += other.sum_yy
        self.sum_xy += other.sum_xy

    @property
    def correlation(self) -> float:
        if self.n < 4:
            return float("nan")
        n = self.n
        covariance = self.sum_xy - self.sum_x * self.sum_y / n
        variance_x = self.sum_xx - self.sum_x * self.sum_x / n
        variance_y = self.sum_yy - self.sum_y * self.sum_y / n
        if variance_x <= 0.0 or variance_y <= 0.0:
            return float("nan")
        return covariance / math.sqrt(variance_x * variance_y)


CellKey = tuple[str, str, str]


@dataclass
class PairStatistics:
    """Accumulated pair moments for every cell, plus what fed them.

    Additive: :meth:`merge` combines two weeks, which is what makes the
    walk-forward refit cheap.
    """

    cells: dict[CellKey, _Cell] = field(default_factory=dict)
    rows: int = 0
    weeks: set[tuple[int, int]] = field(default_factory=set)

    @property
    def pairs(self) -> int:
        return sum(cell.n for cell in self.cells.values())

    @property
    def through(self) -> tuple[int, int]:
        return max(self.weeks) if self.weeks else (0, 0)

    def merge(self, other: "PairStatistics") -> None:
        for key, cell in other.cells.items():
            self.cells.setdefault(key, _Cell()).merge(cell)
        self.rows += other.rows
        self.weeks |= other.weeks

    def estimates(self) -> tuple[CellEstimate, ...]:
        """Every cell as a reportable estimate, strongest evidence first."""
        found = [
            CellEstimate(
                position_a=key[0], position_b=key[1], relation=key[2],
                n=cell.n, correlation=cell.correlation,
            )
            for key, cell in self.cells.items()
            if cell.n >= 4 and not math.isnan(cell.correlation)
        ]
        return tuple(sorted(found, key=lambda c: -c.n))


def accumulate(
    scores: Iterable[PanelScore], *, projection_floor: float = PROJECTION_FLOOR
) -> PairStatistics:
    """Reduce panel scores to per-cell moments.

    Pairs are formed **within a game-week** and nowhere else. Two players in
    different games contribute nothing, which is the model's claim that their
    correlation is zero — expressed by never measuring one rather than by
    measuring one and hoping it comes out small.
    """
    statistics = PairStatistics()
    by_game: dict[tuple[int, int, str], list[PanelScore]] = {}
    for score in scores:
        row = score.row
        if not row.game_id or row.expected < projection_floor:
            continue
        if row.position not in POSITIONS:
            continue
        statistics.rows += 1
        statistics.weeks.add((row.season, row.week))
        by_game.setdefault((row.season, row.week, row.game_id), []).append(score)

    for members in by_game.values():
        for first, second in itertools.combinations(members, 2):
            key, x, y = _orient(first, second)
            if key in EXCLUDED_CELLS:
                continue
            statistics.cells.setdefault(key, _Cell()).add(x, y)
    return statistics


def _orient(
    first: PanelScore, second: PanelScore
) -> tuple[CellKey, float, float]:
    """Put a pair in canonical order so ``(QB, WR)`` and ``(WR, QB)`` are one cell."""
    relation = "same" if first.row.team == second.row.team else "opp"
    if first.row.position <= second.row.position:
        return ((first.row.position, second.row.position, relation), first.z, second.z)
    return ((second.row.position, first.row.position, relation), second.z, first.z)


# ---------------------------------------------------------------------------
# The fit
# ---------------------------------------------------------------------------


#: The position whose team loading is fixed rather than fitted. See
#: :func:`_anchor` for why, and why it is this position.
ANCHOR_POSITION = "QB"


def _anchor(parameters: list[float]) -> list[float]:
    """Pin the team factor's scale to the quarterback. The identification step.

    Without this the fit is under-determined, and not subtly. The team loadings
    enter the objective only through products ``beta_p beta_q``, and the one
    cell that would pin ``beta_QB`` on its own is ``QB-QB same`` — which
    :data:`~nflfp.correlation.model.EXCLUDED_CELLS` removes as a relief-appearance
    artifact. So rescaling ``beta_QB`` up and every other team loading down by
    the same factor leaves every quarterback pair untouched while shrinking the
    pass-catcher pairs toward zero, which is what the data wants. Measured on the
    2019-2025 panel, the objective falls monotonically along exactly that ridge:

    ==========  ===========  ==========
    ``beta_QB``  ``beta_WR``  objective
    ==========  ===========  ==========
    0.30              0.420      541.6
    0.50              0.252      145.7
    0.70              0.180       85.5
    0.90              0.140       66.8
    0.93              0.135       65.1
    ==========  ===========  ==========

    An unconstrained optimiser therefore runs ``beta_QB`` to the edge of the
    feasible box and stops there, at whatever value floating-point arithmetic
    happens to allow. That is not a fitted parameter; it is a boundary artifact
    standing in for a missing normalisation.

    So the normalisation is made explicit and given its football reading. Setting
    ``beta_QB = sqrt(1 - alpha_QB^2)`` — the largest it can be — says: **the
    shared part of an offence's week is the quarterback's own week.** The team
    factor is no longer an abstract axis, it is the quarterback's non-game
    variance, and every pass-catcher's ``beta_p`` reads directly as "how much of
    this position rides on their quarterback".

    Two things this does *not* do. It does not claim a quarterback has no
    randomness — his randomness is the factor, which is why his idiosyncratic
    term is zero by construction rather than by measurement. And it does not
    change any fitted correlation between two players a lineup can hold: the
    products the objective actually depends on are unchanged, and the only
    quantity the constraint sets is ``QB-QB same team``, a pair no supported
    lineup format can contain.
    """
    anchored = list(parameters)
    index = POSITIONS.index(ANCHOR_POSITION) * 2
    anchored[index + 1] = math.sqrt(max(0.0, 1.0 - anchored[index] ** 2))
    return anchored


def fit_loadings(
    statistics: PairStatistics,
    *,
    min_pairs: int = MIN_CELL_PAIRS,
) -> tuple[dict[str, PositionLoading], tuple[tuple[str, float, float], ...], float]:
    """Fit the loadings to the measured cells by weighted least squares.

    Objective: minimise ``sum_c n_c * (r_c - rhat_c)^2`` over the non-negative
    loadings, subject to ``alpha_p^2 + beta_p^2 <= 1`` and to the normalisation
    in :func:`_anchor`. Seven free parameters, nineteen measured cells.

    Weighting by pair count is weighting by precision, since the standard error
    of a correlation goes as ``1/sqrt(n)``. It has a consequence worth stating:
    the well-measured **null** cells (RB-WR, n≈10,000, r≈0) pull as hard as the
    well-measured **signal** cells (QB-WR, n≈8,400, r≈+0.24). That is the
    correct behaviour and it is what stops the fit from spraying correlation
    across pairs that demonstrably do not have any.

    Optimised by cyclic coordinate descent with a golden-section line search.
    Seven smooth parameters on a bounded box does not need anything cleverer, and
    a dependency-free deterministic optimiser keeps the fit reproducible from the
    panel alone.

    Returns:
        ``(loadings, residuals, weighted_rmse)``. Residuals are
        ``(cell, observed, fitted)`` sorted worst-first.
    """
    targets = [
        (key, cell.correlation, cell.n)
        for key, cell in statistics.cells.items()
        if cell.n >= min_pairs and not math.isnan(cell.correlation)
    ]
    if not targets:
        raise ValueError("no cell has enough pairs to fit a correlation structure")

    def objective(parameters: Sequence[float]) -> float:
        anchored = _anchor(list(parameters))
        total = 0.0
        for key, observed, n in targets:
            fitted = _implied(anchored, key)
            gap = observed - fitted
            total += n * gap * gap
        return total

    best_parameters: list[float] | None = None
    best_score = float("inf")
    # Two starts: everything idiosyncratic, and a moderate shared structure.
    # Cheap insurance on a smooth objective, and they agree in practice.
    for start in ([0.0] * 8, [0.2] * 8):
        parameters = _descend(list(start), objective)
        score = objective(parameters)
        if score < best_score:
            best_score, best_parameters = score, parameters
    assert best_parameters is not None
    best_parameters = _anchor(best_parameters)

    loadings = {
        position: _bounded_loading(
            position,
            best_parameters[2 * index],
            best_parameters[2 * index + 1],
        )
        for index, position in enumerate(POSITIONS)
    }

    residuals = []
    weight_total = 0.0
    squared_total = 0.0
    for key, observed, n in sorted(targets, key=lambda t: t[0]):
        fitted = _implied(best_parameters, key)
        residuals.append((f"{key[0]}-{key[1]} {key[2]}", observed, fitted))
        weight_total += n
        squared_total += n * (observed - fitted) ** 2
    residuals.sort(key=lambda r: -abs(r[1] - r[2]))
    rmse = math.sqrt(squared_total / weight_total) if weight_total else 0.0
    return loadings, tuple(residuals), rmse


#: Decimals the published loadings are rounded to. Six is far below the third
#: decimal place where the sampling error on these cells lives, and rounding at
#: all is what keeps a saved model byte-identical to the one that was validated.
LOADING_PRECISION = 6


def _bounded_loading(position: str, game: float, team: float) -> PositionLoading:
    """Round a fitted pair and keep it inside the unit disc.

    The anchored quarterback sits exactly on ``game^2 + team^2 == 1``, so
    rounding the two independently can land a few ulps outside it and trip the
    variance check in :class:`~nflfp.correlation.model.PositionLoading` — a
    correct check failing on arithmetic rather than on a modelling error. The
    team loading is therefore recomputed from the rounded game loading, which
    lands on the constraint from the inside.
    """
    rounded_game = round(min(1.0, max(0.0, game)), LOADING_PRECISION)
    ceiling = math.sqrt(max(0.0, 1.0 - rounded_game ** 2))
    rounded_team = round(min(ceiling, max(0.0, team)), LOADING_PRECISION)
    return PositionLoading(
        position=position, game=rounded_game, team=min(rounded_team, ceiling)
    )


def _implied(parameters: Sequence[float], key: CellKey) -> float:
    """Correlation the parameter vector implies for a cell."""
    position_a, position_b, relation = key
    index_a = POSITIONS.index(position_a) * 2
    index_b = POSITIONS.index(position_b) * 2
    shared = parameters[index_a] * parameters[index_b]
    if relation == "same":
        shared += parameters[index_a + 1] * parameters[index_b + 1]
    return shared


def _descend(
    parameters: list[float], objective, *, passes: int = 60, tolerance: float = 1e-9
) -> list[float]:
    """Cyclic coordinate descent with a golden-section search per coordinate.

    The anchored coordinate is not searched — :func:`_anchor` sets it from the
    quarterback's game loading every time the objective is evaluated, so
    searching it would be optimising a value that is overwritten.
    """
    anchored_index = POSITIONS.index(ANCHOR_POSITION) * 2 + 1
    current = objective(parameters)
    for _ in range(passes):
        previous = current
        for index in range(len(parameters)):
            if index == anchored_index:
                continue
            upper = _upper_bound(parameters, index)
            parameters[index] = _golden(
                lambda value: _probe(parameters, index, value, objective), 0.0, upper
            )
        current = objective(parameters)
        if abs(previous - current) < tolerance:
            break
    return parameters


def _upper_bound(parameters: Sequence[float], index: int) -> float:
    """Largest this loading can be without pushing the total variance over one.

    The anchored position's *game* loading is the exception and gets the full
    ``[0, 1]``: its partner is derived from it rather than fixed beside it, so
    reading the constraint off the partner's current value would pin the search
    to wherever it already was.
    """
    if index == POSITIONS.index(ANCHOR_POSITION) * 2:
        return 1.0
    partner = index + 1 if index % 2 == 0 else index - 1
    return math.sqrt(max(0.0, 1.0 - parameters[partner] ** 2))


def _probe(parameters: list[float], index: int, value: float, objective) -> float:
    original = parameters[index]
    parameters[index] = value
    try:
        return objective(parameters)
    finally:
        parameters[index] = original


def _golden(function, low: float, high: float, *, iterations: int = 60) -> float:
    """Golden-section minimum of a unimodal function on ``[low, high]``.

    The objective is quadratic in one loading with the others held fixed, so it
    is unimodal on the interval and this converges to the exact minimiser.
    """
    if high <= low:
        return low
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = low, high
    c, d = b - ratio * (b - a), a + ratio * (b - a)
    fc, fd = function(c), function(d)
    for _ in range(iterations):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - ratio * (b - a)
            fc = function(c)
        else:
            a, c, fc = c, d, fd
            d = a + ratio * (b - a)
            fd = function(d)
        if abs(b - a) < 1e-10:
            break
    return (a + b) / 2.0


def build_model(
    statistics: PairStatistics,
    *,
    projection_floor: float = PROJECTION_FLOOR,
    profile: str = "half_ppr",
    model_name: str = "shrinkage_eb",
) -> CorrelationModel:
    """Turn accumulated pair statistics into a fitted, reportable model."""
    loadings, residuals, rmse = fit_loadings(statistics)
    season, week = statistics.through
    return CorrelationModel(
        version=CORRELATION_MODEL_VERSION,
        mode=CorrelationMode.GAME_ENVIRONMENT,
        loadings=loadings,
        profile=profile,
        model_name=model_name,
        estimation=EstimationReport(
            projection_floor=projection_floor,
            rows=statistics.rows,
            pairs=statistics.pairs,
            through_season=season,
            through_week=week,
            cells=statistics.estimates(),
            residuals=residuals,
            weighted_rmse=rmse,
        ),
    )


def estimate(
    panel: Panel,
    *,
    projection_floor: float = PROJECTION_FLOOR,
    seed: int = 6_2025,
) -> CorrelationModel:
    """Fit a structure on a whole panel. The convenience path, for reporting.

    Not the path the evaluation uses — that one is :func:`walk_forward_models`,
    which is the same fit under a leakage boundary.
    """
    statistics = accumulate(
        score_panel(panel, seed=seed), projection_floor=projection_floor
    )
    return build_model(
        statistics,
        projection_floor=projection_floor,
        profile=panel.profile,
        model_name=panel.model_name,
    )


def walk_forward_models(
    panel: Panel,
    *,
    seasons: Sequence[int],
    projection_floor: float = PROJECTION_FLOOR,
    min_weeks: int = MIN_WEEKS_TO_FIT,
    seed: int = 6_2025,
    factors: tuple[float, float] | None = None,
) -> Iterator[tuple[tuple[int, int], CorrelationModel | None]]:
    """Yield ``((season, week), model)`` with each model fitted only on the past.

    The model yielded for week ``N`` has seen pairs from weeks strictly before
    ``N`` and no others. ``None`` is yielded while history is too thin to fit,
    and the caller must treat that as "no correlated candidate for this week"
    rather than substituting a later fit — a single leaked week would flatter
    every metric this phase produces.

    ``factors`` selects the tail configuration the marginals are reconstructed
    under before the PIT is taken. ``None`` is production. Phase 6C passes a
    candidate so that the correlated arm of its four-way comparison is fitted
    through the same marginals it is then simulated with — reusing a structure
    estimated under different tails would compare two things at once.
    """
    scores = score_panel(panel, seed=seed, factors=factors)
    by_week: dict[tuple[int, int], list[PanelScore]] = {}
    for score in scores:
        by_week.setdefault((score.row.season, score.row.week), []).append(score)

    running = PairStatistics()
    evaluated = set(seasons)
    for ordinal in sorted(by_week):
        if ordinal[0] in evaluated:
            model = None
            if len(running.weeks) >= min_weeks:
                model = build_model(
                    running,
                    projection_floor=projection_floor,
                    profile=panel.profile,
                    model_name=panel.model_name,
                )
                if model.estimation.through >= ordinal:  # pragma: no cover
                    raise AssertionError(
                        f"correlation fitted through {model.estimation.through} "
                        f"is being applied to {ordinal} — this is leakage"
                    )
            yield ordinal, model
        # Only *after* yielding does this week enter the estimation sample.
        running.merge(accumulate(by_week[ordinal], projection_floor=projection_floor))
