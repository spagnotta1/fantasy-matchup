"""Live scoring and depth charts, without a network or a database.

The live parser is the one place a silent upstream change would corrupt a
number on screen — read a column by position after ESPN reorders it and yards
become attempts — so its assumptions are pinned on ESPN-shaped fixtures. Against
three real completed weeks (2024 wk 14, 2025 wk 5 and wk 10) the same code
matched the official line exactly for 833 of 858 players; every difference was
a two-point conversion except one blocked-punt touchdown, neither of which the
box score carries.
"""

from __future__ import annotations

import pytest

from nflfp.providers.live import LiveLine, LiveWeek, parse_boxscore, parse_scoreboard
from nflfp.services.depth import group_depth
from nflfp.services.live import score_lines


def _scoreboard():
    return {
        "events": [
            {
                "id": "401",
                "date": "2026-09-18T00:15Z",
                "competitions": [
                    {
                        "status": {
                            "displayClock": "4:12",
                            "period": 3,
                            "type": {"state": "in", "shortDetail": "4:12 - 3rd"},
                        },
                        "competitors": [
                            {"homeAway": "home", "score": "17", "team": {"abbreviation": "LAR"}},
                            {"homeAway": "away", "score": "10", "team": {"abbreviation": "WSH"}},
                        ],
                    }
                ],
            }
        ]
    }


def _box():
    return {
        "boxscore": {
            "players": [
                {
                    "team": {"abbreviation": "LAR"},
                    "statistics": [
                        {
                            "name": "passing",
                            "keys": ["completions/passingAttempts", "passingYards", "passingTouchdowns", "interceptions"],
                            "athletes": [{"athlete": {"id": "1", "displayName": "Quarter Back"}, "stats": ["20/30", "250", "2", "1"]}],
                        },
                        {
                            "name": "rushing",
                            # Deliberately reordered: keys are read by name.
                            "keys": ["rushingYards", "rushingAttempts", "rushingTouchdowns"],
                            "athletes": [{"athlete": {"id": "1", "displayName": "Quarter Back"}, "stats": ["12", "3", "0"]}],
                        },
                        {
                            "name": "receiving",
                            "keys": ["receptions", "receivingYards", "receivingTouchdowns", "receivingTargets"],
                            "athletes": [{"athlete": {"id": "2", "displayName": "Wide Out"}, "stats": ["6", "1,02", "--", "9"]}],
                        },
                        {
                            "name": "kickReturns",
                            "keys": ["kickReturns", "kickReturnTouchdowns"],
                            "athletes": [{"athlete": {"id": "2", "displayName": "Wide Out"}, "stats": ["2", "1"]}],
                        },
                        {
                            "name": "puntReturns",
                            "keys": ["puntReturns", "puntReturnTouchdowns"],
                            "athletes": [{"athlete": {"id": "2", "displayName": "Wide Out"}, "stats": ["1", "1"]}],
                        },
                        {
                            "name": "kicking",
                            "keys": ["totalKickingPoints"],
                            "athletes": [{"athlete": {"id": "9", "displayName": "Kicker"}, "stats": ["7"]}],
                        },
                    ],
                }
            ]
        }
    }


class TestScoreboard:
    def test_state_score_and_team_fixups(self):
        (game,) = parse_scoreboard(_scoreboard())
        assert (game.home, game.away) == ("LA", "WAS")
        assert (game.state, game.period, game.clock) == ("in", 3, "4:12")
        assert (game.home_score, game.away_score) == (17, 10)

    def test_a_malformed_payload_is_no_games_not_an_exception(self):
        assert parse_scoreboard(None) == []
        assert parse_scoreboard({"events": [{"competitions": [{"competitors": []}]}]}) == []


class TestBoxScore:
    def test_categories_merge_into_one_line_per_player(self):
        lines = {line.espn_id: line for line in parse_boxscore(_box(), "401")}
        qb = lines["1"].components
        assert qb["passing_yards"] == 250 and qb["passing_tds"] == 2
        # Read by key name even though the rushing columns were reordered.
        assert qb["rushing_yards"] == 12 and qb["carries"] == 3

    def test_placeholders_and_thousands_separators_are_numbers(self):
        wr = {line.espn_id: line for line in parse_boxscore(_box(), "401")}["2"].components
        assert wr["receiving_tds"] == 0.0
        assert wr["receiving_yards"] == 102.0

    def test_return_touchdowns_accumulate_across_categories(self):
        wr = {line.espn_id: line for line in parse_boxscore(_box(), "401")}["2"].components
        assert wr["special_teams_tds"] == 2.0

    def test_categories_that_score_nothing_here_are_ignored(self):
        assert "9" not in {line.espn_id for line in parse_boxscore(_box(), "401")}


class TestScoreLines:
    def _week(self):
        return LiveWeek(
            lines=[
                LiveLine("1", "QB", "LA", "401", {"passing_yards": 250.0, "passing_tds": 2.0}),
                LiveLine("2", "WR", "LA", "401", {"receptions": 6.0, "receiving_yards": 80.0}),
                LiveLine("8", "K", "LA", "401", {"passing_yards": 0.0}),
                LiveLine("7", "Unknown", "LA", "401", {"receptions": 1.0}),
            ]
        )

    def _players(self):
        return {
            "1": {"player_id": "00-1", "display_name": "Quarter Back", "position": "QB"},
            "2": {"player_id": "00-2", "display_name": "Wide Out", "position": "WR"},
            "8": {"player_id": "00-8", "display_name": "Kicker", "position": "K"},
        }

    def test_lines_are_scored_in_the_requested_format(self):
        players = score_lines(self._week(), self._players(), {}, "ppr")
        by_id = {p.player_id: p for p in players}
        assert by_id["00-1"].live_points == pytest.approx(18.0)
        assert by_id["00-2"].live_points == pytest.approx(14.0)

    def test_unprojected_positions_and_unmatched_ids_are_dropped(self):
        ids = {p.player_id for p in score_lines(self._week(), self._players(), {}, "ppr")}
        assert ids == {"00-1", "00-2"}

    def test_the_projection_rides_alongside_unchanged(self):
        projections = {"00-2": {"headline": 11.5, "floor_points": 4.0, "ceiling_points": 21.0}}
        wr = {p.player_id: p for p in score_lines(self._week(), self._players(), projections, "ppr")}["00-2"]
        assert (wr.projected, wr.floor, wr.ceiling) == (11.5, 4.0, 21.0)


class TestDepthGrouping:
    def test_positions_come_back_in_lineup_order_and_depth_order(self):
        rows = [
            {"position": "WR", "depth": 2, "player_id": "b", "player_name": "B"},
            {"position": "WR", "depth": 1, "player_id": "a", "player_name": "A"},
            {"position": "LT", "depth": 1, "player_id": "x", "player_name": "Tackle"},
            {"position": "QB", "depth": 1, "player_id": "q", "player_name": "Q"},
        ]
        grouped = group_depth(rows)
        assert list(grouped) == ["QB", "RB", "WR", "TE"]
        assert [e.name for e in grouped["WR"]] == ["A", "B"]
        assert grouped["RB"] == ()
