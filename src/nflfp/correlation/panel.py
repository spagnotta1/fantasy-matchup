"""The historical panel: what a deployment would have known, and what happened.

Everything in Phase 6B — the correlation estimate, the independent baseline, the
correlated candidate — is measured against this one table. It has to be built
under the same rule that governs Layer 3, restated for a phase that is
estimating a *second* set of parameters on top of the first:

    For evaluation week ``N``, every number used to build the simulation inputs
    must have been computable before week ``N`` kicked off.

That is two separate leakage boundaries, and both are enforced here.

**The projection boundary** is Layer 3b's and is not reimplemented.
:func:`~nflfp.predict.backtest.run_backtest` already walks forward week by week,
refits the base model on strictly-earlier rows, and fits the residual
distribution on residuals that are themselves out-of-fold. Reimplementing that
loop to capture three extra columns would be a second copy of the one piece of
code whose correctness the whole system rests on. So the harness is called
unchanged and the extra columns — team, opponent, game — are **joined back** from
``feat_training_dataset`` on ``(player_id, season, week)``. Those three are
schedule facts, known months in advance, and carry no outcome information.

**The correlation boundary** is this phase's and lives in
:func:`~nflfp.correlation.estimate.walk_forward_estimates`: a correlation
structure applied to week ``N`` is fitted only on panel rows from weeks strictly
before ``N``. The panel itself spans everything; the split is applied at use.

The PIT transform
-----------------
Correlation between two players cannot be estimated on raw fantasy points. A
quarterback's residual is measured in different units from a tight end's, and
both are right-skewed, so a Pearson correlation of raw residuals mostly measures
the skew. :func:`pit` maps each outcome through **its own** published
distribution to a uniform, and :func:`normal_score` maps that to a standard
normal. Correlations on those are copula correlations: unit-free, marginal-free,
and exactly the parameter a Gaussian copula sampler consumes.

Zero is an atom and is treated as one
-------------------------------------
:class:`~nflfp.services.distributions.OutcomeCurve` clamps at zero, so a player
whose P10 and P25 are both zero has a flat segment there, and every one of the
many players who score exactly zero would otherwise map to the same PIT value.
Ties at the bottom of the distribution would bias every correlation upward,
because two players who both scored zero would look like they moved together
perfectly. The fix is the standard **randomised PIT**: for an outcome landing on
an atom, draw uniformly across the probability the atom spans. Under a correct
forecast that restores exact uniformity, which is checkable — and is checked, in
:func:`pit_uniformity`.
"""

from __future__ import annotations

import json
import logging
import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from ..predict.backtest import DEFAULT_PROFILE, run_backtest
from ..predict.dataset import load_rows
from ..predict.registry import get_model_factory
from ..services.distributions import OutcomeCurve

logger = logging.getLogger(__name__)

#: The model whose projections the panel is built from. The published one.
PANEL_MODEL = "shrinkage_eb"

#: Seasons the panel covers. The early ones are burn-in: the residual
#: distribution inside ``run_backtest`` accumulates history as it walks, so the
#: first weeks of the range have no distribution and are dropped by
#: :meth:`Panel.scored`. Starting three seasons before the first evaluation
#: season buys a warm residual history for every week that is actually scored.
PANEL_SEASONS: tuple[int, ...] = (2019, 2020, 2021, 2022, 2023, 2024, 2025)

#: Seasons the matchup evaluation runs on. Strictly inside PANEL_SEASONS so
#: every evaluated week has both a warm residual history behind its marginals
#: and prior seasons behind its correlation estimate.
EVALUATION_SEASONS: tuple[int, ...] = (2022, 2023, 2024, 2025)


