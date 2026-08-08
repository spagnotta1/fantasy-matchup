"""The business layer end to end, against a real Postgres.

These exercise the composition — repository plus assembly plus grading — which
is where the layer's contract actually lives. Two behaviours matter most and
are tested first:

* **an unpublished week is empty, not an error.** The projection job not having
  run is an operational state a UI should render as "projections coming
  Thursday", and a 404 makes that indistinguishable from a bad URL.
* **"this week" means the upcoming week.** A fantasy app is read on Thursday to
  decide a lineup, so a defaulted request must resolve forward, not backward.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from nflfp.services import advice, catalog, matchups, players, projections
from nflfp.services.errors import InvalidRequest, NotFound

from .conftest import requires_db
from .warehouse_stub import GAME_ID, PLAYERS, SEASON, UPCOMING_WEEK, build_warehouse

pytestmark = [pytest.mark.integration, requires_db]


@pytest.fixture()
async def warehouse(async_db_session):
    await build_warehouse(async_db_session)
    return async_db_session


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class TestCatalog:
    async def test_a_defaulted_week_resolves_forward(self, warehouse):
        window = await catalog.resolve_window(warehouse, season=SEASON)
        assert window.week == UPCOMING_WEEK
        assert window.resolution == "upcoming"
        assert window.is_upcoming

    async def test_an_explicit_week_is_honoured_and_labelled(self, warehouse):
        window = await catalog.resolve_window(warehouse, season=SEASON, week=3)
        assert window.week == 3
        assert window.resolution == "explicit"
        assert not window.is_upcoming

    async def test_falls_back_to_history_once_the_season_is_over(self, warehouse):
        await warehouse.execute(
            text("UPDATE game_team SET team_score = 20, opp_score = 17 "
                 "WHERE team_score IS NULL")
        )
        await warehouse.commit()
        window = await catalog.resolve_window(warehouse, season=SEASON)
        assert window.resolution == "latest_completed"
        assert not window.is_upcoming

    async def test_an_unknown_season_is_not_found(self, warehouse):
        with pytest.raises(NotFound):
            await catalog.resolve_window(warehouse, season=1998)

    async def test_an_impossible_week_is_rejected(self, warehouse):
        with pytest.raises(InvalidRequest):
            await catalog.resolve_window(warehouse, season=SEASON, week=99)

    async def test_teams_and_index(self, warehouse):
        teams = await catalog.list_teams(warehouse)
        assert {t.abbr for t in teams} == {"KC", "BUF"}
        index = await catalog.team_index(warehouse)
        assert index["KC"].nickname == "Chiefs"

    async def test_a_missing_team_is_not_found(self, warehouse):
        with pytest.raises(NotFound):
            await catalog.get_team(warehouse, "XXX")

    async def test_an_unknown_scoring_profile_is_refused_not_defaulted(self):
        # A user who asked for PPR and quietly got half-PPR would make lineup
        # decisions on numbers they did not ask for.
        from nflfp.services.errors import UnknownScoringProfile

        with pytest.raises(UnknownScoringProfile):
            catalog.resolve_scoring_profile("superflex")

    async def test_published_weeks_drive_a_week_picker(self, warehouse):
        assert await catalog.list_published_weeks(warehouse, SEASON) == (UPCOMING_WEEK,)


# ---------------------------------------------------------------------------
# Slate
# ---------------------------------------------------------------------------


class TestSlate:
    async def test_returns_a_ranked_tiered_board(self, warehouse):
        slate, window = await projections.get_slate(
            warehouse, season=SEASON, scoring_profile="half_ppr"
        )
        assert window.week == UPCOMING_WEEK
        assert len(slate) == len(PLAYERS)
        assert [e.rank for e in slate.entries] == [1, 2, 3, 4]
        assert all(e.tier >= 1 for e in slate.entries)
        assert slate.model is not None and slate.model.model_name == "shrinkage_eb"
        assert slate.total == len(PLAYERS)

    async def test_the_board_is_ordered_by_the_calibrated_expectation(self, warehouse):
        slate, _ = await projections.get_slate(warehouse, season=SEASON)
        headlines = [e.projection.points.headline for e in slate.entries]
        assert headlines == sorted(headlines, reverse=True)
        assert slate.entries[0].projection.player.name == "Alpha Receiver"

    async def test_context_reaches_the_domain_object(self, warehouse):
        slate, _ = await projections.get_slate(warehouse, season=SEASON)
        top = slate.entries[0].projection
        assert top.usage.snap_pct_l4 == pytest.approx(0.82)
        assert top.matchup is not None and top.matchup.grade.graded
        assert top.game is not None and top.game.spread_source == "market"
        assert top.weather is not None and top.weather.source == "forecast"
        assert top.model is not None

    async def test_context_is_never_marked_applied(self, warehouse):
        slate, _ = await projections.get_slate(warehouse, season=SEASON)
        top = slate.entries[0].projection
        assert top.game is not None and not top.game.applied_to_projection
        assert top.weather is not None and not top.weather.applied_to_projection

    async def test_an_unpublished_week_is_empty_not_an_error(self, warehouse):
        slate, window = await projections.get_slate(
            warehouse, season=SEASON, week=UPCOMING_WEEK + 1
        )
        assert window.week == UPCOMING_WEEK + 1
        assert len(slate) == 0
        assert slate.model is None  # the flag a UI branches on

    async def test_position_rankings_are_within_position(self, warehouse):
        slate, _ = await projections.get_position_rankings(
            warehouse, position="WR", season=SEASON
        )
        assert all(e.projection.player.position == "WR" for e in slate.entries)
        assert [e.positional_rank for e in slate.entries] == [1]

    async def test_an_unsupported_position_explains_itself(self, warehouse):
        with pytest.raises(InvalidRequest, match="K"):
            await projections.get_slate(warehouse, season=SEASON, positions=["K"])

    async def test_paging_bounds_are_enforced(self, warehouse):
        with pytest.raises(InvalidRequest):
            await projections.get_slate(warehouse, season=SEASON, limit=10_000)
        with pytest.raises(InvalidRequest):
            await projections.get_slate(warehouse, season=SEASON, offset=-1)

    async def test_a_single_projection_is_found(self, warehouse):
        projection = await projections.get_projection(
            warehouse, player_id="00-0000001", season=SEASON
        )
        assert projection.player.name == "Alpha Receiver"
        assert projection.points.scoring_profile == "half_ppr"

    async def test_a_missing_single_projection_raises(self, warehouse):
        with pytest.raises(NotFound):
            await projections.get_projection(
                warehouse, player_id="00-9999999", season=SEASON
            )

    async def test_scoring_profile_changes_the_numbers(self, warehouse):
        half, _ = await projections.get_slate(
            warehouse, season=SEASON, scoring_profile="half_ppr"
        )
        ppr, _ = await projections.get_slate(
            warehouse, season=SEASON, scoring_profile="ppr"
        )
        assert (
            half.entries[0].projection.points.headline
            != ppr.entries[0].projection.points.headline
        )


# ---------------------------------------------------------------------------
# Player profile
# ---------------------------------------------------------------------------


class TestPlayers:
    async def test_search_finds_a_player(self, warehouse):
        found = await players.search(warehouse, query="Alpha")
        assert [p.player_id for p in found] == ["00-0000001"]

    async def test_a_one_character_search_is_refused(self, warehouse):
        with pytest.raises(InvalidRequest):
            await players.search(warehouse, query="a")

    async def test_profile_assembles_projection_and_history(self, warehouse):
        profile = await players.get_profile(
            warehouse, player_id="00-0000001", season=SEASON
        )
        assert profile.player.name == "Alpha Receiver"
        assert profile.current is not None
        assert len(profile.history) > 0
        assert profile.trend.games == len(profile.history)
        assert profile.window.week == UPCOMING_WEEK

    async def test_a_profile_renders_without_a_projection(self, warehouse):
        # A bye week, or a run that has not been published, must not 404 a page
        # that has a full season of history to show.
        profile = await players.get_profile(
            warehouse, player_id="00-0000001", season=SEASON, week=UPCOMING_WEEK + 1
        )
        assert profile.current is None
        assert len(profile.history) > 0

    async def test_an_unknown_player_is_not_found(self, warehouse):
        with pytest.raises(NotFound):
            await players.get_profile(warehouse, player_id="00-9999999")

    async def test_history_accuracy_covers_only_graded_weeks(self, warehouse):
        # No projections were stored for the completed weeks in the stub, so
        # accuracy must report zero graded games rather than a flattering zero
        # error.
        _, trend = await players.get_history(
            warehouse, player_id="00-0000001", scoring_profile="half_ppr"
        )
        assert trend.games > 0
        assert trend.graded_games == 0
        assert trend.mean_absolute_error is None


# ---------------------------------------------------------------------------
# Matchups and teams
# ---------------------------------------------------------------------------


class TestMatchups:
    async def test_a_game_is_analysed_from_both_sides(self, warehouse):
        analysis = await matchups.get_matchup(
            warehouse, game_id=GAME_ID, season=SEASON
        )
        assert analysis.home.abbr == "BUF" and analysis.away.abbr == "KC"
        assert set(analysis.defense) == {"BUF", "KC"}
        assert analysis.game is not None
        assert analysis.top_projections

    async def test_defensive_splits_are_per_position(self, warehouse):
        analysis = await matchups.get_matchup(
            warehouse, game_id=GAME_ID, season=SEASON
        )
        buffalo = {m.position: m for m in analysis.defense["BUF"]}
        # BUF allows 26.0 to WRs and 6.0 to RBs. "Good defence" is not one
        # number, and the split is most of what a matchup is worth.
        assert buffalo["WR"].fp_allowed_l4 > buffalo["RB"].fp_allowed_l4
        assert buffalo["WR"].grade.graded

    async def test_an_unknown_game_is_not_found(self, warehouse):
        with pytest.raises(NotFound):
            await matchups.get_matchup(warehouse, game_id="nope", season=SEASON)

    async def test_defense_rankings_cover_every_defence_with_history(self, warehouse):
        rankings, window = await matchups.get_defense_rankings(
            warehouse, season=SEASON
        )
        assert window.week == UPCOMING_WEEK
        assert set(rankings) == {"BUF", "KC"}

    async def test_the_schedule_lists_one_row_per_game(self, warehouse):
        games, window = await matchups.list_matchups(warehouse, season=SEASON)
        assert len(games) == 1
        assert window.week == UPCOMING_WEEK

    async def test_team_outlook_sums_only_projected_players(self, warehouse):
        outlook = await matchups.get_team_outlook(
            warehouse, team="KC", season=SEASON, scoring_profile="half_ppr"
        )
        assert outlook.team.nickname == "Chiefs"
        assert len(outlook.players) == 2
        expected = sum(
            e.projection.points.headline or 0.0 for e in outlook.players
        )
        assert outlook.projected_points == pytest.approx(expected)
        assert outlook.game is not None


# ---------------------------------------------------------------------------
# Advice
# ---------------------------------------------------------------------------


class TestAdvice:
    async def test_start_sit_end_to_end(self, warehouse):
        result = await advice.get_start_sit(
            warehouse,
            player_a="00-0000001",
            player_b="00-0000003",
            season=SEASON,
        )
        assert 0.0 <= result.win_probability <= 1.0
        assert result.rationale
        # Both players are in the same game, so independence does not hold and
        # the caveat must say so.
        assert result.caveats

    async def test_start_sit_names_the_missing_player(self, warehouse):
        with pytest.raises(NotFound, match="00-9999999"):
            await advice.get_start_sit(
                warehouse, player_a="00-0000001", player_b="00-9999999", season=SEASON
            )

    async def test_an_injury_designation_reaches_the_caveats(self, warehouse):
        # Bravo Back is Questionable in the stub warehouse.
        result = await advice.get_start_sit(
            warehouse, player_a="00-0000002", player_b="00-0000004", season=SEASON
        )
        assert any("Questionable" in caveat for caveat in result.caveats)

    async def test_comparison_orders_and_pairs_consecutively(self, warehouse):
        comparison = await advice.compare_players(
            warehouse,
            player_ids=[p[0] for p in PLAYERS],
            season=SEASON,
        )
        expectations = [e.expected for e in comparison.entries]
        assert expectations == sorted(expectations, reverse=True)
        assert len(comparison.head_to_head) == len(PLAYERS) - 1

    async def test_comparison_needs_two_distinct_players(self, warehouse):
        with pytest.raises(InvalidRequest):
            await advice.compare_players(
                warehouse, player_ids=["00-0000001", "00-0000001"], season=SEASON
            )

    async def test_comparison_is_bounded(self, warehouse):
        with pytest.raises(InvalidRequest):
            await advice.compare_players(
                warehouse, player_ids=[f"id-{i}" for i in range(20)], season=SEASON
            )
