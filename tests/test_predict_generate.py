"""The production projection path.

``generate_week`` is the function the Tuesday job runs and the function a
manual rerun runs. The tests below are the pieces of it that can be checked
without a warehouse, and they are the pieces where a mistake is invisible: a
leaked training row backtests beautifully, and a projection stored without a
distribution renders as a confident number.

The end-to-end run is exercised by the integration suite, which needs the
feature views.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from nflfp.predict.generate import GenerationResult, _assert_trained_before, _bundle


# ---------------------------------------------------------------------------
# the leakage rule, enforced on the production path
# ---------------------------------------------------------------------------


def _rows(*pairs) -> list[dict]:
    return [{"season": season, "week": week} for season, week in pairs]


class TestNoLeakage:
    def test_training_strictly_before_the_target_week_is_accepted(self):
        _assert_trained_before(_rows((2024, 17), (2025, 1), (2025, 11)), (2025, 12))

    def test_the_target_week_itself_is_rejected(self):
        """A model trained on the week it is projecting backtests fine and is
        worthless on Thursday, because on Thursday that week has not happened."""
        with pytest.raises(ValueError, match="at or after"):
            _assert_trained_before(_rows((2025, 11), (2025, 12)), (2025, 12))

    def test_a_later_week_is_rejected(self):
        with pytest.raises(ValueError, match="at or after"):
            _assert_trained_before(_rows((2025, 14)), (2025, 12))

    def test_a_later_season_is_rejected(self):
        """Week 1 of next season sorts before week 12 numerically; the
        comparison must be on the (season, week) tuple."""
        with pytest.raises(ValueError, match="at or after"):
            _assert_trained_before(_rows((2026, 1)), (2025, 12))

    def test_the_error_says_how_many_rows_leaked(self):
        with pytest.raises(ValueError, match="2 training row"):
            _assert_trained_before(_rows((2025, 12), (2025, 13)), (2025, 12))


# ---------------------------------------------------------------------------
# bundling: a projection without a distribution is not stored
# ---------------------------------------------------------------------------


@dataclass
class _Prediction:
    player_id: str
    position: str
    season: int = 2025
    week: int = 12
    components: dict = None
    explain: dict = None

    def __post_init__(self):
        self.components = self.components or {"receiving_yards": 50.0}
        self.explain = self.explain or {}


class _Model:
    def __init__(self, predictions):
        self._predictions = predictions

    def predict(self, rows):
        return self._predictions


class _Distribution:
    """Produces a band for some positions and refuses for others."""

    def __init__(self, refuse: set[str]):
        self._refuse = refuse

    def apply(self, position, points):
        if position in self._refuse:
            raise ValueError("no residual history for this position and volume")
        return object()


def _target(player_id: str) -> dict:
    return {
        "game_id": "2025_12_KC_BUF",
        "team": "KC",
        "opponent": "BUF",
        "is_home": False,
        "player_id": player_id,
    }


class TestBundling:
    def test_a_player_with_no_distribution_is_dropped_and_counted(self, monkeypatch):
        """Layer 3b's claim is that the interval is the product. A row with a
        point estimate and no honest spread is indistinguishable in the API
        from one that has been measured."""
        monkeypatch.setattr(
            "nflfp.predict.generate.score_components",
            lambda components, position: {"half_ppr": 10.0, "ppr": 11.0},
        )
        model = _Model([_Prediction("a", "WR"), _Prediction("b", "K")])

        bundles, unprojected = _bundle(
            model, [_target("a"), _target("b")], _Distribution(refuse={"K"})
        )

        assert [b.prediction.player_id for b in bundles] == ["a"]
        assert unprojected == {"no_distribution_K": 1}

    def test_game_context_travels_with_the_projection(self, monkeypatch):
        monkeypatch.setattr(
            "nflfp.predict.generate.score_components",
            lambda components, position: {"half_ppr": 10.0},
        )
        bundles, _ = _bundle(
            _Model([_Prediction("a", "WR")]), [_target("a")], _Distribution(refuse=set())
        )
        assert bundles[0].context == {
            "game_id": "2025_12_KC_BUF",
            "team": "KC",
            "opponent": "BUF",
            "is_home": False,
        }

    def test_every_scoring_profile_gets_its_own_band(self, monkeypatch):
        monkeypatch.setattr(
            "nflfp.predict.generate.score_components",
            lambda components, position: {"standard": 9.0, "half_ppr": 10.0, "ppr": 11.0},
        )
        bundles, _ = _bundle(
            _Model([_Prediction("a", "WR")]), [_target("a")], _Distribution(refuse=set())
        )
        assert set(bundles[0].distributions) == {"standard", "half_ppr", "ppr"}


# ---------------------------------------------------------------------------
# the result a job log stores
# ---------------------------------------------------------------------------


class TestGenerationResult:
    def test_the_detail_is_json_serialisable(self):
        import json

        result = GenerationResult(
            model_run_id=3,
            model_name="shrinkage_eb",
            model_version="1.0",
            season=2025,
            week=12,
            projections_written=412,
            published=True,
            cache_epoch=9,
        )
        assert json.loads(json.dumps(result.as_detail()))["projections_written"] == 412

    def test_empty_fields_are_omitted_rather_than_stored_as_null(self):
        result = GenerationResult(
            model_run_id=None, model_name="m", model_version="1", season=2025, week=1
        )
        detail = result.as_detail()
        assert "model_run_id" not in detail
        assert "unprojected" not in detail
        assert detail["season"] == 2025
