"""Mock draft over HTTP, against a real warehouse.

The unit suite covers everything that decides anything. What is left, and what
only a database can check, is that the pool query returns rows the assembler
understands, that the leakage boundary holds against real seasons, and that the
endpoints refuse what they should.

These require a loaded warehouse and a published week 1 board. Without one they
skip rather than fail: a developer with an empty database has not broken
anything, and a suite that goes red on a fresh clone is a suite people learn to
ignore.
"""

from __future__ import annotations

import pytest

from .conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from nflfp.api.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def draftable_season(client) -> int:
    response = client.get("/api/v1/mock-draft/config")
    assert response.status_code == 200
    seasons = response.json()["data"]["draftable_seasons"]
    if not seasons:
        pytest.skip("no season has a published week 1 board")
    return seasons[0]


def analyse(client, season: int, **overrides) -> dict:
    body = {
        "season": season,
        "teams": 12,
        "rounds": 15,
        "scoring_profile": "ppr",
        "draft_position": 4,
        "simulations": 60,
    }
    body.update(overrides)
    response = client.post("/api/v1/mock-draft/analyze", json=body)
    assert response.status_code == 200, response.text
    return response.json()


class TestConfig:
    def test_the_config_names_what_can_and_cannot_be_drafted(self, client):
        payload = client.get("/api/v1/mock-draft/config").json()["data"]
        assert set(payload["draftable_positions"]) == {"QB", "RB", "WR", "TE"}
        unavailable = {entry["position"] for entry in payload["unavailable_positions"]}
        assert unavailable == {"K", "DST"}
        for entry in payload["unavailable_positions"]:
            assert entry["reason"]
            assert entry["blocked_on"]

    def test_the_limits_are_served_rather_than_assumed_by_the_client(self, client):
        limits = client.get("/api/v1/mock-draft/config").json()["data"]["limits"]
        assert limits["min_teams"] < limits["max_teams"]
        assert limits["default_simulations"] <= limits["max_simulations"]
        assert limits["max_total_drafts"] > 0
        assert {r["slot"] for r in limits["default_roster"]} == {
            "QB", "RB", "WR", "TE", "FLEX"
        }

    def test_the_seasons_offered_are_the_ones_with_a_board(self, client, draftable_season):
        payload = client.get("/api/v1/mock-draft/config").json()["data"]
        assert draftable_season in payload["draftable_seasons"]


