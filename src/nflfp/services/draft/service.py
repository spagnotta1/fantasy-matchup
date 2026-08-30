"""Async orchestration: retrieve, then get off the event loop.

The shape is the one :func:`nflfp.services.simulation.simulate_matchup` already
established, and it is the only shape that works: the retrieval is IO-bound and
belongs on the loop, the simulation is seconds of uninterrupted Python and does
not. A ten-thousand-draft request computed inline would hold the loop for over a
minute, during which a single-replica deployment answers nobody — not a slow
endpoint, an outage.

So the split is strict. Everything above this module is async and touches a
session; everything below it is synchronous, pure and seeded. This module is the
seam, and it is deliberately thin: validate, fetch, hand the whole batch to
:func:`asyncio.to_thread`, wrap the result.

Threading is invisible to the mathematics. Each draft seeds a private
:class:`random.Random` from ``(seed, seat, index)`` and touches no shared state,
so the same request produces the same numbers whether it ran on the loop, in a
worker, or in a notebook.

Nothing is persisted
--------------------
No table, no row, no cache of drafts. A result is reproducible from the settings,
the published run, the historical panel and the seed — all four of which travel
in the response — so storing it would buy nothing that recomputing it does not.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..catalog import resolve_scoring_profile
from ..dto import ModelRef
from ..errors import InvalidRequest
from . import aggregate, pool as pool_module
from .aggregate import DraftComparison, SeatAnalysis
from .engine import (
    CALIBRATION_DRAFTS,
    AvailabilityModel,
    DraftContext,
    calibrate_availability,
)
from .pool import DraftPool, HistoricalEvidence
from .settings import (
    CONSENSUS_BOUNDS,
    DraftLimits,
    DraftSettings,
    validate_draft_position,
    validate_opponent_skill,
    validate_settings,
)
from .valuation import (
    MAX_ORDERLY_SCATTER,
    OpponentSkill,
    ReplacementLevel,
    board_scatter_ratio,
)

logger = logging.getLogger(__name__)

#: Total simulated drafts one request may ask for, across every seat it covers.
#: A comparison of twelve seats at a thousand simulations each is twelve
#: thousand drafts, and the cap is what stops a single request occupying a
#: worker for several minutes. Measured cost is reported in the response, so a
#: caller can size their own request rather than guess.
MAX_TOTAL_DRAFTS = 15_000


@dataclass(frozen=True)
class OpponentModel:
    """The opponent parameters one request actually ran with.

    The skill level and the two numbers travel together because a response that
    reported only the numbers would make a user reverse-engineer which level
    they picked, and one that reported only the level would hide an explicit
    ``history_weight`` override that moved the answer. ``overridden`` says which
    of the two the request set by hand, so the UI can show "Sharp" plainly and
    "Sharp (adjusted)" when it is no longer the level it names.

    Attributes:
        skill: The level the request named, or the default.
        history_weight: The weight actually used.
        noise: The noise actually used.
        overridden: Field names the request set explicitly, overriding the level.
        scatter_ratio: :func:`~nflfp.services.draft.valuation.board_scatter_ratio`
            for this board and this noise — how large the opponents' randomness
            is against the spacing of the board they draft from.
    """

    skill: OpponentSkill
    history_weight: float
    noise: float
    overridden: tuple[str, ...] = ()
    scatter_ratio: float = 0.0

    @property
    def is_level(self) -> bool:
        """Whether this is still the named level, unmodified."""
        return not self.overridden

    def with_scatter(self, ratio: float) -> OpponentModel:
        """Copy carrying the board-scatter measurement, known only after a pool."""
        return OpponentModel(
            skill=self.skill,
            history_weight=self.history_weight,
            noise=self.noise,
            overridden=self.overridden,
            scatter_ratio=ratio,
        )


@dataclass(frozen=True)
class PoolSummary:
    """What the board was built from, for the response's methodology block."""

    players: int
    positions: tuple[str, ...]
    season: int
    board_week: int
    season_games: int
    history_seasons: tuple[int, ...]
    replacement: tuple[ReplacementLevel, ...]
    players_without_history: int
    #: Whether the board is missing the incoming rookie class. Always true while
    #: the foundation projects from a trailing usage window — a player with no
    #: window gets no projection and no pool entry — and carried as a field
    #: rather than as prose so a client can give it its own treatment instead of
    #: burying it in a list of six notices. It becomes false on the day a rookie
    #: model ships, with no edit to the presentation layer.
    rookies_absent: bool = True


