"""The estimation half: the PIT, the fit, and the leakage boundary.

The strongest test here is :class:`TestRecoveryFromKnownLoadings`. Every other
check in this phase compares the fitted structure against reality, where being
wrong and reality being complicated are indistinguishable. That one generates
data from loadings it already knows and asks whether the estimator finds them
again — so a failure is unambiguously the estimator's, which is the only place
in the phase where that is true.

:class:`TestLeakage` is the one whose failure would silently invalidate every
number in ``docs/simulation-readiness.md``. A correlation fitted on the week it
is being scored against would flatter the candidate arm and nothing else in the
harness would notice.
"""

from __future__ import annotations

import math
import random

import pytest

from nflfp.correlation.estimate import (
    MIN_WEEKS_TO_FIT,
    PROJECTION_FLOOR,
    _anchor,
    accumulate,
    build_model,
    fit_loadings,
    walk_forward_models,
)
from nflfp.correlation.model import EXCLUDED_CELLS, POSITIONS
from nflfp.correlation.panel import (
    Panel,
    PanelRow,
    PanelScore,
    _cdf_bounds,
    normal_cdf,
    normal_score,
    pit,
    score_panel,
)
from nflfp.services.distributions import OutcomeCurve


def curve(base: float) -> OutcomeCurve:
    built = OutcomeCurve.from_percentiles(
        p10=base * 0.25, p25=base * 0.60, median=base * 0.92,
        p75=base * 1.35, p90=base * 1.95, expected=base,
    )
    assert built is not None
    return built


class TestNormalScore:
    """The inverse normal CDF, which everything downstream is measured in."""

    @pytest.mark.parametrize(
        ("u", "expected"),
        [(0.5, 0.0), (0.975, 1.959964), (0.025, -1.959964),
         (0.99, 2.326348), (0.01, -2.326348), (0.8413447, 1.0)],
    )
    def test_it_matches_the_known_quantiles(self, u, expected):
        assert normal_score(u) == pytest.approx(expected, abs=1e-5)

    def test_it_round_trips_against_the_cdf(self):
        for u in (0.001, 0.05, 0.3, 0.5, 0.77, 0.95, 0.999):
            assert normal_cdf(normal_score(u)) == pytest.approx(u, abs=1e-6)

    def test_the_endpoints_are_refused_rather_than_returning_an_infinity(self):
        # A single infinite normal score would take an entire correlation cell
        # with it, and it would do so silently.
        for bad in (0.0, 1.0, -0.1, 1.1):
            with pytest.raises(ValueError):
                normal_score(bad)


class TestProbabilityIntegralTransform:
    """Including the zero atom, which is where a naive PIT goes wrong."""

    def test_an_outcome_at_the_median_lands_near_a_half(self):
        rng = random.Random(1)
        outcome = curve(10.0).quantile(0.50)
        assert pit(curve(10.0), outcome, rng) == pytest.approx(0.50, abs=0.01)

    def test_the_bounds_collapse_where_the_curve_is_strictly_increasing(self):
        low, high = _cdf_bounds(curve(10.0), curve(10.0).quantile(0.70))
        assert low == pytest.approx(high, abs=1e-9)
        assert low == pytest.approx(0.70, abs=1e-6)

    def test_the_bounds_span_the_atom_where_the_curve_is_flat(self):
        # A player whose floor and lower quartile are both zero. The stored
        # curve is flat there, so an outcome of zero is consistent with a whole
        # range of probabilities rather than one.
        flat = OutcomeCurve.from_percentiles(
            p10=0.0, p25=0.0, median=4.0, p75=9.0, p90=16.0, expected=5.5
        )
        assert flat is not None
        low, high = _cdf_bounds(flat, 0.0)
        assert high > low, "the zero atom must span a probability interval"
        assert low == pytest.approx(0.0, abs=1e-9)
        assert high >= 0.25

    def test_the_atom_is_spread_uniformly_rather_than_piled_on_one_value(self):
        # This is the whole reason the PIT is randomised. Every zero-scoring
        # player mapping to the same value would make two of them look perfectly
        # correlated, biasing every cell upward.
        flat = OutcomeCurve.from_percentiles(
            p10=0.0, p25=0.0, median=4.0, p75=9.0, p90=16.0, expected=5.5
        )
        assert flat is not None
        rng = random.Random(7)
        values = [pit(flat, 0.0, rng) for _ in range(20_000)]
        assert len(set(values)) > 10_000
        _, high = _cdf_bounds(flat, 0.0)
        assert sum(values) / len(values) == pytest.approx(high / 2, abs=0.02)

    def test_a_calibrated_forecast_produces_a_uniform_pit(self):
        # Draw outcomes *from* the curve, then transform them back through it.
        # A correct PIT returns uniform; anything else means the transform is
        # bending the distribution it is supposed to be measuring against.
        source = curve(12.0)
        rng = random.Random(3)
        counts = [0] * 10
        for _ in range(40_000):
            outcome = source.quantile(rng.random())
            counts[min(int(pit(source, outcome, rng) * 10), 9)] += 1
        for count in counts:
            assert count / 40_000 == pytest.approx(0.10, abs=0.01)


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------


