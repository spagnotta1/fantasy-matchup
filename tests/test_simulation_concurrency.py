"""A simulation must not stop the API answering anybody else.

The engine's *speed* is covered by ``test_simulation_performance.py``. This file
covers something the speed budget cannot see: a 50,000-iteration run is about a
second of uninterrupted Python whatever its budget says, and run on the event
loop that is a second in which a single-replica deployment answers nothing at
all — every other user's page simply stops.

What is asserted, and what deliberately is not
----------------------------------------------
Not a latency bound. How *long* a worker thread stalls the loop is a property of
the platform's GIL scheduling — the same measurement here differs by an order of
magnitude between Windows and Linux — so a millisecond threshold would encode
this machine into the suite and fail on a CI runner for reasons that have
nothing to do with the code.

What is asserted is progress: while the simulation runs, does the loop run *at
all*? That is the difference the change actually made, it is binary, and it is
the same answer on every platform. Called directly the loop makes exactly zero
progress; through a thread it makes plenty.
"""

from __future__ import annotations

import asyncio
import time

from nflfp.services.distributions import OutcomeCurve
from nflfp.services.simulation import (
    MAX_ITERATIONS,
    SimulationInput,
    simulate,
)

LINEUP_SIZE = 9

#: Long enough that a blocked loop is unambiguous rather than a scheduling
#: hiccup, short enough to stay a test. The endpoint permits five times this.
ITERATIONS = 10_000

#: How often the heartbeat asks to be woken.
TICK_SECONDS = 0.005


def lineup(prefix: str, center: float) -> list[SimulationInput]:
    built: list[SimulationInput] = []
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


async def _ticks_during(run) -> tuple[int, object]:
    """Run ``run()`` while counting how many times the loop got control back.

    The counter is a coroutine asking to be woken every few milliseconds. A loop
    blocked by synchronous work cannot wake it, so the count *is* the loop's
    availability — measured from outside the blocking call, which is the only
    place it can be measured. A timer started inside a coroutine that the block
    has already prevented from running would record nothing.
    """
    # Spin the default executor up before anything is timed. The first
    # `to_thread` in a process pays for creating the worker, and that cost lands
    # inside the measured window as ticks the loop did not get — enough, when it
    # was the first call, to halve the count and make the bound below look
    # marginal on a fast machine.
    await asyncio.to_thread(lambda: None)

    ticks = 0
    running = True

    async def heartbeat() -> None:
        nonlocal ticks
        while running:
            await asyncio.sleep(TICK_SECONDS)
            # Re-checked after the sleep, not only before it. The last wake
            # happens *after* the measured call has returned and the loop is
            # free again; counting it would credit a fully blocked run with one
            # tick and make the control below assert `<= 1` for no reason.
            if running:
                ticks += 1

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.02)  # let the heartbeat settle
    ticks = 0

    result = await run()

    running = False
    await beat
    return ticks, result


class TestTheLoopKeepsRunning:
    async def test_calling_simulate_directly_freezes_the_loop(self):
        """The behaviour being prevented, pinned so the fix cannot be undone.

        This is not a test of production code — it is the control. If this ever
        stops freezing the loop, the threading test below has stopped proving
        anything and both need rereading.
        """

        async def blocking():
            return simulate(lineup("a", 10.0), lineup("b", 9.0),
                            iterations=ITERATIONS, seed=42)

        ticks, _ = await _ticks_during(blocking)
        assert ticks == 0, (
            f"the loop woke {ticks} times during a synchronous simulation; "
            "if this no longer blocks, the concurrency test below is vacuous"
        )

    async def test_a_threaded_simulation_leaves_the_loop_available(self):
        async def threaded():
            return await asyncio.to_thread(
                simulate, lineup("a", 10.0), lineup("b", 9.0),
                iterations=ITERATIONS, seed=42,
            )

        ticks, _ = await _ticks_during(threaded)
        # Deliberately a low bar, set from the *slowest* platform measured
        # rather than the fastest: 20 ticks on Linux against 6 on Windows for
        # this size, and the control above scores 0 on both. Three keeps a wide
        # margin under the worse of the two while still being unmistakably
        # "the loop kept running". Tightening it toward the Linux figure would
        # be asserting a property of the CI runner's scheduler.
        assert ticks >= 3, (
            f"the loop only woke {ticks} times while a simulation ran in a "
            "worker thread; it is not being scheduled beside the GIL holder"
        )


class TestThreadingChangesNoNumbers:
    async def test_a_threaded_run_is_bit_identical_to_a_direct_one(self):
        """The whole permission slip for this change.

        `simulate` seeds a private `random.Random` rather than the global one,
        so it neither reads nor perturbs state shared with the event loop and
        the thread it runs on cannot matter. This asserts that rather than
        trusting it — and asserts exact equality, not approximate: a Monte Carlo
        that drifts by a float between two runs of the same seed has lost the
        determinism the module docstring promises as a product requirement.
        """
        a, b = lineup("a", 10.0), lineup("b", 9.0)

        direct = simulate(a, b, iterations=ITERATIONS, seed=42)
        threaded = await asyncio.to_thread(
            simulate, a, b, iterations=ITERATIONS, seed=42)

        assert threaded == direct

    async def test_concurrent_simulations_do_not_contaminate_each_other(self):
        """Two runs in flight at once, on different threads, same seed.

        The failure this rules out is a shared RNG: if `simulate` touched global
        random state, two overlapping runs would interleave their draws and
        neither would reproduce the sequential answer.
        """
        a, b = lineup("a", 10.0), lineup("b", 9.0)
        expected = simulate(a, b, iterations=ITERATIONS, seed=7)

        results = await asyncio.gather(*(
            asyncio.to_thread(simulate, a, b, iterations=ITERATIONS, seed=7)
            for _ in range(4)
        ))
        for result in results:
            assert result == expected


class TestTheLargestPermittedRun:
    async def test_the_maximum_run_still_leaves_the_loop_available(self):
        """The worst case the endpoint accepts, which is the one that matters.

        MAX_ITERATIONS is where a blocked loop is measured in seconds rather
        than milliseconds — the case that reads as "the site is down" rather
        than "that was slow".
        """

        async def threaded():
            return await asyncio.to_thread(
                simulate, lineup("a", 10.0), lineup("b", 9.0),
                iterations=MAX_ITERATIONS, seed=42,
            )

        start = time.perf_counter()
        ticks, _ = await _ticks_during(threaded)
        elapsed = time.perf_counter() - start

        # Measured at 29 (Windows) and 97 (Linux) against 0 for a direct call.
        assert ticks >= 10, (
            f"the loop woke only {ticks} times during a {MAX_ITERATIONS}-"
            f"iteration run lasting {elapsed:.1f}s"
        )
