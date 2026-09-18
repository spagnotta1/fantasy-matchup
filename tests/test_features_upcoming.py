"""Tests for ``feat_upcoming_slate`` — the slate for a week not yet played.

The bug this view exists to fix shipped a **22-player board** for 2026 week 2.
``generate_projections`` resolves its target from ``upcoming_games`` (the
schedule) and then loaded that week's slate from ``feat_training_dataset``,
which is built from recorded production. The job therefore asked for a week
nobody had played and built its board from the games that had — one of sixteen,
at the time it ran.

These tests run the view's real SQL against a small warehouse built in memory,
because the whole of the interesting behaviour is in the SQL: which games form
the slate, which games form each window, and — the one that would be a genuine
disaster to get wrong — that no row of it can reach a training set.

The fixture deliberately models a **partially played week**, which is the state
that produced the bug: week 2 with one game in the books and the rest to come.
"""

from __future__ import annotations

import pytest

from nflfp.features.upcoming import UPCOMING_SLATE
from nflfp.predict.features import AVAILABLE_FEATURES

#: Columns the fixture inserts, named explicitly so a schema change here fails
#: loudly rather than shifting values silently into the wrong column.
COLUMNS = (
    "player_id, player_name, position, season, week, season_type, team, "
    "opponent, offense_pct, target_share, targets, carries, receptions, "
    "attempts, air_yards_share, wopr, fp_half_ppr, receiving_yards, "
    "rushing_yards, passing_yards, receiving_tds, rushing_tds, passing_tds, "
    "passing_interceptions, fumbles_lost_total, special_teams_tds, "
    "passing_2pt_conversions, rushing_2pt_conversions, "
    "receiving_2pt_conversions, receiving_epa, rushing_epa, passing_epa"
)


def _play(con, player, name, position, season, week, team, opponent, points,
          snap=0.7, share=0.2):
    """Record one completed game."""
    con.execute(
        f"INSERT INTO player_week ({COLUMNS}) VALUES "
        "(?, ?, ?, ?, ?, 'REG', ?, ?, ?, ?, 4, 10, 3, 0, 0.1, 0.2, ?, "
        "40, 50, 0, 0, 0.4, 0, 0, 0, 0, 0, 0, 0, 1.0, 1.0, 0)",
        [player, name, position, season, week, team, opponent, snap, share, points],
    )


