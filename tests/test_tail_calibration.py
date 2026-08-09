"""Phase 6C: the tail factors as a parameter, and the harness that measures them.

Two properties carry this file.

**The evaluation's fast path is the production path.**
:class:`~nflfp.evaluation.tails.LineupDraws` re-scores a lineup under any tail
configuration without re-sampling it, by exploiting the fact that the factors
enter only the two outer segments of a piecewise-linear curve. That is an
optimisation, and an optimisation of the thing a production constant will be
chosen on has to be proved equal to what it replaces — not approximately, and not
only on average. :class:`TestFastPathEquivalence` compares it against
:func:`nflfp.services.simulation.simulate` sampling curves built by
:meth:`OutcomeCurve.from_percentiles`, draw for draw.

**A tail factor changes only by an approved decision.** Phase 6C was an
evaluation and shipped nothing; its recommendation of ``1.0 / 2.0`` was approved
and applied in Phase 6D, and :class:`TestProductionDefaultsUnchanged` moved to
the new pair in that same commit. The guard is not "these constants are frozen"
— it is "these constants do not change by accident", which is why it names the
values rather than reading them.
"""

from __future__ import annotations

import random

import pytest

from nflfp.correlation.model import CorrelationMode
from nflfp.correlation.panel import Panel, PanelRow
from nflfp.correlation.sampler import RosterMember, build_sampler
from nflfp.evaluation.tails import (
    KNOT_PROBABILITIES,
    TailFactors,
    build_curve,
    default_grid,
    paired_delta,
    draw_lineup,
    lower_gap,
    percentile,
    pit_of,
    player_metrics,
    run_sweep,
    upper_gap,
)
from nflfp.services.distributions import (
    HARD_FLOOR,
    LOWER_TAIL_FACTOR,
    UPPER_TAIL_FACTOR,
    OutcomeCurve,
)
from nflfp.services.simulation import SimulationInput, _percentile, simulate


def row(
    player_id="00-0000001",
    position="WR",
    team="KC",
    game_id="2023_05_KC_MIN",
    p10=1.4,
    p25=3.2,
    p50=7.1,
    p75=12.8,
    p90=19.4,
    expected=8.6,
    actual=6.2,
    season=2023,
    week=5,
) -> PanelRow:
    return PanelRow(
        player_id=player_id,
        season=season,
        week=week,
        position=position,
        team=team,
        opponent="MIN",
        game_id=game_id,
        expected=expected,
        p10=p10,
        p25=p25,
        p50=p50,
        p75=p75,
        p90=p90,
        samples=300,
        extrapolated=False,
        actual=actual,
    )


def lineup_of(count: int = 7) -> list[PanelRow]:
    """A lineup whose players differ in every way the tails care about."""
    shapes = [
        ("QB", 4.1, 9.6, 15.8, 21.9, 27.4, 16.1, 22.4),
        ("RB", 0.0, 0.0, 6.4, 12.1, 19.9, 8.2, 3.1),
        ("RB", 2.2, 5.1, 9.8, 15.0, 21.6, 10.4, 17.7),
        ("WR", 1.4, 3.2, 7.1, 12.8, 19.4, 8.6, 6.2),
        ("WR", 0.4, 0.4, 4.9, 10.2, 18.1, 7.0, 24.3),
        ("TE", 0.8, 2.0, 5.1, 8.9, 13.7, 6.1, 1.9),
        ("RB", 3.0, 6.0, 10.0, 14.0, 18.0, 10.2, 11.0),
    ]
    return [
        row(
            player_id=f"00-000{index:04d}",
            position=position,
            team="KC" if index % 2 else "MIN",
            p10=p10, p25=p25, p50=p50, p75=p75, p90=p90,
            expected=expected, actual=actual,
        )
        for index, (position, p10, p25, p50, p75, p90, expected, actual)
        in enumerate(shapes[:count])
    ]


