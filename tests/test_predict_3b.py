"""Tests for phase 3b: shrinkage, held-out distributions, calibration, persistence.

The invariants that matter most, and why:

* **Temporal integrity.** A residual model fitted on the week it describes
  reports intervals that are too tight, and nothing about the output looks wrong.
* **Train/serve feature parity.** A feature available post-hoc but not at
  prediction time makes a backtest meaningless. The contract is enforced in code
  and asserted here.
* **Percentile ordering and probability bounds.** P10 <= P25 <= P50 <= P75 <= P90
  must hold at every layer, and probabilities must stay in [0, 1].
* **Historical immutability.** Deploying a new model must not alter what was
  said last week.
"""

from __future__ import annotations

import pytest

from nflfp.predict import features as feature_contract
from nflfp.predict.calibration import (
    by_projection_range,
    calibration_report,
    expected_calibration_error,
    interval_coverage,
    max_calibration_error,
    weighted_calibration_error,
)
from nflfp.predict.distribution import (
    PointDistribution,
    ResidualDistribution,
    crps,
    pinball_loss,
)
from nflfp.predict.models.shrinkage import (
    MAX_K,
    MIN_K,
    ShrinkageModel,
    _decompose,
)
from nflfp.predict.scoring_bridge import COMPONENT_TO_COLUMN

from .conftest import requires_db


def _row(season: int, week: int, player: str = "p1", position: str = "WR", **kw) -> dict:
    row = {
        "player_id": player, "season": season, "week": week, "position": position,
        "fp_half_ppr_actual": 10.0, "fp_half_ppr_l4": 9.0, "games_in_window_l4": 4,
    }
    for column in COMPONENT_TO_COLUMN.values():
        row.setdefault(f"{column}_l4", 0.0)
        row.setdefault(f"{column}_actual", 0.0)
    row.update(kw)
    return row


# ---------------------------------------------------------------------------
# Objective 5: train/serve feature parity
# ---------------------------------------------------------------------------

class TestFeatureContract:
    @pytest.mark.parametrize(
        "name",
        ["team_spread", "total_line", "implied_team_total", "spread_source",
         "temperature_f", "wind_mph", "weather_source"],
    )
    def test_shifted_features_are_excluded(self, name):
        """Market and weather columns resolve differently for history than for
        upcoming games, so they are not prediction-time information."""
        assert not feature_contract.is_available(name)
        assert feature_contract.excluded_reason(name)

    def test_excluded_features_raise_with_an_explanation(self):
        with pytest.raises(ValueError, match="unavailable at prediction time"):
            feature_contract.assert_available(["team_spread"])

    def test_undeclared_features_are_rejected(self):
        """A column added to the feature table for display must not be usable
        by a model just because it exists."""
        with pytest.raises(ValueError, match="not declared"):
            feature_contract.assert_available(["some_new_column"])

    def test_lagged_usage_is_available(self):
        for name in ("snap_pct_l4", "targets_l4", "fp_half_ppr_l4", "games_in_window_l4"):
            assert feature_contract.is_available(name)

    def test_registered_models_only_use_available_features(self):
        """The regression guard against future information re-entering."""
        from nflfp.predict.registry import MODELS

        for name, factory in MODELS.items():
            model = factory()
            required = getattr(model, "required_features", ())
            feature_contract.assert_available(required)

    def test_feature_version_is_recorded(self):
        assert isinstance(feature_contract.FEATURE_VERSION, int)
        assert ShrinkageModel().params()["feature_version"] == (
            feature_contract.FEATURE_VERSION
        )


# ---------------------------------------------------------------------------
# Objective 3: shrinkage
# ---------------------------------------------------------------------------

