"""Tests for the prediction engine (phase 3a).

Two things carry most of the weight here:

* **Leakage.** ``walk_forward`` must never put a row in a training fold that is
  not strictly earlier than the test week. Every backtest number depends on it,
  and getting it wrong produces excellent-looking results that mean nothing.
* **The component path.** Because half-PPR scoring is linear in the components,
  averaging components and then scoring must give exactly the same answer as
  averaging the scores. That equivalence is an end-to-end check on the feature
  columns, the scoring bridge and the Python scorer at once.
"""

from __future__ import annotations

import pytest

from nflfp.predict.backtest import (
    Prediction,
    _metrics,
    _pearson,
    _ranks,
    _spearman,
    run_backtest,
)
from nflfp.predict.base import ComponentPrediction, empty_components
from nflfp.predict.dataset import (
    Split,
    assert_no_leakage,
    load_rows,
    split_by_position,
    walk_forward,
)
from nflfp.predict.calibration import (
    calibration_report,
    expected_calibration_error,
    max_calibration_error,
)
from nflfp.predict.distribution import PointDistribution, ResidualDistribution, quantile
from nflfp.predict.models.baseline_l4 import BaselineL4
from nflfp.predict.registry import UnknownModelError, available, get_model_factory
from nflfp.predict.scoring_bridge import (
    COMPONENT_TO_COLUMN,
    actual_components,
    score_components,
    validate_mapping,
)
from nflfp.scoring import COMPONENT_FIELDS

from .conftest import requires_db


def _row(season: int, week: int, player: str = "p1", position: str = "WR", **kw) -> dict:
    row = {
        "player_id": player,
        "season": season,
        "week": week,
        "position": position,
        "fp_half_ppr_actual": 10.0,
        "fp_half_ppr_l4": 9.0,
    }
    for component, column in COMPONENT_TO_COLUMN.items():
        row.setdefault(f"{column}_l4", 0.0)
        row.setdefault(f"{column}_actual", 0.0)
    row.update(kw)
    return row


# ---------------------------------------------------------------------------
# scoring bridge
# ---------------------------------------------------------------------------

class TestScoringBridge:
    def test_mapping_covers_every_scoring_component(self):
        """A component neither mapped nor declared unmapped is one the model
        predicts and the scorer silently ignores."""
        validate_mapping()

    def test_mapping_includes_the_irregular_name(self):
        """fumbles_lost_total -> fumbles_lost is the one that breaks a naive
        string rule, and it cost 1,018 wrongly-scored player-weeks to find."""
        assert COMPONENT_TO_COLUMN["fumbles_lost_total"] == "fumbles_lost"

    def test_score_components_covers_playable_profiles_only(self):
        scores = score_components({"receptions": 4, "receiving_yards": 40})
        assert set(scores) == {"standard", "half_ppr", "ppr", "ppr_te_premium"}
        assert "nflverse_parity" not in scores

    def test_actual_components_reads_the_actual_suffix(self):
        row = _row(2024, 5, receiving_yards_actual=88.0, receptions_actual=6.0)
        components = actual_components(row)
        assert components["receiving_yards"] == 88.0
        assert components["receptions"] == 6.0


# ---------------------------------------------------------------------------
# walk-forward splitting
# ---------------------------------------------------------------------------

class TestWalkForward:
    def _rows(self) -> list[dict]:
        return [
            _row(season, week, player=f"p{i}")
            for season in (2023, 2024)
            for week in range(1, 19)
            for i in range(40)
        ]

    def test_training_data_strictly_precedes_the_test_week(self):
        for split in walk_forward(self._rows(), test_seasons=[2024]):
            assert_no_leakage(split)
            cutoff = (split.season, split.week)
            assert all((r["season"], r["week"]) < cutoff for r in split.train)
            assert all((r["season"], r["week"]) == cutoff for r in split.test)

    def test_earlier_seasons_are_available_for_training(self):
        """A real deployment has last year's data, so the harness must too."""
        splits = list(walk_forward(self._rows(), test_seasons=[2024]))
        assert any(r["season"] == 2023 for r in splits[0].train)

    def test_splits_are_chronological(self):
        splits = list(walk_forward(self._rows(), test_seasons=[2024]))
        keys = [(s.season, s.week) for s in splits]
        assert keys == sorted(keys)

    def test_thin_training_sets_are_skipped(self):
        rows = [_row(2024, week, player=f"p{i}") for week in (1, 2) for i in range(5)]
        assert list(walk_forward(rows, test_seasons=[2024], min_train_rows=500)) == []

    def test_assert_no_leakage_rejects_a_contaminated_split(self):
        """The guard must catch leakage the loop failed to prevent."""
        bad = Split(
            season=2024, week=5,
            train=[_row(2024, 5), _row(2024, 9)],   # week 9 is in the future
            test=[_row(2024, 5)],
        )
        with pytest.raises(ValueError, match="leakage"):
            assert_no_leakage(bad)

    def test_assert_no_leakage_rejects_a_multi_week_test_fold(self):
        bad = Split(season=2024, week=5, train=[_row(2024, 1)],
                    test=[_row(2024, 5), _row(2024, 6)])
        with pytest.raises(ValueError, match="spans"):
            assert_no_leakage(bad)

    def test_split_by_position(self):
        rows = [_row(2024, 1, position="QB"), _row(2024, 1, position="WR")]
        assert set(split_by_position(rows)) == {"QB", "WR"}


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------

