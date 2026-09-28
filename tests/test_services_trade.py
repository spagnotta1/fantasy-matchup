"""Trade values: the rate carried forward, the waiver-wire zero, the bye week.

Built on hand-made rows for the same reason the draft suite is: every assertion
is arithmetic, and the arithmetic is the whole of what the trade analyzer
stands on. No player here has a history, so every availability is the same
fallback figure and each expected number can be written down exactly.
"""

from __future__ import annotations

import pytest

from nflfp.services.draft.history import FALLBACK_AVAILABILITY
from nflfp.services.draft.settings import validate_settings
from nflfp.services.trade import build_trade_values

SEASON = 2025
WEEK = 5


def board_row(player_id: str, points: float, *, team: str = "AAA", week: int = WEEK) -> dict:
    return {
        "player_id": player_id,
        "player_name": player_id,
        "position": "RB",
        "team": team,
        "week": week,
        "expected_points": points,
    }


def schedule(team: str, weeks: range) -> list[dict]:
    return [{"team": team, "week": w, "opponent": "ZZZ"} for w in weeks]


# Four teams starting one back on two-player rosters: four backs start, the
# bench doubles that to eight rostered, so the ninth-best back is the waiver wire.
SETTINGS = validate_settings(
    teams=4, rounds=2, scoring_profile="ppr", season=SEASON, roster=[{"slot": "RB", "count": 1}]
)
# AAA plays weeks 5-8; BBB is on bye in week 5 and plays 6-8.
SCHEDULE = schedule("AAA", range(5, 9)) + schedule("BBB", range(6, 9))


def values_for(board, bye_rows=()):
    return build_trade_values(
        board_rows=board,
        bye_rows=list(bye_rows),
        panel_rows=[],
        game_counts={SEASON: 17},
        schedule_rows=SCHEDULE,
        settings=SETTINGS,
        week=WEEK,
    )


class TestRestOfSeason:
    def test_is_the_rate_times_games_left_times_availability(self):
        values, _, _ = values_for([board_row("p1", 10.0)])
        (value,) = values
        assert value.games_left == 4
        assert value.availability == pytest.approx(FALLBACK_AVAILABILITY)
        assert value.rest_of_season == pytest.approx(10.0 * 4 * FALLBACK_AVAILABILITY)

    def test_counts_only_the_games_the_team_has_left(self):
        values, _, _ = values_for([board_row("p1", 10.0)], [board_row("p2", 10.0, team="BBB", week=4)])
        by_id = {v.player.player_id: v for v in values}
        assert by_id["p2"].games_left == 3
        assert by_id["p2"].rest_of_season < by_id["p1"].rest_of_season


class TestByeWeek:
    def test_a_bye_team_is_valued_from_its_last_published_week(self):
        values, _, _ = values_for([board_row("p1", 10.0)], [board_row("p2", 12.0, team="BBB", week=4)])
        p2 = next(v for v in values if v.player.player_id == "p2")
        assert p2.on_bye
        assert p2.rate_week == 4
        assert p2.rate == 12.0

    def test_the_most_recent_earlier_week_wins(self):
        values, _, _ = values_for(
            [board_row("p1", 10.0)],
            [board_row("p2", 12.0, team="BBB", week=4), board_row("p2", 6.0, team="BBB", week=3)],
        )
        p2 = next(v for v in values if v.player.player_id == "p2")
        assert (p2.rate_week, p2.rate) == (4, 12.0)

    def test_this_weeks_projection_is_never_replaced(self):
        values, _, _ = values_for([board_row("p1", 10.0)], [board_row("p1", 99.0, week=4)])
        (p1,) = values
        assert not p1.on_bye
        assert p1.rate == 10.0


class TestReplacement:
    BOARD = [board_row(f"p{i:02d}", 20.0 - i) for i in range(12)]

    def test_is_the_best_player_past_the_rostered_depth(self):
        _, levels, names = values_for(self.BOARD)
        assert levels["RB"].starters == 8
        assert names["RB"] == "p08"

    def test_the_replacement_player_is_worth_zero_and_nobody_is_negative(self):
        values, _, _ = values_for(self.BOARD)
        by_id = {v.player.player_id: v for v in values}
        assert by_id["p08"].trade_value == 0.0
        for below in ("p09", "p10", "p11"):
            assert by_id[below].value_over_replacement < 0
            assert by_id[below].trade_value == 0.0
        assert all(v.trade_value >= 0 for v in values)

    def test_value_is_the_surplus_over_the_waiver_wire(self):
        values, levels, _ = values_for(self.BOARD)
        top = values[0]
        assert top.trade_value == pytest.approx(top.rest_of_season - levels["RB"].value)

    def test_ranks_run_one_to_n(self):
        values, _, _ = values_for(self.BOARD)
        assert [v.overall_rank for v in values] == list(range(1, 13))
        assert sorted(v.position_rank for v in values) == list(range(1, 13))
        assert [v.player.player_id for v in values][:3] == ["p00", "p01", "p02"]


def test_is_reproducible():
    board = [board_row(f"p{i:02d}", 20.0 - i) for i in range(12)]
    assert values_for(board)[0] == values_for(board)[0]