@dataclass(frozen=True)
class PanelRow:
    """One player-week as a deployment would have had it, plus the outcome.

    Everything except :attr:`actual` was computable before the week kicked off.
    :attr:`actual` is the thing being predicted and appears in exactly two
    places: the metric that scores a forecast, and the estimation sample for a
    *later* week.
    """

    player_id: str
    season: int
    week: int
    position: str
    team: str | None
    opponent: str | None
    game_id: str | None
    #: The model's calibrated expectation — the number production simulates from.
    expected: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    #: Observations behind the fitted residual distribution.
    samples: int
    extrapolated: bool
    actual: float

    def curve(self, factors: tuple[float, float] | None = None) -> OutcomeCurve:
        """The same reconstruction production uses. Not a parallel one.

        Args:
            factors: ``(lower, upper)`` tail factors. ``None`` — the default and
                every production caller — uses the constants in
                :mod:`nflfp.services.distributions`. Phase 6C passes candidates
                here so that a correlation structure can be re-estimated through
                the marginals a candidate would actually publish; a correlation
                is a property of the PIT, and the PIT moves when the tails do.
        """
        tails = (
            {}
            if factors is None
            else {"lower_tail_factor": factors[0], "upper_tail_factor": factors[1]}
        )
        built = OutcomeCurve.from_percentiles(
            p10=self.p10, p25=self.p25, median=self.p50,
            p75=self.p75, p90=self.p90,
            expected=self.expected, extrapolated=self.extrapolated,
            samples=self.samples,
            **tails,
        )
        if built is None:  # pragma: no cover - five percentiles are always enough
            raise ValueError(f"{self.player_id} {self.season}w{self.week}: no curve")
        return built

    @property
    def ordinal(self) -> tuple[int, int]:
        return (self.season, self.week)


