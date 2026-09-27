"""Tests for the lightgbm_components challenger.

What is asserted here is the Model contract, not the model's skill. Whether the
booster is any good is a walk-forward question with its own procedure
(``scripts/challenger_eval.py``); these check that it is a legal participant:

* deterministic — the same rows fitted twice give identical projections;
* one prediction per input row, in order, including a player with no history;
* no feature outside the contract, and nothing that is not valid JSON in the
  parts that get persisted.

No database. Skipped entirely when the optional ``ml`` extra is not installed,
which is also the one configuration where the registry must not list it.
"""

from __future__ import annotations

import json
import random

import pytest

pytest.importorskip("lightgbm")

from nflfp.predict import features as feature_contract  # noqa: E402
from nflfp.predict.backtest import BacktestResult, PositionMetrics, acceptance_inputs  # noqa: E402
from nflfp.predict.foundation import meets_acceptance  # noqa: E402
from nflfp.predict.models.gbm import LightGBMComponents  # noqa: E402
from nflfp.predict.models.shrinkage import MODELLED_COMPONENTS  # noqa: E402
from nflfp.predict.registry import available  # noqa: E402
from nflfp.predict.scoring_bridge import COMPONENT_TO_COLUMN  # noqa: E402


def _rows(count: int, seed: int = 7) -> list[dict]:
    """Synthetic player-weeks with every available feature populated.

    Receiving yards follow targets so there is signal to find; the rest is
    noise. Enough rows that every component clears the fit threshold.
    """
    rng = random.Random(seed)
    rows = []
    for i in range(count):
        targets = rng.uniform(0, 10)
        row = {
            "player_id": f"p{i % 200}",
            "season": 2020 + i // 2000,
            "week": 1 + (i // 100) % 17,
            "position": ("QB", "RB", "WR", "TE")[i % 4],
        }
        for name in feature_contract.AVAILABLE_FEATURES:
            row[name] = rng.uniform(0, 1)
        row["targets_l4"] = targets
        row["is_home"] = bool(i % 2)
        for component in MODELLED_COMPONENTS:
            column = COMPONENT_TO_COLUMN[component]
            row[f"{column}_actual"] = float(rng.randint(0, 3))
        row["receiving_yards_actual"] = targets * 8 + rng.gauss(0, 10)
        rows.append(row)
    return rows


@pytest.fixture(scope="module")
def fitted() -> tuple[LightGBMComponents, list[dict]]:
    rows = _rows(4000)
    model = LightGBMComponents()
    model.fit(rows)
    return model, rows


class TestContract:
    def test_it_is_registered_when_lightgbm_is_installed(self):
        assert "lightgbm_components" in available()

    def test_it_reads_only_available_features(self):
        feature_contract.assert_available(LightGBMComponents().required_features)

    def test_refitting_on_the_same_rows_is_identical(self, fitted):
        model, rows = fitted
        again = LightGBMComponents()
        again.fit(rows)
        first = [p.components for p in model.predict(rows[:200])]
        second = [p.components for p in again.predict(rows[:200])]
        assert first == second

    def test_one_prediction_per_row_in_order(self, fitted):
        model, rows = fitted
        sample = rows[10:60]
        predictions = model.predict(sample)
        assert [p.player_id for p in predictions] == [r["player_id"] for r in sample]
        assert [p.week for p in predictions] == [r["week"] for r in sample]

    def test_a_player_with_no_history_still_gets_a_projection(self, fitted):
        """A hole in the slate is invisible downstream; a thin projection is not."""
        model, rows = fitted
        rookie = {k: v for k, v in rows[0].items() if not k.endswith("_actual")}
        for name in feature_contract.USAGE_FEATURES:
            rookie[name] = None
        [prediction] = model.predict([rookie])
        assert all(value == value for value in prediction.components.values())  # no NaN
        assert prediction.explain["source"] == "no_history"
        assert prediction.explain["games_in_window"] == 0.0

    def test_counts_are_never_negative(self, fitted):
        model, rows = fitted
        for prediction in model.predict(rows[:400]):
            for component in ("passing_tds", "rushing_tds", "receptions", "receiving_tds"):
                assert prediction.components[component] >= 0.0

    def test_it_learns_the_signal_it_was_given(self, fitted):
        model, rows = fitted
        low = dict(rows[0], targets_l4=1.0)
        high = dict(rows[0], targets_l4=9.0)
        [p_low, p_high] = model.predict([low, high])
        assert p_high.components["receiving_yards"] > p_low.components["receiving_yards"] + 20

    def test_what_gets_persisted_is_valid_json(self, fitted):
        model, rows = fitted
        json.dumps(model.params(), allow_nan=False)
        rookie = dict(rows[0], games_in_window_l4=None, fp_half_ppr_l4=None)
        json.dumps(model.predict([rookie])[0].explain, allow_nan=False)

    def test_an_empty_slate_is_an_empty_list(self, fitted):
        model, _ = fitted
        assert model.predict([]) == []


class TestAcceptanceInputs:
    def test_absent_measurements_fail_rather_than_pass(self):
        """The shared reduction substitutes failing values for missing ones, so
        a backtest that produced no distributions cannot clear the bar."""
        result = BacktestResult(model_name="m", model_version="1", profile="half_ppr", weeks=0)
        passed, reasons = meets_acceptance(**acceptance_inputs(result))
        assert not passed
        assert any("coverage" in reason for reason in reasons)
        assert any("CRPS" in reason for reason in reasons)

    def test_mae_is_carried_through_per_position(self):
        result = BacktestResult(model_name="m", model_version="1", profile="half_ppr", weeks=1)
        result.by_position = {
            "QB": PositionMetrics("QB", 10, 6.0, 8.0, 0.0, 0.5, 0.5),
        }
        assert acceptance_inputs(result)["mae_by_position"] == {"QB": 6.0}