class TestBaselineL4:
    def test_projects_lagged_components(self):
        model = BaselineL4()
        model.fit([_row(2024, 1)])
        row = _row(2024, 5, receiving_yards_l4=70.0, receptions_l4=5.0)
        prediction = model.predict([row])[0]
        assert prediction.components["receiving_yards"] == 70.0
        assert prediction.components["receptions"] == 5.0
        assert prediction.explain["source"] == "history"

    def test_cold_start_uses_a_positional_prior(self):
        """12.9% of Week 1 rows have no history; a hole in the slate is worse
        than a low-confidence entry."""
        model = BaselineL4()
        model.fit([
            _row(2024, 1, player=f"p{i}", position="WR", receiving_yards_actual=float(v))
            for i, v in enumerate([10, 20, 30, 40, 50])
        ])
        rookie = _row(2025, 1, player="rookie", fp_half_ppr_l4=None)
        prediction = model.predict([rookie])[0]
        assert prediction.explain["source"] == "positional_prior"
        assert prediction.components["receiving_yards"] == 30.0  # median

    def test_priors_are_medians_not_means(self):
        """Weekly scoring is right-skewed; a mean prior over-projects the
        replacement-level player it describes."""
        model = BaselineL4()
        model.fit([
            _row(2024, 1, player=f"p{i}", receiving_yards_actual=float(v))
            for i, v in enumerate([0, 0, 0, 0, 100])
        ])
        assert model.params()["priors"]["WR"]["receiving_yards"] == 0.0

    def test_is_deterministic(self):
        """A projection that changes when regenerated cannot be explained."""
        rows = [_row(2024, 5, player=f"p{i}") for i in range(20)]
        first = BaselineL4()
        first.fit(rows)
        second = BaselineL4()
        second.fit(rows)
        assert [p.components for p in first.predict(rows)] == [
            p.components for p in second.predict(rows)
        ]

    def test_returns_one_prediction_per_row_in_order(self):
        rows = [_row(2024, 5, player=f"p{i}") for i in range(10)]
        model = BaselineL4()
        model.fit(rows)
        predictions = model.predict(rows)
        assert [p.player_id for p in predictions] == [r["player_id"] for r in rows]

    def test_params_are_json_serialisable(self):
        import json

        model = BaselineL4()
        model.fit([_row(2024, 1)])
        json.dumps(model.params())


# ---------------------------------------------------------------------------
# distribution
# ---------------------------------------------------------------------------