@dataclass(frozen=True)
class DraftAnalysis:
    """One seat, analysed.

    ``history`` is the pool's historical evidence keyed by player id. It rides
    along rather than being re-fetched by the presentation layer because the
    pool already holds it and a second query to decorate fifteen roster rows
    would be a round-trip spent on data already in memory.
    """

    settings: DraftSettings
    draft_position: int
    seat: SeatAnalysis
    pool: PoolSummary
    model: ModelRef | None
    calibration_drafts: int
    opponents: OpponentModel
    elapsed_seconds: float
    notices: tuple[str, ...]
    history: Mapping[str, HistoricalEvidence]

    @property
    def history_weight(self) -> float:
        return self.opponents.history_weight

    @property
    def noise(self) -> float:
        return self.opponents.noise


@dataclass(frozen=True)
class DraftPositionComparison:
    """Every seat, ranked."""

    settings: DraftSettings
    comparison: DraftComparison
    seats: tuple[SeatAnalysis, ...]
    pool: PoolSummary
    model: ModelRef | None
    calibration_drafts: int
    opponents: OpponentModel
    elapsed_seconds: float
    notices: tuple[str, ...]
    history: Mapping[str, HistoricalEvidence]

    @property
    def history_weight(self) -> float:
        return self.opponents.history_weight

    @property
    def noise(self) -> float:
        return self.opponents.noise


def limits() -> DraftLimits:
    """Bounds a client builds its configuration form from."""
    return DraftLimits()


async def draftable_seasons(session: AsyncSession) -> tuple[int, ...]:
    """Seasons with a published week 1 board, newest first.

    A season picker must be built from this rather than from the schedule: the
    warehouse holds decades of seasons and the model can only project a week
    whose features exist, so offering every scheduled season would offer a user
    dozens of drafts that cannot be run.

    A season that has not started can qualify. Week 1's usage window is the tail
    of the previous season — that is what
    :mod:`nflfp.features.preseason` assembles, and it is what a manager actually
    has in August — so publishing a week 1 run for the coming season makes it
    appear here like any other. The pool that results carries no rookies, which
    is a material gap rather than a rounding, and
    :attr:`PoolSummary.rookies_absent` is how a client is told.
    """
    from .. import repository

    published = await repository.published_season_weeks(session)
    return tuple(
        sorted({season for season, week in published if week == 1}, reverse=True)
    )


async def analyse_draft_position(
    session: AsyncSession,
    *,
    draft_position: int,
    teams: int,
    rounds: int,
    season: int,
    scoring_profile: str | None = None,
    roster: Sequence[object] | None = None,
    draft_format: str = "snake",
    simulations: int | None = None,
    seed: int | None = None,
    opponent_skill: str | None = None,
    history_weight: float | None = None,
    noise: float | None = None,
) -> DraftAnalysis:
    """Simulate one seat many times and summarise what it builds.

    Raises:
        InvalidRequest: for an incoherent configuration, including a request
            whose total simulated drafts exceed :data:`MAX_TOTAL_DRAFTS`.
        NoProjectionsPublished: when the season has no published week 1 run.
    """
    settings, opponents = _prepare(
        teams=teams,
        rounds=rounds,
        season=season,
        scoring_profile=scoring_profile,
        roster=roster,
        draft_format=draft_format,
        simulations=simulations,
        seed=seed,
        opponent_skill=opponent_skill,
        history_weight=history_weight,
        noise=noise,
        seats=1,
    )
    seat = validate_draft_position(draft_position, settings)

    pool = await pool_module.build_pool(session, settings)
    started = time.perf_counter()

    context, availability, analyses = await asyncio.to_thread(
        _run, pool, settings, opponents, (seat,)
    )
    elapsed = time.perf_counter() - started
    opponents = _measure(opponents, context, settings)

    logger.info(
        "mock draft %s seat %d: %d simulation(s) in %.2fs "
        "(seed %d, opponents %s)",
        settings.season, seat, settings.simulations, elapsed, settings.seed,
        opponents.skill.name,
    )
    return DraftAnalysis(
        settings=settings,
        draft_position=seat,
        seat=analyses[0],
        pool=_summarise(pool, context),
        model=pool.model,
        calibration_drafts=availability.drafts,
        opponents=opponents,
        elapsed_seconds=elapsed,
        notices=_notices(pool, settings, opponents),
        history=_history(pool),
    )


