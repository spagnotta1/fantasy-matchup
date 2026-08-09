"""The REST API, against a real Postgres.

The load-bearing tests here are the **provenance contract** ones. A projection
screen mixes model output, analysis derived above the model, and context the
model does not use, and the whole point of Layer 5 is that those stay
distinguishable on the wire. If they blur, every honesty property the layers
below worked for is lost at the last step.

The other group worth reading is :class:`TestExtensionPoints`, which proves the
readiness claims are wired rather than promised: writing an injury multiplier
into the database flips ``applied_to_projection`` with no code change, and a
kicker request answers with a reason instead of a shrug.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from nflfp.api.main import API_PREFIX, create_app
from nflfp.api.provenance import Provenance
from nflfp.db.engine import get_db_session

from .conftest import requires_db
from .warehouse_stub import GAME_ID, PLAYERS, SEASON, UPCOMING_WEEK, build_warehouse

pytestmark = [pytest.mark.integration, requires_db]


@pytest.fixture()
async def client(async_db_session):
    """A test client whose requests run against the throwaway schema.

    The session dependency is overridden rather than the engine, so every
    request in a test shares one transaction against one schema — which is what
    lets a test mutate the warehouse mid-test and see the effect through HTTP.
    """
    from httpx import ASGITransport, AsyncClient

    await build_warehouse(async_db_session)

    app = create_app()

    async def _session_override():
        yield async_db_session

    app.dependency_overrides[get_db_session] = _session_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http

    app.dependency_overrides.clear()


def url(path: str) -> str:
    return f"{API_PREFIX}{path}"


async def first_projection(client) -> dict:
    response = await client.get(url("/projections"), params={"season": SEASON})
    assert response.status_code == 200
    return response.json()["data"][0]["projection"]


# ---------------------------------------------------------------------------
# The provenance contract
# ---------------------------------------------------------------------------


class TestProvenanceContract:
    async def test_a_projection_has_all_three_blocks(self, client):
        # Always present, even when empty, so a client branches on values
        # rather than on whether a key exists.
        projection = await first_projection(client)
        assert set(projection) >= {"prediction", "matchup", "usage", "context"}

    async def test_each_block_is_labelled(self, client):
        projection = await first_projection(client)
        assert projection["prediction"]["provenance"] == Provenance.MODEL.value
        assert projection["matchup"]["provenance"] == Provenance.DERIVED.value
        assert projection["usage"]["provenance"] == Provenance.DERIVED.value
        assert projection["context"]["provenance"] == Provenance.CONTEXT.value

    async def test_model_output_lives_only_in_the_prediction_block(self, client):
        # Points and components are the model's; nothing else may carry them,
        # or a client could read a projected total off a context panel.
        projection = await first_projection(client)
        assert "points" in projection["prediction"]
        assert "components" in projection["prediction"]
        assert "points" not in projection["matchup"]
        assert "points" not in projection["context"]

    async def test_derived_matchup_declares_it_is_not_an_adjustment(self, client):
        # The grade is real analysis the model never consumed. Presenting it
        # without this flag would imply the projection already reflects it.
        projection = await first_projection(client)
        matchup = projection["matchup"]
        assert matchup["applied_to_projection"] is False
        assert matchup["source"] == "feat_defense_position"

    async def test_context_declares_it_is_not_applied_and_says_why(self, client):
        projection = await first_projection(client)
        context = projection["context"]
        for block in ("game", "weather", "injury"):
            if context[block] is not None:
                assert context[block]["applied_to_projection"] is False
                assert context[block]["unapplied_reason"]

    async def test_the_headline_number_is_the_calibrated_mean(self, client):
        # `predicted` is conditionally biased by construction and must never be
        # what a client displays.
        points = (await first_projection(client))["prediction"]["points"]
        assert points["expected"] is not None
        assert points["predicted"] != points["expected"]

    async def test_history_is_labelled_as_an_outcome_not_a_prediction(self, client):
        response = await client.get(url(f"/players/{PLAYERS[0][0]}/history"))
        assert response.status_code == 200
        weeks = response.json()["data"]
        assert weeks
        assert all(week["provenance"] == Provenance.ACTUAL.value for week in weeks)

    async def test_the_legend_covers_every_label_in_use(self, client):
        response = await client.get(url("/meta/provenance"))
        legend = response.json()["data"]
        assert set(legend) == {p.value for p in Provenance}
        assert all(text.strip() for text in legend.values())

    async def test_defensive_analysis_is_derived_everywhere_it_appears(self, client):
        response = await client.get(
            url("/defense-rankings"), params={"season": SEASON}
        )
        assert response.status_code == 200
        for entries in response.json()["data"].values():
            assert all(e["provenance"] == Provenance.DERIVED.value for e in entries)


# ---------------------------------------------------------------------------
# Extension points — the readiness claims, checked
# ---------------------------------------------------------------------------


class TestExtensionPoints:
    async def test_an_injury_multiplier_flips_applied_with_no_code_change(
        self, client, async_db_session
    ):
        # The readiness claim, made checkable: the column already exists and is
        # already read. A future engine that fits an injury adjustment writes
        # it, and the same field a client renders starts meaning something
        # different — no schema version, no client change.
        before = await first_projection(client)
        assert before["context"]["injury"] is None or (
            before["context"]["injury"]["applied_to_projection"] is False
        )

        await async_db_session.execute(
            text(
                "UPDATE projections SET injury_multiplier = 0.75 "
                "WHERE player_id = :p AND season = :s AND week = :w"
            ),
            {"p": PLAYERS[0][0], "s": SEASON, "w": UPCOMING_WEEK},
        )
        await async_db_session.commit()

        after = await first_projection(client)
        injury = after["context"]["injury"]
        assert injury is not None
        assert injury["applied_to_projection"] is True
        assert injury["multiplier"] == pytest.approx(0.75)
        assert injury["unapplied_reason"] is None

    async def test_a_weather_multiplier_flips_applied_too(
        self, client, async_db_session
    ):
        await async_db_session.execute(
            text(
                "UPDATE projections SET weather_multiplier = 0.92 "
                "WHERE season = :s AND week = :w"
            ),
            {"s": SEASON, "w": UPCOMING_WEEK},
        )
        await async_db_session.commit()

        weather = (await first_projection(client))["context"]["weather"]
        assert weather is not None
        assert weather["applied_to_projection"] is True
        assert weather["multiplier"] == pytest.approx(0.92)

    async def test_positions_endpoint_declares_projected_and_planned(self, client):
        response = await client.get(url("/meta/positions"))
        assert response.status_code == 200
        by_position = {entry["position"]: entry for entry in response.json()["data"]}
        assert {"QB", "RB", "WR", "TE"} <= set(by_position)
        assert all(by_position[p]["projected"] for p in ("QB", "RB", "WR", "TE"))
        # The readiness story for K/DST is data a client can render, not a
        # sentence in a changelog.
        for position in ("K", "DST"):
            entry = by_position[position]
            assert entry["status"] == "planned"
            assert entry["projected"] is False
            assert entry["reason"]
            assert entry["blocked_on"]

    async def test_requesting_a_planned_position_explains_itself(self, client):
        response = await client.get(url("/rankings/K"), params={"season": SEASON})
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "invalid_request"
        assert "Kicker" in body["message"]
        assert "blocked on" in body["message"].lower()

    async def test_an_unrecognised_position_is_a_different_error(self, client):
        response = await client.get(url("/rankings/ZZ"), params={"season": SEASON})
        assert response.status_code == 422
        assert "unrecognised" in response.json()["message"]

    async def test_search_accepts_a_planned_position(self, client):
        # Looking up a kicker's name is reasonable even though nothing
        # projects them.
        response = await client.get(
            url("/search"), params={"q": "Alpha", "positions": ["K"]}
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# The frozen foundation
# ---------------------------------------------------------------------------


class TestFrozenFoundation:
    async def test_meta_model_publishes_what_was_measured(self, client):
        response = await client.get(url("/meta/model"))
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["frozen"] is True
        assert data["model"] == "shrinkage_eb"
        assert data["phase"] == "3b"

        coverage = data["validation"]["interval_coverage"]["p10_p90"]
        assert coverage["observed"] == pytest.approx(0.803)
        assert coverage["nominal"] == pytest.approx(0.80)

    async def test_it_publishes_the_bar_a_successor_must_clear(self, client):
        data = (await client.get(url("/meta/model"))).json()["data"]
        assert data["acceptance"]["requires_walk_forward"] is True
        assert data["acceptance"]["must_beat_baseline"] is True
        assert {bar["position"] for bar in data["baseline_bar"]} == {
            "QB", "RB", "WR", "TE"
        }

    async def test_it_states_what_the_model_excludes(self, client):
        data = (await client.get(url("/meta/model"))).json()["data"]
        excluded = " ".join(data["excluded_inputs"]).lower()
        assert "market" in excluded
        assert "weather" in excluded

    async def test_the_run_serving_projections_is_reported(self, client):
        response = await client.get(url("/projections"), params={"season": SEASON})
        model = response.json()["meta"]["model"]
        assert model["model_name"] == "shrinkage_eb"
        assert model["run_id"] > 0


# ---------------------------------------------------------------------------
# Ordinary endpoint behaviour
# ---------------------------------------------------------------------------


class TestProjectionEndpoints:
    async def test_the_board_is_ranked_and_tiered(self, client):
        response = await client.get(url("/projections"), params={"season": SEASON})
        assert response.status_code == 200
        entries = response.json()["data"]
        assert [e["rank"] for e in entries] == [1, 2, 3, 4]
        assert all(e["tier"] >= 1 for e in entries)

    async def test_meta_reports_the_resolved_window(self, client):
        response = await client.get(url("/projections"), params={"season": SEASON})
        window = response.json()["meta"]["window"]
        assert window["week"] == UPCOMING_WEEK
        assert window["resolution"] == "upcoming"
        assert window["is_upcoming"] is True

    async def test_pagination_metadata(self, client):
        response = await client.get(
            url("/projections"), params={"season": SEASON, "limit": 2}
        )
        page = response.json()["meta"]["page"]
        assert page["total"] == len(PLAYERS)
        assert page["returned"] == 2
        assert page["limit"] == 2

    async def test_an_unpublished_week_is_an_empty_board_with_a_notice(self, client):
        response = await client.get(
            url("/projections"), params={"season": SEASON, "week": UPCOMING_WEEK + 1}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["meta"]["model"] is None
        assert any("not an error" in n for n in body["meta"]["notices"])

    async def test_a_missing_projection_is_a_404_with_a_code(self, client):
        response = await client.get(
            url("/projections/00-9999999"), params={"season": SEASON}
        )
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    async def test_an_unknown_scoring_profile_is_refused(self, client):
        response = await client.get(
            url("/projections"), params={"season": SEASON, "scoring_profile": "superflex"}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "unknown_scoring_profile"
        assert response.json()["field"] == "scoring_profile"

    async def test_query_bounds_are_enforced_at_the_edge(self, client):
        assert (
            await client.get(url("/projections"), params={"season": SEASON, "limit": 9999})
        ).status_code == 422
        assert (
            await client.get(url("/projections"), params={"season": SEASON, "week": 99})
        ).status_code == 422

    async def test_position_rankings(self, client):
        response = await client.get(url("/rankings/WR"), params={"season": SEASON})
        entries = response.json()["data"]
        assert all(
            e["projection"]["player"]["position"] == "WR" for e in entries
        )
        assert [e["positional_rank"] for e in entries] == [1]


class TestPlayerEndpoints:
    async def test_search(self, client):
        response = await client.get(url("/search"), params={"q": "Alpha"})
        assert response.status_code == 200
        assert response.json()["data"][0]["name"] == "Alpha Receiver"

    async def test_a_short_search_term_is_refused_by_the_schema(self, client):
        assert (await client.get(url("/search"), params={"q": "a"})).status_code == 422

    async def test_profile_assembles_projection_and_history(self, client):
        response = await client.get(
            url(f"/players/{PLAYERS[0][0]}/profile"), params={"season": SEASON}
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["current"] is not None
        assert data["history"]
        assert data["trend"]["games"] > 0

    async def test_a_profile_without_a_projection_still_renders(self, client):
        response = await client.get(
            url(f"/players/{PLAYERS[0][0]}/profile"),
            params={"season": SEASON, "week": UPCOMING_WEEK + 1},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["current"] is None
        assert body["meta"]["notices"]

    async def test_accuracy_is_absent_rather_than_flattering(self, client):
        # No stored projections cover the stub's completed weeks.
        response = await client.get(
            url(f"/players/{PLAYERS[0][0]}/profile"), params={"season": SEASON}
        )
        trend = response.json()["data"]["trend"]
        assert trend["graded_games"] == 0
        assert trend["mean_absolute_error"] is None

    async def test_an_unknown_player_is_a_404(self, client):
        assert (
            await client.get(url("/players/00-9999999/profile"))
        ).status_code == 404


class TestMatchupEndpoints:
    async def test_a_game_is_analysed_from_both_sides(self, client):
        response = await client.get(
            url(f"/matchups/{GAME_ID}"), params={"season": SEASON}
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert set(data["defense"]) == {"KC", "BUF"}
        assert data["top_projections"]

    async def test_defensive_splits_differ_by_position(self, client):
        data = (
            await client.get(url(f"/matchups/{GAME_ID}"), params={"season": SEASON})
        ).json()["data"]
        buffalo = {m["position"]: m for m in data["defense"]["BUF"]}
        assert buffalo["WR"]["fp_allowed_l4"] > buffalo["RB"]["fp_allowed_l4"]

    async def test_an_unknown_game_is_a_404(self, client):
        assert (
            await client.get(url("/matchups/nope"), params={"season": SEASON})
        ).status_code == 404

    async def test_games_lists_one_row_per_game(self, client):
        response = await client.get(url("/games"), params={"season": SEASON})
        games = response.json()["data"]
        assert len(games) == 1
        assert games[0]["is_upcoming"] is True

    async def test_team_outlook_labels_its_total_honestly(self, client):
        response = await client.get(
            url("/teams/KC/outlook"), params={"season": SEASON}
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["players"]) == 2
        assert data["projected_points"] > 0
        assert data["context"]["game"] is not None


class TestAdviceEndpoints:
    async def test_start_sit_returns_a_probability_and_caveats(self, client):
        response = await client.get(
            url("/start-sit"),
            params={
                "season": SEASON,
                "player_a": PLAYERS[0][0],
                "player_b": PLAYERS[2][0],
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert 0.0 <= data["win_probability"] <= 1.0
        assert data["verdict"] in ("clear", "lean", "toss_up")
        assert data["rationale"]
        # Same game, so independence does not hold and it must say so.
        assert data["caveats"]

    async def test_a_toss_up_names_nobody(self, client, async_db_session):
        # Force two near-identical distributions.
        await async_db_session.execute(
            text(
                "UPDATE projection_points SET expected_points = 12.0, "
                "predicted_points = 12.0, floor_points = 5.0, p25_points = 8.0, "
                "median_points = 11.5, p75_points = 15.0, ceiling_points = 21.0"
            )
        )
        await async_db_session.commit()
        response = await client.get(
            url("/start-sit"),
            params={
                "season": SEASON,
                "player_a": PLAYERS[0][0],
                "player_b": PLAYERS[2][0],
            },
        )
        data = response.json()["data"]
        assert data["verdict"] == "toss_up"
        assert data["recommended"] is None

    async def test_comparing_a_player_with_themselves_is_refused(self, client):
        response = await client.get(
            url("/start-sit"),
            params={
                "season": SEASON,
                "player_a": PLAYERS[0][0],
                "player_b": PLAYERS[0][0],
            },
        )
        assert response.status_code == 422

    async def test_compare_orders_and_pairs(self, client):
        response = await client.get(
            url("/compare"),
            params={"season": SEASON, "player_ids": [p[0] for p in PLAYERS]},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        expectations = [e["expected"] for e in data["entries"]]
        assert expectations == sorted(expectations, reverse=True)
        assert len(data["head_to_head"]) == len(PLAYERS) - 1

    async def test_compare_is_bounded(self, client):
        response = await client.get(
            url("/compare"),
            params={"season": SEASON, "player_ids": [f"id-{i}" for i in range(20)]},
        )
        assert response.status_code == 422


class TestPlayerIndex:
    """`GET /players` — the listing search cannot replace, because search
    needs a name and "who plays for KC?" has none."""

    async def test_browses_the_dimension_alphabetically(self, client):
        response = await client.get(url("/players"))
        assert response.status_code == 200
        names = [player["name"] for player in response.json()["data"]]
        assert names == sorted(names)

    async def test_reports_the_total_before_paging(self, client):
        """So a client renders "showing 2 of 4" without a second call."""
        body = (await client.get(url("/players"), params={"limit": 2})).json()
        assert len(body["data"]) == 2
        assert body["meta"]["page"]["total"] == len(PLAYERS)
        assert body["meta"]["page"]["returned"] == 2

    async def test_paging_does_not_skip_or_repeat(self, client):
        """The reason ordering is by name and not by anything derived: a
        listing that reorders itself between pages makes paging lose rows."""
        first = await client.get(url("/players"), params={"limit": 2, "offset": 0})
        second = await client.get(url("/players"), params={"limit": 2, "offset": 2})
        ids = [p["player_id"] for p in first.json()["data"] + second.json()["data"]]
        assert len(set(ids)) == len(PLAYERS)

    async def test_filters_by_team(self, client):
        body = (await client.get(url("/players"), params={"teams": "KC"})).json()
        assert {player["team"] for player in body["data"]} == {"KC"}

    async def test_filters_by_position(self, client):
        body = (await client.get(url("/players"), params={"positions": "WR"})).json()
        assert {player["position"] for player in body["data"]} == {"WR"}

    async def test_an_unprojected_position_is_listed_not_refused(self, client):
        """Unlike /rankings/K. Listing a kicker is reasonable; only inventing
        a projection for one is not."""
        response = await client.get(url("/players"), params={"positions": "K"})
        assert response.status_code == 200

    async def test_an_unrecognised_position_is_a_422(self, client):
        response = await client.get(url("/players"), params={"positions": "QUARTERBACK"})
        assert response.status_code == 422
        assert "unrecognised position" in response.json()["message"]


class TestWeekSummary:
    """`GET /weeks/{week}` — the endpoint that distinguishes "no games" from
    "the projection job has not run".

    Every request here names the season explicitly. Omitting it resolves the
    week against ``current_season()``, which rolls over in March — so a suite
    that relied on the default passed until the league year moved past the stub
    warehouse's ``SEASON`` and then failed on a calendar date rather than on a
    code change. The endpoint's defaulting behaviour is covered by the slate
    tests, which is the right place for it.
    """

    async def week(self, client, week: int) -> dict:
        response = await client.get(url(f"/weeks/{week}"), params={"season": SEASON})
        assert response.status_code == 200, response.text
        return response.json()

    async def test_returns_the_schedule_and_the_counts(self, client):
        body = (await self.week(client, UPCOMING_WEEK))["data"]
        assert body["week"] == UPCOMING_WEEK
        assert body["game_count"] == len(body["games"])
        assert body["game_count"] >= 1
        assert body["completed_games"] + body["upcoming_games"] == body["game_count"]

    async def test_an_upcoming_week_counts_its_games_as_upcoming(self, client):
        body = (await self.week(client, UPCOMING_WEEK))["data"]
        assert body["upcoming_games"] >= 1
        assert body["completed_games"] == 0

    async def test_a_completed_week_counts_its_games_as_played(self, client):
        body = (await self.week(client, UPCOMING_WEEK - 1))["data"]
        assert body["completed_games"] >= 1

    async def test_a_published_week_says_so_and_names_the_run(self, client):
        body = (await self.week(client, UPCOMING_WEEK))["data"]
        assert body["projections_published"] is True
        assert body["projection_count"] == len(PLAYERS)
        assert body["model"]["run_id"]

    async def test_an_unprojected_week_is_answered_not_refused(self, client):
        """A week on the schedule with no run is a state a UI renders as
        "projections coming Thursday", not a 404."""
        body = await self.week(client, UPCOMING_WEEK - 1)
        assert body["data"]["projections_published"] is False
        assert body["data"]["projection_count"] == 0
        # The notice has to explain the *difference* between an empty board and
        # a broken one, which is the whole reason this endpoint exists.
        notices = body["meta"]["notices"]
        assert any("No projection run is published" in notice for notice in notices)
        assert any("the weekly job runs" in notice for notice in notices)

    async def test_an_impossible_week_is_rejected_at_the_edge(self, client):
        assert (await client.get(url("/weeks/99"))).status_code == 422


class TestSeasonAvailability:
    """`GET /seasons` — what a season picker may honestly offer.

    The warehouse holds a game table going back to 1999. A picker built from
    *that* offers twenty-eight seasons on a deployment that has published one
    week, and every selection but one lands on an empty product. So the
    endpoint answers from the run table, and this is the test that stops the
    schedule from leaking back into it.
    """

    async def seasons(self, client) -> dict:
        response = await client.get(url("/seasons"))
        assert response.status_code == 200, response.text
        return response.json()

    async def test_a_season_carries_the_weeks_it_published(self, client):
        entries = (await self.seasons(client))["data"]
        assert [entry["season"] for entry in entries] == [SEASON]
        assert entries[0]["published_weeks"] == [UPCOMING_WEEK]
        assert entries[0]["latest_published_week"] == UPCOMING_WEEK

    async def test_a_scheduled_season_with_no_run_is_not_offered(
        self, client, async_db_session
    ):
        """The case the frontend cannot detect for itself.

        1999 has games. It has never been projected, and a user who selects it
        gets a screen with nothing on it and no explanation — which reads as a
        broken application rather than an unpublished season.
        """
        await async_db_session.execute(
            text(
                "INSERT INTO game_team (game_id, season, week, team, opponent,"
                " is_home) VALUES ('1999_1_A_B', 1999, 1, 'KC', 'BUF', true)"
            )
        )
        assert 1999 not in [e["season"] for e in (await self.seasons(client))["data"]]

    async def test_an_unpublished_run_does_not_make_a_season_available(
        self, client, async_db_session
    ):
        """Availability is publication, not existence of a run.

        A run that succeeded but was never promoted serves nothing — the read
        path filters on `status = 'published'` everywhere else, and a season
        picker that disagreed with it would offer a week whose board is empty.
        """
        await async_db_session.execute(
            text(
                "INSERT INTO model_runs (model_name, model_version, algorithm,"
                " season, week, status, feature_schema_version, created_at,"
                " updated_at) VALUES ('shrinkage_eb', '1.0.0', 'baseline', 2024, 5,"
                " 'succeeded', 1, now(), now())"
            )
        )
        assert 2024 not in [e["season"] for e in (await self.seasons(client))["data"]]

    async def test_the_weeks_endpoint_agrees_with_the_season_list(self, client):
        """Two endpoints, one answer. A client may build its week picker from
        either, and they must not disagree about what is published."""
        entry = (await self.seasons(client))["data"][0]
        weeks = (await client.get(url(f"/seasons/{entry['season']}/weeks"))).json()
        assert weeks["data"] == entry["published_weeks"]

    async def test_nothing_published_is_an_empty_list_with_a_notice(
        self, client, async_db_session
    ):
        await async_db_session.execute(
            text("UPDATE model_runs SET status = 'superseded'")
        )
        body = await self.seasons(client)
        assert body["data"] == []
        assert any("No projection run" in n for n in body["meta"]["notices"])


class TestOperational:
    async def test_health_reports_the_database(self, client):
        response = await client.get(url("/health"))
        assert response.status_code == 200
        assert response.json()["status"] in ("ok", "degraded")

    async def test_liveness_checks_nothing_external(self, client):
        """A liveness probe that consults Postgres restarts every healthy
        container the moment the database fails over."""
        body = (await client.get(url("/health/live"))).json()
        assert body["status"] == "ok"
        assert body["database"] is None

    async def test_readiness_checks_the_database(self, client):
        """An instance that cannot reach Postgres should leave rotation, not
        be restarted."""
        body = (await client.get(url("/health/ready"))).json()
        assert body["database"] is True
        assert body["checks"]["database"] == "ok"

    async def test_readiness_never_fails_on_the_cache(self, client):
        """Taking a working API offline to protect an optimisation is
        backwards. With no cache configured the state is `disabled`, which is
        a supported deployment rather than a degraded one."""
        body = (await client.get(url("/health/ready"))).json()
        assert body["cache"] == "disabled"
        assert body["status"] == "ok"

    async def test_every_response_is_correlated_and_timed(self, client):
        response = await client.get(url("/projections"), params={"season": SEASON})
        assert response.headers["X-Request-ID"]
        assert float(response.headers["X-Response-Time-ms"]) >= 0

    async def test_an_inbound_request_id_is_honoured_not_replaced(self, client):
        """Otherwise the platform's id and ours can never be joined."""
        response = await client.get(
            url("/projections"), headers={"X-Request-ID": "upstream-123"}
        )
        assert response.headers["X-Request-ID"] == "upstream-123"

    async def test_the_cache_state_is_on_every_response(self, client):
        """A support question about a stale number should be answered by a
        header rather than a log dig. With no cache configured, a cacheable
        path still reports MISS and a non-cacheable one reports BYPASS."""
        board = await client.get(url("/projections"), params={"season": SEASON})
        health = await client.get(url("/health"))
        assert board.headers["X-Cache"] == "MISS"
        assert health.headers["X-Cache"] == "BYPASS"

    async def test_the_cache_policy_is_served_as_data(self, client):
        response = await client.get(url("/meta/cache"))
        assert response.status_code == 200
        rules = response.json()["data"]
        assert {rule["prefix"] for rule in rules} >= {"/api/v1/projections", "/api/v1/health"}
        assert all(rule["reason"] for rule in rules)

    async def test_a_missing_matview_is_a_503_with_a_remedy(self, client, async_db_session):
        # A `pipeline full` publish drops raw_* with CASCADE, taking dependent
        # matviews with it. That is recoverable, so it must not look like a bug.
        from nflfp.services.repository import clear_relation_cache

        await async_db_session.execute(text("DROP TABLE feat_player_usage"))
        await async_db_session.commit()
        clear_relation_cache()

        response = await client.get(url("/projections"), params={"season": SEASON})
        assert response.status_code == 503
        body = response.json()
        assert body["code"] == "data_unavailable"
        assert "build_features" in body["remedy"]
        assert response.headers["Retry-After"] == "60"
        clear_relation_cache()

    async def test_a_season_with_no_schedule_is_a_404(self, client):
        # The default season is the current league year, which rolls over in
        # March. Before the schedule for it is ingested there is genuinely
        # nothing to resolve a week against, and saying so beats guessing at
        # the previous season.
        response = await client.get(url("/projections"), params={"season": 1999})
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    async def test_errors_share_one_shape(self, client):
        response = await client.get(
            url("/projections/00-9999999"), params={"season": SEASON}
        )
        assert set(response.json()) == {"code", "message", "field", "remedy"}

    async def test_an_unrouted_path_uses_the_same_shape(self, client):
        """The error a client meets first, while integrating.

        Left to the framework this is `{"detail": "Not Found"}` — a second
        error contract, produced by a typo, that no client parses. A typo must
        not be the one failure the error handling does not cover.
        """
        response = await client.get(url("/no-such-endpoint"))
        assert response.status_code == 404
        body = response.json()
        assert set(body) == {"code", "message", "field", "remedy"}
        assert body["code"] == "not_found"
        assert "detail" not in body

    async def test_a_wrong_method_uses_the_same_shape(self, client):
        response = await client.post(url("/seasons"))
        assert response.status_code == 405
        assert response.json()["code"] == "method_not_allowed"
        # Starlette's own `Allow` header still travels; only the body changes.
        assert "GET" in response.headers.get("allow", "")

    async def test_a_schema_validation_failure_uses_the_same_shape(self, client):
        """FastAPI's default here is a list of Pydantic issues under `detail`.
        The client highlights `field`, so it has to be a field name rather than
        a `loc` array with a transport prefix on the front."""
        response = await client.get(url("/projections"), params={"week": "not-a-week"})
        assert response.status_code == 422
        body = response.json()
        assert set(body) == {"code", "message", "field", "remedy"}
        assert body["code"] == "invalid_request"
        assert body["field"] == "week"

    async def test_the_openapi_document_builds(self, client):
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        assert spec["info"]["title"].startswith("nflfp")
        # The provenance contract is documented where a client author reads it.
        assert "provenance" in spec["info"]["description"].lower()

    async def test_the_root_points_at_the_api(self, client):
        body = (await client.get("/")).json()
        assert body["api"] == API_PREFIX
        assert body["model"] == "shrinkage_eb"