@dataclass(frozen=True)
class Panel:
    """The whole historical panel, and the ways it gets sliced.

    Immutable and ordered chronologically, which is what lets every
    "weeks before N" query below be a filter rather than a re-sort.
    """

    profile: str
    model_name: str
    rows: tuple[PanelRow, ...]

    @classmethod
    def of(cls, profile: str, model_name: str, rows: Iterable[PanelRow]) -> "Panel":
        ordered = tuple(
            sorted(rows, key=lambda r: (r.season, r.week, r.player_id))
        )
        return cls(profile=profile, model_name=model_name, rows=ordered)

    def __len__(self) -> int:
        return len(self.rows)

    def before(self, season: int, week: int) -> "Panel":
        """Rows strictly earlier than a week. The leakage boundary, as a method.

        Every correlation parameter applied to ``(season, week)`` is fitted from
        the output of this call and from nothing else.
        """
        cutoff = (season, week)
        return Panel(
            profile=self.profile,
            model_name=self.model_name,
            rows=tuple(r for r in self.rows if r.ordinal < cutoff),
        )

    def week(self, season: int, week: int) -> tuple[PanelRow, ...]:
        """Rows for exactly one week."""
        return tuple(r for r in self.rows if r.ordinal == (season, week))

    def weeks(self, seasons: Sequence[int] | None = None) -> tuple[tuple[int, int], ...]:
        """Every ``(season, week)`` present, in order."""
        wanted = None if seasons is None else set(seasons)
        return tuple(sorted({
            r.ordinal for r in self.rows
            if wanted is None or r.season in wanted
        }))

    def by_game(self, season: int, week: int) -> dict[str, list[PanelRow]]:
        """One week's rows grouped by game — the unit correlation lives in."""
        grouped: dict[str, list[PanelRow]] = {}
        for row in self.week(season, week):
            if row.game_id:
                grouped.setdefault(row.game_id, []).append(row)
        return grouped

    # -- persistence --------------------------------------------------------

    def save(self, path: Path) -> None:
        """Write as JSON Lines with a header. Cheap to rebuild, slow to wait for.

        The panel takes about a minute to generate and is an input to every
        other step in the phase, so it is cached. The header records what
        produced it, because a panel built from a different model or profile is
        a different object and silently reusing one would invalidate every
        number downstream.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "kind": "correlation_panel",
                "profile": self.profile,
                "model_name": self.model_name,
                "rows": len(self.rows),
            }) + "\n")
            for row in self.rows:
                handle.write(json.dumps(asdict(row)) + "\n")
        logger.info("wrote %d panel row(s) to %s", len(self.rows), path)

    @classmethod
    def load(cls, path: Path) -> "Panel":
        with path.open("r", encoding="utf-8") as handle:
            header = json.loads(handle.readline())
            if header.get("kind") != "correlation_panel":
                raise ValueError(f"{path} is not a correlation panel")
            rows = [PanelRow(**json.loads(line)) for line in handle if line.strip()]
        return cls.of(header["profile"], header["model_name"], rows)


def build_panel(
    *,
    database_url: str,
    seasons: Sequence[int] = PANEL_SEASONS,
    profile: str = DEFAULT_PROFILE,
    model_name: str = PANEL_MODEL,
) -> Panel:
    """Walk forward through history and record what each week would have shown.

    The projection half is :func:`~nflfp.predict.backtest.run_backtest`,
    unmodified. The identity half — which team, which opponent, which game — is
    joined on afterwards from the feature table, and is schedule data rather
    than outcome data.

    Args:
        database_url: SQLAlchemy URL for the warehouse.
        seasons: Seasons to walk. The first of these is burn-in.
        profile: Scoring profile. One panel per profile; they are not
            interchangeable, because the residual distributions differ.
        model_name: Registered model to project with.

    Returns:
        A panel holding only rows that carry a held-out distribution — a
        projection with no distribution cannot be simulated, so it cannot appear
        in a matchup and has no place here.
    """
    engine = create_engine(database_url)
    with Session(engine) as session:
        rows = load_rows(session, completed_only=True)
        identity = _identity_map(session)

    result = run_backtest(
        get_model_factory(model_name),
        rows,
        test_seasons=list(seasons),
        profile=profile,
    )

    panel_rows: list[PanelRow] = []
    missing_identity = 0
    for prediction in result.scored:
        key = (prediction.player_id, prediction.season, prediction.week)
        where = identity.get(key)
        if where is None:
            missing_identity += 1
            continue
        team, opponent, game_id = where
        distribution = prediction.distribution
        assert distribution is not None  # .scored guarantees it
        panel_rows.append(
            PanelRow(
                player_id=prediction.player_id,
                season=prediction.season,
                week=prediction.week,
                position=prediction.position,
                team=team,
                opponent=opponent,
                game_id=game_id,
                expected=distribution.expected_points,
                p10=distribution.p10,
                p25=distribution.p25,
                p50=distribution.p50,
                p75=distribution.p75,
                p90=distribution.p90,
                samples=distribution.sample_size,
                extrapolated=distribution.extrapolated,
                actual=prediction.actual,
            )
        )

    if missing_identity:
        logger.warning(
            "%d scored prediction(s) had no schedule identity and were dropped",
            missing_identity,
        )
    logger.info(
        "panel: %d row(s) over %s, %d prediction(s) had no distribution",
        len(panel_rows), list(seasons),
        len(result.predictions) - len(result.scored),
    )
    return Panel.of(profile, model_name, panel_rows)


def _identity_map(session: Session) -> dict[tuple[str, int, int], tuple[str, str, str]]:
    """``(player, season, week) -> (team, opponent, game)`` from the schedule.

    Read from the feature table rather than from ``player_week`` so it is the
    same row the model was handed, which removes any chance of the panel
    describing a player-week the projection did not come from.
    """
    statement = text(
        "SELECT player_id, season, week, team, opponent, game_id "
        "FROM feat_training_dataset"
    )
    return {
        (row.player_id, int(row.season), int(row.week)):
            (row.team, row.opponent, row.game_id)
        for row in session.execute(statement)
    }


# ---------------------------------------------------------------------------
# Probability integral transform
# ---------------------------------------------------------------------------

#: PIT values are clamped this far from the endpoints before the normal score is
#: taken. Without it a single outcome above the curve's support becomes an
#: infinite normal score and takes the whole correlation estimate with it.
PIT_EPSILON = 1e-4


def pit(curve: OutcomeCurve, actual: float, rng: random.Random) -> float:
    """Randomised probability integral transform of one outcome.

    Returns the outcome's position within its own forecast distribution, in
    [0, 1]. Under a perfectly calibrated forecast this is uniform, which makes
    it both the input a copula needs and a diagnostic of the marginals.

    The randomisation applies only where the curve is flat — an atom, in
    practice always the clamp at zero. There, the outcome is consistent with any
    probability in ``[F(x-), F(x)]`` and one is drawn uniformly. Elsewhere the
    interval has zero width and the draw is deterministic, so this is not a
    Monte Carlo estimate of anything; the RNG exists for the zero atom alone.

    Args:
        curve: The player's published distribution.
        actual: What they scored.
        rng: Seeded generator, so a panel PIT is reproducible.
    """
    low, high = _cdf_bounds(curve, actual)
    value = low if high <= low else low + (high - low) * rng.random()
    return min(1.0 - PIT_EPSILON, max(PIT_EPSILON, value))


def _cdf_bounds(curve: OutcomeCurve, value: float) -> tuple[float, float]:
    """``(F(x-), F(x))`` — the probability interval an outcome is consistent with.

    They differ only on a flat segment of the quantile function. Read straight
    off the knots rather than by inverting :meth:`OutcomeCurve.cdf` twice,
    because the whole point is the width of a segment that ``cdf`` collapses.
    """
    knots = curve.knots
    x = float(value)
    if x < knots[0][1]:
        return (0.0, 0.0)
    if x > knots[-1][1]:
        return (1.0, 1.0)

    low: float | None = None
    high: float | None = None
    for (p_lo, v_lo), (p_hi, v_hi) in zip(knots, knots[1:]):
        if v_hi < x or v_lo > x:
            continue
        span = v_hi - v_lo
        if span <= 0.0:
            # Flat in value: the whole probability span is consistent with x.
            at_low, at_high = p_lo, p_hi
        else:
            position = p_lo + (p_hi - p_lo) * (x - v_lo) / span
            at_low = at_high = position
        low = at_low if low is None else min(low, at_low)
        high = at_high if high is None else max(high, at_high)

    if low is None or high is None:  # pragma: no cover - covered by the guards
        collapsed = curve.cdf(x)
        return (collapsed, collapsed)
    return (low, high)


def normal_score(u: float) -> float:
    """``Phi^-1(u)`` — a uniform mapped to a standard normal.

    Acklam's rational approximation, accurate to about 1.15e-9 across the
    range, which is four orders of magnitude below the sampling error on any
    correlation this phase estimates. Written out rather than imported because
    the prediction layer already refuses a SciPy dependency and one correlation
    module is not the reason to add it.
    """
    if not 0.0 < u < 1.0:
        raise ValueError(f"normal score needs u in (0, 1), got {u}")

    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    low, high = 0.02425, 1.0 - 0.02425

    if u < low:
        q = math.sqrt(-2.0 * math.log(u))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
    if u > high:
        q = math.sqrt(-2.0 * math.log(1.0 - u))
        return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
    q = u - 0.5
    r = q * q
    return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
           (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0)


def normal_cdf(z: float) -> float:
    """``Phi(z)`` — the inverse direction, for the correlated sampler."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