class TestShrinkage:
    def test_k_is_derived_not_hardcoded(self):
        """k = var_within / var_between, computed from the sample."""
        # Ten players, each with four observations. Large within-player spread
        # and small between-player spread should give a large k.
        noisy = {f"p{i}": [i, i + 20, i, i + 20] for i in range(12)}
        params = _decompose(noisy)
        assert params is not None
        assert params.sigma_within > params.sigma_between
        assert params.k > 1.0

    def test_consistent_players_get_little_shrinkage(self):
        """Low within-player noise and wide talent spread means trust the player."""
        consistent = {f"p{i}": [i * 5.0] * 6 for i in range(12)}
        params = _decompose(consistent)
        assert params is not None
        assert params.k == pytest.approx(MIN_K)

    def test_k_is_bounded(self):
        pure_noise = {f"p{i}": [0.0, 100.0, 0.0, 100.0] for i in range(12)}
        params = _decompose(pure_noise)
        assert MIN_K <= params.k <= MAX_K

    def test_thin_samples_produce_no_parameters(self):
        """Better no shrinkage constant than one from three observations."""
        assert _decompose({"p1": [1.0, 2.0, 3.0, 4.0]}) is None

    def test_shrinkage_pulls_extremes_toward_the_prior(self):
        """The core behaviour: an extreme lagged average must not pass through."""
        model = ShrinkageModel()
        train = [
            _row(2024, w, player=f"p{i}", receiving_yards_actual=float(40 + (i % 5) * 10))
            for i in range(30) for w in range(1, 8)
        ]
        model.fit(train)

        extreme = _row(2025, 1, player="star", receiving_yards_l4=300.0)
        projected = model.predict([extreme])[0].components["receiving_yards"]
        assert projected < 300.0, "extreme projection was not shrunk"
        assert projected > 60.0, "shrunk all the way to the prior"

    def test_no_history_falls_back_to_the_prior(self):
        model = ShrinkageModel()
        train = [
            _row(2024, w, player=f"p{i}", receiving_yards_actual=50.0)
            for i in range(30) for w in range(1, 8)
        ]
        model.fit(train)

        rookie = _row(2025, 1, player="rookie", fp_half_ppr_l4=None, games_in_window_l4=None)
        prediction = model.predict([rookie])[0]
        assert prediction.explain["source"] == "positional_prior"
        assert prediction.components["receiving_yards"] == pytest.approx(50.0, abs=1e-6)

    def test_more_evidence_means_less_shrinkage(self):
        """n enters where first principles put it: weight = n / (n + k)."""
        model = ShrinkageModel()
        train = [
            _row(2024, w, player=f"p{i}", receiving_yards_actual=float(30 + i))
            for i in range(30) for w in range(1, 8)
        ]
        model.fit(train)

        thin = model.predict([_row(2025, 1, receiving_yards_l4=200.0, games_in_window_l4=1)])[0]
        thick = model.predict([_row(2025, 1, receiving_yards_l4=200.0, games_in_window_l4=4)])[0]
        assert thick.components["receiving_yards"] > thin.components["receiving_yards"]

    def test_extra_prior_games_is_configurable_and_monotonic(self):
        train = [
            _row(2024, w, player=f"p{i}", receiving_yards_actual=float(30 + i))
            for i in range(30) for w in range(1, 8)
        ]
        gentle, firm = ShrinkageModel(), ShrinkageModel(extra_prior_games=20.0)
        gentle.fit(train)
        firm.fit(train)
        row = _row(2025, 1, receiving_yards_l4=200.0)
        assert (
            firm.predict([row])[0].components["receiving_yards"]
            < gentle.predict([row])[0].components["receiving_yards"]
        )

    def test_params_are_reproducible_and_serialisable(self):
        import json

        train = [
            _row(2024, w, player=f"p{i}", receiving_yards_actual=float(30 + i))
            for i in range(30) for w in range(1, 8)
        ]
        first, second = ShrinkageModel(), ShrinkageModel()
        first.fit(train)
        second.fit(train)
        assert first.params() == second.params()
        json.dumps(first.params())

    def test_shrinkage_is_deterministic(self):
        train = [
            _row(2024, w, player=f"p{i}", receiving_yards_actual=float(30 + i))
            for i in range(30) for w in range(1, 8)
        ]
        rows = [_row(2025, 1, player=f"q{i}") for i in range(10)]
        a, b = ShrinkageModel(), ShrinkageModel()
        a.fit(train)
        b.fit(train)
        assert [p.components for p in a.predict(rows)] == [p.components for p in b.predict(rows)]


# ---------------------------------------------------------------------------
# Objective 4: distributions
# ---------------------------------------------------------------------------