async def compare_draft_positions(
    session: AsyncSession,
    *,
    teams: int,
    rounds: int,
    season: int,
    scoring_profile: str | None = None,
    roster: Sequence[object] | None = None,
    draft_format: str = "snake",
    simulations: int | None = None,
    seed: int | None = None,
    opponent_skill: str | None = None,
    history_weight: float | None = None,
    noise: float | None = None,
) -> DraftPositionComparison:
    """Simulate every seat and rank them.

    One calibration and one pool serve all of them, which is most of why this
    costs less than running :func:`analyse_draft_position` once per seat: the
    availability curves do not depend on which seat is being analysed.
    """
    settings, opponents = _prepare(
        teams=teams,
        rounds=rounds,
        season=season,
        scoring_profile=scoring_profile,
        roster=roster,
        draft_format=draft_format,
        simulations=simulations,
        seed=seed,
        opponent_skill=opponent_skill,
        history_weight=history_weight,
        noise=noise,
        seats=teams,
    )

    pool = await pool_module.build_pool(session, settings)
    started = time.perf_counter()

    seats = tuple(range(1, settings.teams + 1))
    context, availability, analyses = await asyncio.to_thread(
        _run, pool, settings, opponents, seats
    )
    elapsed = time.perf_counter() - started
    opponents = _measure(opponents, context, settings)

    comparison = aggregate.compare_seats(analyses)
    logger.info(
        "mock draft %s comparison: %d seat(s) x %d simulation(s) in %.2fs, "
        "best seat %d%s",
        settings.season, len(seats), settings.simulations, elapsed,
        comparison.best_position,
        "" if comparison.spread_is_resolvable else " (spread within noise)",
    )
    return DraftPositionComparison(
        settings=settings,
        comparison=comparison,
        seats=tuple(analyses),
        pool=_summarise(pool, context),
        model=pool.model,
        calibration_drafts=availability.drafts,
        opponents=opponents,
        elapsed_seconds=elapsed,
        notices=_notices(pool, settings, opponents)
        + (()
           if comparison.spread_is_resolvable
           else (
               "The gap between the best and worst draft position is smaller "
               "than the simulation's own error, so the ranking below is not "
               "separable from noise at this simulation count. Raise the "
               "simulation count to resolve it, or read the seats as "
               "equivalent.",
           )),
        history=_history(pool),
    )


def _run(
    pool: DraftPool,
    settings: DraftSettings,
    opponents: OpponentModel,
    seats: Sequence[int],
) -> tuple[DraftContext, AvailabilityModel, list[SeatAnalysis]]:
    """The whole synchronous batch. Runs in a worker thread; touches no session.

    Kept as one function rather than three awaited calls so that the loop is
    released once and reacquired once. Three hops would mean three context
    switches and three chances for another request to interleave a CPU-bound
    section onto the loop between them.
    """
    context = DraftContext.build(
        pool,
        settings,
        history_weight=opponents.history_weight,
        noise=opponents.noise,
    )
    availability = calibrate_availability(context, seed=settings.seed)
    analyses = [
        aggregate.analyse_seat(
            context,
            draft_position=seat,
            availability=availability,
            simulations=settings.simulations,
            seed=settings.seed,
        )
        for seat in seats
    ]
    return context, availability, analyses


def _prepare(
    *,
    teams: int,
    rounds: int,
    season: int,
    scoring_profile: str | None,
    roster: Sequence[object] | None,
    draft_format: str,
    simulations: int | None,
    seed: int | None,
    opponent_skill: str | None,
    history_weight: float | None,
    noise: float | None,
    seats: int,
) -> tuple[DraftSettings, OpponentModel]:
    """Validate everything before a single query is spent.

    The opponent model resolves in two steps: the named skill level supplies the
    pair, then an explicit ``history_weight`` or ``noise`` overrides its half of
    it. That ordering is what lets the level be the ordinary control and the two
    raw numbers stay available for a sensitivity check, without either meaning
    having to give way to the other.
    """
    profile = resolve_scoring_profile(scoring_profile)
    settings = validate_settings(
        teams=teams,
        rounds=rounds,
        scoring_profile=profile,
        season=season,
        roster=roster,
        draft_format=draft_format,
        simulations=(
            DraftLimits().default_simulations if simulations is None else simulations
        ),
        seed=seed,
    )

    total = settings.simulations * seats
    if total > MAX_TOTAL_DRAFTS:
        raise InvalidRequest(
            f"{seats} seat(s) at {settings.simulations} simulations is "
            f"{total:,} simulated drafts, above the {MAX_TOTAL_DRAFTS:,} a "
            "single request may run. Lower the simulation count, or analyse "
            "one draft position instead of comparing all of them.",
            field="simulations",
        )

    level = validate_opponent_skill(opponent_skill)
    return settings, OpponentModel(
        skill=level,
        history_weight=_bounded(
            "history_weight", history_weight, level.history_weight
        ),
        noise=_bounded("noise", noise, level.noise),
        overridden=tuple(
            field
            for field, value in (
                ("history_weight", history_weight), ("noise", noise)
            )
            if value is not None
        ),
    )


