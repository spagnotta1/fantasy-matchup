"""The planning and accountability views, without a database.

Each view has one pure function where it can silently go wrong, and these tests
pin it: the track record's grouping-set classification (a misread flag files the
overall row as a position), the schedule grid (a bye must be a bye, and an
ungraded defence must stay ungraded), and the value board's rank alignment (the
rookie misalignment that would make every veteran look like a bargain).
"""

from __future__ import annotations

from nflfp.services import schedule, track_record
from nflfp.services.draft import value_board

from .draft_fixtures import make_player

# ---------------------------------------------------------------------------
# Track record
# ---------------------------------------------------------------------------


def _agg(**overrides):
    row = {
        "g_season": 1,
        "g_week": 1,
        "g_position": 1,
        "g_band": 1,
        "season": None,
        "week": None,
        "position": None,
        "band": None,
        "graded": 500,
        "mean_absolute_error": 4.3,
        "bias": -0.05,
        "interval_graded": 500,
        "coverage_80": 0.79,
        "coverage_50": 0.5,
        "boom_predicted": 0.07,
        "boom_observed": 0.073,
        "bust_predicted": 0.53,
        "bust_observed": 0.53,
    }
    row.update(overrides)
    return row


class TestTrackRecordGrouping:
    def test_each_grouping_set_lands_in_its_own_group(self):
        rows = [
            _agg(),
            _agg(g_position=0, position="WR"),
            _agg(g_season=0, season=2024),
            _agg(g_season=0, g_position=0, season=2024, position="RB"),
            _agg(g_season=0, g_week=0, season=2024, week=3),
            _agg(g_band=0, band=10.0),
        ]
        groups = track_record.summarise(rows)
        assert len(groups["overall"]) == 1
        assert groups["overall"][0].position is None and groups["overall"][0].season is None
        assert [a.position for a in groups["position"]] == ["WR"]
        assert [a.season for a in groups["season"]] == [2024]
        assert [(a.season, a.position) for a in groups["season_position"]] == [(2024, "RB")]
        assert [(a.season, a.week) for a in groups["weekly"]] == [(2024, 3)]
        assert [(a.band_low, a.band_high) for a in groups["band"]] == [(10.0, 15.0)]

    def test_the_top_band_is_open_ended(self):
        (band,) = track_record.summarise([_agg(g_band=0, band=25.0)])["band"]
        assert band.band_low == 25.0
        assert band.band_high is None

    def test_a_null_value_under_a_rolled_up_flag_is_not_read_as_a_group(self):
        # A real SQL null in `position` for an ungrouped row is still "all
        # positions" only when the flag says so; otherwise it is dropped rather
        # than guessed at.
        groups = track_record.summarise([_agg(g_season=0, g_week=1, g_position=1, g_band=0)])
        assert all(not values for values in groups.values())

    def test_a_small_group_is_flagged_thin(self):
        (acc,) = track_record.summarise([_agg(graded=12)])["overall"]
        assert acc.thin


def _outcome(player_id, projected, actual, floor=None, ceiling=None):
    return {
        "player_id": player_id,
        "player_name": player_id,
        "position": "WR",
        "team": "KC",
        "opponent": "BUF",
        "is_home": True,
        "projected": projected,
        "floor_points": floor,
        "ceiling_points": ceiling,
        "actual": actual,
    }