class TestDistributions:
    def _fitted(self, spread: int = 40) -> ResidualDistribution:
        samples = []
        for base in (3.0, 8.0, 14.0, 22.0):
            for offset in range(-8, 12):
                samples.extend([("WR", base, base + offset)] * spread)
        return ResidualDistribution(min_bin_samples=100).fit(samples)

    def test_percentiles_are_ordered(self):
        band = self._fitted().apply("WR", 12.0)
        assert band.p10 <= band.p25 <= band.p50 <= band.p75 <= band.p90

    def test_probabilities_are_bounded(self):
        band = self._fitted().apply("WR", 12.0)
        for value in (band.boom_probability, band.bust_probability, band.confidence):
            assert 0.0 <= value <= 1.0

    def test_standard_deviation_is_non_negative(self):
        assert self._fitted().apply("WR", 12.0).standard_deviation >= 0.0

    def test_floor_is_clamped_at_zero(self):
        assert self._fitted().apply("WR", 1.0).p10 >= 0.0

    def test_expected_points_differs_from_the_raw_projection(self):
        """The bias correction. Raw output is conditionally biased; the
        distribution mean is not."""
        band = self._fitted().apply("WR", 8.0)
        assert band.expected_points != band.predicted_points

    def test_bins_are_equal_count_not_equal_width(self):
        """Resolution follows data density, so sparse high projections do not
        get a spuriously precise interval."""
        distribution = self._fitted()
        counts = [b["n"] for b in distribution.describe()["WR"]]
        assert len(counts) > 1
        assert max(counts) - min(counts) <= max(counts) * 0.5

    def test_high_and_low_projections_use_different_residuals(self):
        """The phase-3a failure: one bucket above 18 pooled 18.5 with 35."""
        distribution = self._fitted()
        low = distribution.apply("WR", 3.0)
        high = distribution.apply("WR", 22.0)
        assert low.p90 < high.p90
        assert low.p10 < high.p10

    def test_extrapolation_is_flagged(self):
        """The honest statement about a 60-point projection is 'never seen'."""
        assert self._fitted().apply("WR", 60.0).extrapolated is True
        assert self._fitted().apply("WR", 8.0).extrapolated is False

    def test_sample_size_is_reported(self):
        assert self._fitted().apply("WR", 12.0).sample_size > 0

    def test_unfitted_position_raises(self):
        with pytest.raises(ValueError, match="no fitted residuals"):
            self._fitted().apply("QB", 10.0)

    def test_out_of_order_percentiles_are_rejected(self):
        with pytest.raises(ValueError, match="out of order"):
            PointDistribution(
                predicted_points=10, expected_points=10,
                p10=9, p25=8, p50=7, p75=6, p90=5,
                standard_deviation=1, confidence=0.5,
                boom_probability=0.1, bust_probability=0.1,
            )

    def test_out_of_range_probabilities_are_rejected(self):
        with pytest.raises(ValueError, match=r"must be in \[0, 1\]"):
            PointDistribution(
                predicted_points=10, expected_points=10,
                p10=1, p25=2, p50=3, p75=4, p90=5,
                standard_deviation=1, confidence=0.5,
                boom_probability=1.7, bust_probability=0.1,
            )

    def test_sample_quantiles_feed_a_simulator(self):
        """The simulation engine draws from these rather than assuming a shape."""
        values = self._fitted().sample_quantiles("WR", 12.0)
        assert len(values) > 10
        assert values == sorted(values)
        assert all(v >= 0 for v in values)


class TestProbabilisticScores:
    def test_crps_rewards_a_sharp_correct_forecast(self):
        sharp = [10.0] * 100
        vague = [float(v) for v in range(0, 100)]
        assert crps(sharp, 10.0) < crps(vague, 10.0)

    def test_crps_punishes_a_sharp_wrong_forecast(self):
        sharp_wrong = [30.0] * 100
        vague = sorted(float(v) for v in range(0, 60))
        assert crps(sharp_wrong, 5.0) > crps(vague, 5.0)

    def test_crps_reduces_to_absolute_error_for_a_point_forecast(self):
        assert crps([7.0], 10.0) == pytest.approx(3.0)

    def test_pinball_loss_is_asymmetric(self):
        """A P90 that is too low must cost more than one that is too high."""
        too_low = pinball_loss(10.0, 20.0, 0.90)
        too_high = pinball_loss(30.0, 20.0, 0.90)
        assert too_low > too_high

    def test_pinball_is_symmetric_at_the_median(self):
        assert pinball_loss(8.0, 10.0, 0.5) == pytest.approx(pinball_loss(12.0, 10.0, 0.5))