def synthetic_scores(loadings, *, games=4000, seed=5):
    """Panel scores generated from a known factor structure.

    Two teams per game, a fixed roster shape per team, and normal scores built
    exactly as the model says they should be. The rows carry projections above
    the floor so nothing is filtered out, and the outcome is irrelevant — the
    estimator reads ``z``, which is set directly here.

    **Two of every position except quarterback**, which is not cosmetic. A
    position's game loading is identified most directly by its own
    same-position opposing cell, so a shape with one tight end per team leaves
    ``alpha_TE`` resting on the single smallest cell in the table — and a
    three-sigma fluctuation there moves the fitted loading by 0.25. That is a
    real property of the estimator rather than a quirk of the fixture: it is
    why the fit on live data leans on the QB-TE and WR-TE cross cells, where
    ``TE-TE opp`` has only 606 pairs.
    """
    rng = random.Random(seed)
    shape = ("QB", "RB", "RB", "WR", "WR", "TE", "TE")
    scores = []
    for index in range(games):
        game_factor = rng.gauss(0.0, 1.0)
        for side, team in enumerate(("H", "A")):
            team_factor = rng.gauss(0.0, 1.0)
            for slot, position in enumerate(shape):
                alpha, beta = loadings[position]
                delta = math.sqrt(max(0.0, 1.0 - alpha ** 2 - beta ** 2))
                z = (
                    alpha * game_factor
                    + beta * team_factor
                    + delta * rng.gauss(0.0, 1.0)
                )
                row = PanelRow(
                    player_id=f"g{index}{team}{slot}", season=2024,
                    week=1 + index % 17, position=position,
                    team=f"{team}{index}", opponent=None, game_id=f"G{index}",
                    expected=12.0, p10=3.0, p25=7.0, p50=11.0, p75=16.0,
                    p90=23.0, samples=1000, extrapolated=False, actual=11.0,
                )
                scores.append(
                    PanelScore(row=row, u=normal_cdf(z), z=z)
                )
    return scores


