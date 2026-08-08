"""The reconstructed outcome curve, and the head-to-head integral over it.

Two properties matter more than the rest and are tested first:

* the curve **passes through the stored percentiles exactly** — a reconstructed
  P90 must be the P90 the calibration measured, or every downstream probability
  is quietly built on a different distribution than the one that was validated;
* :func:`probability_beats` is **deterministic** — a start/sit call that returns
  a different number on every request is not a recommendation.
"""

from __future__ import annotations

import pytest

from nflfp.services.distributions import (
    INTEGRATION_POINTS,
    OutcomeCurve,
    compare,
    probability_beats,
    probability_total_at_least,
)


def curve(
    p10=2.0, p25=5.0, median=9.0, p75=14.0, p90=21.0, expected=10.2, **kwargs
) -> OutcomeCurve:
    built = OutcomeCurve.from_percentiles(
        p10=p10, p25=p25, median=median, p75=p75, p90=p90, expected=expected, **kwargs
    )
    assert built is not None
    return built


class TestConstruction:
    def test_passes_through_every_stored_percentile(self):
        c = curve()
        stored = ((0.10, 2.0), (0.25, 5.0), (0.50, 9.0), (0.75, 14.0), (0.90, 21.0))
        for probability, value in stored:
            assert c.quantile(probability) == pytest.approx(value, abs=1e-9)

    def test_works_from_a_three_point_summary(self):
        c = OutcomeCurve.from_percentiles(p10=1.0, median=8.0, p90=19.0)
        assert c is not None
        assert c.quantile(0.5) == pytest.approx(8.0)

    def test_returns_none_when_there_is_not_enough_stored(self):
        # A missing distribution is a normal state — an unpublished week, a
        # model that declined to project. Callers must not need a try/except
        # on the common path.
        assert OutcomeCurve.from_percentiles(p10=1.0, median=None, p90=None) is None

    def test_rejects_a_reversed_distribution(self):
        with pytest.raises(ValueError):
            OutcomeCurve.from_percentiles(p10=20.0, median=8.0, p90=1.0)

    def test_from_row_reads_the_stored_column_names(self):
        c = OutcomeCurve.from_row(
            {
                "floor_points": 2.0,
                "p25_points": 5.0,
                "median_points": 9.0,
                "p75_points": 14.0,
                "ceiling_points": 21.0,
                "expected_points": 10.2,
                "extrapolated": True,
                "distribution_samples": 340,
            }
        )
        assert c is not None
        assert c.expected == 10.2 and c.extrapolated and c.samples == 340

    def test_tails_extend_past_the_stored_range(self):
        c = curve()
        assert c.lower < 2.0
        assert c.upper > 21.0

    def test_the_lower_tail_respects_the_hard_floor(self):
        # Fantasy scoring can go slightly negative; it cannot go to -40.
        c = curve(p10=0.0, p25=0.2, median=1.0, p75=3.0, p90=30.0)
        assert c.lower >= -6.0

    def test_a_flat_bottom_gets_no_imaginary_spread(self):
        # A player whose P10 and P25 are both zero has no observed downside
        # spread, and inventing one would fabricate a negative outcome.
        c = curve(p10=0.0, p25=0.0, median=1.0, p75=4.0, p90=10.0)
        assert c.lower == 0.0


class TestCdf:
    def test_inverts_the_quantile_function(self):
        c = curve()
        for q in (0.15, 0.3, 0.5, 0.7, 0.85):
            assert c.cdf(c.quantile(q)) == pytest.approx(q, abs=1e-6)

    def test_is_monotone(self):
        c = curve()
        values = [c.cdf(x) for x in range(-10, 40)]
        assert values == sorted(values)

    def test_saturates_outside_the_support(self):
        c = curve()
        assert c.cdf(c.lower - 5) == 0.0
        assert c.cdf(c.upper + 5) == 1.0

    def test_at_least_and_at_most_are_complementary(self):
        c = curve()
        assert c.probability_at_least(9.0) + c.probability_at_most(9.0) == pytest.approx(1.0)

    def test_a_flat_segment_returns_the_highest_consistent_probability(self):
        # Makes P(points >= x) conservative rather than optimistic, which is
        # the right direction for a boom probability.
        c = curve(p10=0.0, p25=0.0, median=2.0, p75=6.0, p90=12.0)
        assert c.cdf(0.0) >= 0.25