@pytest.fixture()
def warehouse():
    """2025 complete; 2026 week 1 played, week 2 half played, week 3 not."""
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE player_week (
            player_id VARCHAR, player_name VARCHAR, position VARCHAR,
            season INTEGER, week INTEGER, season_type VARCHAR,
            team VARCHAR, opponent VARCHAR,
            offense_pct DOUBLE, target_share DOUBLE, targets DOUBLE,
            carries DOUBLE, receptions DOUBLE, attempts DOUBLE,
            air_yards_share DOUBLE, wopr DOUBLE, fp_half_ppr DOUBLE,
            receiving_yards DOUBLE, rushing_yards DOUBLE, passing_yards DOUBLE,
            receiving_tds DOUBLE, rushing_tds DOUBLE, passing_tds DOUBLE,
            passing_interceptions DOUBLE, fumbles_lost_total DOUBLE,
            special_teams_tds DOUBLE, passing_2pt_conversions DOUBLE,
            rushing_2pt_conversions DOUBLE, receiving_2pt_conversions DOUBLE,
            receiving_epa DOUBLE, rushing_epa DOUBLE, passing_epa DOUBLE
        )
        """
    )
    # A veteran on AAA: four 2025 games and both played 2026 games.
    for week, points in ((15, 3.0), (16, 4.0), (17, 5.0), (18, 6.0)):
        _play(con, "vet", "Vet Back", "RB", 2025, week, "AAA", "ZZZ", points)
    _play(con, "vet", "Vet Back", "RB", 2026, 1, "AAA", "BBB", 10.0)
    _play(con, "vet", "Vet Back", "RB", 2026, 2, "AAA", "CCC", 20.0)
    # A receiver on BBB whose week 2 game has NOT been played.
    _play(con, "wr1", "Wide Out", "WR", 2025, 18, "BBB", "ZZZ", 12.0)
    _play(con, "wr1", "Wide Out", "WR", 2026, 1, "BBB", "AAA", 14.0)
    # The leakage probe: a player_week row for a game whose score has not
    # reached game_team, so week 3 is still upcoming. A window that reached it
    # would be predicting a game from its own result.
    _play(con, "vet", "Vet Back", "RB", 2026, 3, "AAA", "DDD", 999.0)

    con.execute(
        """
        CREATE TABLE game_team (
            game_id VARCHAR, season INTEGER, week INTEGER, game_type VARCHAR,
            team VARCHAR, opponent VARCHAR, team_score INTEGER
        )
        """
    )
    con.execute(
        "INSERT INTO game_team VALUES "
        # week 1: both games played
        "('2026_01_AAA', 2026, 1, 'REG', 'AAA', 'BBB', 21),"
        "('2026_01_BBB', 2026, 1, 'REG', 'BBB', 'AAA', 17),"
        # week 2: AAA/CCC played (the Thursday game), BBB/DDD have not
        "('2026_02_AAA', 2026, 2, 'REG', 'AAA', 'CCC', 24),"
        "('2026_02_CCC', 2026, 2, 'REG', 'CCC', 'AAA', 20),"
        "('2026_02_BBB', 2026, 2, 'REG', 'BBB', 'DDD', NULL),"
        "('2026_02_DDD', 2026, 2, 'REG', 'DDD', 'BBB', NULL),"
        # week 3: nothing played
        "('2026_03_AAA', 2026, 3, 'REG', 'AAA', 'DDD', NULL),"
        "('2026_03_BBB', 2026, 3, 'REG', 'BBB', 'CCC', NULL),"
        # a postseason game, which is not a fantasy slate
        "('2026_19_AAA', 2026, 19, 'POST', 'AAA', 'BBB', NULL)"
    )
    con.execute(
        "CREATE VIEW upcoming_games AS SELECT * FROM game_team "
        "WHERE team_score IS NULL"
    )

    con.execute(
        "CREATE TABLE raw_rosters (season INTEGER, gsis_id VARCHAR, "
        "full_name VARCHAR, position VARCHAR, team VARCHAR)"
    )
    con.execute(
        "INSERT INTO raw_rosters VALUES "
        "(2026, 'vet', 'Vet Back', 'RB', 'AAA'),"
        "(2026, 'wr1', 'Wide Out', 'WR', 'BBB'),"
        # rostered, never played: no window, no row
        "(2026, 'rook', 'Rookie Back', 'RB', 'AAA'),"
        # no projection model for the position
        "(2026, 'kick', 'Kicker', 'K', 'AAA')"
    )

    con.execute(
        """
        CREATE VIEW feat_game_context AS
        SELECT game_id, team,
               TRUE  AS is_home,
               FALSE AS div_game,
               CAST(7 AS INTEGER)   AS rest_days,
               CAST(0 AS INTEGER)   AS rest_advantage,
               CAST(NULL AS DOUBLE) AS team_spread,
               CAST(NULL AS DOUBLE) AS total_line,
               CAST(NULL AS DOUBLE) AS implied_team_total,
               CAST(NULL AS DOUBLE) AS implied_opp_total,
               CAST(NULL AS DOUBLE) AS spread_movement,
               CAST(NULL AS VARCHAR) AS spread_source,
               CAST(NULL AS DOUBLE) AS temperature_f,
               CAST(NULL AS DOUBLE) AS wind_mph,
               CAST(NULL AS DOUBLE) AS precipitation_probability,
               FALSE AS is_indoor,
               FALSE AS roof_uncertain,
               CAST(NULL AS VARCHAR) AS weather_source
        FROM game_team
        """
    )
    # The rolling defensive views reset each season and withhold a grade below
    # three games of history, so an early-season join finds nothing. Stubbed
    # empty rather than populated: what matters here is that the join shape is
    # right and a miss yields null rather than dropping the row.
    con.execute(
        """
        CREATE VIEW feat_defense_position_rolling AS
        SELECT CAST(NULL AS INTEGER) AS season, CAST(NULL AS INTEGER) AS week,
               CAST(NULL AS VARCHAR) AS defteam, CAST(NULL AS VARCHAR) AS position,
               CAST(NULL AS DOUBLE) AS fp_allowed_l4,
               CAST(NULL AS BIGINT) AS fp_allowed_rank,
               CAST(NULL AS DOUBLE) AS targets_allowed_l4,
               CAST(NULL AS DOUBLE) AS carries_allowed_l4
        WHERE FALSE
        """
    )
    con.execute(
        """
        CREATE VIEW feat_defense_rolling AS
        SELECT CAST(NULL AS INTEGER) AS season, CAST(NULL AS INTEGER) AS week,
               CAST(NULL AS VARCHAR) AS defteam,
               CAST(NULL AS BIGINT) AS fp_allowed_rank,
               CAST(NULL AS DOUBLE) AS plays_faced_l4
        WHERE FALSE
        """
    )
    con.execute(f"CREATE VIEW slate AS {UPCOMING_SLATE.sql}")
    yield con
    con.close()


class TestWhichGamesFormTheSlate:
    def test_a_played_week_is_not_on_the_slate(self, warehouse):
        """Week 1 is complete. Projecting it would be projecting the past."""
        weeks = {row[0] for row in warehouse.execute("SELECT week FROM slate").fetchall()}
        assert 1 not in weeks

    def test_the_slate_reaches_past_week_one(self, warehouse):
        """The whole point. ``feat_preseason_slate`` stops at week 1; the
        weekly job needs every week after it."""
        weeks = {row[0] for row in warehouse.execute("SELECT week FROM slate").fetchall()}
        assert weeks == {2, 3}

    def test_a_partially_played_week_yields_only_the_unplayed_games(self, warehouse):
        """The exact shape that produced the 22-player board.

        AAA and CCC played their week 2 game; BBB and DDD have not. Only the
        latter belong on a week 2 slate — the played teams are served by
        ``feat_training_dataset`` instead, and the two sets must not overlap or
        ``_season_rows`` would double-count them.
        """
        teams = {
            row[0]
            for row in warehouse.execute(
                "SELECT team FROM slate WHERE week = 2"
            ).fetchall()
        }
        assert teams == {"BBB"}

    def test_the_postseason_is_not_a_fantasy_slate(self, warehouse):
        weeks = {row[0] for row in warehouse.execute("SELECT week FROM slate").fetchall()}
        assert 19 not in weeks

    def test_rookies_are_absent_rather_than_guessed_at(self, warehouse):
        ids = {row[0] for row in warehouse.execute("SELECT player_id FROM slate").fetchall()}
        assert "rook" not in ids
        assert "vet" in ids

    def test_unprojectable_positions_never_reach_the_board(self, warehouse):
        positions = {
            row[0] for row in warehouse.execute("SELECT position FROM slate").fetchall()
        }
        assert "K" not in positions


class TestTheWindow:
    def test_the_window_stops_strictly_before_the_target_week(self, warehouse):
        """The leakage boundary, asserted against a row that would trip it.

        ``vet`` has a player_week row for 2026 week 3 scoring 999, for a game
        whose score has not reached ``game_team`` — so week 3 is still
        upcoming. A window including it would predict a game from its result.
        """
        (points,) = warehouse.execute(
            "SELECT fp_half_ppr_l4 FROM slate WHERE player_id = 'vet' AND week = 3"
        ).fetchone()
        # The four completed games before 2026 w3: 2025 w17 (5), 2025 w18 (6),
        # 2026 w1 (10), 2026 w2 (20). Emphatically not 999.
        assert points == pytest.approx((5.0 + 6.0 + 10.0 + 20.0) / 4)

    def test_no_row_carries_a_window_inflated_by_its_own_week(self, warehouse):
        """The general form: no slate row may show a window average that could
        only come from including the 999-point future game."""
        (leaked,) = warehouse.execute(
            "SELECT count(*) FROM slate WHERE fp_half_ppr_l4 > 100"
        ).fetchone()
        assert leaked == 0

    def test_the_window_crosses_the_offseason_when_it_has_to(self, warehouse):
        """A week 2 row reaches back into last season, exactly as the in-season
        view does — its four-game window is partitioned by player, not by
        season, so last December is information available in September."""
        (points,) = warehouse.execute(
            "SELECT fp_half_ppr_l4 FROM slate WHERE player_id = 'wr1' AND week = 2"
        ).fetchone()
        # wr1 has two completed games: 2025 w18 (12) and 2026 w1 (14).
        assert points == pytest.approx((12.0 + 14.0) / 2)

    def test_evidence_weight_reports_a_short_window(self, warehouse):
        """``games_in_window_l4`` is what lets the shrinkage distrust a thin
        average. A two-game window must say two, not four."""
        (games,) = warehouse.execute(
            "SELECT games_in_window_l4 FROM slate WHERE player_id = 'wr1' AND week = 2"
        ).fetchone()
        assert games == 2

    def test_season_to_date_counts_only_this_seasons_completed_games(self, warehouse):
        """``games_played_season`` mirrors the in-season ``_SEASON`` partition:
        this season only, everything strictly before this week."""
        (played,) = warehouse.execute(
            "SELECT games_played_season FROM slate "
            "WHERE player_id = 'vet' AND week = 3"
        ).fetchone()
        assert played == 2  # 2026 weeks 1 and 2, not the 2025 games

    def test_the_trend_column_measures_against_the_most_recent_game(self, warehouse):
        """``snap_pct_trend`` is the four-game average minus the last game,
        which is what the in-season view's LAG produces."""
        (trend,) = warehouse.execute(
            "SELECT snap_pct_trend FROM slate WHERE player_id = 'vet' AND week = 3"
        ).fetchone()
        # Every fixture game uses the same snap share, so the trend is flat.
        assert trend == pytest.approx(0.0)