class TestAnalyse:
    def test_a_seat_analysis_comes_back_whole(self, client, draftable_season):
        payload = analyse(client, draftable_season)
        seat = payload["data"]["seat"]
        assert seat["draft_position"] == 4
        assert len(seat["roster"]) == 15
        assert seat["roster_value"]["observations"] == 60
        assert seat["picks"] == sorted(seat["picks"])
        assert payload["data"]["methodology"]["seed"] > 0

    def test_every_pick_carries_a_reason_built_from_its_numbers(
        self, client, draftable_season
    ):
        seat = analyse(client, draftable_season)["data"]["seat"]
        for pick in seat["roster"]:
            rationale = pick["rationale"]
            assert rationale is not None
            assert pick["name"] in rationale["explanation"]
            assert rationale["slot"] in {"starter", "flex", "bench"}
            assert 0.0 <= rationale["survival_at_next_pick"] <= 1.0

    def test_the_three_kinds_of_number_stay_apart(self, client, draftable_season):
        """A projected rate, a recorded season and a derived estimate, in one card."""
        seat = analyse(client, draftable_season)["data"]["seat"]
        with_history = [p for p in seat["roster"] if p["historical"]["seasons"]]
        assert with_history, "expected at least one drafted player with history"

        pick = with_history[0]
        assert pick["projected_points_per_game"] > 0  # model
        assert pick["historical"]["seasons"][0]["total_points"] >= 0  # actual
        assert pick["season_value"] == pytest.approx(  # derived, and multiplicative
            pick["projected_points_per_game"] * pick["expected_games"], rel=1e-6
        )

    def test_history_never_reaches_the_season_being_drafted(
        self, client, draftable_season
    ):
        payload = analyse(client, draftable_season)
        assert all(
            season < draftable_season
            for season in payload["data"]["pool"]["history_seasons"]
        )
        for pick in payload["data"]["seat"]["roster"]:
            for entry in pick["historical"]["seasons"]:
                assert entry["season"] < draftable_season

    def test_the_board_is_week_one_and_says_so(self, client, draftable_season):
        pool = analyse(client, draftable_season)["data"]["pool"]
        assert pool["board_week"] == 1
        assert pool["season"] == draftable_season
        assert pool["players"] > 100

    def test_replacement_levels_are_reported_with_the_player_behind_them(
        self, client, draftable_season
    ):
        pool = analyse(client, draftable_season)["data"]["pool"]
        by_position = {entry["position"]: entry for entry in pool["replacement"]}
        assert set(by_position) == {"QB", "RB", "WR", "TE"}
        assert by_position["RB"]["starters"] >= 24
        assert sum(entry["flex_share"] for entry in pool["replacement"]) == 12

    def test_availability_percentages_are_coherent(self, client, draftable_season):
        seat = analyse(client, draftable_season)["data"]["seat"]
        assert seat["availability"]
        for entry in seat["availability"]:
            assert 0.0 <= entry["next_pick_probability"] <= 1.0
            assert 0.0 <= entry["selected_rate"] <= 1.0
            assert entry["drafted_before_next_pick"] == pytest.approx(
                1.0 - entry["next_pick_probability"]
            )

    def test_the_notices_carry_the_methodology_limits(self, client, draftable_season):
        notices = " ".join(analyse(client, draftable_season)["meta"]["notices"])
        assert "per-game rate" in notices
        assert "rookies" in notices
        assert "average-draft-position" in notices
        assert "Kickers and team defences" in notices

    def test_the_same_seed_returns_the_same_draft(self, client, draftable_season):
        a = analyse(client, draftable_season, seed=99)["data"]["seat"]
        b = analyse(client, draftable_season, seed=99)["data"]["seat"]
        assert [p["player_id"] for p in a["roster"]] == [
            p["player_id"] for p in b["roster"]
        ]
        assert a["roster_value"]["mean"] == b["roster_value"]["mean"]

    def test_a_different_seed_returns_a_different_draft(self, client, draftable_season):
        a = analyse(client, draftable_season, seed=1)["data"]["seat"]
        b = analyse(client, draftable_season, seed=2)["data"]["seat"]
        assert [p["player_id"] for p in a["roster"]] != [
            p["player_id"] for p in b["roster"]
        ]

    def test_the_response_echoes_a_reproducible_configuration(
        self, client, draftable_season
    ):
        data = analyse(client, draftable_season, seed=7)["data"]
        assert data["settings"]["seed"] == 7
        assert data["settings"]["season"] == draftable_season
        assert data["settings"]["starters"] + data["settings"]["bench"] == 15
        assert data["methodology"]["calibration_drafts"] > 0

    def test_a_custom_roster_changes_the_draft(self, client, draftable_season):
        superflex = analyse(
            client,
            draftable_season,
            roster=[
                {"slot": "QB", "count": 2},
                {"slot": "RB", "count": 2},
                {"slot": "WR", "count": 3},
                {"slot": "TE", "count": 1},
            ],
        )["data"]
        assert superflex["settings"]["starters"] == 8
        quarterbacks = sum(
            1 for p in superflex["seat"]["roster"] if p["position"] == "QB"
        )
        assert quarterbacks >= 2


