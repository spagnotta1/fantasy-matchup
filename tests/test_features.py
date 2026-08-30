"""Tests for the feature layer.

The unit tests here guard the property that matters most and is hardest to
notice when it breaks: **no feature may use information from the week it
describes.** A leaked feature does not throw, does not look wrong in a row, and
produces a backtest that looks excellent — right up until the model is asked to
project a game that has not happened.

The integration tests assert it again against real data, by recomputing a
window by hand and comparing.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from nflfp.features import REGISTRY, build_features, lagged_window
from nflfp.features.base import FeatureRegistry, FeatureView
from nflfp.features.preseason import PRESEASON_SLATE
from nflfp.predict.features import AVAILABLE_FEATURES

from .conftest import requires_db


# ---------------------------------------------------------------------------
# registry mechanics
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_declared_order_is_dependency_order(self):
        """validate() fails if a view references one registered after it."""
        REGISTRY.validate()

    def test_every_view_declares_a_unique_index(self):
        """REFRESH MATERIALIZED VIEW CONCURRENTLY requires one. Without it the
        refresh takes an ACCESS EXCLUSIVE lock and blocks every reader."""
        for view in REGISTRY.views:
            assert view.unique_index, view.name

    def test_every_view_is_documented(self):
        for view in REGISTRY.views:
            assert view.description.strip(), view.name

    def test_names_are_prefixed_and_unique(self):
        names = REGISTRY.names()
        assert len(names) == len(set(names))
        assert all(n.startswith("feat_") for n in names)

    def test_duplicate_registration_is_rejected(self):
        registry = FeatureRegistry()
        view = FeatureView("feat_x", "SELECT 1", ("t",), ("a",))
        registry.register(view)
        with pytest.raises(ValueError, match="duplicate"):
            registry.register(FeatureView("feat_x", "SELECT 2", ("t",), ("a",)))

    def test_forward_dependency_is_rejected(self):
        registry = FeatureRegistry()
        registry.register(FeatureView("feat_a", "SELECT 1", ("feat_b",), ("x",)))
        registry.register(FeatureView("feat_b", "SELECT 1", ("t",), ("x",)))
        with pytest.raises(ValueError, match="registered later"):
            registry.validate()

    def test_views_with_missing_inputs_are_skipped_not_failed(self):
        """raw_pbp is opt-in; a feature needing it must not break the build."""
        registry = FeatureRegistry()
        registry.register(FeatureView("feat_ok", "SELECT 1", ("player_week",), ("x",)))
        registry.register(FeatureView("feat_pbp", "SELECT 1", ("raw_pbp",), ("x",)))
        ready = registry.buildable({"player_week"})
        assert [v.name for v in ready] == ["feat_ok"]

    def test_a_feature_may_depend_on_an_earlier_feature(self):
        registry = FeatureRegistry()
        registry.register(FeatureView("feat_a", "SELECT 1", ("player_week",), ("x",)))
        registry.register(FeatureView("feat_b", "SELECT 1", ("feat_a",), ("x",)))
        assert len(registry.buildable({"player_week"})) == 2


# ---------------------------------------------------------------------------
# leakage
# ---------------------------------------------------------------------------

class TestPreseasonSlate:
    """The board for a season nobody has played yet.

    The slate is the only way to draft an upcoming season, because every other
    feature row in the system is derived from recorded production and an
    unplayed season has none. These tests run the view's real SQL against a
    small warehouse built in memory, because the interesting behaviour is
    entirely in the SQL: which players appear, whose games form their window,
    and — the one that would be a genuine disaster to get wrong — that not one
    of its rows can reach a training set.
    """

    @pytest.fixture()
    def warehouse(self):
        """A two-season warehouse: 2025 played, 2026 scheduled and rostered."""
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
                special_teams_tds DOUBLE, receiving_epa DOUBLE,
                rushing_epa DOUBLE, passing_epa DOUBLE
            )
            """
        )
        # A veteran with six 2025 games, rising through the season, so a
        # four-game window and an eight-game window give different answers.
        for week, points in enumerate([5.0, 6.0, 7.0, 20.0, 22.0, 24.0], start=13):
            con.execute(
                "INSERT INTO player_week VALUES ('vet', 'Vet Back', 'RB', 2025, ?, "
                "'REG', 'AAA', 'BBB', 0.7, 0.1, 4, 12, 3, 0, 0.1, 0.2, ?, "
                "30, 60, 0, 0, 0.5, 0, 0, 0, 0, 1.0, 1.0, 0)",
                [week, points],
            )
        # A player who moved teams: their window is AAA's, their 2026 seat CCC's.
        con.execute(
            "INSERT INTO player_week VALUES ('mover', 'Free Agent', 'WR', 2025, 17, "
            "'REG', 'AAA', 'BBB', 0.8, 0.25, 9, 0, 6, 0, 0.3, 0.5, 15.0, "
            "80, 0, 0, 1, 0, 0, 0, 0, 0, 2.0, 0.0, 0)"
        )

        con.execute(
            """
            CREATE TABLE game_team (
                game_id VARCHAR, season INTEGER, week INTEGER, game_type VARCHAR,
                team VARCHAR, opponent VARCHAR
            )
            """
        )
        con.execute(
            "INSERT INTO game_team VALUES "
            "('2026_01_AAA', 2026, 1, 'REG', 'AAA', 'BBB'),"
            "('2026_01_BBB', 2026, 1, 'REG', 'BBB', 'AAA'),"
            "('2026_01_CCC', 2026, 1, 'REG', 'CCC', 'DDD'),"
            "('2026_02_AAA', 2026, 2, 'REG', 'AAA', 'CCC')"
        )

        con.execute(
            "CREATE TABLE raw_rosters (season INTEGER, gsis_id VARCHAR, "
            "full_name VARCHAR, position VARCHAR, team VARCHAR)"
        )
        con.execute(
            "INSERT INTO raw_rosters VALUES "
            "(2026, 'vet', 'Vet Back', 'RB', 'AAA'),"
            "(2026, 'mover', 'Free Agent', 'WR', 'CCC'),"
            # A rookie: rostered, never played. Must not appear.
            "(2026, 'rook', 'Rookie Back', 'RB', 'AAA'),"
            # A kicker: rostered, but there is no model for the position.
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
        con.execute(f"CREATE VIEW slate AS {PRESEASON_SLATE.sql}")
        yield con
        con.close()

    def test_rookies_are_absent_rather_than_guessed_at(self, warehouse):
        """The gap the draft pool has to declare, asserted at its source."""
        ids = {row[0] for row in warehouse.execute("SELECT player_id FROM slate").fetchall()}
        assert "rook" not in ids
        assert "vet" in ids

    def test_unprojectable_positions_never_reach_the_board(self, warehouse):
        positions = {
            row[0] for row in warehouse.execute("SELECT position FROM slate").fetchall()
        }
        assert "K" not in positions

    def test_the_window_is_the_last_four_games_of_the_previous_season(self, warehouse):
        """Not the whole season, and not a window that stops one game short."""
        (points,) = warehouse.execute(
            "SELECT fp_half_ppr_l4 FROM slate WHERE player_id = 'vet'"
        ).fetchone()
        # Weeks 15-18: 7, 20, 22, 24.
        assert points == pytest.approx((7.0 + 20.0 + 22.0 + 24.0) / 4)

    def test_the_window_ends_with_the_players_last_game(self, warehouse):
        """The in-season view lags by a week; a preseason row must not.

        A window that stopped one game short would silently discard the most
        recent evidence there is — the single most informative game on the
        board — and nothing downstream would show it.
        """
        (games,) = warehouse.execute(
            "SELECT games_in_window_l4 FROM slate WHERE player_id = 'vet'"
        ).fetchone()
        assert games == 4

    def test_a_player_who_moved_carries_their_old_usage_to_their_new_team(
        self, warehouse
    ):
        team, opponent, share = warehouse.execute(
            "SELECT team, opponent, target_share_l4 FROM slate "
            "WHERE player_id = 'mover'"
        ).fetchone()
        assert (team, opponent) == ("CCC", "DDD")
        assert share == pytest.approx(0.25)

    def test_only_week_one_is_on_the_slate(self, warehouse):
        weeks = {row[0] for row in warehouse.execute("SELECT week FROM slate").fetchall()}
        assert weeks == {1}

    def test_no_slate_row_can_reach_a_training_set(self, warehouse):
        """The property the whole design rests on.

        ``dataset.load_rows(completed_only=True)`` selects on
        ``fp_half_ppr_actual IS NOT NULL``. Every target column here is null, so
        a preseason row cannot become a training example however the view is
        joined — which is what lets this table exist beside the real one without
        a guard anybody has to remember.
        """
        (leaked,) = warehouse.execute(
            "SELECT count(*) FROM slate WHERE fp_half_ppr_actual IS NOT NULL "
            "OR fp_ppr_actual IS NOT NULL OR fp_standard_actual IS NOT NULL"
        ).fetchone()
        assert leaked == 0

    def test_the_key_is_unique(self, warehouse):
        """The view declares (player_id, season, week) unique; prove it can be."""
        (dupes,) = warehouse.execute(
            "SELECT count(*) FROM (SELECT player_id, season, week FROM slate "
            "GROUP BY 1, 2, 3 HAVING count(*) > 1)"
        ).fetchone()
        assert dupes == 0

    def test_the_model_can_read_every_feature_it_needs(self, warehouse):
        """The slate has to be the same shape as the table it stands in for."""
        columns = {
            row[0]
            for row in warehouse.execute("DESCRIBE slate").fetchall()
        }
        missing = set(AVAILABLE_FEATURES) - columns
        assert not missing, f"slate is missing model features: {sorted(missing)}"


class TestNoLeakage:
    def test_lagged_window_excludes_the_current_row(self):
        frame = lagged_window("player_id", preceding=4)
        assert "ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING" in frame
        assert "CURRENT ROW" not in frame

    @pytest.mark.parametrize("view", REGISTRY.views, ids=lambda v: v.name)
    def test_no_window_frame_reaches_the_current_row(self, view):
        """The core anti-leakage assertion, applied to every definition.

        Any window ending at CURRENT ROW or UNBOUNDED FOLLOWING would let a
        feature see the outcome it is meant to predict.
        """
        sql = view.sql.upper()
        assert "AND CURRENT ROW" not in sql, f"{view.name} has a window reaching the current row"
        assert "UNBOUNDED FOLLOWING" not in sql, f"{view.name} looks into the future"

    @pytest.mark.parametrize("view", REGISTRY.views, ids=lambda v: v.name)
    def test_every_window_frame_ends_at_1_preceding(self, view):
        frames = re.findall(r"ROWS BETWEEN .*? AND (\S+(?: \S+)?)", view.sql.upper())
        for ending in frames:
            assert ending.startswith("1 PRECEDING"), (
                f"{view.name} has a window ending at {ending!r}, not '1 PRECEDING'"
            )

    def test_defensive_windows_reset_each_season(self):
        """A defence turns over in the offseason; carrying December into
        September would describe a unit that no longer exists."""
        from nflfp.features import defense

        assert "PARTITION BY defteam, season" in defense.DEFENSE_ROLLING.sql

    def test_player_usage_rolling_windows_span_seasons(self):
        """The opposite choice, deliberately: usage persists year over year
        (r = 0.63-0.73), and carrying last December into Week 1 is what gives
        the opening slate any features at all.

        Asserted against the window constants rather than the rendered SQL,
        because the season-to-date columns *do* partition by season and would
        otherwise make a whole-body match ambiguous.
        """
        from nflfp.features import usage

        # The rolling windows: player only, so they cross the season boundary.
        assert "PARTITION BY player_id ORDER BY" in usage._U
        assert "PARTITION BY player_id ORDER BY" in usage._E
        # The season-to-date window: reset per season, as its name promises.
        assert "PARTITION BY player_id, season" in usage._SEASON


# ---------------------------------------------------------------------------
# integration
# ---------------------------------------------------------------------------

@requires_db
@pytest.mark.integration
class TestAgainstRealData:
    """These run against the developer warehouse in ``public``.

    Read-only apart from the build test, which is skipped unless the feature
    views already exist — building them in a throwaway schema would need the
    whole 182k-row warehouse copied into it.
    """

    def _skip_without_features(self, pg_engine):
        with pg_engine.connect() as conn:
            present = conn.execute(
                text("SELECT count(*) FROM pg_matviews WHERE matviewname = 'feat_training_dataset'")
            ).scalar_one()
        if not present:
            pytest.skip("feature views not built; run `python -m nflfp.jobs run build_features`")

    def test_lagged_usage_matches_a_manual_recomputation(self, pg_engine):
        """The strongest available statement that the lag is real.

        Recomputes snap_pct_l4 from player_week for every row and asserts the
        stored value agrees everywhere.
        """
        self._skip_without_features(pg_engine)
        with pg_engine.connect() as conn:
            disagreements = conn.execute(
                text(
                    """
                    SELECT count(*) FROM (
                      SELECT u.snap_pct_l4 AS stored,
                             avg(pw.offense_pct) OVER (
                                 PARTITION BY pw.player_id ORDER BY pw.season, pw.week
                                 ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING) AS manual
                      FROM player_week pw
                      JOIN feat_player_usage u
                        ON u.player_id = pw.player_id
                       AND u.season = pw.season AND u.week = pw.week
                      WHERE pw.season_type = 'REG'
                    ) t
                    WHERE (stored IS NULL) <> (manual IS NULL)
                       OR abs(coalesce(stored, 0) - coalesce(manual, 0)) > 1e-9
                    """
                )
            ).scalar_one()
        assert disagreements == 0

    def test_defensive_ranks_span_the_league(self, pg_engine):
        self._skip_without_features(pg_engine)
        with pg_engine.connect() as conn:
            low, high = conn.execute(
                text(
                    "SELECT min(fp_allowed_rank), max(fp_allowed_rank) "
                    "FROM feat_defense_rolling WHERE fp_allowed_l4 IS NOT NULL"
                )
            ).one()
        assert (low, high) == (1, 32)

    def test_spread_sign_convention_survives_the_feature_layer(self, pg_engine):
        """team_spread must stay 'points THIS team is favoured by'.

        Inverting it produces a model that is confidently wrong in a way no
        aggregate metric reveals, so it is pinned to the correlation the README
        documents against actual margin (+0.44).
        """
        self._skip_without_features(pg_engine)
        with pg_engine.connect() as conn:
            correlation = conn.execute(
                text(
                    """
                    SELECT corr(c.team_spread, g.team_score - g.opp_score)
                    FROM feat_game_context c
                    JOIN game_team g USING (game_id, team)
                    WHERE c.team_spread IS NOT NULL AND g.team_score IS NOT NULL
                    """
                )
            ).scalar_one()
        assert 0.35 < correlation < 0.55, f"spread sign looks inverted: r={correlation}"

    def test_implied_totals_sum_to_the_game_total(self, pg_engine):
        self._skip_without_features(pg_engine)
        with pg_engine.connect() as conn:
            bad = conn.execute(
                text(
                    """
                    SELECT count(*) FROM feat_game_context
                    WHERE implied_team_total IS NOT NULL
                      AND abs((implied_team_total + implied_opp_total) - total_line) > 1e-6
                    """
                )
            ).scalar_one()
        assert bad == 0

    def test_training_dataset_joins_are_covered(self, pg_engine):
        """A LEFT JOIN that silently matches nothing is the classic way a
        feature table ends up full of NULLs nobody notices."""
        self._skip_without_features(pg_engine)
        with pg_engine.connect() as conn:
            total, context, defense = conn.execute(
                text(
                    """
                    SELECT count(*),
                           count(implied_team_total),
                           count(opp_defense_rank_vs_position)
                    FROM feat_training_dataset
                    WHERE season = 2024 AND week >= 6 AND fp_half_ppr_actual IS NOT NULL
                    """
                )
            ).one()
        assert total > 1000
        assert context / total > 0.95
        assert defense / total > 0.95

    def test_build_is_deterministic(self, pg_engine):
        """Same warehouse state, same feature values — the property a backtest
        depends on."""
        self._skip_without_features(pg_engine)
        from sqlalchemy.orm import Session

        with Session(pg_engine) as session:
            first = session.execute(
                text("SELECT count(*), round(sum(fp_half_ppr_l4)::numeric, 4) FROM feat_player_usage")
            ).one()
            build_features(session)
            session.commit()
            second = session.execute(
                text("SELECT count(*), round(sum(fp_half_ppr_l4)::numeric, 4) FROM feat_player_usage")
            ).one()
        assert first == second