class TestMean:
    def test_reconstruction_agrees_with_the_stored_mean(self):
        # If these diverge badly the tail assumption is doing too much work.
        c = curve()
        assert c.mean() == pytest.approx(c.expected, abs=1.5)

    def test_a_symmetric_curve_has_its_median_as_its_mean(self):
        c = curve(p10=5.0, p25=7.5, median=10.0, p75=12.5, p90=15.0, expected=10.0)
        assert c.mean() == pytest.approx(10.0, abs=0.2)


class TestProbabilityBeats:
    def test_identical_curves_are_a_coin_flip(self):
        c = curve()
        assert probability_beats(c, c) == pytest.approx(0.5, abs=0.01)

    def test_is_deterministic(self):
        a, b = curve(), curve(median=11.0, p75=16.0, p90=24.0, expected=12.5)
        assert probability_beats(a, b) == probability_beats(a, b)

    def test_is_complementary(self):
        a = curve()
        b = curve(p10=4.0, p25=7.0, median=11.0, p75=16.0, p90=24.0, expected=12.5)
        assert probability_beats(a, b) + probability_beats(b, a) == pytest.approx(1.0, abs=0.02)

    def test_a_dominating_curve_almost_always_wins(self):
        weak = curve(p10=0.0, p25=1.0, median=2.0, p75=3.0, p90=4.0, expected=2.1)
        strong = curve(p10=25.0, p25=28.0, median=31.0, p75=34.0, p90=38.0, expected=31.0)
        assert probability_beats(strong, weak) > 0.99

    def test_a_small_edge_stays_near_a_coin_flip(self):
        # The whole reason the start/sit threshold exists: half a point of
        # projection is not half a point of certainty.
        a = curve(expected=10.2)
        b = curve(p10=1.5, p25=4.5, median=8.5, p75=13.5, p90=20.5, expected=9.7)
        assert 0.5 < probability_beats(a, b) < 0.56

    def test_a_margin_makes_winning_harder(self):
        a, b = curve(), curve()
        assert probability_beats(a, b, margin=5.0) < probability_beats(a, b)

    def test_grid_resolution_barely_moves_the_answer(self):
        a = curve()
        b = curve(median=11.0, expected=12.0)
        coarse = probability_beats(a, b, points=64)
        fine = probability_beats(a, b, points=4096)
        assert abs(coarse - fine) < 0.01
        assert INTEGRATION_POINTS >= 64

    def test_rejects_a_degenerate_grid(self):
        c = curve()
        with pytest.raises(ValueError):
            probability_beats(c, c, points=1)


class TestCompare:
    def test_reports_when_the_mean_and_the_odds_disagree(self):
        # A high mean carried entirely by a long ceiling. This is exactly the
        # case a points-only comparison gets wrong, and the reason the whole
        # distribution is stored.
        spiky = curve(p10=0.0, p25=1.0, median=3.0, p75=8.0, p90=45.0, expected=11.0)
        steady = curve(p10=7.0, p25=8.5, median=10.0, p75=11.5, p90=13.0, expected=10.0)
        result = compare(spiky, steady)
        assert result.expected_margin > 0
        assert result.win_probability < 0.5
        assert result.mean_and_odds_disagree

    def test_correlation_is_disclosed_not_applied(self):
        c = curve()
        assert compare(c, c).correlation_warning is None
        assert compare(c, c, correlated=True).correlation_warning is not None

    def test_falls_back_to_the_reconstructed_mean(self):
        a = OutcomeCurve.from_percentiles(p10=1.0, median=8.0, p90=19.0)
        b = OutcomeCurve.from_percentiles(p10=1.0, median=8.0, p90=19.0)
        assert a is not None and b is not None
        assert compare(a, b).expected_margin == pytest.approx(0.0, abs=1e-9)


class TestLineupTotal:
    def test_an_empty_lineup_has_no_chance(self):
        assert probability_total_at_least([], 100.0) == 0.0

    def test_the_threshold_moves_the_probability_the_right_way(self):
        lineup = [curve() for _ in range(6)]
        assert probability_total_at_least(lineup, 30.0) > probability_total_at_least(
            lineup, 120.0
        )

    def test_the_mean_total_is_roughly_even_money(self):
        lineup = [curve() for _ in range(8)]
        total = sum(c.expected for c in lineup if c.expected is not None)
        assert probability_total_at_least(lineup, total) == pytest.approx(0.5, abs=0.02)
