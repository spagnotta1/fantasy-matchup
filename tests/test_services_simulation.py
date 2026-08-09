"""The Monte Carlo engine.

A stochastic simulation is easy to test badly. Two rules are followed
throughout:

* **No exact probability is asserted without a fixed seed.** Every test that
  names a number either seeds the run or asserts a tolerance derived from the
  Monte Carlo standard error, which for a proportion is
  ``sqrt(p(1-p)/n)`` — about 0.005 at ``p=0.5, n=10,000``.
* **Statistical claims are made against constructed distributions**, not against
  the stub warehouse. "Team A centred on 20 beats Team B centred on 10" is a
  property of the sampler; verifying it against real projections would be
  testing the projections.

The structural invariants — percentile ordering, probabilities summing to one,
nothing silently dropped — are asserted on every run, because those are the
properties a caller builds a UI on top of and a violation of any of them is
silent.
"""

from __future__ import annotations

import math

import pytest

from nflfp.services import simulation
from nflfp.services.distributions import OutcomeCurve
from nflfp.services.errors import InvalidRequest
from nflfp.services.simulation import (
    DEFAULT_ITERATIONS,
    DEFAULT_SEED,
    MAX_ITERATIONS,
    MIN_ITERATIONS,
    SimulationInput,
    simulate,
)


def curve(center: float, spread: float = 7.0) -> OutcomeCurve:
    """A right-skewed curve centred near ``center``, in the shape Layer 3b stores.

    The asymmetry is deliberate and matches the real distributions: the ceiling
    sits further from the median than the floor does, which is why the engine
    samples percentiles rather than a fitted normal.
    """
    built = OutcomeCurve.from_percentiles(
        p10=max(0.0, center - spread),
        p25=max(0.0, center - spread * 0.45),
        median=center - 0.4,
        p75=center + spread * 0.5,
        p90=center + spread * 1.3,
        expected=center,
    )
    assert built is not None
    return built


def player(
    player_id: str,
    center: float,
    *,
    slot: str = "WR",
    spread: float = 7.0,
    team: str = "KC",
    game_id: str | None = "g1",
) -> SimulationInput:
    built = curve(center, spread)
    return SimulationInput(
        player_id=player_id,
        name=player_id.upper(),
        slot=slot,
        position="WR",
        team=team,
        game_id=game_id,
        curve=built,
        expected_points=center,
        floor=built.quantile(0.10),
        ceiling=built.quantile(0.90),
    )


def team(prefix: str, center: float, size: int = 7, **kwargs) -> list[SimulationInput]:
    """A lineup whose players all sit at the same centre."""
    return [player(f"{prefix}{i}", center, **kwargs) for i in range(size)]