class TestDistribution:
    """Kept minimal: the substantive distribution tests live in test_predict_3b,
    against the held-out implementation this file predates."""

    def test_quantile_interpolates(self):
        values = [0.0, 10.0]
        assert quantile(values, 0.0) == 0.0
        assert quantile(values, 0.5) == 5.0
        assert quantile(values, 1.0) == 10.0

    def _fitted(self) -> ResidualDistribution:
        samples = [
            ("WR", 10.0, 10.0 + offset)
            for offset in [-8, -5, -3, -1, 0, 1, 2, 4, 7, 12] * 40
        ]
        return ResidualDistribution(min_bin_samples=100).fit(samples)

    def test_quantiles_are_ordered(self):
        band = self._fitted().apply("WR", 10.0)
        assert band.floor_points <= band.median_points <= band.ceiling_points

    def test_floor_is_clamped_at_zero(self):
        assert self._fitted().apply("WR", 1.0).floor_points >= 0.0

    def test_probabilities_are_in_range(self):
        band = self._fitted().apply("WR", 10.0)
        assert 0.0 <= band.boom_probability <= 1.0
        assert 0.0 <= band.bust_probability <= 1.0
        assert 0.0 <= band.confidence <= 1.0

    def test_unfitted_position_raises(self):
        with pytest.raises(ValueError, match="no fitted residuals"):
            self._fitted().apply("QB", 10.0)

    def test_out_of_order_quantiles_are_rejected(self):
        with pytest.raises(ValueError, match="out of order"):
            PointDistribution(
                predicted_points=10, expected_points=10,
                p10=15, p25=14, p50=10, p75=8, p90=5,
                standard_deviation=1, confidence=0.5,
                boom_probability=0.1, bust_probability=0.1,
            )

    def test_perfect_calibration_scores_zero_error(self):
        probabilities = [0.0] * 100 + [1.0] * 100
        outcomes = [False] * 100 + [True] * 100
        assert expected_calibration_error(
            calibration_report(probabilities, outcomes)
        ) == pytest.approx(0.0)

    def test_miscalibration_is_detected(self):
        """Claiming 90% when it happens 10% of the time must score badly."""
        probabilities = [0.9] * 100
        outcomes = [True] * 10 + [False] * 90
        assert expected_calibration_error(
            calibration_report(probabilities, outcomes)
        ) == pytest.approx(0.8, abs=0.01)

    def test_max_calibration_error_catches_what_ece_hides(self):
        probabilities = [0.1] * 970 + [0.95] * 100
        outcomes = [False] * 873 + [True] * 97 + [False] * 100
        report = calibration_report(probabilities, outcomes)
        assert expected_calibration_error(report) < 0.10
        assert max_calibration_error(report) > 0.90

    def test_calibration_requires_matching_lengths(self):
        with pytest.raises(ValueError, match="same length"):
            calibration_report([0.5], [True, False])


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_pearson_of_a_perfect_line(self):
        assert _pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)

    def test_ranks_share_ties(self):
        assert _ranks([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]

    def test_spearman_detects_monotonic_but_nonlinear_agreement(self):
        assert _spearman([1, 2, 3, 4], [1, 4, 9, 16]) == pytest.approx(1.0)

    def test_metrics_report_signed_bias(self):
        predictions = [
            Prediction("p", 2024, 1, "WR", predicted=12.0, actual=10.0),
            Prediction("q", 2024, 1, "WR", predicted=8.0, actual=6.0),
        ]
        metrics = _metrics("WR", predictions)
        assert metrics.mae == pytest.approx(2.0)
        assert metrics.bias == pytest.approx(2.0)  # systematically high


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_baseline_is_registered(self):
        assert "baseline_l4" in available()

    def test_factory_returns_a_fresh_instance_each_call(self):
        """The harness needs an unfitted model per fold; a shared instance
        would carry one fold's training into another's evaluation."""
        factory = get_model_factory("baseline_l4")
        assert factory() is not factory()

    def test_unknown_model_lists_what_is_available(self):
        with pytest.raises(UnknownModelError, match="registered:"):
            get_model_factory("xgboost_v9")


# ---------------------------------------------------------------------------
# base
# ---------------------------------------------------------------------------

def test_empty_components_covers_every_scoring_field():
    """A model declining to project a stat must yield 0.0, not a missing key
    that a later reader would see as None."""
    assert set(empty_components()) == set(COMPONENT_FIELDS)
    assert set(empty_components().values()) == {0.0}


def test_component_prediction_key():
    prediction = ComponentPrediction("p1", 2024, 5, "WR")
    assert prediction.key == ("p1", 2024, 5)


# ---------------------------------------------------------------------------
# integration
# ---------------------------------------------------------------------------

@requires_db
@pytest.mark.integration
class TestAgainstRealData:
    def _rows(self, pg_engine) -> list[dict]:
        from sqlalchemy.orm import Session

        with Session(pg_engine) as session:
            return load_rows(session, seasons=[2023, 2024], completed_only=True)

    def test_component_scoring_reproduces_the_points_average(self, pg_engine):
        """The equivalence that validates the whole component path.

        Half-PPR scoring is linear in the components, so scoring the lagged
        component averages must equal the lagged average of the points. If the
        feature columns, the bridge mapping or the Python scorer were wrong,
        this is where it would show.
        """
        rows = self._rows(pg_engine)
        model = BaselineL4()
        model.fit(rows[:1000])

        checked = mismatched = 0
        for row in rows:
            if row.get("fp_half_ppr_l4") is None:
                continue
            prediction = model.predict([row])[0]
            points = score_components(
                prediction.components, position=prediction.position
            )["half_ppr"]
            checked += 1
            if abs(points - float(row["fp_half_ppr_l4"])) > 0.005:
                mismatched += 1

        assert checked > 5000
        assert mismatched == 0, f"{mismatched}/{checked} component scores disagree"

    def test_backtest_beats_nothing_but_runs_end_to_end(self, pg_engine):
        from sqlalchemy.orm import Session

        with Session(pg_engine) as session:
            rows = load_rows(session, completed_only=True)

        result = run_backtest(
            get_model_factory("baseline_l4"), rows, test_seasons=[2024]
        )
        assert result.weeks > 15
        assert len(result.predictions) > 3000
        assert set(result.by_position) == {"QB", "RB", "WR", "TE"}
        # Sanity, not a quality bar: a model with no skill would sit near zero.
        for metrics in result.by_position.values():
            assert metrics.spearman > 0.3, metrics

    def test_backtest_is_reproducible(self, pg_engine):
        from sqlalchemy.orm import Session

        with Session(pg_engine) as session:
            rows = load_rows(session, seasons=[2022, 2023], completed_only=True)

        first = run_backtest(get_model_factory("baseline_l4"), rows, test_seasons=[2023])
        second = run_backtest(get_model_factory("baseline_l4"), rows, test_seasons=[2023])
        assert first.as_metrics()["by_position"] == second.as_metrics()["by_position"]