class TestProductionDefaultsUnchanged:
    def test_the_shipped_constants_are_the_approved_phase_6c_ones(self):
        # Phase 6A-6C shipped 1.5 / 2.5. Phase 6C measured 36 configurations on
        # held-out lineups and recommended 1.0 / 2.0; that recommendation was
        # approved and applied in Phase 6D, and this assertion moved with it in
        # the same commit. The friction is the point: if this fails because
        # somebody changed the constants, change it deliberately and say so in
        # docs/simulation-readiness.md.
        assert LOWER_TAIL_FACTOR == 1.0
        assert UPPER_TAIL_FACTOR == 2.0

    def test_an_unqualified_curve_is_the_incumbent_curve(self):
        default = OutcomeCurve.from_percentiles(
            p10=1.4, p25=3.2, median=7.1, p75=12.8, p90=19.4
        )
        explicit = OutcomeCurve.from_percentiles(
            p10=1.4, p25=3.2, median=7.1, p75=12.8, p90=19.4,
            lower_tail_factor=LOWER_TAIL_FACTOR,
            upper_tail_factor=UPPER_TAIL_FACTOR,
        )
        assert default is not None and explicit is not None
        assert default.knots == explicit.knots

    def test_incumbent_reads_the_constants_rather_than_repeating_them(self):
        assert TailFactors.incumbent().as_pair() == (
            LOWER_TAIL_FACTOR, UPPER_TAIL_FACTOR
        )
        assert TailFactors.incumbent().is_incumbent