class TestScorecard:
    def test_beats_and_misses_are_ordered_by_the_size_of_the_difference(self):
        rows = [
            _outcome("a", 12.0, 30.0),
            _outcome("b", 15.0, 20.0),
            _outcome("c", 18.0, 2.0),
            _outcome("d", 10.0, 7.0),
        ]
        card = track_record.build_scorecard(2025, 5, rows, None, size=5)
        assert [o.player_id for o in card.beats] == ["a", "b"]
        assert [o.player_id for o in card.misses] == ["c", "d"]

    def test_players_nobody_started_are_left_out(self):
        rows = [_outcome("backup", 2.0, 25.0), _outcome("starter", 14.0, 20.0)]
        card = track_record.build_scorecard(2025, 5, rows, None)
        assert [o.player_id for o in card.beats] == ["starter"]
        assert card.min_projection == track_record.SCORECARD_MIN_PROJECTION

    def test_inside_range_is_unknown_without_a_range(self):
        assert track_record.outcome_from_row(_outcome("a", 10.0, 12.0)).inside_range is None
        assert track_record.outcome_from_row(_outcome("a", 10.0, 12.0, 5.0, 20.0)).inside_range

    def test_the_requested_week_wins_when_it_has_outcomes(self):
        weekly = track_record.summarise(
            [
                _agg(g_season=0, g_week=0, season=2025, week=3),
                _agg(g_season=0, g_week=0, season=2025, week=7),
            ]
        )["weekly"]
        assert track_record.scorecard_week(weekly, 2025, 3) == (2025, 3)

    def test_an_ungraded_week_falls_back_to_the_latest_graded_one_in_scope(self):
        weekly = track_record.summarise(
            [
                _agg(g_season=0, g_week=0, season=2024, week=17),
                _agg(g_season=0, g_week=0, season=2025, week=7),
            ]
        )["weekly"]
        assert track_record.scorecard_week(weekly, 2025, 12) == (2025, 7)
        assert track_record.scorecard_week(weekly, None, None) == (2025, 7)
        assert track_record.scorecard_week([], 2025, 1) is None


# ---------------------------------------------------------------------------
# Strength of schedule
# ---------------------------------------------------------------------------


def _form(defteam, rank, games=4, position="WR"):
    return {
        "defteam": defteam,
        "position": position,
        "fp_allowed_rank": rank,
        "games_in_window": games,
        "fp_allowed_l4": 20.0,
    }


def _game(team, opponent, week, is_home=True):
    return {"team": team, "opponent": opponent, "week": week, "is_home": is_home, "game_id": f"g{week}"}


class TestScheduleStrength:
    def build(self, schedule_rows, form_rows, weeks=(5, 6, 7), from_week=5):
        return schedule.build_schedule(
            season=2025,
            from_week=from_week,
            position="WR",
            weeks=weeks,
            schedule_rows=schedule_rows,
            form_rows=form_rows,
        )

    def test_a_week_with_no_game_is_a_bye_not_a_missing_grade(self):
        _, teams = self.build([_game("KC", "BUF", 5), _game("KC", "DEN", 7)], [_form("BUF", 32)])
        (kc,) = teams
        assert [c.week for c in kc.cells] == [5, 6, 7]
        assert kc.cells[1].is_bye and kc.cells[1].grade is None

    def test_a_thin_defence_stays_ungraded_and_does_not_count(self):
        _, teams = self.build(
            [_game("KC", "BUF", 5), _game("KC", "DEN", 6)],
            [_form("BUF", 32), _form("DEN", 1, games=2)],
        )
        (kc,) = teams
        assert kc.cells[1].grade is not None and not kc.cells[1].grade.graded
        assert kc.graded_games == 1
        assert kc.mean_score == 100.0  # BUF alone: rank 32 of 32 is the softest

    def test_an_opponent_with_no_form_row_is_ungraded_with_a_reason(self):
        _, teams = self.build([_game("KC", "BUF", 5)], [])
        (kc,) = teams
        grade = kc.cells[0].grade
        assert grade is not None and not grade.graded and grade.reason

    def test_teams_are_ordered_softest_first_and_ungradable_last(self):
        _, teams = self.build(
            [_game("AAA", "SOFT", 5), _game("BBB", "HARD", 5), _game("CCC", "NONE", 5)],
            [_form("SOFT", 32), _form("HARD", 1)],
        )
        assert [t.team for t in teams] == ["AAA", "BBB", "CCC"]

    def test_weeks_before_the_selected_week_are_not_scheduled(self):
        weeks, _ = self.build([_game("KC", "BUF", 5)], [], weeks=(3, 4, 5, 6))
        assert weeks == (5, 6)

    def test_other_positions_rows_are_ignored(self):
        _, teams = self.build([_game("KC", "BUF", 5)], [_form("BUF", 32, position="RB")])
        assert not teams[0].cells[0].grade.graded