@dataclass(frozen=True)
class PanelScore:
    """One panel row reduced to what the estimator consumes."""

    row: PanelRow
    u: float
    z: float


def score_panel(
    panel: Panel,
    *,
    seed: int = 6_2025,
    factors: tuple[float, float] | None = None,
) -> list[PanelScore]:
    """PIT and normal-score every row. Deterministic given the seed.

    ``factors`` is forwarded to :meth:`PanelRow.curve` and is ``None`` for every
    production and Phase 6B path.
    """
    rng = random.Random(seed)
    scored: list[PanelScore] = []
    for row in panel.rows:
        u = pit(row.curve(factors), row.actual, rng)
        scored.append(PanelScore(row=row, u=u, z=normal_score(u)))
    return scored


def pit_uniformity(scores: Sequence[PanelScore], bins: int = 10) -> list[tuple[float, int, float]]:
    """PIT histogram — the marginals' own calibration, as a diagnostic.

    A correlation estimated from normal scores inherits every defect in the
    marginals that produced them. If the PIT is U-shaped the intervals are too
    narrow; if it is hump-shaped they are too wide; either way part of what looks
    like correlation is really miscalibration, and the reader is entitled to see
    that before believing a correlation number.

    Returns:
        ``(bin_lower, count, share)`` per bin. A flat 1/bins share is perfect.
    """
    counts = [0] * bins
    for score in scores:
        counts[min(int(score.u * bins), bins - 1)] += 1
    total = max(1, len(scores))
    return [(index / bins, count, count / total) for index, count in enumerate(counts)]