class TestCurveUnderCandidateFactors:
    @pytest.mark.parametrize("lower", [0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
    @pytest.mark.parametrize("upper", [0.0, 0.5, 1.5, 2.5, 3.0])
    def test_percentiles_stay_ordered(self, lower, upper):
        curve = build_curve(lineup_of()[0], TailFactors(lower, upper))
        values = [curve.quantile(q) for q in (0.0, *KNOT_PROBABILITIES, 1.0)]
        assert values == sorted(values)

    @pytest.mark.parametrize("lower", [0.0, 1.0, 1.5, 2.5])
    @pytest.mark.parametrize("upper", [0.0, 1.0, 2.5, 3.0])
    def test_the_stored_percentiles_are_untouched(self, lower, upper):
        # The whole claim of this phase is that it changes the assumption
        # outside the stored range and nothing inside it.
        source = lineup_of()[0]
        curve = build_curve(source, TailFactors(lower, upper))
        for probability, stored in zip(
            KNOT_PROBABILITIES,
            (source.p10, source.p25, source.p50, source.p75, source.p90),
        ):
            assert curve.quantile(probability) == pytest.approx(stored, abs=1e-9)

    def test_expected_values_stay_finite_across_the_grid(self):
        for factors in default_grid():
            curve = build_curve(lineup_of()[0], factors)
            value = curve.mean()
            assert value == value and abs(value) < 1e6  # not NaN, not runaway

    def test_a_larger_factor_never_narrows_its_own_tail(self):
        source = lineup_of()[0]
        lows = [build_curve(source, TailFactors(f, 2.5)).lower for f in
                (0.0, 0.5, 1.0, 1.5, 2.0, 2.5)]
        highs = [build_curve(source, TailFactors(1.5, f)).upper for f in
                 (0.0, 0.5, 1.0, 1.5, 2.0, 2.5)]
        assert lows == sorted(lows, reverse=True)
        assert highs == sorted(highs)

    def test_the_other_tail_is_left_alone(self):
        source = lineup_of()[0]
        assert (
            build_curve(source, TailFactors(0.0, 2.5)).upper
            == build_curve(source, TailFactors(2.5, 2.5)).upper
        )
        assert (
            build_curve(source, TailFactors(1.5, 0.0)).lower
            == build_curve(source, TailFactors(1.5, 3.0)).lower
        )

    def test_a_zero_factor_stops_at_the_stored_knot(self):
        source = lineup_of()[0]
        curve = build_curve(source, TailFactors(0.0, 0.0))
        assert curve.lower == pytest.approx(source.p10)
        assert curve.upper == pytest.approx(source.p90)

    def test_the_hard_floor_still_binds_at_a_large_lower_factor(self):
        source = row(p10=2.0, p25=14.0, p50=18.0, p75=24.0, p90=30.0)
        assert build_curve(source, TailFactors(2.5, 2.5)).lower >= HARD_FLOOR


class TestGaps:
    def test_the_lower_gap_matches_the_curve_it_describes(self):
        source = lineup_of()[0]
        for factor in (0.0, 0.7, 1.5, 2.5, 4.0):
            curve = build_curve(source, TailFactors(factor, 2.5))
            assert lower_gap(source.p10, source.p25, factor) == pytest.approx(
                source.p10 - curve.lower, abs=1e-12
            )

    def test_the_upper_gap_matches_the_curve_it_describes(self):
        source = lineup_of()[0]
        for factor in (0.0, 0.7, 2.5, 3.0):
            curve = build_curve(source, TailFactors(1.5, factor))
            assert upper_gap(source.p75, source.p90, factor) == pytest.approx(
                curve.upper - source.p90, abs=1e-12
            )

    def test_a_flat_bottom_gets_no_gap_at_any_factor(self):
        # P10 == P25 means no observed downside spread; inventing one would
        # fabricate a negative outcome for a player who has never had one.
        assert lower_gap(0.0, 0.0, 2.5) == 0.0

    def test_a_stored_floor_below_the_hard_floor_gets_no_gap(self):
        assert lower_gap(-8.0, -2.0, 1.5) == 0.0


class TestFastPathEquivalence:
    """The decomposition must reproduce the production sampler exactly."""

    @pytest.mark.parametrize(
        "factors",
        [TailFactors(1.5, 2.5), TailFactors(0.0, 0.5), TailFactors(2.5, 3.0),
         TailFactors(0.5, 1.5)],
    )
    def test_totals_match_a_real_simulation_draw_for_draw(self, factors):
        rows = lineup_of()
        members = [
            RosterMember(position=r.position, team=r.team, game_id=r.game_id)
            for r in rows
        ]
        sampler = build_sampler(members, mode=CorrelationMode.INDEPENDENT)
        rng = random.Random(11)
        uniforms = [sampler.draw(rng) for _ in range(200)]

        fast = draw_lineup(rows, uniforms, range(len(rows)))
        totals = fast.totals(factors)

        curves = [build_curve(r, factors) for r in rows]
        for index, draw in enumerate(uniforms):
            expected = sum(
                curve.quantile(u) for curve, u in zip(curves, draw)
            )
            assert totals[index] == pytest.approx(expected, abs=1e-9)

    def test_it_matches_the_engine_end_to_end(self):
        # Not just the arithmetic: the same numbers simulate() would report.
        factors = TailFactors(1.0, 1.5)
        rows = lineup_of()
        inputs = [
            SimulationInput(
                player_id=r.player_id, name=r.player_id, slot=r.position,
                position=r.position, team=r.team, game_id=r.game_id,
                curve=build_curve(r, factors), expected_points=r.expected,
                floor=r.p10, ceiling=r.p90,
            )
            for r in rows
        ]
        result_a, _, _, _ = simulate(inputs, inputs, iterations=500, seed=99)

        members = [
            RosterMember(position=r.position, team=r.team, game_id=r.game_id)
            for r in rows
        ]
        sampler = build_sampler(members * 2, mode=CorrelationMode.INDEPENDENT)
        rng = random.Random(99)
        uniforms = [sampler.draw(rng) for _ in range(500)]
        fast = draw_lineup(rows, uniforms, range(len(rows)))
        totals = sorted(fast.totals(factors))

        assert percentile(totals, 0.10) == pytest.approx(result_a.p10, abs=1e-9)
        assert percentile(totals, 0.90) == pytest.approx(result_a.p90, abs=1e-9)
        assert sum(totals) / len(totals) == pytest.approx(
            result_a.expected_score, abs=1e-9
        )

    def test_it_is_deterministic(self):
        rows = lineup_of()
        members = [
            RosterMember(position=r.position, team=r.team, game_id=r.game_id)
            for r in rows
        ]
        sampler = build_sampler(members, mode=CorrelationMode.INDEPENDENT)
        uniforms = [sampler.draw(random.Random(3)) for _ in range(50)]
        first = draw_lineup(rows, uniforms, range(len(rows))).totals(
            TailFactors(1.5, 2.5)
        )
        second = draw_lineup(rows, uniforms, range(len(rows))).totals(
            TailFactors(1.5, 2.5)
        )
        assert first == second

    def test_a_wider_upper_tail_never_lowers_a_total(self):
        rows = lineup_of()
        members = [
            RosterMember(position=r.position, team=r.team, game_id=r.game_id)
            for r in rows
        ]
        sampler = build_sampler(members, mode=CorrelationMode.INDEPENDENT)
        rng = random.Random(7)
        uniforms = [sampler.draw(rng) for _ in range(300)]
        draws = draw_lineup(rows, uniforms, range(len(rows)))
        narrow = draws.totals(TailFactors(1.5, 1.0))
        wide = draws.totals(TailFactors(1.5, 3.0))
        assert all(w >= n - 1e-12 for w, n in zip(wide, narrow))

    def test_a_wider_lower_tail_never_raises_a_total(self):
        rows = lineup_of()
        members = [
            RosterMember(position=r.position, team=r.team, game_id=r.game_id)
            for r in rows
        ]
        sampler = build_sampler(members, mode=CorrelationMode.INDEPENDENT)
        rng = random.Random(7)
        uniforms = [sampler.draw(rng) for _ in range(300)]
        draws = draw_lineup(rows, uniforms, range(len(rows)))
        narrow = draws.totals(TailFactors(0.0, 2.5))
        wide = draws.totals(TailFactors(2.5, 2.5))
        assert all(w <= n + 1e-12 for w, n in zip(wide, narrow))


class TestPairedDelta:
    def test_it_measures_the_difference_and_its_error(self):
        incumbent = [1.0, 2.0, 3.0, 4.0]
        candidate = [1.5, 2.5, 3.5, 4.5]
        delta = paired_delta("crps", incumbent, candidate)
        assert delta.delta == pytest.approx(0.5)
        assert delta.standard_error == pytest.approx(0.0, abs=1e-12)
        assert delta.n == 4

    def test_a_noisy_difference_is_not_significant(self):
        rng = random.Random(2)
        incumbent = [rng.gauss(10, 3) for _ in range(400)]
        candidate = [value + rng.gauss(0, 3) for value in incumbent]
        assert not paired_delta("crps", incumbent, candidate).significant

    def test_a_consistent_difference_is(self):
        rng = random.Random(2)
        incumbent = [rng.gauss(10, 3) for _ in range(400)]
        candidate = [value - 0.4 for value in incumbent]
        delta = paired_delta("crps", incumbent, candidate)
        assert delta.significant and delta.delta < 0

    def test_unpaired_series_are_refused(self):
        # Two configurations scored on different observations are not a paired
        # comparison, and reporting a standard error for one would be a lie.
        with pytest.raises(ValueError):
            paired_delta("crps", [1.0, 2.0], [1.0])


class TestPercentileDefinition:
    def test_it_is_the_engine_s_definition(self):
        sample = sorted(random.Random(1).random() * 40 for _ in range(1_000))
        for probability in (0.05, 0.10, 0.25, 0.5, 0.75, 0.90, 0.95):
            assert percentile(sample, probability) == pytest.approx(
                _percentile(sample, probability), abs=1e-12
            )

    def test_pit_is_bounded_and_monotone(self):
        sample = sorted(float(value) for value in range(100))
        assert 0.0 < pit_of(sample, -50.0) < 0.01
        assert 0.99 < pit_of(sample, 500.0) <= 1.0
        assert pit_of(sample, 10.0) < pit_of(sample, 80.0)


class TestPlayerMetrics:
    def test_knot_coverage_does_not_move_with_the_factors(self):
        # The invariant that lets a lineup-level recalibration claim it has not
        # touched what Layer 3b validated.
        rows = lineup_of() * 20
        first = player_metrics(rows, TailFactors(1.5, 2.5))
        second = player_metrics(rows, TailFactors(0.0, 1.0))
        assert first.knot_coverage == second.knot_coverage

    def test_crps_and_drift_do_move(self):
        rows = lineup_of() * 20
        wide = player_metrics(rows, TailFactors(2.5, 3.0))
        narrow = player_metrics(rows, TailFactors(0.0, 0.5))
        assert wide.crps != narrow.crps
        assert wide.mean_drift > narrow.mean_drift

    def test_it_is_deterministic(self):
        rows = lineup_of() * 5
        assert (
            player_metrics(rows, TailFactors(1.5, 2.5)).crps
            == player_metrics(rows, TailFactors(1.5, 2.5)).crps
        )


class TestSweep:
    def _panel(self) -> Panel:
        rows = []
        rng = random.Random(4)
        for week in (1, 2):
            for index in range(40):
                position = ("QB", "RB", "WR", "TE")[index % 4]
                base = 6.0 + rng.random() * 12.0
                rows.append(
                    row(
                        player_id=f"00-00{index:05d}",
                        position=position,
                        team=f"T{index % 8}",
                        game_id=f"2023_{week:02d}_G{index % 4}",
                        p10=base * 0.2, p25=base * 0.5, p50=base * 0.9,
                        p75=base * 1.4, p90=base * 2.0,
                        expected=base, actual=base * rng.random() * 2.0,
                        season=2023, week=week,
                    )
                )
        return Panel.of("half_ppr", "shrinkage_eb", rows)

    def test_it_scores_every_candidate_on_the_same_lineups(self):
        grid = (TailFactors(1.5, 2.5), TailFactors(0.5, 1.0))
        result = run_sweep(
            self._panel(), grid=grid, seasons=(2023,), period="test",
            matchups_per_week=4, iterations=200, seed=5,
        )
        assert result.weeks == 2
        assert result.results[grid[0]].lineup.n == result.results[grid[1]].lineup.n
        assert result.results[grid[0]].lineup.n == result.lineups

    def test_a_narrower_configuration_produces_narrower_intervals(self):
        grid = (TailFactors(2.5, 3.0), TailFactors(0.0, 0.5))
        result = run_sweep(
            self._panel(), grid=grid, seasons=(2023,), period="test",
            matchups_per_week=4, iterations=200, seed=5,
        )
        assert (
            result.results[grid[1]].lineup.mean_width_80
            < result.results[grid[0]].lineup.mean_width_80
        )

    def test_the_sweep_is_reproducible(self):
        grid = (TailFactors(1.5, 2.5),)
        kwargs = dict(
            grid=grid, seasons=(2023,), period="test",
            matchups_per_week=4, iterations=200, seed=5,
        )
        first = run_sweep(self._panel(), **kwargs)
        second = run_sweep(self._panel(), **kwargs)
        assert first.results[grid[0]].lineup.crps == pytest.approx(
            second.results[grid[0]].lineup.crps, abs=1e-12
        )
        assert first.results[grid[0]].matchup.brier == pytest.approx(
            second.results[grid[0]].matchup.brier, abs=1e-12
        )

    def test_metrics_are_numerically_valid(self):
        grid = default_grid()
        result = run_sweep(
            self._panel(), grid=grid, seasons=(2023,), period="test",
            matchups_per_week=3, iterations=200, seed=5,
        )
        for factor_result in result.results.values():
            lineup = factor_result.lineup
            assert 0.0 <= lineup.coverage_80 <= 1.0
            assert 0.0 <= lineup.coverage_90 <= 1.0
            assert lineup.crps >= 0.0
            assert lineup.crps == lineup.crps  # not NaN
            assert sum(lineup.pit) == pytest.approx(1.0, abs=1e-9)
            assert list(lineup.knot_coverage) == sorted(lineup.knot_coverage)
            matchup = factor_result.matchup
            assert 0.0 <= matchup.brier <= 1.0
            assert matchup.log_loss >= 0.0

    def test_series_are_collected_only_when_asked_for(self):
        grid = (TailFactors(1.5, 2.5), TailFactors(0.5, 2.0))
        kwargs = dict(
            grid=grid, seasons=(2023,), period="test",
            matchups_per_week=4, iterations=200, seed=5,
        )
        quiet = run_sweep(self._panel(), **kwargs)
        loud = run_sweep(self._panel(), collect_series=True, **kwargs)
        assert quiet.results[grid[0]].lineup_series == {}
        assert len(loud.results[grid[0]].lineup_series["crps"]) == loud.lineups
        assert len(loud.results[grid[0]].matchup_series["brier"]) == loud.matchups

    def test_collecting_series_does_not_change_the_metrics(self):
        grid = (TailFactors(1.5, 2.5),)
        kwargs = dict(
            grid=grid, seasons=(2023,), period="test",
            matchups_per_week=4, iterations=200, seed=5,
        )
        quiet = run_sweep(self._panel(), **kwargs)
        loud = run_sweep(self._panel(), collect_series=True, **kwargs)
        assert quiet.results[grid[0]].lineup.crps == pytest.approx(
            loud.results[grid[0]].lineup.crps, abs=1e-12
        )

    def test_the_series_mean_is_the_reported_metric(self):
        # The paired standard errors have to belong to the same experiment as
        # the point estimates they qualify.
        grid = (TailFactors(1.5, 2.5),)
        sweep = run_sweep(
            self._panel(), grid=grid, seasons=(2023,), period="test",
            matchups_per_week=4, iterations=200, seed=5, collect_series=True,
        )
        result = sweep.results[grid[0]]
        series = result.lineup_series
        assert sum(series["crps"]) / len(series["crps"]) == pytest.approx(
            result.lineup.crps, abs=1e-9
        )
        assert sum(series["inside_80"]) / len(series["inside_80"]) == pytest.approx(
            result.lineup.coverage_80, abs=1e-9
        )
        brier = result.matchup_series["brier"]
        assert sum(brier) / len(brier) == pytest.approx(
            result.matchup.brier, abs=1e-9
        )

    def test_the_selection_rule_prefers_the_flatter_pit(self):
        grid = (TailFactors(1.5, 2.5), TailFactors(0.5, 1.0))
        result = run_sweep(
            self._panel(), grid=grid, seasons=(2023,), period="test",
            matchups_per_week=4, iterations=200, seed=5,
        )
        best = result.best()
        assert result.results[best].lineup.pit_divergence == min(
            r.lineup.pit_divergence for r in result.results.values()
        )