def assert_coherent(result: simulation.TeamSimulation) -> None:
    """Invariants every team result must satisfy, whatever the inputs."""
    assert result.percentiles_are_ordered, (
        f"{result.p10} {result.p25} {result.median_score} {result.p75} {result.p90}"
    )
    total = result.win_probability + result.loss_probability + result.tie_probability
    assert math.isclose(total, 1.0, abs_tol=1e-9)
    for probability in (
        result.win_probability,
        result.loss_probability,
        result.tie_probability,
    ):
        assert 0.0 <= probability <= 1.0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Reproducibility is a product property, not a testing convenience.

    ``probability_beats`` is deterministic by construction on the grounds that a
    start/sit call returning a different answer on every refresh is unusable.
    A simulation owes the same.
    """

    def test_the_same_seed_reproduces_the_result_exactly(self):
        a, b = team("a", 14.0), team("b", 13.0)
        first = simulate(a, b, iterations=2_000, seed=42)
        second = simulate(a, b, iterations=2_000, seed=42)
        assert first == second

    def test_a_different_seed_gives_a_different_sample(self):
        a, b = team("a", 14.0), team("b", 13.0)
        first = simulate(a, b, iterations=2_000, seed=1)
        second = simulate(a, b, iterations=2_000, seed=2)
        assert first[0].expected_score != second[0].expected_score

    def test_two_seeds_agree_to_within_sampling_error(self):
        # Different samples, same distribution. If these diverged the sampler
        # would be seed-dependent in a way a seed is not supposed to be.
        a, b = team("a", 14.0), team("b", 13.0)
        first = simulate(a, b, iterations=20_000, seed=1)[0]
        second = simulate(a, b, iterations=20_000, seed=2)[0]
        assert abs(first.win_probability - second.win_probability) < 0.02

    def test_the_result_does_not_depend_on_the_global_rng(self):
        # A private Random, not random.seed(). Seeding the module-level RNG
        # would make one simulation's draws depend on anything else in the
        # process that had called random.
        import random as global_random

        a, b = team("a", 14.0), team("b", 13.0)
        global_random.seed(7)
        first = simulate(a, b, iterations=1_000, seed=99)
        [global_random.random() for _ in range(1000)]
        second = simulate(a, b, iterations=1_000, seed=99)
        assert first == second

    def test_lineup_order_fixes_the_draw_sequence(self):
        # Stated so that a future "sort the lineup for tidiness" change fails
        # here rather than silently changing what every stored seed means.
        # The players must differ for the order to be observable, which is
        # itself the point: the seed contract is about the submitted request.
        a = [player(f"a{i}", 8.0 + 3.0 * i) for i in range(7)]
        b = team("b", 13.0)
        forward = simulate(a, b, iterations=1_000, seed=42)[0]
        reversed_ = simulate(a[::-1], b, iterations=1_000, seed=42)[0]

        # Position in the lineup decides which uniform a player receives, so
        # the same player at a different index draws a different sample.
        first = {p.player_id: p.simulated_mean for p in forward.players}
        second = {p.player_id: p.simulated_mean for p in reversed_.players}
        assert first.keys() == second.keys()
        assert first["a0"] != second["a0"]

        # The team total happens to be invariant here only because these curves
        # are pure location shifts of one shape, which makes the sum symmetric
        # in the draws. That is a property of the fixture, not a guarantee, and
        # it is why the assertion above is per player.
        assert forward.expected_score == pytest.approx(reversed_.expected_score)

    def test_the_default_seed_is_fixed_rather_than_entropy(self):
        a, b = team("a", 14.0), team("b", 13.0)
        assert simulate(a, b, iterations=500) == simulate(
            a, b, iterations=500, seed=DEFAULT_SEED
        )


# ---------------------------------------------------------------------------
# Aggregation and coherence
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_the_simulated_mean_tracks_the_sum_of_stored_expectations(self):
        # The cheapest available check that the sampler drew from the
        # distributions it was handed rather than from something else.
        a, b = team("a", 12.0), team("b", 12.0)
        result_a, _, _, _ = simulate(a, b, iterations=DEFAULT_ITERATIONS, seed=7)
        assert result_a.projection_sum == pytest.approx(7 * 12.0)
        # The sampled mean converges on the *reconstruction's* mean, which is
        # the exact statement of "it drew from the curve it was handed".
        assert result_a.expected_score == pytest.approx(
            7 * curve(12.0).mean(), rel=0.02
        )

    def test_the_reconstruction_sits_above_the_stored_mean(self):
        # Not a bug and worth pinning: distributions.py extends the upper tail
        # 2.5x the P75-P90 segment against 1.5x on the lower, because weekly
        # scoring is right-skewed. The sampled total therefore runs a little
        # above the sum of stored expectations, and `projection_sum` is
        # reported beside `expected_score` so a caller can see the gap rather
        # than discover it.
        a, b = team("a", 12.0), team("b", 12.0)
        result_a, _, _, _ = simulate(a, b, iterations=DEFAULT_ITERATIONS, seed=7)
        assert result_a.expected_score > result_a.projection_sum
        assert result_a.expected_score < result_a.projection_sum * 1.15

    def test_the_team_total_is_the_sum_of_its_players(self):
        a, b = team("a", 12.0), team("b", 12.0)
        result_a, _, _, _ = simulate(a, b, iterations=5_000, seed=3)
        assert result_a.expected_score == pytest.approx(
            sum(entry.simulated_mean for entry in result_a.players), rel=1e-9
        )

    def test_every_lineup_slot_is_reported_back(self):
        # Nothing silently dropped: a simulation that lost a player would
        # report a total that is a starter light with no signal.
        a, b = team("a", 12.0), team("b", 12.0)
        result_a, result_b, _, _ = simulate(a, b, iterations=500, seed=1)
        assert [p.player_id for p in result_a.players] == [p.player_id for p in a]
        assert [p.player_id for p in result_b.players] == [p.player_id for p in b]

    def test_percentiles_are_ordered(self):
        a, b = team("a", 15.0), team("b", 9.0)
        result_a, result_b, _, _ = simulate(a, b, iterations=DEFAULT_ITERATIONS, seed=5)
        assert_coherent(result_a)
        assert_coherent(result_b)

    def test_percentiles_are_ordered_even_at_the_minimum_count(self):
        # The interesting case: with few draws the percentiles are adjacent
        # order statistics and any smoothing step could reorder them.
        a, b = team("a", 15.0), team("b", 9.0)
        result_a, _, _, _ = simulate(a, b, iterations=MIN_ITERATIONS, seed=5)
        assert_coherent(result_a)

    def test_the_median_sits_between_p25_and_p75(self):
        a, b = team("a", 15.0), team("b", 9.0)
        result, _, _, _ = simulate(a, b, iterations=DEFAULT_ITERATIONS, seed=5)
        assert result.p25 <= result.median_score <= result.p75

    def test_probabilities_sum_to_one_on_both_sides(self):
        a, b = team("a", 14.0), team("b", 14.0)
        result_a, result_b, _, _ = simulate(a, b, iterations=DEFAULT_ITERATIONS, seed=11)
        assert result_a.win_probability == pytest.approx(result_b.loss_probability)
        assert result_a.tie_probability == pytest.approx(result_b.tie_probability)
        assert_coherent(result_a)
        assert_coherent(result_b)

    def test_the_mean_margin_is_the_difference_of_the_means(self):
        a, b = team("a", 16.0), team("b", 11.0)
        result_a, result_b, mean_margin, _ = simulate(a, b, iterations=5_000, seed=4)
        assert mean_margin == pytest.approx(
            result_a.expected_score - result_b.expected_score, rel=1e-9
        )

    def test_the_median_margin_can_differ_from_the_mean_margin(self):
        # Two lineups of different volatility produce a skewed margin. That the
        # two disagree is the reason both are reported.
        a = team("a", 14.0, spread=3.0)
        b = team("b", 14.0, spread=14.0)
        _, _, mean_margin, median_margin = simulate(a, b, iterations=20_000, seed=6)
        assert mean_margin != median_margin


class TestTies:
    def test_ties_are_counted_at_scoring_precision(self):
        # Reconstructed curves are continuous; real scoring is not. Comparing
        # raw floats would report a tie probability of exactly zero for every
        # matchup ever simulated, which is a lie of a different kind.
        a, b = team("a", 12.0), team("b", 12.0)
        result_a, _, _, _ = simulate(a, b, iterations=50_000, seed=8)
        assert 0.0 <= result_a.tie_probability < 0.01

    def test_identical_lineups_tie_every_time_they_are_compared_to_themselves(self):
        # A degenerate curve: every draw is the same number, so both sides
        # always score the same and the result is all ties.
        flat = OutcomeCurve(knots=((0.0, 10.0), (1.0, 10.0)), expected=10.0)
        entry = SimulationInput(
            "x", "X", "WR", "WR", "KC", "g1", flat, 10.0, 10.0, 10.0
        )
        result_a, result_b, _, _ = simulate([entry], [entry], iterations=200, seed=1)
        assert result_a.tie_probability == 1.0
        assert result_a.win_probability == 0.0
        assert_coherent(result_a)
        assert_coherent(result_b)


# ---------------------------------------------------------------------------
# Statistical sanity
# ---------------------------------------------------------------------------


class TestStatisticalSanity:
    """Synthetic distributions where the right answer is not in dispute."""

    def test_a_far_better_team_wins_overwhelmingly(self):
        a = team("a", 20.0)
        b = team("b", 10.0)
        result_a, result_b, margin, _ = simulate(
            a, b, iterations=DEFAULT_ITERATIONS, seed=42
        )
        assert result_a.win_probability > 0.95
        assert result_b.win_probability < 0.05
        assert margin > 0
        assert_coherent(result_a)

    def test_equal_teams_approach_fifty_percent(self):
        a = team("a", 13.5)
        b = team("b", 13.5)
        result_a, _, _, _ = simulate(a, b, iterations=DEFAULT_ITERATIONS, seed=42)
        # Two standard errors at n=10,000 is 0.01; the tolerance is wider
        # because the two lineups are distinct samples, not one compared to
        # itself.
        assert result_a.win_probability == pytest.approx(0.5, abs=0.03)

    def test_a_slightly_better_team_is_only_slightly_favoured(self):
        # The property the whole distribution layer exists for: half a point of
        # projection is not half a point of certainty.
        a = team("a", 13.6)
        b = team("b", 13.5)
        result_a, _, _, _ = simulate(a, b, iterations=DEFAULT_ITERATIONS, seed=42)
        assert 0.48 < result_a.win_probability < 0.56

    def test_the_win_probability_is_monotone_in_the_gap(self):
        b = team("b", 12.0)
        previous = 0.0
        for center in (10.0, 12.0, 14.0, 16.0, 18.0):
            result, _, _, _ = simulate(
                team("a", center), b, iterations=20_000, seed=42
            )
            assert result.win_probability >= previous - 0.01
            previous = result.win_probability

    def test_a_wider_lineup_has_a_wider_interval(self):
        narrow, _, _, _ = simulate(
            team("a", 13.0, spread=3.0), team("b", 13.0), iterations=20_000, seed=42
        )
        wide, _, _, _ = simulate(
            team("a", 13.0, spread=14.0), team("b", 13.0), iterations=20_000, seed=42
        )
        assert (wide.p90 - wide.p10) > (narrow.p90 - narrow.p10)

    def test_the_sample_converges_as_iterations_grow(self):
        # Not a tautology: it fails if the sampler has a bias that does not
        # shrink, which is the failure mode a fixed seed would otherwise hide.
        a, b = team("a", 14.0), team("b", 12.0)
        reference = simulate(a, b, iterations=100_000, seed=1)[0].win_probability
        errors = [
            abs(simulate(a, b, iterations=n, seed=99)[0].win_probability - reference)
            for n in (200, 20_000)
        ]
        assert errors[1] < errors[0]

    def test_a_low_floor_player_drags_the_team_floor(self):
        steady = team("a", 12.0, spread=2.0)
        boom_bust = team("a", 12.0, spread=2.0)[:-1] + [
            player("volatile", 12.0, spread=18.0)
        ]
        steady_result, _, _, _ = simulate(
            steady, team("b", 12.0), iterations=20_000, seed=3
        )
        volatile_result, _, _, _ = simulate(
            boom_bust, team("b", 12.0), iterations=20_000, seed=3
        )
        assert volatile_result.p10 < steady_result.p10
        assert volatile_result.p90 > steady_result.p90


# ---------------------------------------------------------------------------
# Bounds and refusals
# ---------------------------------------------------------------------------


class TestBounds:
    def test_an_empty_lineup_is_refused(self):
        with pytest.raises(InvalidRequest):
            simulate([], team("b", 12.0), iterations=100, seed=1)
        with pytest.raises(InvalidRequest):
            simulate(team("a", 12.0), [], iterations=100, seed=1)

    def test_a_non_positive_iteration_count_is_refused(self):
        with pytest.raises(InvalidRequest):
            simulate(team("a", 12.0), team("b", 12.0), iterations=0, seed=1)

    def test_a_single_iteration_still_produces_a_coherent_result(self):
        # Statistically useless and structurally valid. The engine is called
        # directly by benchmarks and, one day, by a background job; the request
        # bound is enforced above it, not here.
        result_a, result_b, _, _ = simulate(
            team("a", 12.0), team("b", 12.0), iterations=1, seed=1
        )
        assert_coherent(result_a)
        assert result_a.p10 == result_a.p90

    def test_a_ten_thousand_iteration_run_completes(self):
        result_a, _, _, _ = simulate(
            team("a", 14.0), team("b", 12.0), iterations=DEFAULT_ITERATIONS, seed=1
        )
        assert_coherent(result_a)

    def test_the_bounds_are_ordered_and_the_default_sits_inside_them(self):
        assert MIN_ITERATIONS < DEFAULT_ITERATIONS < MAX_ITERATIONS

    def test_the_maximum_is_a_transport_bound_not_an_engine_one(self):
        # The engine runs past MAX_ITERATIONS happily. The ceiling belongs to
        # the synchronous request, and a hundred-thousand-iteration run is a
        # background job rather than an impossibility.
        result, _, _, _ = simulate(
            team("a", 12.0), team("b", 12.0), iterations=MAX_ITERATIONS + 1, seed=1
        )
        assert_coherent(result)


# ---------------------------------------------------------------------------
# Percentile helper
# ---------------------------------------------------------------------------


class TestPercentile:
    def test_it_matches_the_linear_interpolation_definition(self):
        # numpy's default and R type 7, so a number here can be checked against
        # either without a footnote.
        values = [0.0, 1.0, 2.0, 3.0, 4.0]
        assert simulation._percentile(values, 0.0) == 0.0
        assert simulation._percentile(values, 1.0) == 4.0
        assert simulation._percentile(values, 0.5) == 2.0
        assert simulation._percentile(values, 0.25) == 1.0
        assert simulation._percentile(values, 0.10) == pytest.approx(0.4)

    def test_a_single_observation_is_every_percentile(self):
        assert simulation._percentile([7.5], 0.10) == 7.5
        assert simulation._percentile([7.5], 0.90) == 7.5

    def test_an_empty_sample_is_refused(self):
        with pytest.raises(InvalidRequest):
            simulation._percentile([], 0.5)


# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------


class TestAssumptions:
    def test_the_unprojected_positions_are_read_from_the_registry(self):
        # Not hard-coded to False. The day a kicker model ships this flips on
        # its own, and this test is what proves the wiring is real.
        from nflfp.services.positions import describe

        assumptions = simulation.SimulationAssumptions.current()
        assert assumptions.kicker_projection_available is describe("K").is_projected
        assert assumptions.defense_projection_available is describe("DST").is_projected

    def test_independence_is_declared_true(self):
        assert simulation.SimulationAssumptions.current().player_independence is True

    def test_no_adjustment_is_claimed(self):
        assumptions = simulation.SimulationAssumptions.current()
        assert assumptions.injury_adjustment_applied is False
        assert assumptions.matchup_adjustment_applied is False
        assert assumptions.weather_adjustment_applied is False

    def test_every_costly_assumption_produces_a_note(self):
        notes = simulation.SimulationAssumptions.current().notes()
        joined = " ".join(notes)
        assert "independently" in joined
        assert "kickers" in joined
        assert "injury" in joined
        assert "matchup_score is NULL" in joined

    def test_a_fully_supported_build_has_fewer_notes(self):
        # The notes are derived from the flags, so a future build with a kicker
        # model stops claiming a kicker gap without an edit.
        #
        # Correlation is the exception and stays: dropping independence does not
        # remove a disclosure, it replaces one. A correlated run is an
        # experimental mode drawing from a fitted structure, and a response that
        # said nothing about which structure would be less honest than the
        # independent one it replaced, not more.
        complete = simulation.SimulationAssumptions(
            player_independence=False,
            kicker_projection_available=True,
            defense_projection_available=True,
            injury_adjustment_applied=True,
            matchup_adjustment_applied=True,
            weather_adjustment_applied=True,
            correlation_mode="game_environment",
            correlation_model_version="1.0.0",
        )
        notes = complete.notes()
        assert len(notes) == 1
        assert "game-environment correlation structure" in notes[0]
        assert "1.0.0" in notes[0]
        for gone in ("kickers", "injury", "matchup_score is NULL"):
            assert gone not in " ".join(notes)

    def test_the_sampling_method_is_named(self):
        assert (
            simulation.SimulationAssumptions.current().sampling_method
            == "inverse_transform_from_stored_percentiles"
        )