# ---------------------------------------------------------------------------
# Objective 1: calibration
# ---------------------------------------------------------------------------

class TestCalibration:
    def test_max_error_catches_what_ece_hides(self):
        """The reason both are reported, and neither may replace the other."""
        probabilities = [0.1] * 970 + [0.95] * 100
        outcomes = [False] * 873 + [True] * 97 + [False] * 100
        report = calibration_report(probabilities, outcomes)
        assert expected_calibration_error(report) < 0.10
        assert max_calibration_error(report) > 0.90

    def test_weighted_error_sits_between_the_two(self):
        probabilities = [0.1] * 970 + [0.95] * 100
        outcomes = [False] * 873 + [True] * 97 + [False] * 100
        report = calibration_report(probabilities, outcomes)
        weighted = weighted_calibration_error(report)
        assert expected_calibration_error(report) < weighted < max_calibration_error(report)

    def test_small_bins_are_excluded_from_max_error(self):
        """Three coin flips is not evidence of miscalibration."""
        report = calibration_report([0.5] * 3 + [0.1] * 500, [True] * 3 + [False] * 500)
        assert max_calibration_error(report, min_count=30) < 0.2

    def test_coverage_reports_width_alongside_rate(self):
        """Coverage alone is gameable: 0-to-100 covers everything and says nothing."""
        result = interval_coverage([(0.0, 100.0)] * 10, [5.0] * 10, 0.80, "vacuous")
        assert result.observed == 1.0
        assert result.mean_width == 100.0

    def test_coverage_verdicts(self):
        narrow = interval_coverage([(9.0, 11.0)] * 100, [float(i) for i in range(100)], 0.80, "n")
        assert narrow.verdict == "too narrow"
        wide = interval_coverage([(-100.0, 100.0)] * 100, [5.0] * 100, 0.80, "w")
        assert wide.verdict == "too wide"

    def test_projection_ranges_include_the_high_end_and_flag_small_samples(self):
        predicted = [2.0] * 500 + [32.0] * 5
        actual = [2.0] * 500 + [18.0] * 5
        p10 = [0.0] * 505
        p90 = [10.0] * 500 + [40.0] * 5
        ranges = by_projection_range(predicted, actual, p10, p90)
        labels = [r.label for r in ranges]
        assert "30+" in labels
        top = next(r for r in ranges if r.label == "30+")
        assert top.reliable is False       # 5 observations
        assert top.bias == pytest.approx(14.0)

    def test_calibration_requires_matching_lengths(self):
        with pytest.raises(ValueError, match="same length"):
            calibration_report([0.5], [True, False])


# ---------------------------------------------------------------------------
# Objectives 2 and 6: held-out fitting and persistence
# ---------------------------------------------------------------------------

