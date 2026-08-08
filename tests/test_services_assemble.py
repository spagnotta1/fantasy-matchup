"""Row-to-domain mapping, ranking and tiering — all without a database.

The point of :mod:`nflfp.services.assemble` being pure is that these behaviours
get unit tests instead of integration tests. A tier boundary in the wrong place
renders perfectly and changes what people start.
"""

from __future__ import annotations

import pytest

from nflfp.predict.base import POSITIONS
from nflfp.services import assemble
from nflfp.services.dto import PlayerProjection, PlayerRef, PointDistribution


def projection(
    player_id: str,
    *,
    expected: float,
    position: str = "WR",
    spread: float = 6.0,
    team: str = "KC",
    game_id: str | None = "2025_10_KC_BUF",
) -> PlayerProjection:
    """A projection with a plausible right-skewed distribution around `expected`."""
    return PlayerProjection(
        player=PlayerRef(player_id=player_id, name=player_id, position=position, team=team),
        season=2025,
        week=10,
        team=team,
        opponent="BUF",
        is_home=True,
        game_id=game_id,
        points=PointDistribution(
            scoring_profile="half_ppr",
            expected=expected,
            predicted=expected,
            floor=max(0.0, expected - spread),
            p25=max(0.0, expected - spread / 2),
            median=expected - 0.5,
            p75=expected + spread / 2,
            ceiling=expected + spread * 1.6,
        ),
    )


class TestSupportedPositions:
    def test_matches_the_prediction_engine(self):
        # The business layer declares its own tuple rather than importing the
        # engine's, so this is the test that stops the two drifting apart.
        assert assemble.SUPPORTED_POSITIONS == POSITIONS


class TestPlayerRef:
    def test_falls_back_to_the_id_when_the_dimension_row_is_missing(self):
        # A mid-week signing has a projection before the player dimension
        # catches up. A hole in a list is harder to notice than an ugly label.
        ref = assemble.player_ref({"player_id": "00-0099999"})
        assert ref.name == "00-0099999"

    def test_prefers_the_dimension_name(self):
        ref = assemble.player_ref(
            {"player_id": "00-0034796", "player_name": "Lamar Jackson", "position": "QB"}
        )
        assert ref.name == "Lamar Jackson" and ref.position == "QB"


class TestPointDistribution:
    def test_derives_the_labels_from_the_stored_numbers(self):
        distribution = assemble.point_distribution(
            {
                "scoring_profile": "half_ppr",
                "predicted_points": 12.0,
                "expected_points": 11.4,
                "floor_points": 3.0,
                "p25_points": 6.0,
                "median_points": 10.5,
                "p75_points": 15.0,
                "ceiling_points": 24.0,
                "confidence": 0.82,
                "extrapolated": False,
            }
        )
        assert distribution.confidence_label == "high"
        assert distribution.shape == "steady"
        assert distribution.headline == 11.4

    def test_the_headline_is_the_calibrated_mean(self):
        # predicted_points is conditionally biased by construction — shrinkage
        # trades bias for variance — so it must never be the headline when a
        # calibrated expectation exists.
        distribution = assemble.point_distribution(
            {"scoring_profile": "ppr", "predicted_points": 32.0, "expected_points": 18.0}
        )
        assert distribution.headline == 18.0

    def test_falls_back_to_predicted_for_pre_calibration_rows(self):
        distribution = assemble.point_distribution(
            {"scoring_profile": "ppr", "predicted_points": 9.0, "expected_points": None}
        )
        assert distribution.headline == 9.0

    def test_extrapolation_caps_the_confidence_label(self):
        distribution = assemble.point_distribution(
            {
                "scoring_profile": "ppr",
                "predicted_points": 30.0,
                "confidence": 0.9,
                "extrapolated": True,
            }
        )
        assert distribution.confidence_label == "moderate"


class TestPlayerProjection:
    def _row(self, **overrides) -> dict:
        row = {
            "player_id": "00-0036322",
            "player_name": "Ja'Marr Chase",
            "position": "WR",
            "season": 2025,
            "week": 10,
            "team": "CIN",
            "opponent": "BAL",
            "is_home": False,
            "game_id": "2025_10_CIN_BAL",
            "model_run_id": 7,
            "model_name": "shrinkage_eb",
            "model_version": "1.0.0",
            "algorithm": "baseline",
            "feature_schema_version": 1,
            "scoring_profile": "half_ppr",
            "predicted_points": 15.2,
            "expected_points": 14.8,
        }
        row.update(overrides)
        return row

    def test_absent_context_is_omitted_not_nulled(self):
        # "We have no market for this game" and "the spread is zero" must stay
        # distinguishable, so an empty join produces None rather than a
        # dataclass full of Nones.
        assembled = assemble.player_projection(self._row(game_id=None))
        assert assembled.game is None
        assert assembled.weather is None
        assert assembled.matchup is None
        assert assembled.injury is None

    def test_matchup_is_graded_from_the_joined_defensive_form(self):
        assembled = assemble.player_projection(
            self._row(
                opp_defense_rank_vs_position=29,
                opp_defense_games_in_window=4,
                opp_fp_allowed_vs_position_l4=22.4,
            )
        )
        assert assembled.matchup is not None
        assert assembled.matchup.grade.graded
        # Both the rank and the magnitude travel together; either alone misleads.
        assert assembled.matchup.fp_allowed_vs_position_l4 == 22.4

    def test_weather_source_of_none_is_not_weather(self):
        assembled = assemble.player_projection(self._row(weather_source="none"))
        assert assembled.weather is None

    def test_context_is_never_marked_as_applied(self):
        # Layer 3b measured market and weather against the baseline's residual
        # and excluded them. Reporting them as applied would be a lie.
        assembled = assemble.player_projection(
            self._row(
                team_spread=-3.5,
                weather_source="forecast",
                wind_mph=22.0,
                injury_report_status="Questionable",
            )
        )
        assert assembled.game is not None and not assembled.game.applied_to_projection
        assert assembled.weather is not None and not assembled.weather.applied_to_projection
        assert assembled.injury is not None and not assembled.injury.applied_to_projection

    def test_lineage_travels_with_every_projection(self):
        assembled = assemble.player_projection(self._row())
        assert assembled.model is not None
        assert assembled.model.model_name == "shrinkage_eb"
        assert assembled.model.run_id == 7


