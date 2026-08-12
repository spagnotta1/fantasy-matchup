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
    validate_settings,
)
from .valuation import CONSENSUS_HISTORY_WEIGHT, CONSENSUS_NOISE, ReplacementLevel

logger = logging.getLogger(__name__)

#: Total simulated drafts one request may ask for, across every seat it covers.
#: A comparison of twelve seats at a thousand simulations each is twelve
#: thousand drafts, and the cap is what stops a single request occupying a
#: worker for several minutes. Measured cost is reported in the response, so a
#: caller can size their own request rather than guess.
MAX_TOTAL_DRAFTS = 15_000


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
    history_weight: float
    noise: float
    elapsed_seconds: float
    notices: tuple[str, ...]
    history: Mapping[str, HistoricalEvidence]


@dataclass(frozen=True)
class DraftPositionComparison:
    """Every seat, ranked."""

    settings: DraftSettings
    comparison: DraftComparison
    seats: tuple[SeatAnalysis, ...]
    pool: PoolSummary
    model: ModelRef | None
    calibration_drafts: int
    history_weight: float
    noise: float
    elapsed_seconds: float
    notices: tuple[str, ...]
    history: Mapping[str, HistoricalEvidence]


def limits() -> DraftLimits:
    """Bounds a client builds its configuration form from."""
    return DraftLimits()


async def draftable_seasons(session: AsyncSession) -> tuple[int, ...]:
    """Seasons with a published week 1 board, newest first.

    A season picker must be built from this rather than from the schedule. The
    warehouse holds decades of seasons and the model can only project a week
    whose features exist, which for week 1 means the season must already have
    been played — so offering every season in the schedule would offer a user
    dozens of drafts that cannot be run.
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
    history_weight: float | None = None,
    noise: float | None = None,
) -> DraftAnalysis:
    """Simulate one seat many times and summarise what it builds.

    Raises:
        InvalidRequest: for an incoherent configuration, including a request
            whose total simulated drafts exceed :data:`MAX_TOTAL_DRAFTS`.
        NoProjectionsPublished: when the season has no published week 1 run.
    """
    settings, weights = _prepare(
        teams=teams,
        rounds=rounds,
        season=season,
        scoring_profile=scoring_profile,
        roster=roster,
        draft_format=draft_format,
        simulations=simulations,
        seed=seed,
        history_weight=history_weight,
        noise=noise,
        seats=1,
    )
    seat = validate_draft_position(draft_position, settings)

    pool = await pool_module.build_pool(session, settings)
    started = time.perf_counter()

    context, availability, analyses = await asyncio.to_thread(
        _run, pool, settings, weights, (seat,)
    )
    elapsed = time.perf_counter() - started

    logger.info(
        "mock draft %s seat %d: %d simulation(s) in %.2fs (seed %d)",
        settings.season, seat, settings.simulations, elapsed, settings.seed,
    )
    return DraftAnalysis(
        settings=settings,
        draft_position=seat,
        seat=analyses[0],
        pool=_summarise(pool, context),
        model=pool.model,
        calibration_drafts=availability.drafts,
        history_weight=weights[0],
        noise=weights[1],
        elapsed_seconds=elapsed,
        notices=_notices(pool, settings, weights),
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
    history_weight: float | None = None,
    noise: float | None = None,
) -> DraftPositionComparison:
    """Simulate every seat and rank them.

    One calibration and one pool serve all of them, which is most of why this
    costs less than running :func:`analyse_draft_position` once per seat: the
    availability curves do not depend on which seat is being analysed.
    """
    settings, weights = _prepare(
        teams=teams,
        rounds=rounds,
        season=season,
        scoring_profile=scoring_profile,
        roster=roster,
        draft_format=draft_format,
        simulations=simulations,
        seed=seed,
        history_weight=history_weight,
        noise=noise,
        seats=teams,
    )

    pool = await pool_module.build_pool(session, settings)
    started = time.perf_counter()

    seats = tuple(range(1, settings.teams + 1))
    context, availability, analyses = await asyncio.to_thread(
        _run, pool, settings, weights, seats
    )
    elapsed = time.perf_counter() - started

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
        history_weight=weights[0],
        noise=weights[1],
        elapsed_seconds=elapsed,
        notices=_notices(pool, settings, weights)
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
    weights: tuple[float, float],
    seats: Sequence[int],
) -> tuple[DraftContext, AvailabilityModel, list[SeatAnalysis]]:
    """The whole synchronous batch. Runs in a worker thread; touches no session.

    Kept as one function rather than three awaited calls so that the loop is
    released once and reacquired once. Three hops would mean three context
    switches and three chances for another request to interleave a CPU-bound
    section onto the loop between them.
    """
    context = DraftContext.build(
        pool, settings, history_weight=weights[0], noise=weights[1]
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
    history_weight: float | None,
    noise: float | None,
    seats: int,
) -> tuple[DraftSettings, tuple[float, float]]:
    """Validate everything before a single query is spent."""
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

    return settings, (
        _bounded("history_weight", history_weight, CONSENSUS_HISTORY_WEIGHT),
        _bounded("noise", noise, CONSENSUS_NOISE),
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
    pool: DraftPool, settings: DraftSettings, weights: tuple[float, float]
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

    return pool.notices + depth + (
        f"These are simulated outcomes from {settings.simulations:,} drafts at "
        f"seed {settings.seed}, not predictions. The same settings, published "
        "run and seed reproduce them exactly; a different seed will not.",
        "Opposing managers are simulated from an internal consensus board — "
        f"{1 - weights[0]:.0%} value over replacement, {weights[0]:.0%} last "
        "completed season's actual points — with randomness added. This "
        "repository contains no average-draft-position data, so that model is "
        "a stated assumption and has not been validated against how people "
        "really draft.",
        "Kickers and team defences are not draftable here: no validated "
        "projection exists for either. A roster including them would need "
        "values this engine would have to invent. See /meta/positions.",
    )