@requires_db
@pytest.mark.integration
class TestHeldOutBacktest:
    def _rows(self, pg_engine, seasons):
        from sqlalchemy.orm import Session

        from nflfp.predict.dataset import load_rows

        with Session(pg_engine) as session:
            return load_rows(session, seasons=seasons, completed_only=True)

    def test_distributions_are_fitted_only_on_earlier_weeks(self, pg_engine):
        """The 3b correctness property.

        Phase 3a fitted residuals on the same predictions it scored, which
        understates interval width. Here the burn-in proves the ordering: the
        earliest weeks get no distribution because no earlier residuals exist.
        """
        from nflfp.predict.backtest import run_backtest
        from nflfp.predict.registry import get_model_factory

        rows = self._rows(pg_engine, [2022, 2023])
        result = run_backtest(
            get_model_factory("shrinkage_eb"), rows,
            test_seasons=[2023], min_residuals=2000,
        )
        scored = result.scored
        unscored = [p for p in result.predictions if p.distribution is None]

        assert unscored, "expected a burn-in with no held-out residuals"
        assert scored, "expected later weeks to receive distributions"
        # Every unscored prediction must precede every scored one.
        assert max((p.season, p.week) for p in unscored) <= min(
            (p.season, p.week) for p in scored
        )

    def test_held_out_coverage_is_close_to_nominal(self, pg_engine):
        from nflfp.predict.backtest import run_backtest
        from nflfp.predict.registry import get_model_factory

        rows = self._rows(pg_engine, [2021, 2022, 2023])
        result = run_backtest(
            get_model_factory("shrinkage_eb"), rows, test_seasons=[2022, 2023]
        )
        p10_p90 = next(c for c in result.coverage if c.label == "P10-P90")
        assert 0.74 <= p10_p90.observed <= 0.86, p10_p90

    def test_backtest_is_reproducible(self, pg_engine):
        from nflfp.predict.backtest import run_backtest
        from nflfp.predict.registry import get_model_factory

        rows = self._rows(pg_engine, [2022, 2023])
        first = run_backtest(get_model_factory("shrinkage_eb"), rows, test_seasons=[2023])
        second = run_backtest(get_model_factory("shrinkage_eb"), rows, test_seasons=[2023])

        # Wall-clock duration is recorded for operational reporting and is not
        # part of the result; everything that describes the *output* must match.
        left, right = first.as_metrics(), second.as_metrics()
        left.pop("duration_seconds")
        right.pop("duration_seconds")
        assert left == right


