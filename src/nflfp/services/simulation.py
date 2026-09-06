"""The stateless Matchup Simulation Engine.

What this is
------------
Two lineups go in; two score distributions and a win probability come out. It is
a **consumer** of the frozen prediction foundation and creates nothing: no
model is invoked, no projection is computed, no distribution is fitted, no
uncertainty is invented. Every number it samples was measured by Layer 3b,
stored in ``projection_points``, and is reconstructed by
:class:`~nflfp.services.distributions.OutcomeCurve`.

The pipeline, and where each step lives::

    validated lineup            services.lineup
            |
            v
    published projections       services.rosters.get_roster_projections
            |
            v
    outcome curves              dto.PointDistribution.curve()
            |
            v
    Monte Carlo                 simulate() — this module, pure
            |
            v
    team score distributions
            |
            v
    matchup result

Why Monte Carlo and not a convolution
-------------------------------------
:func:`~nflfp.services.distributions.probability_beats` answers the two-player
question exactly, by quadrature, with no sampling. The lineup question is a sum
of seven right-skewed piecewise-linear variables per side and then a comparison
of two such sums; the exact convolution is tractable but expensive and would
have to be rewritten the moment correlation arrives. Sampling costs a seed and
gives the joint distribution — margin percentiles, tie rate, any threshold
question a product manager asks next week — for the same code.

The sampling is **inverse transform**: draw ``u ~ U(0,1)``, take
``curve.quantile(u)``. That is the one method that samples the stored
distribution rather than a parametric stand-in for it, which matters because
Layer 3b chose empirical residual quantiles over a Gaussian precisely for the
right skew and the hard floor near zero.

Where it runs
-------------
:func:`simulate` is pure, synchronous and CPU-bound, and
:func:`simulate_matchup` hands it to a worker thread rather than running it on
the event loop. At the maximum permitted 50,000 iterations it is about a second
of uninterrupted Python, which on a single-replica deployment is a second in
which nobody else's request is answered. The threading is invisible to the
mathematics — see the comment at the call site — and :func:`simulate` itself
stays callable synchronously, which is what the benchmarks and the backtest do.

Determinism is a product requirement, not a testing convenience
---------------------------------------------------------------
``probability_beats`` is deterministic by construction, on the stated grounds
that a start/sit call returning a different answer on every refresh is not
acceptable. A simulation owes the same property, so the seed defaults to
:data:`DEFAULT_SEED` rather than to entropy, is always reported, and the sampling
order is fixed by lineup order. The same lineups, the same published run and the
same seed produce the same result, on any machine, forever.

What it assumes, and does not hide
----------------------------------
**Independence.** Every player is drawn from their own uniform. Teammates divide
one offence's plays, opposing players share pace and game script, and two
lineups holding players from the same game are correlated with each other. The
error is concentrated in the *spread* rather than the centre. Phase 6D
measured how much that costs at the shipped tail factors: on 2,878 held-out
lineups the 80% interval covers 0.7943 against a nominal 0.800 and the 90%
interval 0.8919, and applying a fitted correlation structure moves both *past*
nominal while moving no proper score significantly. So independence is an
approximation with a measured and currently small cost, not a known defect;
what residual dependence there is concentrates in a QB drawn alongside his own
receivers. :attr:`MatchupSimulation.caveats` names
every group that breaks the assumption.

**No kickers, no defences.** Not simulable, for the reasons in
:mod:`nflfp.services.positions`. Refused at validation rather than silently
dropped.

**No injury adjustment.** ``injury_multiplier`` is stored and unwritten. A
player designated Out contributes their full projected distribution, because
that is what the projection says and this engine does not overrule it. The
designation travels in the caveats.

**No matchup adjustment.** ``matchup_score`` is NULL in the projection model and
the grade is derived above it. Nothing here consumes one.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .. import correlation
from ..correlation import CorrelationMode, CorrelationModel, Sampler
from . import lineup as lineup_module
from . import positions, rosters
from .catalog import resolve_scoring_profile
from .distributions import OutcomeCurve
from .dto import ModelRef, PlayerProjection, SlateWindow
from .errors import InvalidRequest
from .lineup import Lineup, LineupFormat, STANDARD_FORMAT

logger = logging.getLogger(__name__)

#: Iterations a request gets when it names none. Ten thousand puts the Monte
#: Carlo standard error on a win probability near 0.5 at 0.5 percentage points
#: — an order of magnitude below the calibration error of the distributions
#: being sampled, so more iterations would be measuring the sampler rather than
#: the football.
DEFAULT_ITERATIONS = 10_000

#: Fewest a caller may ask for. Below this the percentile estimates are noise:
#: a P10 from 50 draws is the fifth order statistic and moves by whole points
#: between seeds.
MIN_ITERATIONS = 100

#: Most a **synchronous HTTP request** may ask for. A fourteen-player matchup
#: costs about 15 microseconds per iteration on one core, so the default run is
#: ~150 ms and this ceiling is ~0.8 s — comfortably inside a request budget,
#: which matters because the endpoint is synchronous CPU work and holds an
#: event-loop worker for its whole duration.
#:
#: This is a transport bound, not a statistical one. A hundred thousand
#: iterations is a legitimate thing to want and the engine will run it happily
#: when called directly; it is a background job, not a synchronous request.
MAX_ITERATIONS = 50_000

#: The seed used when a caller names none. A fixed default rather than entropy,
#: so an unseeded request is still reproducible and a user refreshing the page
#: does not watch their win probability wander.
DEFAULT_SEED = 20260101

#: Decimal places a fantasy platform scores to. Totals are rounded here before
#: they are compared, which is what makes a tie a real event rather than a
#: measure-zero one: the reconstructed curves are continuous, real scoring is
#: not, and comparing raw floats would report a tie probability of exactly zero
#: for every matchup ever simulated.
SCORING_PRECISION = 2


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimulatedPlayer:
    """One lineup slot, as it entered the simulation.

    The point estimates here are **model** provenance — they are read from the
    stored distribution, not produced by the simulation — and are carried so a
    caller can show what the team total is made of without a second request.
    """

    player_id: str
    name: str
    slot: str
    position: str | None
    team: str | None
    game_id: str | None
    expected_points: float | None
    floor: float | None
    ceiling: float | None
    #: The mean of this player's own draws. Should sit within sampling error of
    #: ``expected_points``; a gap is the tail assumption in
    #: :mod:`~nflfp.services.distributions` showing up, not a bug.
    simulated_mean: float


@dataclass(frozen=True)
class TeamSimulation:
    """One team's simulated week.

    Every field except :attr:`projection_sum` is **derived**: a statistic of the
    sampled totals. :attr:`projection_sum` is the sum of the stored calibrated
    means and is the one model-provenance number in here, kept beside the
    simulated mean because the two agreeing is the cheapest available check that
    the sampler is drawing from the distribution it was handed.
    """

    side: str
    players: tuple[SimulatedPlayer, ...]
    projection_sum: float
    expected_score: float
    median_score: float
    p10: float
    p25: float
    p75: float
    p90: float
    win_probability: float
    loss_probability: float
    tie_probability: float

    @property
    def percentiles_are_ordered(self) -> bool:
        """P10 <= P25 <= P50 <= P75 <= P90. Guaranteed by construction."""
        values = (self.p10, self.p25, self.median_score, self.p75, self.p90)
        return all(a <= b for a, b in zip(values, values[1:]))


@dataclass(frozen=True)
class SimulationAssumptions:
    """What the engine assumed, stated as data rather than as prose.

    Every field is derived from a registry or from the engine's actual
    behaviour, never hard-coded to a hopeful value. ``kicker_projection_available``
    reads :data:`~nflfp.services.positions.POSITION_SUPPORT`, so it flips to
    ``True`` the day a kicker model ships and this class does not change.
    """

    #: Player outcomes were drawn independently. Derived from
    #: :attr:`correlation_mode` rather than stored separately, so the flag and
    #: the sampler cannot disagree.
    player_independence: bool
    kicker_projection_available: bool
    defense_projection_available: bool
    #: The engine applied no injury multiplier. Designations are reported in
    #: :attr:`MatchupSimulation.caveats`.
    injury_adjustment_applied: bool
    #: No matchup grade is an input. ``matchup_score`` is NULL in the projection
    #: model and the grade is derived above it.
    matchup_adjustment_applied: bool
    #: No weather multiplier is an input; Layer 3b excluded weather on evidence.
    weather_adjustment_applied: bool
    #: How the joint distribution was drawn. The Phase 6B addition.
    correlation_mode: str = CorrelationMode.INDEPENDENT.value
    #: Version of the fitted structure, when one was used.
    correlation_model_version: str | None = None
    sampling_method: str = "inverse_transform_from_stored_percentiles"

    @classmethod
    def current(
        cls, sampler: Sampler | None = None
    ) -> "SimulationAssumptions":
        """The assumptions this build actually operates under.

        Reads the sampler that ran rather than a constant, so the reported mode
        is the mode that was used. A response describing a correlated
        simulation that silently ran independently would be worse than no
        disclosure at all.
        """
        mode = CorrelationMode.INDEPENDENT if sampler is None else sampler.mode
        return cls(
            player_independence=mode is CorrelationMode.INDEPENDENT,
            kicker_projection_available=_position_is_projected("K"),
            defense_projection_available=_position_is_projected("DST"),
            injury_adjustment_applied=False,
            matchup_adjustment_applied=False,
            weather_adjustment_applied=False,
            correlation_mode=mode.value,
            correlation_model_version=(
                None if sampler is None else sampler.model_version
            ),
        )

    def notes(self) -> tuple[str, ...]:
        """One sentence per assumption that is currently costing accuracy."""
        lines: list[str] = []
        if self.player_independence:
            lines.append(
                "Player outcomes were drawn independently. Teammates share one "
                "offence's plays and opposing players share pace and game "
                "script, so the true joint distribution is correlated. The "
                "error falls on the spread rather than the centre, and it is "
                "small where it has been measured: 80% interval coverage of "
                "0.7943 against a nominal 0.800 over 2,878 held-out lineups. "
                "The correlated mode moves that past nominal rather than onto "
                "it, which is why it is not the default."
            )
        else:
            lines.append(
                "Player outcomes were drawn from a fitted game-environment "
                "correlation structure "
                f"(version {self.correlation_model_version}): players in the "
                "same game share a game factor and teammates additionally "
                "share their offence's factor, with loadings estimated from "
                "held-out historical outcomes. Each player's own distribution "
                "is unchanged — correlation moves the joint distribution, not "
                "the marginals. This is an experimental mode; see "
                "docs/simulation-readiness.md for what it was and was not "
                "measured to improve."
            )
        if not self.kicker_projection_available or not self.defense_projection_available:
            missing = [
                label
                for label, available in (
                    ("kickers", self.kicker_projection_available),
                    ("team defences", self.defense_projection_available),
                )
                if not available
            ]
            lines.append(
                f"No projections exist for {' or '.join(missing)}, so these "
                "totals cover only the skill positions and are not comparable "
                "to a full lineup score. See /meta/positions."
            )
        if not self.injury_adjustment_applied:
            lines.append(
                "No injury adjustment was applied — the engine has no fitted "
                "injury multiplier. A player designated Out contributes their "
                "full projected distribution."
            )
        if not self.matchup_adjustment_applied:
            lines.append(
                "No matchup adjustment was applied. matchup_score is NULL in "
                "the projection model; the matchup grade is derived above the "
                "model and is not an input to it."
            )
        return tuple(lines)


@dataclass(frozen=True)
class MatchupSimulation:
    """The result of one simulated matchup.

    ``model`` is the published run the distributions came from. Together with
    :attr:`seed` and :attr:`iterations` it is what makes this result
    reproducible: the same lineups against the same run with the same seed give
    the same numbers, and a superseded run is still on disk to prove what was
    shown at the time.
    """

    season: int
    week: int
    scoring_profile: str
    lineup_format: str
    iterations: int
    seed: int
    team_a: TeamSimulation
    team_b: TeamSimulation
    #: ``E[a] - E[b]`` over the simulated totals. Positive favours team A.
    score_differential: float
    #: The median of the sampled margins. Differs from
    #: :attr:`score_differential` when the margin is skewed, which it is
    #: whenever one lineup is more volatile than the other.
    median_differential: float
    model: ModelRef | None
    assumptions: SimulationAssumptions
    caveats: tuple[str, ...] = ()

    @property
    def probabilities_sum_to_one(self) -> bool:
        """Win + loss + tie sums to one on both sides, to floating tolerance."""
        for team in (self.team_a, self.team_b):
            total = team.win_probability + team.loss_probability + team.tie_probability
            if abs(total - 1.0) > 1e-9:
                return False
        return True


def _position_is_projected(position: str) -> bool:
    support = positions.describe(position)
    return support is not None and support.is_projected


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimulationInput:
    """One player as the sampler sees them: a slot, a curve, and a name.

    Assembled by :func:`_prepare` so that :func:`simulate` needs neither a
    session nor a DTO and can be handed synthetic curves by a test.
    """

    player_id: str
    name: str
    slot: str
    position: str | None
    team: str | None
    game_id: str | None
    curve: OutcomeCurve
    expected_points: float | None
    floor: float | None
    ceiling: float | None


def build_roster_sampler(
    team_a: Sequence[SimulationInput],
    team_b: Sequence[SimulationInput],
    *,
    mode: CorrelationMode = CorrelationMode.INDEPENDENT,
    model: CorrelationModel | None = None,
) -> Sampler:
    """The sampler for one matchup, over **both** lineups at once.

    Kept beside :func:`simulate` rather than inside it so a caller — the
    benchmark, the stress tests, the Phase 6B evaluation — can build a sampler,
    inspect it, and hand the same one to several runs.
    """
    members = [
        correlation.RosterMember(
            position=player.position, team=player.team, game_id=player.game_id
        )
        for player in (*team_a, *team_b)
    ]
    return correlation.build_sampler(members, mode=mode, model=model)


def simulate(
    team_a: Sequence[SimulationInput],
    team_b: Sequence[SimulationInput],
    *,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
    sampler: Sampler | None = None,
) -> tuple[TeamSimulation, TeamSimulation, float, float]:
    """Run the Monte Carlo. Pure, synchronous, and the whole of the statistics.

    Args:
        team_a: Team A's lineup, already resolved to curves.
        team_b: Team B's lineup.
        iterations: Draws. Bounded by the caller, not here — the bound is a
            transport concern and this function is also called by a benchmark
            and, one day, by a background job.
        seed: Seeds a private :class:`random.Random`, never the global one.
            Seeding the module-level RNG would make one simulation's draws
            depend on whatever else in the process had called ``random``.
        sampler: How the per-iteration uniforms are drawn. Defaults to
            :class:`~nflfp.correlation.IndependentSampler`, which is Phase 6A's
            behaviour exactly — same draw order, same sequence, same numbers.
            The dependency structure is the *only* thing a sampler may vary;
            each player's uniform is marginally ``U(0,1)`` whichever one is used,
            so the points sampled for a player still come from the distribution
            Layer 3b published for them.

    Returns:
        ``(team_a_result, team_b_result, mean_margin, median_margin)``.

    Raises:
        InvalidRequest: for an empty lineup, a non-positive iteration count, or
            a sampler built for a different roster. The first two are caller
            errors that would otherwise produce a confident zero; the third
            would silently pair players with other players' draws.
    """
    if not team_a or not team_b:
        raise InvalidRequest("both lineups must contain at least one player")
    if iterations < 1:
        raise InvalidRequest(
            f"iterations must be positive, got {iterations}", field="simulation_count"
        )

    if sampler is None:
        sampler = correlation.IndependentSampler(count=len(team_a) + len(team_b))

    rng = random.Random(seed)
    # Bound locally: this is the hot loop, and an attribute lookup per player
    # per iteration is 140,000 of them in a default request.
    draw = sampler.draw
    quantiles_a = [player.curve.quantile for player in team_a]
    quantiles_b = [player.curve.quantile for player in team_b]
    split = len(team_a)

    # Checked once, against a *throwaway* generator. Drawing the probe from
    # ``rng`` would advance it and shift every subsequent draw, which would
    # break the seed contract — the same lineups and seed would stop reproducing
    # a Phase 6A result. A length mismatch is otherwise silent: the loop would
    # index past the end for a short draw, or quietly ignore the tail of a long
    # one and pair team B with team A's uniforms.
    probe = draw(random.Random(seed))
    if len(probe) != split + len(team_b):
        raise InvalidRequest(
            f"sampler produces {len(probe)} uniform(s) for a matchup of "
            f"{split + len(team_b)} player(s); it was built for a different "
            "roster and would pair players with other players' draws"
        )

    totals_a: list[float] = []
    totals_b: list[float] = []
    margins: list[float] = []
    per_player_a = [0.0] * len(team_a)
    per_player_b = [0.0] * len(team_b)
    wins_a = 0
    wins_b = 0
    ties = 0

    for _ in range(iterations):
        # One joint draw across both lineups. Sampling the two sides separately
        # would model two managers watching different afternoons, and the
        # cross-lineup dependence is the part that moves the win probability
        # rather than only the intervals.
        uniforms = draw(rng)

        total_a = 0.0
        for index, quantile in enumerate(quantiles_a):
            points = quantile(uniforms[index])
            per_player_a[index] += points
            total_a += points

        total_b = 0.0
        for index, quantile in enumerate(quantiles_b):
            points = quantile(uniforms[split + index])
            per_player_b[index] += points
            total_b += points

        totals_a.append(total_a)
        totals_b.append(total_b)
        margins.append(total_a - total_b)

        # Rounded to the precision a fantasy platform scores to. See
        # SCORING_PRECISION: comparing raw floats makes every tie impossible.
        scored_a = round(total_a, SCORING_PRECISION)
        scored_b = round(total_b, SCORING_PRECISION)
        if scored_a > scored_b:
            wins_a += 1
        elif scored_b > scored_a:
            wins_b += 1
        else:
            ties += 1

    totals_a.sort()
    totals_b.sort()
    margins.sort()

    tie_probability = ties / iterations
    result_a = _summarise(
        side="team_a",
        players=team_a,
        totals=totals_a,
        per_player=per_player_a,
        iterations=iterations,
        win_probability=wins_a / iterations,
        loss_probability=wins_b / iterations,
        tie_probability=tie_probability,
    )
    result_b = _summarise(
        side="team_b",
        players=team_b,
        totals=totals_b,
        per_player=per_player_b,
        iterations=iterations,
        win_probability=wins_b / iterations,
        loss_probability=wins_a / iterations,
        tie_probability=tie_probability,
    )
    mean_margin = sum(margins) / iterations
    return result_a, result_b, mean_margin, _percentile(margins, 0.50)


def _summarise(
    *,
    side: str,
    players: Sequence[SimulationInput],
    totals: Sequence[float],
    per_player: Sequence[float],
    iterations: int,
    win_probability: float,
    loss_probability: float,
    tie_probability: float,
) -> TeamSimulation:
    """Turn a sorted list of team totals into the reported summary.

    Percentiles come from the sorted sample, so ``p10 <= p25 <= median <= p75
    <= p90`` holds by construction rather than by assertion — there is no
    smoothing step that could reorder them.
    """
    return TeamSimulation(
        side=side,
        players=tuple(
            SimulatedPlayer(
                player_id=player.player_id,
                name=player.name,
                slot=player.slot,
                position=player.position,
                team=player.team,
                game_id=player.game_id,
                expected_points=player.expected_points,
                floor=player.floor,
                ceiling=player.ceiling,
                simulated_mean=total / iterations,
            )
            for player, total in zip(players, per_player)
        ),
        projection_sum=sum(
            player.expected_points or 0.0 for player in players
        ),
        expected_score=sum(totals) / iterations,
        median_score=_percentile(totals, 0.50),
        p10=_percentile(totals, 0.10),
        p25=_percentile(totals, 0.25),
        p75=_percentile(totals, 0.75),
        p90=_percentile(totals, 0.90),
        win_probability=win_probability,
        loss_probability=loss_probability,
        tie_probability=tie_probability,
    )


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    """Linear-interpolated percentile of an already-sorted sample.

    The same definition NumPy and R type 7 use, so a number reported here can be
    checked against either without a footnote. Interpolating rather than picking
    the nearest order statistic matters at small iteration counts, where the
    step between adjacent draws is a visible fraction of the interval.
    """
    if not sorted_values:
        raise InvalidRequest("cannot take a percentile of an empty sample")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = probability * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return float(
        sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def simulate_matchup(
    session: AsyncSession,
    *,
    team_a: Sequence[Mapping[str, object] | lineup_module.LineupEntry],
    team_b: Sequence[Mapping[str, object] | lineup_module.LineupEntry],
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int | None = None,
    lineup_format: LineupFormat = STANDARD_FORMAT,
    model_name: str | None = None,
    correlation_mode: CorrelationMode = CorrelationMode.INDEPENDENT,
    correlation_model: CorrelationModel | None = None,
) -> tuple[MatchupSimulation, SlateWindow]:
    """Validate two lineups, fetch their projections, and simulate the matchup.

    Nothing is persisted. The result is computed and returned inline, which is
    what makes this endpoint stateless and what makes ``fantasy_rosters`` and
    ``matchup_simulations`` a later decision rather than a prerequisite.

    Args:
        session: Open async session.
        team_a: Team A's lineup — mappings with ``player_id`` and ``slot``.
        team_b: Team B's lineup.
        season: Season, defaulting to the current league year.
        week: Week, defaulting to the upcoming slate.
        scoring_profile: League format, defaulting to the configured one.
        iterations: Draws, bounded by the caller.
        seed: Reproducibility seed. ``None`` uses :data:`DEFAULT_SEED`, so an
            unseeded request is still reproducible.
        lineup_format: The league shape both lineups must satisfy.
        model_name: Pin to a specific model instead of whatever is published.
        correlation_mode: How player outcomes are drawn.
            :attr:`~nflfp.correlation.CorrelationMode.INDEPENDENT` is the
            default and the production behaviour.
        correlation_model: The fitted structure a correlated mode needs.
            Required for any mode other than independent — see
            :func:`~nflfp.correlation.build_sampler` for why no fallback.

    Returns:
        The simulation and the window it resolved to.

    Raises:
        InvalidRequest: for an invalid lineup, an out-of-range iteration count,
            a player with no published projection, or a player with no stored
            distribution. Every one of these names the player or the slot: a
            simulation that quietly dropped a starter would report a team total
            missing that player's whole contribution and a win probability
            wrong in a direction the caller cannot see.
    """
    # Everything cheap and local first. A lineup with two quarterbacks in it is
    # rejectable without a database, and resolving a week we are about to throw
    # away is a wasted round-trip that turns into a 500 when Postgres is down.
    if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
        raise InvalidRequest(
            f"simulation_count must be between {MIN_ITERATIONS} and "
            f"{MAX_ITERATIONS}, got {iterations}. Larger runs are a background "
            "job rather than a synchronous request.",
            field="simulation_count",
        )
    profile = resolve_scoring_profile(scoring_profile)
    lineup_a = lineup_module.validate_structure(
        team_a, side="team_a", format=lineup_format
    )
    lineup_b = lineup_module.validate_structure(
        team_b, side="team_b", format=lineup_format
    )

    # One query for both lineups. A player may legitimately appear on both
    # sides only in the sense that two different managers cannot start the same
    # player — which is a league rule this engine does not enforce, because a
    # what-if comparison of two hypothetical lineups is a legitimate use.
    roster, window = await rosters.get_roster_projections(
        session,
        player_ids=[*lineup_a.player_ids, *lineup_b.player_ids],
        season=season,
        week=week,
        scoring_profile=profile,
        model_name=model_name,
    )
    _refuse_gaps(roster, lineup_a, lineup_b)

    by_id = {entry.player.player_id: entry for entry in roster.entries}
    positions_by_player = {
        player_id: entry.player.position for player_id, entry in by_id.items()
    }
    lineup_module.validate_eligibility(lineup_a, positions_by_player)
    lineup_module.validate_eligibility(lineup_b, positions_by_player)

    inputs_a = _prepare(lineup_a, by_id)
    inputs_b = _prepare(lineup_b, by_id)

    resolved_seed = DEFAULT_SEED if seed is None else int(seed)
    sampler = build_roster_sampler(
        inputs_a, inputs_b, mode=correlation_mode, model=correlation_model
    )
    # The one genuinely CPU-bound step in the API, moved off the event loop.
    #
    # `simulate` is pure Python and holds the interpreter for its whole run: a
    # 50,000-iteration matchup is ~1 s of uninterrupted work. Called directly
    # from this coroutine it stops the loop dead — measured on Linux, a 50k run
    # blocked the loop for 1,024 ms and served zero other requests in that time,
    # so with `numReplicas: 1` one person's simulation is everyone else's frozen
    # page. Through a worker thread the same run leaves the loop stalling 69 ms
    # at worst and serving other requests throughout.
    #
    # A thread rather than a process, and no queue: the GIL is released
    # periodically, which is all that is needed to keep an *I/O* loop scheduled
    # beside a CPU-bound thread, and the run is already bounded by
    # MAX_ITERATIONS to something that fits a request. A process pool would pay
    # pickling on every call to solve a problem this does not have, and a job
    # queue would make a synchronous endpoint asynchronous — a product change,
    # not a performance one.
    #
    # Nothing about the mathematics moves. `simulate` seeds a private
    # `random.Random`, never the global one, so it neither reads nor perturbs
    # any state shared with the loop, and the same lineups and seed produce the
    # same numbers whichever thread runs them. A test asserts exactly that.
    # `to_thread` copies the context, so the request id keeps travelling.
    result_a, result_b, mean_margin, median_margin = await asyncio.to_thread(
        simulate,
        inputs_a, inputs_b,
        iterations=iterations, seed=resolved_seed, sampler=sampler,
    )

    logger.info(
        "simulated %sw%s (%s): %d iterations, seed %d, %s, team_a win %.3f",
        window.season, window.week, profile, iterations, resolved_seed,
        correlation_mode.value, result_a.win_probability,
    )

    return (
        MatchupSimulation(
            season=window.season,
            week=window.week,
            scoring_profile=profile,
            lineup_format=lineup_format.name,
            iterations=iterations,
            seed=resolved_seed,
            team_a=result_a,
            team_b=result_b,
            score_differential=mean_margin,
            median_differential=median_margin,
            model=_model_of(roster.entries),
            assumptions=SimulationAssumptions.current(sampler),
            caveats=_caveats(roster, lineup_a, lineup_b, by_id, sampler),
        ),
        window,
    )


def _refuse_gaps(
    roster: rosters.RosterProjections, *lineups: Lineup
) -> None:
    """Refuse the whole simulation if any starter has no projection.

    The other consumers of :func:`~nflfp.services.rosters.get_roster_projections`
    report gaps and carry on, which is right for a screen that lists what it
    found. It is wrong here. A team total is a sum, so a missing starter does
    not make the answer slightly less complete — it removes that player's entire
    contribution and produces a win probability that is confidently wrong with
    nothing on the screen to say so.
    """
    if roster.complete:
        return

    sides = {}
    for lineup in lineups:
        for player_id in lineup.player_ids:
            sides.setdefault(player_id, lineup.side)

    detail = "; ".join(
        f"{sides.get(gap.player_id, 'lineup')}: {gap.detail}"
        for gap in roster.unavailable
    )
    raise InvalidRequest(
        f"{len(roster.unavailable)} of {len(roster.requested)} named players "
        f"have no published projection for this week, so no team total can be "
        f"computed. {detail}",
        field=sides.get(roster.unavailable[0].player_id, "team_a"),
    )


def _prepare(
    lineup: Lineup, by_id: Mapping[str, PlayerProjection]
) -> list[SimulationInput]:
    """Resolve each slot to a sampleable curve, in lineup order.

    Lineup order, not sorted order: the order fixes the sequence of draws from
    the seeded RNG, and it is the order the caller submitted, so the seed
    contract ("same inputs, same seed, same result") is a statement about the
    request rather than about an internal sort that could change.

    Raises:
        InvalidRequest: for a projection with fewer than three stored
            percentiles. A point estimate cannot be sampled, and substituting
            ``expected +/- some percentage`` is exactly the fabrication the
            distribution layer exists to prevent.
    """
    prepared: list[SimulationInput] = []
    for entry in lineup.entries:
        projection = by_id[entry.player_id]
        curve = projection.points.curve()
        if curve is None:
            raise InvalidRequest(
                f"{lineup.side}: no outcome distribution is stored for "
                f"{projection.player.name} ({entry.player_id}); a simulation "
                "samples a distribution and cannot be run from a point "
                "estimate.",
                field=f"{lineup.side}.player_id",
            )
        prepared.append(
            SimulationInput(
                player_id=entry.player_id,
                name=projection.player.name,
                slot=entry.slot,
                position=projection.player.position,
                team=projection.team,
                game_id=projection.game_id,
                curve=curve,
                expected_points=projection.points.headline,
                floor=projection.points.floor,
                ceiling=projection.points.ceiling,
            )
        )
    return prepared


def _model_of(entries: Sequence[PlayerProjection]) -> ModelRef | None:
    """The run behind these projections.

    One run covers a whole published week, so the first entry's is every
    entry's. Returned rather than asserted because a pinned ``model_name`` and
    an unpinned request can legitimately disagree, and the caller is entitled to
    know which one they got.
    """
    for entry in entries:
        if entry.model is not None:
            return entry.model
    return None


def _caveats(
    roster: rosters.RosterProjections,
    lineup_a: Lineup,
    lineup_b: Lineup,
    by_id: Mapping[str, PlayerProjection],
    sampler: Sampler | None = None,
) -> tuple[str, ...]:
    """Disclosures the result must carry.

    Assembled from the existing machinery rather than restated: the coverage
    gaps come from :class:`~nflfp.services.rosters.RosterProjections`, the
    correlation groups from :func:`~nflfp.services.rosters.correlation_groups`,
    and the standing assumptions from
    :meth:`SimulationAssumptions.notes`. A caveat written here would be one this
    module could forget to update when the layer below it changed.
    """
    assumptions = SimulationAssumptions.current(sampler)
    caveats: list[str] = list(assumptions.notes())

    # Correlation, reported per side and then across the matchup. The last is
    # the one a pairwise start/sit call never has to think about: two lineups
    # holding players from the same game are correlated *with each other*, which
    # moves the win probability rather than just the intervals.
    #
    # Reported whichever mode ran. Under independence they name what is being
    # ignored; under a correlated mode they name what is being modelled, and a
    # reader is entitled to know which players a fitted structure was applied to.
    for lineup in (lineup_a, lineup_b):
        entries = [by_id[player_id] for player_id in lineup.player_ids]
        for caveat in rosters.lineup_caveats(entries):
            caveats.append(f"{lineup.side}: {caveat}")

    shared_games = _shared_games(lineup_a, lineup_b, by_id)
    if shared_games and assumptions.player_independence:
        caveats.append(
            "The two lineups hold players from the same game(s) "
            f"({', '.join(shared_games)}). Those outcomes are correlated across "
            "the matchup, which moves the win probability itself rather than "
            "only the intervals — one manager's ceiling week tends to arrive on "
            "the same afternoon as the other's."
        )
    elif shared_games:
        caveats.append(
            "The two lineups hold players from the same game(s) "
            f"({', '.join(shared_games)}). That cross-matchup dependence is "
            "modelled: both lineups were drawn from one joint sample, so the "
            "win probability accounts for it."
        )

    for lineup in (lineup_a, lineup_b):
        for player_id in lineup.player_ids:
            projection = by_id[player_id]
            injury = projection.injury
            if injury is not None and injury.will_not_play:
                caveats.append(
                    f"{lineup.side}: {projection.player.name} is listed OUT. "
                    "The projection does not know that — the engine has no "
                    "fitted injury adjustment — so their full distribution is "
                    "in this team's total."
                )
            elif injury is not None and injury.is_questionable_or_worse:
                caveats.append(
                    f"{lineup.side}: {projection.player.name} is listed "
                    f"{injury.report_status}. The projection does not adjust "
                    "for designation."
                )
            if projection.points.extrapolated:
                caveats.append(
                    f"{lineup.side}: {projection.player.name}'s projection is "
                    "above anything seen when the outcome distribution was "
                    "fitted, so the interval sampled for them is an "
                    "extrapolation."
                )

    return tuple(caveats)


def _shared_games(
    lineup_a: Lineup, lineup_b: Lineup, by_id: Mapping[str, PlayerProjection]
) -> tuple[str, ...]:
    """Games with a player on both sides of the matchup."""
    games_a = {
        by_id[player_id].game_id
        for player_id in lineup_a.player_ids
        if by_id[player_id].game_id
    }
    games_b = {
        by_id[player_id].game_id
        for player_id in lineup_b.player_ids
        if by_id[player_id].game_id
    }
    return tuple(sorted(game for game in games_a & games_b if game))