class TestTheContractWithEverythingAbove:
    def test_no_slate_row_can_reach_a_training_set(self, warehouse):
        """The property the whole design rests on, as for the preseason slate.

        ``dataset.load_rows(completed_only=True)`` selects on
        ``fp_half_ppr_actual IS NOT NULL``. Every target column here is null,
        so no scheduled row can become a training example however it is joined
        — which is what lets this view exist beside the real one without a
        guard anybody has to remember.
        """
        (leaked,) = warehouse.execute(
            "SELECT count(*) FROM slate WHERE fp_half_ppr_actual IS NOT NULL "
            "OR fp_ppr_actual IS NOT NULL OR fp_standard_actual IS NOT NULL"
        ).fetchone()
        assert leaked == 0

    def test_the_key_is_unique(self, warehouse):
        """The view declares (player_id, season, week) unique, which is what a
        concurrent refresh depends on. Prove it can be."""
        (dupes,) = warehouse.execute(
            "SELECT count(*) FROM (SELECT player_id, season, week FROM slate "
            "GROUP BY 1, 2, 3 HAVING count(*) > 1)"
        ).fetchone()
        assert dupes == 0

    def test_the_model_can_read_every_feature_it_needs(self, warehouse):
        """The slate has to be the same shape as the table it stands in for."""
        columns = {row[0] for row in warehouse.execute("DESCRIBE slate").fetchall()}
        missing = set(AVAILABLE_FEATURES) - columns
        assert not missing, f"slate is missing model features: {sorted(missing)}"