class TestRankBoard:
    def test_orders_by_the_calibrated_expectation(self):
        board = assemble.rank_board(
            [
                projection("c", expected=8.0),
                projection("a", expected=18.0),
                projection("b", expected=12.0),
            ]
        )
        assert [e.projection.player.player_id for e in board] == ["a", "b", "c"]
        assert [e.rank for e in board] == [1, 2, 3]

    def test_positional_rank_is_within_position(self):
        board = assemble.rank_board(
            [
                projection("wr1", expected=18.0, position="WR"),
                projection("rb1", expected=16.0, position="RB"),
                projection("wr2", expected=14.0, position="WR"),
            ]
        )
        by_id = {e.projection.player.player_id: e for e in board}
        assert by_id["wr1"].positional_rank == 1
        assert by_id["rb1"].positional_rank == 1
        assert by_id["wr2"].positional_rank == 2

    def test_ordering_is_total_and_therefore_stable(self):
        # Two identical projections must not swap places between requests.
        rows = [projection("b", expected=10.0), projection("a", expected=10.0)]
        first = [e.projection.player.player_id for e in assemble.rank_board(rows)]
        second = [e.projection.player.player_id for e in assemble.rank_board(rows[::-1])]
        assert first == second == ["a", "b"]

    def test_an_empty_board_is_empty(self):
        assert assemble.rank_board([]) == []


class TestTiering:
    def test_adjacent_players_share_a_tier(self):
        # A 0.4-point gap between two similarly-shaped distributions is noise;
        # a tier boundary there would be false precision.
        tiers = assemble.assign_tiers(
            [projection("a", expected=14.0), projection("b", expected=13.6)]
        )
        assert tiers == [1, 1]

    def test_a_large_separation_breaks_the_tier(self):
        tiers = assemble.assign_tiers(
            [projection("a", expected=22.0, spread=3.0), projection("b", expected=4.0, spread=3.0)]
        )
        assert tiers == [1, 2]

    def test_tiers_are_non_decreasing_down_the_board(self):
        board = [projection(f"p{i}", expected=24.0 - i * 1.4) for i in range(16)]
        tiers = assemble.assign_tiers(board)
        assert tiers == sorted(tiers)
        assert tiers[0] == 1

    def test_wide_distributions_produce_fewer_tiers_than_narrow_ones(self):
        # The whole reason tiers are built from distributions rather than a
        # fixed points gap: the same spacing means different things at
        # different levels of uncertainty.
        spacing = [24.0 - i * 2.0 for i in range(8)]
        narrow = assemble.assign_tiers(
            [projection(f"n{i}", expected=v, spread=1.0) for i, v in enumerate(spacing)]
        )
        wide = assemble.assign_tiers(
            [projection(f"w{i}", expected=v, spread=14.0) for i, v in enumerate(spacing)]
        )
        assert max(wide) < max(narrow)

    def test_a_missing_distribution_falls_back_to_a_points_gap(self):
        thin = PlayerProjection(
            player=PlayerRef(player_id="thin", name="thin", position="WR"),
            season=2025,
            week=10,
            team="KC",
            opponent="BUF",
            is_home=True,
            game_id=None,
            points=PointDistribution(
                scoring_profile="half_ppr", expected=3.0, predicted=3.0
            ),
        )
        tiers = assemble.assign_tiers([projection("a", expected=20.0), thin])
        assert tiers == [1, 2]

    def test_no_projections_no_tiers(self):
        assert assemble.assign_tiers([]) == []


class TestHistorySummary:
    def _week(self, actual, projected=None, week=1):
        return assemble.historical_week(
            {
                "season": 2024,
                "week": week,
                "team": "KC",
                "opponent": "DEN",
                "is_home": True,
                "actual_points": actual,
                "projected_points": projected,
            },
            points_column="actual_points",
        )

    def test_error_is_projection_minus_actual(self):
        week = self._week(10.0, projected=13.0)
        assert week.error == pytest.approx(3.0)

    def test_accuracy_covers_only_graded_weeks(self):
        # Averaging error over weeks that never had a projection would report a
        # better model than exists.
        weeks = [self._week(10.0, 13.0, 1), self._week(8.0, None, 2), self._week(20.0, 18.0, 3)]
        summary = assemble.summarise_history(weeks)
        assert summary.games == 3
        assert summary.graded_games == 2
        assert summary.mean_absolute_error == pytest.approx(2.5)
        assert summary.bias == pytest.approx(0.5)

    def test_boom_and_bust_rates(self):
        weeks = [self._week(v, week=i) for i, v in enumerate([2.0, 4.0, 12.0, 25.0])]
        summary = assemble.summarise_history(weeks)
        assert summary.bust_rate == pytest.approx(0.5)
        assert summary.boom_rate == pytest.approx(0.25)

    def test_an_empty_history_is_not_a_crash(self):
        summary = assemble.summarise_history([])
        assert summary.games == 0
        assert summary.mean_points is None
        assert summary.graded_games == 0