def _measure(
    opponents: OpponentModel, context: DraftContext, settings: DraftSettings
) -> OpponentModel:
    """Attach the board-scatter measurement, which needs the built context.

    ``noise_scale`` rather than ``noise`` is the input, because the ratio is
    only meaningful in the units the engine actually adds its randomness in.
    """
    return opponents.with_scatter(
        board_scatter_ratio(
            context.consensus,
            noise_scale=context.noise_scale,
            drafted=settings.total_picks,
        )
    )


def _bounded(field: str, value: float | None, default: float) -> float:
    if value is None:
        return default
    low, high = CONSENSUS_BOUNDS[field]
    if not low <= value <= high:
        raise InvalidRequest(
            f"{field} must be between {low} and {high}, got {value}", field=field
        )
    return float(value)


def _history(pool: DraftPool) -> dict[str, HistoricalEvidence]:
    """Historical evidence keyed by player id, for decorating a roster."""
    return {player.player_id: player.historical for player in pool.players}


def _summarise(pool: DraftPool, context: DraftContext) -> PoolSummary:
    return PoolSummary(
        players=len(pool.players),
        positions=pool.positions,
        season=pool.season,
        board_week=pool.board_week,
        season_games=pool.season_games,
        history_seasons=pool.history_seasons,
        replacement=tuple(
            context.levels[position] for position in sorted(context.levels)
        ),
        players_without_history=sum(
            1
            for player in pool.players
            if player.historical.availability_basis == "position_prior"
        ),
    )


def _notices(
    pool: DraftPool, settings: DraftSettings, opponents: OpponentModel
) -> tuple[str, ...]:
    """Everything a client must show beside a simulated draft.

    The pool's own disclosures, plus the two that belong to the simulation
    rather than to the board: that these are simulated outcomes and not
    predictions, and that the opponent model is an assumption nothing in this
    repository can validate.
    """
    shortfall = settings.total_picks - len(pool.players)
    depth: tuple[str, ...] = ()
    if shortfall > 0:
        depth = (
            f"This league drafts {settings.total_picks} players and only "
            f"{len(pool.players)} are projected, so the last rounds run out of "
            "board. Seats reached those picks in a different order, so their "
            "late-round rosters are not strictly comparable. Reduce the rounds "
            "or the league size to remove the effect.",
        )

    scatter: tuple[str, ...] = ()
    if opponents.scatter_ratio > MAX_ORDERLY_SCATTER:
        scatter = (
            "At this noise setting the randomness in the opposing managers' "
            f"selections is {opponents.scatter_ratio:.0f} times the spacing "
            "between neighbouring players on their own board, so a player's "
            "effective draft position moves by more than a round for no "
            "reason. Talent will slide to your seat that would not slide in "
            "any real draft, and the draft positions will finish closer "
            "together than they should. Lower the noise, or pick a sharper "
            "opponent skill level.",
        )

    return pool.notices + depth + scatter + (
        f"These are simulated outcomes from {settings.simulations:,} drafts at "
        f"seed {settings.seed}, not predictions. The same settings, published "
        "run and seed reproduce them exactly; a different seed will not.",
        "Opposing managers are simulated from an internal consensus board — "
        f"{1 - opponents.history_weight:.0%} value over replacement, "
        f"{opponents.history_weight:.0%} last completed season's actual "
        f"points — with randomness added, at the "
        f"{opponents.skill.label.lower()} skill level"
        + (
            f" adjusted by an explicit {' and '.join(opponents.overridden)}"
            if opponents.overridden
            else ""
        )
        + ". This repository contains no average-draft-position data, so that "
        "model is a stated assumption and has not been validated against how "
        "people really draft. It is a request field precisely so a conclusion "
        "that depends on it can be found out.",
        "Kickers and team defences are not draftable here: no validated "
        "projection exists for either. A roster including them would need "
        "values this engine would have to invent. See /meta/positions.",
    )