class TestRecoveryFromKnownLoadings:
    """Generate from known parameters; check the estimator finds them."""

    LOADINGS = {
        "QB": (0.40, math.sqrt(1.0 - 0.40 ** 2)),  # anchored, as the fit assumes
        "RB": (0.10, 0.12),
        "WR": (0.20, 0.18),
        "TE": (0.15, 0.16),
    }

    @pytest.fixture(scope="class")
    def recovered(self):
        statistics = accumulate(synthetic_scores(self.LOADINGS))
        loadings, _, rmse = fit_loadings(statistics)
        return loadings, rmse

    @pytest.mark.parametrize("position", POSITIONS)
    def test_each_loading_comes_back(self, recovered, position):
        loadings, _ = recovered
        game, team = self.LOADINGS[position]
        # 4,000 games is ~24,000 pairs per cell; the sampling error on a
        # correlation there is ~0.006, and a loading is roughly its square root,
        # so 0.03 is a comfortable several standard errors.
        assert loadings[position].game == pytest.approx(game, abs=0.03), position
        assert loadings[position].team == pytest.approx(team, abs=0.03), position

    def test_the_fit_is_tight_when_the_structure_is_the_true_one(self, recovered):
        _, rmse = recovered
        assert rmse < 0.01, (
            "the estimator cannot reproduce data generated by its own model, "
            "so the misfit measured on real data is not evidence about football"
        )

    def test_a_null_structure_is_recovered_as_null(self):
        flat = {position: (0.0, 0.0) for position in POSITIONS}
        model = build_model(accumulate(synthetic_scores(flat, games=3000)))
        # Asserted on the implied *correlations*, not the raw loadings. The
        # quarterback's team loading is the anchor and is pinned near 1 whatever
        # the data says — what makes the structure null is that every other
        # position loads near zero, so every product does too.
        #
        # The band is sampling error, not slack. The smallest cell here holds
        # ~6,000 pairs, so a correlation measured at exactly zero still lands
        # within ~0.013 of it, and a same-position loading is the square root of
        # such a cell. Three of those is 0.04.
        for index, first in enumerate(POSITIONS):
            for second in POSITIONS[index:]:
                for same in (True, False):
                    if (first, second, "same" if same else "opp") in EXCLUDED_CELLS:
                        continue
                    assert abs(
                        model.correlation(first, second, same_team=same)
                    ) < 0.04, (first, second, same)


class TestTheAnchor:
    """The identification constraint, checked as a constraint."""

    def test_it_pins_the_quarterback_to_the_unit_circle(self):
        anchored = _anchor([0.4, 0.0] + [0.2, 0.2] * 3)
        assert anchored[0] ** 2 + anchored[1] ** 2 == pytest.approx(1.0, abs=1e-12)

    def test_it_leaves_every_other_position_alone(self):
        original = [0.4, 0.9] + [0.11, 0.22, 0.33, 0.44, 0.55, 0.66]
        anchored = _anchor(original)
        assert anchored[2:] == original[2:]

    def test_a_fitted_quarterback_has_no_idiosyncratic_term_by_construction(self):
        loadings, _, _ = fit_loadings(
            accumulate(synthetic_scores(TestRecoveryFromKnownLoadings.LOADINGS))
        )
        # Not a claim that quarterbacks are deterministic — their randomness
        # *is* the team factor under this normalisation. See _anchor. The
        # tolerance is the loading precision the fit rounds to, not a hedge:
        # the constraint is exact and only the rounding is not.
        assert loadings["QB"].idiosyncratic == pytest.approx(0.0, abs=1e-3)
        assert loadings["QB"].shared_variance == pytest.approx(1.0, abs=1e-5)


class TestExcludedCells:
    def test_the_relief_quarterback_cell_never_reaches_the_fit(self):
        loadings = {position: (0.2, 0.2) for position in POSITIONS}
        # Two quarterbacks per team, which is what a relief appearance looks
        # like in the panel and what the exclusion exists to keep out.
        scores = synthetic_scores(loadings, games=500)
        extra = []
        for score in scores:
            if score.row.position == "QB":
                extra.append(
                    PanelScore(
                        row=PanelRow(**{
                            **score.row.__dict__,
                            "player_id": score.row.player_id + "_backup",
                        }),
                        u=score.u, z=-score.z,
                    )
                )
        statistics = accumulate([*scores, *extra])
        assert ("QB", "QB", "same") not in statistics.cells
        assert ("QB", "QB", "same") in EXCLUDED_CELLS

    def test_pairs_from_different_games_are_never_formed(self):
        loadings = {position: (0.3, 0.3) for position in POSITIONS}
        statistics = accumulate(synthetic_scores(loadings, games=100))
        # Seven players a side, fourteen a game: 91 pairs per game and not one
        # more. A single cross-game pair would show up here immediately.
        assert statistics.pairs == 100 * 91

    def test_players_below_the_projection_floor_are_excluded(self):
        loadings = {position: (0.3, 0.3) for position in POSITIONS}
        scores = synthetic_scores(loadings, games=50)
        benched = [
            PanelScore(
                row=PanelRow(**{**s.row.__dict__, "expected": PROJECTION_FLOOR - 0.1}),
                u=s.u, z=s.z,
            )
            for s in scores
        ]
        assert accumulate(benched).pairs == 0