@requires_db
@pytest.mark.integration
class TestPersistence:
    def _distribution(self, **kw) -> PointDistribution:
        defaults = dict(
            predicted_points=12.0, expected_points=12.5,
            p10=4.0, p25=8.0, p50=12.0, p75=17.0, p90=23.0,
            standard_deviation=6.5, confidence=0.6,
            boom_probability=0.2, bust_probability=0.15,
            sample_size=1200,
        )
        defaults.update(kw)
        return PointDistribution(**defaults)

    def _bundle(self, player: str = "p1", week: int = 5):
        from nflfp.predict.base import ComponentPrediction
        from nflfp.predict.persist import ProjectionBundle

        return ProjectionBundle(
            prediction=ComponentPrediction(
                player_id=player, season=2026, week=week, position="WR",
                components={"receiving_yards": 70.0, "receptions": 5.0},
                explain={"source": "history"},
            ),
            distributions={"half_ppr": self._distribution()},
            context={"team": "BUF", "opponent": "NYJ"},
        )

    def test_round_trip_preserves_the_distribution(self, db_session):
        from nflfp.predict.persist import (
            CALIBRATION_METHOD, create_model_run, persist_projections,
        )
        from nflfp.db.models.projection import ProjectionPoints

        run = create_model_run(
            db_session, model_name="t_model", model_version="1.0.0",
            algorithm="baseline", season=2026, week=5, params={"k": 2.0},
        )
        persist_projections(db_session, run, [self._bundle()])
        db_session.commit()

        stored = db_session.query(ProjectionPoints).one()
        assert stored.expected_points == pytest.approx(12.5)
        assert [stored.floor_points, stored.p25_points, stored.median_points,
                stored.p75_points, stored.ceiling_points] == [4.0, 8.0, 12.0, 17.0, 23.0]
        assert stored.standard_deviation == pytest.approx(6.5)
        assert stored.calibration_method == CALIBRATION_METHOD
        assert stored.distribution_samples == 1200

    def test_lineage_is_recorded(self, db_session):
        from nflfp.predict.features import FEATURE_VERSION
        from nflfp.predict.persist import create_model_run

        run = create_model_run(
            db_session, model_name="t_lineage", model_version="2.1.0",
            algorithm="baseline", season=2026, week=5,
            params={"k": 2.0}, snapshot={"last_pipeline_run": 42},
        )
        db_session.commit()
        assert run.feature_schema_version == FEATURE_VERSION
        assert run.params["data_snapshot"]["last_pipeline_run"] == 42
        assert run.started_at is not None

    def test_out_of_order_percentiles_are_rejected_by_the_database(self, db_session):
        """The ORM guards it, so bypass the ORM to prove the constraint exists."""
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        from nflfp.predict.persist import create_model_run, persist_projections

        run = create_model_run(
            db_session, model_name="t_order", model_version="1.0.0",
            algorithm="baseline", season=2026, week=5,
        )
        persist_projections(db_session, run, [self._bundle()])
        db_session.commit()

        with pytest.raises(IntegrityError):
            db_session.execute(text("UPDATE projection_points SET p25_points = 99"))
            db_session.commit()
        db_session.rollback()

    def test_a_new_model_does_not_change_historical_predictions(self, db_session):
        """The immutability requirement: deploying v2 must not rewrite v1."""
        from nflfp.db.models.projection import ProjectionPoints
        from nflfp.predict.persist import (
            create_model_run, persist_projections, publish_run,
        )

        old = create_model_run(
            db_session, model_name="t_hist", model_version="1.0.0",
            algorithm="baseline", season=2026, week=5,
        )
        persist_projections(db_session, old, [self._bundle()])
        publish_run(db_session, old)
        db_session.commit()

        original = [
            (p.expected_points, p.p25_points)
            for p in db_session.query(ProjectionPoints).all()
        ]

        new = create_model_run(
            db_session, model_name="t_hist", model_version="2.0.0",
            algorithm="baseline", season=2026, week=5,
        )
        persist_projections(
            db_session, new,
            [ProjectionBundleFactory(self._bundle(), expected=99.0)],
        )
        publish_run(db_session, new)
        db_session.commit()

        # The old rows are still there and unchanged.
        db_session.expire_all()
        old_rows = (
            db_session.query(ProjectionPoints)
            .join(ProjectionPoints.projection)
            .filter_by(model_run_id=old.id)
            .all()
        )
        assert [(p.expected_points, p.p25_points) for p in old_rows] == original
        assert old.status == "superseded"
        assert new.status == "published"

    def test_only_one_published_run_per_week(self, db_session):
        from sqlalchemy.exc import IntegrityError

        from nflfp.db.enums import ModelRunStatus
        from nflfp.predict.persist import create_model_run

        first = create_model_run(
            db_session, model_name="t_pub", model_version="1.0.0",
            algorithm="baseline", season=2026, week=5,
        )
        first.status = ModelRunStatus.PUBLISHED.value
        db_session.commit()

        second = create_model_run(
            db_session, model_name="t_pub", model_version="2.0.0",
            algorithm="baseline", season=2026, week=5,
        )
        second.status = ModelRunStatus.PUBLISHED.value
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_simulation_interface_returns_a_full_distribution(self, db_session):
        """What the Monte Carlo engine will call. It must never have to
        reconstruct a shape from expected +/- a percentage."""
        from nflfp.predict.persist import (
            create_model_run, load_distribution, persist_projections, publish_run,
        )

        run = create_model_run(
            db_session, model_name="t_sim", model_version="1.0.0",
            algorithm="baseline", season=2026, week=5,
        )
        persist_projections(db_session, run, [self._bundle(player="sim1")])
        publish_run(db_session, run)
        db_session.commit()

        found = load_distribution(
            db_session, player_id="sim1", season=2026, week=5,
            scoring_profile="half_ppr",
        )
        assert found is not None
        assert found.floor_points <= found.p25_points <= found.median_points
        assert found.median_points <= found.p75_points <= found.ceiling_points
        assert found.standard_deviation > 0
        assert 0 <= found.boom_probability <= 1

    def test_unpublished_runs_are_invisible_to_the_simulator(self, db_session):
        from nflfp.predict.persist import (
            create_model_run, load_distribution, persist_projections,
        )

        run = create_model_run(
            db_session, model_name="t_draft", model_version="1.0.0",
            algorithm="baseline", season=2026, week=5,
        )
        persist_projections(db_session, run, [self._bundle(player="draft1")])
        db_session.commit()

        assert load_distribution(
            db_session, player_id="draft1", season=2026, week=5,
            scoring_profile="half_ppr",
        ) is None


def ProjectionBundleFactory(bundle, *, expected: float):
    """A copy of `bundle` with a different expected value, for the immutability test."""
    from dataclasses import replace

    band = bundle.distributions["half_ppr"]
    return replace(
        bundle,
        distributions={"half_ppr": replace(band, expected_points=expected)},
    )
