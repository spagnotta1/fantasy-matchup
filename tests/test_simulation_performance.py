"""How long a simulation takes, and the bound that follows from it.

Why this is a test and not a script somebody ran once
-----------------------------------------------------
:data:`~nflfp.services.simulation.MAX_ITERATIONS` is a promise about latency,
and a promise about latency that nothing checks decays the first time the hot
loop gains a line. So the ceiling is asserted here against the measured cost:
if a change makes an iteration three times more expensive, the bound stops being
honest and this fails rather than the endpoint quietly starting to time out.

The thresholds are deliberately loose — several times the measured cost on a
developer laptop — because a CI runner is slower and a flaky performance test
gets deleted, which is worse than a loose one. They are catching a regression in
*order of magnitude*, which is the kind that matters for a synchronous endpoint.

Phase 6B added a second sampler, so the bound has to hold for both. The
correlated one costs more per iteration — it draws normals rather than uniforms
and pushes each through an error function — and the ratio is asserted rather
than assumed, because "how much does correlation cost" is a question the
decision to ship it depends on.
"""

from __future__ import annotations

import time

import pytest

from nflfp.correlation import CorrelationMode, RosterMember, build_sampler
from nflfp.correlation.fitted import GAME_ENVIRONMENT_V1
from nflfp.services.distributions import OutcomeCurve
from nflfp.services.simulation import (
    DEFAULT_ITERATIONS,
    MAX_ITERATIONS,
    SimulationInput,
    simulate,
)

#: A full standard lineup per side — fourteen curves, the shape of a real
#: request. Benchmarking a two-player matchup would flatter the result by a
#: factor of seven.
LINEUP_SIZE = 7

#: Seconds a default (10,000-iteration) run may take. Measured at ~0.15 s on one
#: core of a developer machine; the budget is an order of magnitude above that.
DEFAULT_RUN_BUDGET = 3.0

#: Seconds the largest permitted synchronous run may take. Measured at ~0.8 s;
#: the budget again leaves an order of magnitude, and the endpoint holds an
#: event-loop worker for the whole duration.
MAX_RUN_BUDGET = 10.0


def lineup(prefix: str, center: float) -> list[SimulationInput]:
    built = []
    for index in range(LINEUP_SIZE):
        points = center + index
        curve = OutcomeCurve.from_percentiles(
            p10=max(0.0, points - 7.0),
            p25=max(0.0, points - 3.0),
            median=points - 0.4,
            p75=points + 3.5,
            p90=points + 9.0,
            expected=points,
        )
        assert curve is not None
        built.append(
            SimulationInput(
                player_id=f"{prefix}{index}",
                name=f"{prefix}{index}".upper(),
                slot="FLEX",
                position="WR",
                team="KC",
                game_id=f"g{index}",
                curve=curve,
                expected_points=points,
                floor=points - 7.0,
                ceiling=points + 9.0,
            )
        )
    return built


#: Multiple of the independent cost the correlated sampler may take. Measured at
#: roughly 2x: it draws a normal per player plus one per game and per team, and
#: an error function per player, against one uniform per player. The budget
#: leaves room for a slower machine while still failing if the correlated path
#: becomes an order of magnitude more expensive — at which point it would be a
#: background job rather than a request parameter, and that is a decision to
#: take deliberately rather than discover in production.
CORRELATION_COST_BUDGET = 6.0


def timed(iterations: int, *, correlated: bool = False) -> float:
    a, b = lineup("a", 10.0), lineup("b", 9.0)
    sampler = None
    if correlated:
        sampler = build_sampler(
            [
                RosterMember(position=p.position, team=p.team, game_id=p.game_id)
                for p in (*a, *b)
            ],
            mode=CorrelationMode.GAME_ENVIRONMENT,
            model=GAME_ENVIRONMENT_V1,
        )
    start = time.perf_counter()
    simulate(a, b, iterations=iterations, seed=42, sampler=sampler)
    return time.perf_counter() - start


@pytest.mark.parametrize(
    ("iterations", "budget"),
    [(1_000, DEFAULT_RUN_BUDGET), (DEFAULT_ITERATIONS, DEFAULT_RUN_BUDGET)],
)
def test_a_typical_run_is_fast(iterations, budget):
    elapsed = timed(iterations)
    assert elapsed < budget, (
        f"{iterations} iterations took {elapsed:.2f}s, budget {budget}s"
    )


def test_the_largest_permitted_run_stays_inside_a_request_budget():
    # This is the assertion that keeps MAX_ITERATIONS honest. If it fails, the
    # fix is to lower the constant or speed up the loop — not to raise the
    # budget.
    elapsed = timed(MAX_ITERATIONS)
    assert elapsed < MAX_RUN_BUDGET, (
        f"{MAX_ITERATIONS} iterations took {elapsed:.2f}s, budget "
        f"{MAX_RUN_BUDGET}s; MAX_ITERATIONS no longer describes a synchronous "
        "request"
    )


def test_the_cost_is_linear_in_iterations():
    # A superlinear sampler would make the bound meaningless: a limit set from
    # a 10,000-iteration measurement would not describe a 50,000-iteration run.
    # Ten times the work, generously under twenty times the wall clock.
    small = timed(2_000)
    large = timed(20_000)
    assert large < small * 20 + 0.5, f"2k={small:.3f}s 20k={large:.3f}s"


def test_the_engine_terminates_on_the_minimum_and_the_maximum():
    # No unbounded loop at either end. Cheap, and the failure it catches — an
    # endpoint that never returns — is the one that takes a service down rather
    # than making it slow.
    assert timed(100) < 1.0
    assert timed(MAX_ITERATIONS) < MAX_RUN_BUDGET


class TestCorrelatedSamplerCost:
    """What the correlated candidate costs, asserted rather than assumed."""

    @pytest.mark.parametrize(
        "iterations", [1_000, DEFAULT_ITERATIONS, MAX_ITERATIONS]
    )
    def test_a_correlated_run_stays_inside_the_same_budget(self, iterations):
        budget = MAX_RUN_BUDGET if iterations == MAX_ITERATIONS else DEFAULT_RUN_BUDGET
        elapsed = timed(iterations, correlated=True)
        assert elapsed < budget, (
            f"{iterations} correlated iterations took {elapsed:.2f}s, budget "
            f"{budget}s — the correlated mode no longer fits a synchronous "
            "request and MAX_ITERATIONS does not describe it"
        )

    def test_correlation_costs_a_small_multiple_not_an_order_of_magnitude(self):
        # Warm both paths first: the first call in a process pays import and
        # allocation costs that would otherwise land entirely on whichever arm
        # ran first and make the ratio meaningless.
        timed(2_000)
        timed(2_000, correlated=True)

        independent = min(timed(20_000) for _ in range(3))
        correlated = min(timed(20_000, correlated=True) for _ in range(3))
        ratio = correlated / independent
        assert ratio < CORRELATION_COST_BUDGET, (
            f"correlated sampling is {ratio:.1f}x the independent cost "
            f"({correlated:.3f}s against {independent:.3f}s), above the "
            f"{CORRELATION_COST_BUDGET}x budget"
        )

    def test_the_correlated_cost_is_also_linear_in_iterations(self):
        # Same argument as the independent case: a bound set from one
        # measurement only describes another if the cost is linear.
        small = timed(2_000, correlated=True)
        large = timed(20_000, correlated=True)
        assert large < small * 20 + 0.5, f"2k={small:.3f}s 20k={large:.3f}s"
