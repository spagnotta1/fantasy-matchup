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


# ---------------------------------------------------------------------------
# the backfill
# ---------------------------------------------------------------------------


class _RowWiseModel:
    """A model whose prediction depends only on the row it is given.

    That is the property :class:`~nflfp.predict.generate.FitCache` relies on to
    hoist residual scoring out of the per-week loop, so the test double has to
    have it — and ``_fitted_on`` records the training set so a test can prove
    the cached and uncached paths fitted the same one.
    """

    name = "rowwise"
    version = "1.0.0"
    algorithm = "test"

    def __init__(self):
        self._fitted_on: list[tuple[int, int]] = []

    def params(self) -> dict:
        return {}

    def fit(self, rows):
        self._fitted_on = [(int(r["season"]), int(r["week"])) for r in rows]

    def predict(self, rows):
        return [_Prediction(str(r["player_id"]), str(r["position"]),
                            season=int(r["season"]), week=int(r["week"]),
                            components={"receiving_yards": float(r["seed"])})
                for r in rows]


def _history_rows() -> list[dict]:
    """Three seasons of completed player-weeks, deterministic and tiny."""
    rows = []
    for season in (2022, 2023, 2024):
        for week in range(1, 5):
            for index in range(3):
                rows.append(
                    {
                        "season": season,
                        "week": week,
                        "player_id": f"p{index}",
                        "position": "WR",
                        "seed": season + week + index,
                        "fp_half_ppr_actual": float(10 + index),
                    }
                )
    return rows


class TestFitCacheEquivalence:
    """The backfill's whole correctness claim.

    A backfilled board has to be the board the weekly job would have written
    for that week. The cache exists only to stop reloading and refitting
    identical inputs, so if it ever changes a number it is a bug — and one that
    would be invisible, because a wrong-but-plausible projection renders
    exactly like a right one.
    """

    def _fit(self, cache):
        from nflfp.predict.generate import _fit_distribution

        history = _history_rows()
        return [
            _fit_distribution(
                _RowWiseModel, history, cutoff=cutoff, profile="half_ppr", cache=cache
            )[1]
            for cutoff in [(2024, 1), (2024, 2), (2024, 3), (2024, 4)]
        ]

    def test_a_cached_backfill_produces_the_uncached_samples_exactly(self):
        from nflfp.predict.generate import FitCache

        assert self._fit(FitCache()) == self._fit(None)

    def test_the_residual_model_is_fitted_once_per_season_not_once_per_week(self):
        """The saving that makes a backfill minutes rather than an hour."""
        from nflfp.predict.generate import FitCache

        cache = FitCache()
        self._fit(cache)
        assert len(cache.residuals) == 1

    def test_a_week_only_sees_residuals_from_before_it(self):
        """The cached list runs to the end of the season; a week takes the
        prefix it is entitled to. Taking the whole list would leak."""
        from nflfp.predict.generate import FitCache

        samples = self._fit(FitCache())
        assert [len(s) for s in samples] == sorted(len(s) for s in samples)
        assert len(samples[0]) < len(samples[-1])


class TestBackfillResult:
    def test_skips_are_summarised_by_reason_not_listed_per_week(self):
        import json

        from nflfp.predict.generate import BackfillResult, BackfillWeek

        result = BackfillResult(model_name="m", model_version="1")
        result.weeks = [
            BackfillWeek(2018, 1, projections=300),
            BackfillWeek(2017, 1, skipped=True, skip_reason="no residual history"),
            BackfillWeek(2017, 2, skipped=True, skip_reason="no residual history"),
        ]
        detail = result.as_detail()

        assert detail["weeks_generated"] == 1
        assert detail["weeks_skipped"] == 2
        assert detail["skipped_because"] == {"no residual history": 2}
        assert detail["seasons"] == [2018]
        assert json.loads(json.dumps(detail))["projections"] == 300

    def test_a_refused_week_contributes_no_projections(self):
        """A skip is a week with no board, not a week with an empty one."""
        from nflfp.predict.generate import BackfillResult, BackfillWeek

        result = BackfillResult(model_name="m", model_version="1")
        result.weeks = [BackfillWeek(2016, 1, skipped=True, skip_reason="too early")]
        assert result.projections_written == 0
        assert result.seasons_covered == []