class TestRefusals:
    def test_a_kicker_slot_is_refused_with_its_blockers(self, client, draftable_season):
        response = client.post(
            "/api/v1/mock-draft/analyze",
            json={
                "season": draftable_season,
                "draft_position": 1,
                "simulations": 50,
                "roster": [{"slot": "QB", "count": 1}, {"slot": "K", "count": 1}],
            },
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "invalid_request"
        assert body["field"] == "roster"
        assert "Blocked on:" in body["message"]

    def test_a_season_with_no_board_is_refused_by_name(self, client):
        response = client.post(
            "/api/v1/mock-draft/analyze",
            json={"season": 1999, "draft_position": 1, "simulations": 50},
        )
        assert response.status_code == 404
        assert response.json()["code"] == "no_projections_published"

    def test_a_seat_outside_the_league_is_refused(self, client, draftable_season):
        response = client.post(
            "/api/v1/mock-draft/analyze",
            json={
                "season": draftable_season,
                "teams": 10,
                "draft_position": 11,
                "simulations": 50,
            },
        )
        assert response.status_code == 422
        assert response.json()["field"] == "draft_position"

    def test_a_draft_too_short_for_its_lineup_is_refused(self, client, draftable_season):
        response = client.post(
            "/api/v1/mock-draft/analyze",
            json={
                "season": draftable_season,
                "rounds": 3,
                "draft_position": 1,
                "simulations": 50,
            },
        )
        assert response.status_code == 422
        assert response.json()["field"] == "rounds"

    def test_an_oversized_comparison_is_refused_with_the_arithmetic(
        self, client, draftable_season
    ):
        response = client.post(
            "/api/v1/mock-draft/compare",
            json={"season": draftable_season, "teams": 12, "simulations": 10_000},
        )
        assert response.status_code == 422
        message = response.json()["message"]
        assert "120,000" in message
        assert response.json()["field"] == "simulations"

    def test_an_unknown_scoring_profile_is_refused_not_defaulted(
        self, client, draftable_season
    ):
        response = client.post(
            "/api/v1/mock-draft/analyze",
            json={
                "season": draftable_season,
                "draft_position": 1,
                "simulations": 50,
                "scoring_profile": "sixpoint_passing_td",
            },
        )
        assert response.status_code == 422
        assert response.json()["code"] == "unknown_scoring_profile"


class TestComparison:
    @pytest.fixture(scope="class")
    def comparison(self, client, draftable_season) -> dict:
        response = client.post(
            "/api/v1/mock-draft/compare",
            json={
                "season": draftable_season,
                "teams": 12,
                "rounds": 15,
                "scoring_profile": "ppr",
                "simulations": 60,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    def test_every_seat_is_present_once_and_in_order(self, comparison):
        seats = comparison["data"]["seats"]
        assert [s["draft_position"] for s in seats] == list(range(1, 13))

    def test_exactly_one_seat_is_best_and_it_leads(self, comparison):
        seats = comparison["data"]["seats"]
        best = [s for s in seats if s["is_best"]]
        assert len(best) == 1
        assert best[0]["draft_position"] == comparison["data"]["best_position"]
        assert best[0]["roster_value"]["mean"] == max(
            s["roster_value"]["mean"] for s in seats
        )

    def test_the_spread_is_reported_with_whether_it_is_resolvable(self, comparison):
        data = comparison["data"]
        assert data["spread"] >= 0
        assert isinstance(data["spread_is_resolvable"], bool)
        if not data["spread_is_resolvable"]:
            assert any("noise" in n for n in comparison["meta"]["notices"])

    def test_each_seat_carries_a_roster_so_a_click_costs_no_request(self, comparison):
        detail = comparison["data"]["detail"]
        assert len(detail) == 12
        for entry in detail:
            assert len(entry["roster"]) == 15
            assert entry["waits"]

    def test_a_seat_analysis_matches_the_comparison_that_contains_it(
        self, client, draftable_season, comparison
    ):
        """The seed keys on the seat, so a seat is the same draft either way."""
        seat_4 = next(
            s for s in comparison["data"]["detail"] if s["draft_position"] == 4
        )
        alone = analyse(client, draftable_season, simulations=60)["data"]["seat"]
        assert [p["player_id"] for p in alone["roster"]] == [
            p["player_id"] for p in seat_4["roster"]
        ]
        assert alone["roster_value"]["mean"] == pytest.approx(
            seat_4["roster_value"]["mean"]
        )

    def test_the_ranking_is_not_presented_as_a_guarantee(self, comparison):
        notices = " ".join(comparison["meta"]["notices"])
        assert "simulated outcomes" in notices
        assert "not predictions" in notices
