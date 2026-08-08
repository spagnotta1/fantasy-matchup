"""The business layer's SQL, executed against a real Postgres.

Unit tests cover the football; these cover the queries, which unit tests
cannot. Four things can only fail here:

* a column that does not exist, or that exists on three tables and resolves by
  join order — ``position`` is on the projection, the player dimension *and* the
  feature table, which is exactly the kind of ambiguity that produces tight ends
  graded against cornerback coverage;
* the defensive-form window, whose whole purpose is to produce a row for a week
  that **has not been played** — the case ``feat_defense_position_rolling``
  cannot serve and the reason this layer aggregates at read time;
* the published-run filter, which must ignore superseded and failed runs;
* the graceful-degradation path when a materialized view is missing, which is
  the ordinary aftermath of a ``pipeline full`` publish.

The warehouse and feature relations are built here as **stub tables** with the
real column names, rather than by running the pipeline. A test that needs a
1.8-million-row nflverse load to check a join is a test nobody runs.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from nflfp.services import repository
from nflfp.services.errors import DataUnavailable, UnknownScoringProfile

from .conftest import requires_db
from .warehouse_stub import GAME_ID, PLAYERS, SEASON, UPCOMING_WEEK, build_warehouse

pytestmark = [pytest.mark.integration, requires_db]

@pytest.fixture()
async def warehouse(async_db_session):
    """A stub warehouse with one published run, ready to query."""
    await build_warehouse(async_db_session)
    return async_db_session


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


class TestCalendarQueries:
    async def test_first_upcoming_week_is_the_one_without_a_result(self, warehouse):
        assert await repository.first_upcoming_week(warehouse, SEASON) == UPCOMING_WEEK

    async def test_latest_completed_week_is_the_one_before(self, warehouse):
        assert await repository.latest_completed_week(warehouse, SEASON) == UPCOMING_WEEK - 1

    async def test_published_weeks_lists_only_published_runs(self, warehouse):
        assert await repository.published_weeks(warehouse, SEASON) == [UPCOMING_WEEK]

    async def test_seasons_available(self, warehouse):
        assert await repository.seasons_available(warehouse) == [SEASON]


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


class TestFetchProjections:
    async def test_returns_the_slate_ordered_by_expectation(self, warehouse):
        rows = await repository.fetch_projections(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
        )
        assert len(rows) == len(PLAYERS)
        expectations = [row["expected_points"] for row in rows]
        assert expectations == sorted(expectations, reverse=True)

    async def test_the_scoring_profile_selects_a_different_row(self, warehouse):
        half = await repository.fetch_projections(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
        )
        ppr = await repository.fetch_projections(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="ppr"
        )
        assert half[0]["expected_points"] != ppr[0]["expected_points"]

    async def test_position_resolves_to_the_projection_not_the_dimension(self, warehouse):
        # `position` exists on projections, raw_players and feat_player_usage.
        # An unqualified reference would resolve by join order.
        rows = await repository.fetch_projections(
            warehouse,
            season=SEASON,
            week=UPCOMING_WEEK,
            scoring_profile="half_ppr",
            positions=["WR"],
        )
        assert [row["position"] for row in rows] == ["WR"]

    async def test_filters_compose(self, warehouse):
        rows = await repository.fetch_projections(
            warehouse,
            season=SEASON,
            week=UPCOMING_WEEK,
            scoring_profile="half_ppr",
            teams=["KC"],
            positions=["WR", "RB"],
        )
        assert {row["team"] for row in rows} == {"KC"}
        assert len(rows) == 2

    async def test_player_and_game_filters(self, warehouse):
        rows = await repository.fetch_projections(
            warehouse,
            season=SEASON,
            week=UPCOMING_WEEK,
            scoring_profile="half_ppr",
            player_ids=["00-0000001"],
        )
        assert len(rows) == 1 and rows[0]["player_id"] == "00-0000001"

        everyone = await repository.fetch_projections(
            warehouse,
            season=SEASON,
            week=UPCOMING_WEEK,
            scoring_profile="half_ppr",
            game_id=GAME_ID,
        )
        assert len(everyone) == len(PLAYERS)

    async def test_a_limit_returns_the_top_n(self, warehouse):
        rows = await repository.fetch_projections(
            warehouse,
            season=SEASON,
            week=UPCOMING_WEEK,
            scoring_profile="half_ppr",
            limit=2,
        )
        assert len(rows) == 2
        assert rows[0]["player_id"] == "00-0000001"

    async def test_carries_lineage_and_player_metadata(self, warehouse):
        rows = await repository.fetch_projections(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
        )
        row = rows[0]
        assert row["model_name"] == "shrinkage_eb"
        assert row["player_name"] == "Alpha Receiver"
        assert row["feature_schema_version"] == 1

    async def test_carries_usage_and_market_context(self, warehouse):
        rows = await repository.fetch_projections(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
        )
        row = rows[0]
        assert row["snap_pct_l4"] == pytest.approx(0.82)
        assert row["snap_pct_trend"] == pytest.approx(0.07)
        assert row["spread_source"] == "market"
        assert row["weather_source"] == "forecast"

    async def test_an_unknown_scoring_profile_is_refused(self, warehouse):
        with pytest.raises(UnknownScoringProfile):
            await repository.fetch_projections(
                warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="superflex"
            )

    async def test_count_matches_the_slate(self, warehouse):
        total = await repository.count_projections(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
        )
        assert total == len(PLAYERS)


class TestPublishedRunFiltering:
    async def test_only_published_runs_are_read(self, warehouse):
        await warehouse.execute(
            text("UPDATE model_runs SET status = 'superseded'")
        )
        await warehouse.commit()
        rows = await repository.fetch_projections(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
        )
        assert rows == []

    async def test_a_newer_published_run_replaces_the_old_one(self, warehouse):
        # Publishing is a flag, not a table swap. The old projections stay on
        # disk and must simply stop being read.
        await warehouse.execute(text("UPDATE model_runs SET status = 'superseded'"))
        new_run = (
            await warehouse.execute(
                text(
                    "INSERT INTO model_runs (model_name, model_version, algorithm,"
                    " season, week, status, feature_schema_version, published_at,"
                    " created_at, updated_at) VALUES ('shrinkage_eb', '2.0.0',"
                    " 'baseline', :s, :w, 'published', 1, now(), now(), now())"
                    " RETURNING id"
                ),
                {"s": SEASON, "w": UPCOMING_WEEK},
            )
        ).scalar_one()
        projection_id = (
            await warehouse.execute(
                text(
                    "INSERT INTO projections (model_run_id, player_id, season, week,"
                    " game_id, team, opponent, position, created_at, updated_at)"
                    " VALUES (:r, '00-0000001', :s, :w, :g, 'KC', 'BUF', 'WR', now(),"
                    " now()) RETURNING id"
                ),
                {"r": new_run, "s": SEASON, "w": UPCOMING_WEEK, "g": GAME_ID},
            )
        ).scalar_one()
        await warehouse.execute(
            text(
                "INSERT INTO projection_points (projection_id, scoring_profile,"
                " predicted_points, expected_points) VALUES (:p, 'half_ppr', 9.9, 9.9)"
            ),
            {"p": projection_id},
        )
        await warehouse.commit()

        rows = await repository.fetch_projections(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
        )
        assert len(rows) == 1
        assert rows[0]["model_version"] == "2.0.0"

    async def test_model_name_pins_the_run(self, warehouse):
        rows = await repository.fetch_projections(
            warehouse,
            season=SEASON,
            week=UPCOMING_WEEK,
            scoring_profile="half_ppr",
            model_name="something_else",
        )
        assert rows == []

    async def test_fetch_published_model(self, warehouse):
        run = await repository.fetch_published_model(
            warehouse, season=SEASON, week=UPCOMING_WEEK
        )
        assert run is not None and run["model_name"] == "shrinkage_eb"

    async def test_no_published_model_returns_none(self, warehouse):
        run = await repository.fetch_published_model(
            warehouse, season=SEASON, week=UPCOMING_WEEK + 1
        )
        assert run is None


# ---------------------------------------------------------------------------
# Defensive form — the reason this layer aggregates at read time
# ---------------------------------------------------------------------------


class TestDefensiveForm:
    async def test_produces_a_row_for_an_unplayed_week(self, warehouse):
        # feat_defense_position_rolling has no row for week 10, because week 10
        # has not been played. This is the query that exists to fix that.
        rows = await repository.fetch_defense_form(
            warehouse, season=SEASON, week=UPCOMING_WEEK
        )
        assert rows
        assert all(row["games_in_window"] == 4 for row in rows)

    async def test_uses_only_the_four_most_recent_completed_games(self, warehouse):
        # Nine weeks of history exist; the window must take four.
        rows = await repository.fetch_defense_form(
            warehouse, season=SEASON, week=UPCOMING_WEEK, defteams=["BUF"], positions=["WR"]
        )
        assert len(rows) == 1
        assert rows[0]["games_in_window"] == 4
        assert rows[0]["fp_allowed_l4"] == pytest.approx(26.0)

    async def test_never_reaches_the_week_being_projected(self, warehouse):
        # The lag rule, enforced end to end: adding a week-10 defensive row
        # must not change a week-10 window.
        before = await repository.fetch_defense_form(
            warehouse, season=SEASON, week=UPCOMING_WEEK, defteams=["BUF"], positions=["WR"]
        )
        await warehouse.execute(
            text(
                "INSERT INTO feat_defense_position (season, week, defteam, position,"
                " fp_allowed, players_faced, targets_allowed, carries_allowed,"
                " total_yards_allowed) VALUES (:s, :w, 'BUF', 'WR', 99.0, 3, 8, 12, 190)"
            ),
            {"s": SEASON, "w": UPCOMING_WEEK},
        )
        await warehouse.commit()
        after = await repository.fetch_defense_form(
            warehouse, season=SEASON, week=UPCOMING_WEEK, defteams=["BUF"], positions=["WR"]
        )
        assert after[0]["fp_allowed_l4"] == before[0]["fp_allowed_l4"]

    async def test_rank_one_is_the_toughest_defence(self, warehouse):
        await warehouse.execute(
            text(
                "INSERT INTO feat_defense_position (season, week, defteam, position,"
                " fp_allowed, players_faced, targets_allowed, carries_allowed,"
                " total_yards_allowed)"
                " SELECT :s, w, 'KC', 'WR', 4.0, 3, 8, 12, 190"
                " FROM generate_series(1, :n) AS w"
            ),
            {"s": SEASON, "n": UPCOMING_WEEK - 1},
        )
        await warehouse.commit()
        rows = await repository.fetch_defense_form(
            warehouse, season=SEASON, week=UPCOMING_WEEK, positions=["WR"]
        )
        by_team = {row["defteam"]: row for row in rows}
        # KC allows 4.0, BUF allows 26.0 — KC is the tougher matchup.
        assert by_team["KC"]["fp_allowed_rank"] == 1
        assert by_team["BUF"]["fp_allowed_rank"] == 2

    async def test_defensive_form_reaches_the_projection_query(self, warehouse):
        rows = await repository.fetch_projections(
            warehouse,
            season=SEASON,
            week=UPCOMING_WEEK,
            scoring_profile="half_ppr",
            positions=["WR"],
        )
        row = rows[0]
        assert row["opp_defense_rank_vs_position"] is not None
        assert row["opp_defense_games_in_window"] == 4
        assert row["opp_fp_allowed_vs_position_l4"] == pytest.approx(26.0)
        assert row["opp_pace_l4"] == pytest.approx(62.0)

    async def test_week_one_has_no_defensive_history(self, warehouse):
        rows = await repository.fetch_defense_form(warehouse, season=SEASON, week=1)
        assert rows == []


# ---------------------------------------------------------------------------
# Players, teams, games
# ---------------------------------------------------------------------------


class TestPlayerQueries:
    async def test_fetch_player(self, warehouse):
        row = await repository.fetch_player(warehouse, "00-0000001")
        assert row is not None and row["display_name"] == "Alpha Receiver"

    async def test_missing_player_is_none(self, warehouse):
        assert await repository.fetch_player(warehouse, "00-9999999") is None

    async def test_search_matches_a_substring(self, warehouse):
        rows = await repository.search_players(warehouse, query="Receiver")
        assert [row["player_id"] for row in rows] == ["00-0000001"]

    async def test_search_prefers_a_prefix_match(self, warehouse):
        rows = await repository.search_players(warehouse, query="a")
        assert rows[0]["display_name"].lower().startswith("a")

    async def test_search_can_filter_by_position(self, warehouse):
        rows = await repository.search_players(warehouse, query="a", positions=["QB"])
        assert {row["position"] for row in rows} == {"QB"}

    async def test_search_rejects_an_empty_term(self, warehouse):
        with pytest.raises(ValueError):
            await repository.search_players(warehouse, query="   ")

    async def test_history_joins_the_stored_projection(self, warehouse):
        rows = await repository.fetch_player_history(
            warehouse, player_id="00-0000001", scoring_profile="half_ppr", limit=5
        )
        assert len(rows) == 5
        # Newest first.
        assert rows[0]["week"] > rows[-1]["week"]
        assert rows[0]["actual_points"] is not None

    async def test_history_respects_the_scoring_profile(self, warehouse):
        half = await repository.fetch_player_history(
            warehouse, player_id="00-0000001", scoring_profile="half_ppr", limit=1
        )
        ppr = await repository.fetch_player_history(
            warehouse, player_id="00-0000001", scoring_profile="ppr", limit=1
        )
        assert half[0]["actual_points"] != ppr[0]["actual_points"]


class TestTeamAndGameQueries:
    async def test_fetch_teams(self, warehouse):
        rows = await repository.fetch_teams(warehouse)
        assert [row["team_abbr"] for row in rows] == ["BUF", "KC"]

    async def test_games_collapse_to_one_row_per_game(self, warehouse):
        rows = await repository.fetch_games(
            warehouse, season=SEASON, week=UPCOMING_WEEK
        )
        assert len(rows) == 1
        assert rows[0]["home_team"] == "BUF" and rows[0]["away_team"] == "KC"
        assert rows[0]["is_upcoming"] is True

    async def test_completed_games_are_not_upcoming(self, warehouse):
        rows = await repository.fetch_games(warehouse, season=SEASON, week=1)
        assert rows[0]["is_upcoming"] is False
        assert rows[0]["home_score"] == 24

    async def test_game_context_is_per_team(self, warehouse):
        rows = await repository.fetch_game_context(
            warehouse, season=SEASON, week=UPCOMING_WEEK, game_id=GAME_ID
        )
        assert {row["team"] for row in rows} == {"KC", "BUF"}


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


class TestMissingRelations:
    async def test_a_dropped_matview_names_itself_and_the_fix(self, warehouse):
        # A `pipeline full` publish drops raw_* with CASCADE, taking dependent
        # matviews with it. That must produce an actionable error, not
        # `relation "feat_player_usage" does not exist` from 400 lines of SQL.
        await warehouse.execute(text("DROP TABLE feat_player_usage"))
        await warehouse.commit()
        repository.clear_relation_cache()

        with pytest.raises(DataUnavailable) as caught:
            await repository.fetch_projections(
                warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
            )
        assert caught.value.relation == "feat_player_usage"
        assert "build_features" in caught.value.remedy

    async def test_the_remedy_matches_the_missing_relation(self, warehouse):
        # A matview needs build_features; a warehouse view needs the pipeline;
        # an application table needs a migration. The wrong command is barely
        # better than no command.
        assert "build_features" in DataUnavailable("feat_player_usage").remedy
        assert "pipeline full" in DataUnavailable("game_team").remedy
        assert "pipeline full" in DataUnavailable("raw_players").remedy
        assert "alembic" in DataUnavailable("model_runs").remedy

    async def test_an_unbuilt_warehouse_is_actionable_on_every_endpoint(
        self, warehouse
    ):
        # The first-run failure mode: the default week resolves against
        # upcoming_games, so before the pipeline has run an unguarded version
        # turns every endpoint into an unexplained 500 at once.
        from nflfp.services import catalog

        await warehouse.execute(text("DROP VIEW upcoming_games"))
        await warehouse.commit()
        repository.clear_relation_cache()

        with pytest.raises(DataUnavailable) as caught:
            await catalog.resolve_window(warehouse, season=SEASON)
        assert caught.value.relation == "upcoming_games"
        assert "pipeline" in caught.value.remedy
        repository.clear_relation_cache()

    async def test_a_missing_team_dimension_degrades_rather_than_fails(self, warehouse):
        await warehouse.execute(text("DROP TABLE raw_teams"))
        await warehouse.commit()
        repository.clear_relation_cache()
        assert await repository.fetch_teams(warehouse) == []

    async def test_relation_existence_is_cached_but_clearable(self, warehouse):
        assert await repository.relation_exists(warehouse, "projections") is True
        repository.clear_relation_cache()
        assert await repository.relation_exists(warehouse, "nonexistent_table") is False