# ---------------------------------------------------------------------------
# Value board
# ---------------------------------------------------------------------------


def _adp(player_id, position, adp, *, name=None, status="matched"):
    return {
        "player_id": player_id,
        "adp_name": name or player_id or "Rookie",
        "position": position,
        "team": "KC",
        "adp": adp,
        "adp_formatted": f"{int(adp)}",
        "high": adp - 3,
        "low": adp + 3,
        "stdev": 2.0,
        "teams": 12,
        "total_drafts": 900,
        "window_start": "2025-08-25",
        "window_end": "2025-09-01",
        "is_preseason": True,
        "match_status": status,
    }


class TestValueBoard:
    def test_ranks_are_within_position_so_quarterbacks_are_not_all_bargains(self):
        players = [
            make_player("qb1", "QB", 380.0),
            make_player("wr1", "WR", 300.0),
            make_player("wr2", "WR", 250.0),
        ]
        board = value_board.build_value_board(
            players, [_adp("wr1", "WR", 3), _adp("wr2", "WR", 9), _adp("qb1", "QB", 40)]
        )
        qb = next(e for e in board.entries if e.player.position == "QB")
        assert (qb.market_rank, qb.value_rank, qb.rank_gap) == (1, 1, 0)

    def test_a_rookie_ahead_in_the_market_does_not_shift_veteran_ranks(self):
        # The market takes a rookie first; the pool cannot value him. Ranked over
        # all market entries, wr1 would be market WR2 and look like a value.
        players = [make_player("wr1", "WR", 300.0), make_player("wr2", "WR", 250.0)]
        board = value_board.build_value_board(
            players,
            [_adp(None, "WR", 2, name="Rookie Star", status="matched"),
             _adp("wr1", "WR", 5), _adp("wr2", "WR", 11)],
        )
        by_id = {e.player.player.player_id: e for e in board.entries}
        assert by_id["wr1"].rank_gap == 0 and by_id["wr2"].rank_gap == 0
        (rookie,) = board.market_only
        assert rookie.name == "Rookie Star" and "rookie" in rookie.reason

    def test_a_positive_gap_means_the_pool_likes_him_more_than_the_market(self):
        players = [make_player("wr1", "WR", 200.0), make_player("wr2", "WR", 280.0)]
        board = value_board.build_value_board(players, [_adp("wr1", "WR", 5), _adp("wr2", "WR", 30)])
        by_id = {e.player.player.player_id: e for e in board.entries}
        assert by_id["wr2"].rank_gap == 1 and by_id["wr1"].rank_gap == -1

    def test_players_the_market_ignored_are_listed_as_unpriced(self):
        players = [make_player("wr1", "WR", 300.0), make_player("deep", "WR", 90.0)]
        board = value_board.build_value_board(players, [_adp("wr1", "WR", 5)])
        assert [p.player.player_id for p in board.unpriced] == ["deep"]

    def test_unmatched_and_ambiguous_names_say_why(self):
        board = value_board.build_value_board(
            [],
            [_adp(None, "RB", 20, name="Robbie Chosen", status="unmatched"),
             _adp(None, "WR", 30, name="Mike Williams", status="ambiguous")],
        )
        reasons = {m.name: m.reason for m in board.market_only}
        assert "did not match" in reasons["Robbie Chosen"]
        assert "more than one" in reasons["Mike Williams"]

    def test_a_thin_or_in_season_market_is_said_out_loud(self):
        rows = [dict(_adp("wr1", "WR", 5), total_drafts=137, is_preseason=False)]
        board = value_board.build_value_board([make_player("wr1", "WR", 300.0)], rows)
        notices = " ".join(value_board.market_notices(board, 2026))
        assert "137 drafts" in notices
        assert "in-season market" in notices

    def test_no_market_at_all_is_a_notice_not_an_error(self):
        board = value_board.build_value_board([make_player("wr1", "WR", 300.0)], [])
        assert board.entries == () and board.market is None
        assert any("No ADP" in n for n in value_board.market_notices(board, 2026))