# ---------------------------------------------------------------------------
# Leakage
# ---------------------------------------------------------------------------


def panel_of(scores) -> Panel:
    return Panel.of("half_ppr", "shrinkage_eb", [score.row for score in scores])


class TestLeakage:
    """The boundary whose failure would invalidate every metric in the phase."""

    @pytest.fixture(scope="class")
    def walked(self):
        # Outcomes have to *vary*. A panel where everyone scores their median
        # has zero variance in the normal scores, every cell's correlation is
        # undefined, and the fit would raise rather than test anything.
        rng = random.Random(11)
        rows = []
        for season in (2023, 2024):
            for week in range(1, 19):
                for game in range(40):
                    for slot, position in enumerate(("QB", "RB", "WR", "TE")):
                        for team in ("H", "A"):
                            rows.append(
                                PanelRow(
                                    player_id=f"{season}{week}{game}{team}{slot}",
                                    season=season, week=week, position=position,
                                    team=f"{team}{game}", opponent=None,
                                    game_id=f"{season}_{week}_{game}",
                                    expected=12.0, p10=3.0, p25=7.0, p50=11.0,
                                    p75=16.0, p90=23.0, samples=1000,
                                    extrapolated=False,
                                    actual=round(rng.uniform(0.0, 30.0), 2),
                                )
                            )
        panel = Panel.of("half_ppr", "shrinkage_eb", rows)
        return panel, list(walk_forward_models(panel, seasons=[2024]))

    def test_every_fitted_structure_predates_the_week_it_is_used_for(self, walked):
        _, results = walked
        for ordinal, model in results:
            if model is None:
                continue
            assert model.estimation.through < ordinal, (
                f"a structure fitted through {model.estimation.through} is "
                f"being applied to {ordinal}"
            )

    def test_the_evaluated_weeks_are_exactly_the_requested_season(self, walked):
        _, results = walked
        assert {ordinal[0] for ordinal, _ in results} == {2024}

    def test_thin_history_yields_no_model_rather_than_a_bad_one(self, walked):
        # None means "run independent for this week". Substituting a later fit
        # would be the leak; substituting a default would be inventing a
        # correlation nothing measured.
        panel, results = walked
        for ordinal, model in results:
            prior_weeks = len(set(panel.before(*ordinal).weeks()))
            if prior_weeks < MIN_WEEKS_TO_FIT:
                assert model is None, ordinal

    def test_the_estimation_sample_grows_monotonically(self, walked):
        _, results = walked
        sizes = [m.estimation.pairs for _, m in results if m is not None]
        assert sizes == sorted(sizes)
        assert sizes[0] < sizes[-1]


class TestPanelRoundTrip:
    def test_a_saved_panel_reloads_identically(self, tmp_path):
        loadings = {position: (0.2, 0.2) for position in POSITIONS}
        panel = panel_of(synthetic_scores(loadings, games=50))
        path = tmp_path / "panel.jsonl"
        panel.save(path)
        assert Panel.load(path).rows == panel.rows

    def test_a_saved_model_reloads_identically(self, tmp_path):
        loadings = {position: (0.3, 0.25) for position in POSITIONS}
        model = build_model(accumulate(synthetic_scores(loadings, games=200)))
        path = tmp_path / "model.json"
        model.save(path)
        from nflfp.correlation.model import CorrelationModel

        reloaded = CorrelationModel.load(path)
        for position in POSITIONS:
            assert reloaded.loading(position) == model.loading(position)
        assert reloaded.estimation.through == model.estimation.through

    def test_scoring_a_panel_is_deterministic(self):
        loadings = {position: (0.2, 0.2) for position in POSITIONS}
        panel = panel_of(synthetic_scores(loadings, games=30))
        assert [s.u for s in score_panel(panel)] == [
            s.u for s in score_panel(panel)
        ]
