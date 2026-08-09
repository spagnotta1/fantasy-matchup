"""``POST /simulations``, driven through the real ASGI app against real Postgres.

These are not mocked-session tests. The app is built by the same factory
production uses, the request goes through the same middleware stack, and the
projections it samples are read out of a throwaway Postgres schema by the same
SQL. That matters more here than for a read endpoint: the simulation is the
first thing in the codebase that combines a request body, two-stage validation
and a service that fetches before it computes, and every one of those seams is
somewhere a unit test with a stubbed session would agree with itself.

What is asserted, in order of how badly it would hurt to get wrong:

1. **Nothing is silently dropped.** A lineup naming a player with no projection
   fails the whole request. A team total missing a starter is wrong in a
   direction nobody looking at the screen can see.
2. **The seed contract holds over HTTP.** Same body, same numbers.
3. **The provenance labels survive serialisation.** Simulated output is
   `derived`, never `model`.
4. **The caveats reach the response.** A win probability without them is the
   dishonest version of this feature.
"""

from __future__ import annotations

import pytest

from nflfp.api.main import API_PREFIX, create_app
from nflfp.api.provenance import Provenance
from nflfp.db.engine import get_db_session
from nflfp.services.simulation import DEFAULT_SEED, MAX_ITERATIONS

from .conftest import requires_db
from .warehouse_stub import (
    SEASON,
    SIM_BENCHED,
    SIM_KICKER,
    SIM_TEAM_A,
    SIM_TEAM_B,
    UPCOMING_WEEK,
    add_players,
    build_warehouse,
)

pytestmark = [pytest.mark.integration, requires_db]

URL = f"{API_PREFIX}/simulations"

#: The slots a standard lineup fills, in the order the fixtures are listed.
SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX")


def lineup(players) -> list[dict]:
    return [
        {"player_id": spec[0], "slot": slot} for spec, slot in zip(players, SLOTS)
    ]


def body(**overrides) -> dict:
    payload = {
        "season": SEASON,
        "week": UPCOMING_WEEK,
        "scoring_profile": "ppr",
        "simulation_count": 2_000,
        "seed": 42,
        "team_a": lineup(SIM_TEAM_A),
        "team_b": lineup(SIM_TEAM_B),
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
async def client(async_db_session):
    """A test client whose requests run against the throwaway schema."""
    from httpx import ASGITransport, AsyncClient

    run_id = await build_warehouse(async_db_session)
    await add_players(
        async_db_session,
        run_id,
        [*SIM_TEAM_A, *SIM_TEAM_B, SIM_KICKER, SIM_BENCHED],
    )

    app = create_app()

    async def _session_override():
        yield async_db_session

    app.dependency_overrides[get_db_session] = _session_override

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=60.0
    ) as http:
        yield http

    app.dependency_overrides.clear()


async def simulate(client, **overrides):
    return await client.post(URL, json=body(**overrides))


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


class TestASuccessfulSimulation:
    async def test_it_returns_two_hundred_with_an_envelope(self, client):
        response = await simulate(client)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert set(payload) == {"data", "meta"}

    async def test_the_stronger_lineup_is_heavily_favoured(self, client):
        # Team A's expectations sum to 114, team B's to 59. The winner is not in
        # dispute, which is what makes this assertable without pinning a
        # stochastic number.
        data = (await simulate(client)).json()["data"]
        assert data["team_a"]["win_probability"] > 0.95
        assert data["team_b"]["win_probability"] < 0.05
        assert data["score_differential"] > 0

    async def test_probabilities_are_coherent(self, client):
        data = (await simulate(client)).json()["data"]
        for side in ("team_a", "team_b"):
            team = data[side]
            total = (
                team["win_probability"]
                + team["loss_probability"]
                + team["tie_probability"]
            )
            assert total == pytest.approx(1.0, abs=1e-9)
        assert data["team_a"]["win_probability"] == pytest.approx(
            data["team_b"]["loss_probability"]
        )

    async def test_percentiles_are_ordered(self, client):
        data = (await simulate(client)).json()["data"]
        for side in ("team_a", "team_b"):
            team = data[side]
            values = [team[k] for k in ("p10", "p25", "median_score", "p75", "p90")]
            assert values == sorted(values)

    async def test_every_submitted_slot_comes_back(self, client):
        # The invariant a team total depends on. Seven in, seven out, in order.
        data = (await simulate(client)).json()["data"]
        for side, roster in (("team_a", SIM_TEAM_A), ("team_b", SIM_TEAM_B)):
            players = data[side]["players"]
            assert [p["player_id"] for p in players] == [s[0] for s in roster]
            assert [p["slot"] for p in players] == list(SLOTS)

    async def test_the_projection_sum_is_the_sum_of_the_stored_expectations(
        self, client
    ):
        data = (await simulate(client)).json()["data"]
        for side, roster in (("team_a", SIM_TEAM_A), ("team_b", SIM_TEAM_B)):
            assert data[side]["projection_sum"] == pytest.approx(
                sum(spec[4] for spec in roster)
            )

    async def test_the_window_and_model_travel_in_meta(self, client):
        meta = (await simulate(client)).json()["meta"]
        assert meta["window"]["season"] == SEASON
        assert meta["window"]["week"] == UPCOMING_WEEK
        assert meta["scoring_profile"] == "ppr"
        # Lineage: which published run these distributions came from.
        assert meta["model"]["model_name"] == "shrinkage_eb"

    async def test_the_scoring_profile_changes_the_answer(self, client):
        # Not a formality — a simulation that ignored the profile would sample
        # the default one and report a total for a league the user is not in.
        half = (await simulate(client, scoring_profile="half_ppr")).json()["data"]
        full = (await simulate(client, scoring_profile="ppr")).json()["data"]
        assert half["team_a"]["projection_sum"] != full["team_a"]["projection_sum"]

    async def test_the_week_defaults_when_omitted(self, client):
        response = await client.post(
            URL, json={k: v for k, v in body().items() if k != "week"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["meta"]["window"]["week"] == UPCOMING_WEEK


# ---------------------------------------------------------------------------
# Determinism over the wire
# ---------------------------------------------------------------------------


class TestReproducibility:
    async def test_the_same_body_returns_the_same_numbers(self, client):
        first = (await simulate(client)).json()["data"]
        second = (await simulate(client)).json()["data"]
        assert first == second

    async def test_a_different_seed_returns_a_different_sample(self, client):
        first = (await simulate(client, seed=1)).json()["data"]
        second = (await simulate(client, seed=2)).json()["data"]
        assert first["team_a"]["expected_score"] != second["team_a"]["expected_score"]

    async def test_omitting_the_seed_does_not_randomise(self, client):
        # A user refreshing the page must not watch their win probability
        # wander. The default seed is fixed and echoed back.
        payload = {k: v for k, v in body().items() if k != "seed"}
        first = (await client.post(URL, json=payload)).json()["data"]
        second = (await client.post(URL, json=payload)).json()["data"]
        assert first == second
        assert first["simulation"]["seed"] == DEFAULT_SEED

    async def test_the_seed_and_iteration_count_are_echoed(self, client):
        data = (await simulate(client, seed=7, simulation_count=1_500)).json()["data"]
        assert data["simulation"]["seed"] == 7
        assert data["simulation"]["iterations"] == 1_500

    async def test_the_response_is_never_served_from_cache(self, client):
        # POST bypasses the response cache by construction. Asserted because a
        # cached simulation would be indistinguishable from a reproducible one
        # right up until the published run changed underneath it.
        response = await simulate(client)
        assert response.headers["X-Cache"] == "BYPASS"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class TestProvenanceContract:
    async def test_simulated_output_is_derived_not_model(self, client):
        # The load-bearing label. A simulation consumes model predictions but
        # is a calculation above the model; calling its output `model` would
        # extend the foundation's measured guarantees to a number nobody
        # measured.
        data = (await simulate(client)).json()["data"]
        assert data["team_a"]["provenance"] == Provenance.DERIVED.value
        assert data["team_b"]["provenance"] == Provenance.DERIVED.value
        assert data["simulation"]["provenance"] == Provenance.DERIVED.value
        assert data["assumptions"]["provenance"] == Provenance.DERIVED.value

    async def test_the_per_player_projection_stays_model(self, client):
        data = (await simulate(client)).json()["data"]
        for player in data["team_a"]["players"]:
            assert player["provenance"] == Provenance.MODEL.value
            assert player["expected_points"] is not None

    async def test_the_sampling_method_is_named_rather_than_implied(self, client):
        data = (await simulate(client)).json()["data"]
        assert (
            data["simulation"]["sampling_method"]
            == "inverse_transform_from_stored_percentiles"
        )


class TestAssumptionsAreDeclared:
    async def test_independence_is_a_field_not_a_footnote(self, client):
        assumptions = (await simulate(client)).json()["data"]["assumptions"]
        assert assumptions["player_independence"] is True

    async def test_the_unprojected_positions_are_declared_unavailable(self, client):
        assumptions = (await simulate(client)).json()["data"]["assumptions"]
        assert assumptions["kicker_projection_available"] is False
        assert assumptions["defense_projection_available"] is False

    async def test_no_adjustment_is_claimed(self, client):
        assumptions = (await simulate(client)).json()["data"]["assumptions"]
        assert assumptions["injury_adjustment_applied"] is False
        assert assumptions["matchup_adjustment_applied"] is False
        assert assumptions["weather_adjustment_applied"] is False

    async def test_the_notes_explain_each_gap(self, client):
        notes = " ".join((await simulate(client)).json()["data"]["assumptions"]["notes"])
        assert "independently" in notes
        assert "kickers" in notes

    async def test_the_caveats_reach_meta_notices(self, client):
        notices = (await simulate(client)).json()["meta"]["notices"]
        assert notices
        assert any("independently" in notice for notice in notices)

    async def test_correlated_lineups_are_disclosed(self, client):
        # Two players from one offence on the same side. The independent sum
        # understates how much this lineup's weeks move together, and the
        # response has to say so.
        notices = (await simulate(client)).json()["meta"]["notices"]
        assert any("share an offence" in notice for notice in notices)
        assert any(notice.startswith("team_a:") for notice in notices)


# ---------------------------------------------------------------------------
# Correlation mode
# ---------------------------------------------------------------------------


class TestCorrelationMode:
    """The Phase 6B addition, over the wire.

    The contract that matters most here is that the response reports the mode
    that *ran*. Everything else in this class is a consequence of that: a caller
    reading `correlation_mode` must be able to trust it more than they trust the
    request they think they sent.
    """

    async def test_the_default_is_independent_and_says_so(self, client):
        data = (await simulate(client)).json()["data"]
        assert data["simulation"]["correlation_mode"] == "independent"
        assert data["simulation"]["correlation_model_version"] is None
        assert data["assumptions"]["player_independence"] is True

    async def test_omitting_the_field_does_not_change_the_numbers(self, client):
        # The default has to be the Phase 6A behaviour exactly, or shipping this
        # phase silently changed every existing caller's win probability.
        explicit = await simulate(client, correlation_mode="independent")
        implicit = await client.post(
            URL,
            json={k: v for k, v in body().items() if k != "correlation_mode"},
        )
        assert explicit.json()["data"] == implicit.json()["data"]

    async def test_the_game_environment_mode_runs_and_identifies_itself(self, client):
        response = await simulate(
            client, scoring_profile="half_ppr", correlation_mode="game_environment"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["simulation"]["correlation_mode"] == "game_environment"
        assert data["simulation"]["correlation_model_version"] == "1.0.0"
        assert data["assumptions"]["player_independence"] is False
        assert data["assumptions"]["correlation_mode"] == "game_environment"

    async def test_the_correlated_notice_names_the_structure(self, client):
        response = await simulate(
            client, scoring_profile="half_ppr", correlation_mode="game_environment"
        )
        notices = response.json()["meta"]["notices"]
        assert any("correlation structure" in notice for notice in notices)
        assert not any(
            "drawn independently" in notice for notice in notices
        ), "a correlated run must not still claim independence"

    async def test_correlation_widens_the_interval_without_moving_the_centre(
        self, client
    ):
        # The whole practical claim of the phase, asserted end to end. The
        # fitted loadings are modest, so the shift is small; what must hold is
        # the *direction* and the fact that the centre stays put.
        base = (
            await simulate(client, scoring_profile="half_ppr")
        ).json()["data"]["team_a"]
        candidate = (
            await simulate(
                client,
                scoring_profile="half_ppr",
                correlation_mode="game_environment",
            )
        ).json()["data"]["team_a"]

        assert candidate["expected_score"] == pytest.approx(
            base["expected_score"], rel=0.03
        )
        assert candidate["projection_sum"] == base["projection_sum"]
        assert (candidate["p90"] - candidate["p10"]) >= (base["p90"] - base["p10"])

    async def test_a_profile_with_no_fitted_structure_is_refused(self, client):
        # PPR, not half-PPR. Correlations are measured through each player's own
        # outcome distribution and those differ by profile, so serving the
        # half-PPR structure here would be an unmeasured claim wearing a
        # measured one's version number. Refused, with the remedy in the text.
        response = await simulate(
            client, scoring_profile="ppr", correlation_mode="game_environment"
        )
        assert response.status_code == 422
        payload = response.json()
        assert payload["field"] == "correlation_mode"
        assert "half_ppr" in payload["message"]
        assert "independent" in payload["message"]

    async def test_an_unknown_mode_is_refused_rather_than_defaulted(self, client):
        response = await simulate(client, correlation_mode="magic")
        assert response.status_code == 422
        payload = response.json()
        assert payload["field"] == "correlation_mode"
        assert "game_environment" in payload["message"]

    async def test_a_correlated_run_is_still_reproducible(self, client):
        first = await simulate(
            client, scoring_profile="half_ppr", correlation_mode="game_environment"
        )
        second = await simulate(
            client, scoring_profile="half_ppr", correlation_mode="game_environment"
        )
        assert first.json()["data"] == second.json()["data"]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class TestRefusals:
    async def test_a_kicker_slot_is_refused_with_a_reason(self, client):
        broken = lineup(SIM_TEAM_A)
        broken[-1] = {"player_id": SIM_KICKER[0], "slot": "K"}
        response = await simulate(client, team_a=broken)
        assert response.status_code == 422
        payload = response.json()
        assert payload["code"] == "invalid_request"
        # Not "unknown slot". The reason and the blockers, from the position
        # registry — the same answer /meta/positions gives.
        assert "distance-bucketed" in payload["message"]
        assert "Blocked on" in payload["message"]

    async def test_a_defense_slot_is_refused_with_a_reason(self, client):
        broken = lineup(SIM_TEAM_B)
        broken[-1] = {"player_id": "00-0009999", "slot": "DST"}
        response = await simulate(client, team_b=broken)
        assert response.status_code == 422
        assert "team-week fact table" in response.json()["message"]

    async def test_a_kicker_in_the_flex_is_refused_rather_than_dropped(self, client):
        # The same gap wearing a different label, and the case that would
        # silently cost a team twenty points if it were tolerated.
        broken = lineup(SIM_TEAM_A)
        broken[-1] = {"player_id": SIM_KICKER[0], "slot": "FLEX"}
        response = await simulate(client, team_a=broken)
        assert response.status_code == 422
        message = response.json()["message"]
        assert SIM_KICKER[1] in message or SIM_KICKER[0] in message
        assert "Kicker" in message

    async def test_a_player_with_no_projection_fails_the_whole_request(self, client):
        broken = lineup(SIM_TEAM_A)
        broken[-1] = {"player_id": SIM_BENCHED[0], "slot": "FLEX"}
        response = await simulate(client, team_a=broken)
        assert response.status_code == 422
        message = response.json()["message"]
        assert "no published projection" in message
        # And which side, because with two lineups that is the first question.
        assert "team_a" in message

    async def test_an_unknown_player_id_fails_the_whole_request(self, client):
        broken = lineup(SIM_TEAM_B)
        broken[0] = {"player_id": "00-0000000", "slot": "QB"}
        response = await simulate(client, team_b=broken)
        assert response.status_code == 422
        assert "player dimension" in response.json()["message"]

    async def test_a_missing_required_slot_is_refused(self, client):
        response = await simulate(client, team_a=lineup(SIM_TEAM_A)[:-1])
        assert response.status_code == 422
        assert "FLEX" in response.json()["message"]

    async def test_a_duplicate_player_is_refused(self, client):
        broken = lineup(SIM_TEAM_A)
        broken[2] = {"player_id": broken[1]["player_id"], "slot": "RB"}
        response = await simulate(client, team_a=broken)
        assert response.status_code == 422
        assert "more than once" in response.json()["message"]

    async def test_an_ineligible_flex_is_refused(self, client):
        # A quarterback in the FLEX. Legal in a superflex league, which is a
        # different format, not a wider FLEX.
        broken = lineup(SIM_TEAM_A)
        broken[-1] = {"player_id": SIM_TEAM_A[0][0], "slot": "FLEX"}
        broken[0] = {"player_id": SIM_TEAM_B[0][0], "slot": "QB"}
        response = await simulate(client, team_a=broken)
        assert response.status_code == 422
        assert "Flex" in response.json()["message"]

    async def test_an_unknown_scoring_profile_is_refused(self, client):
        response = await simulate(client, scoring_profile="superflex_ppr")
        assert response.status_code == 422
        assert response.json()["code"] == "unknown_scoring_profile"

    async def test_a_week_outside_the_range_is_refused_by_the_schema(self, client):
        response = await simulate(client, week=99)
        assert response.status_code == 422

    async def test_the_iteration_count_is_bounded_at_the_edge(self, client):
        assert (await simulate(client, simulation_count=1)).status_code == 422
        assert (
            await simulate(client, simulation_count=MAX_ITERATIONS + 1)
        ).status_code == 422

    async def test_an_empty_lineup_is_refused(self, client):
        assert (await simulate(client, team_a=[])).status_code == 422


# ---------------------------------------------------------------------------
# The slot registry, served
# ---------------------------------------------------------------------------


class TestTheSlotCapabilityEndpoint:
    async def test_it_serves_the_vocabulary(self, client):
        response = await client.get(f"{API_PREFIX}/meta/lineup-slots")
        assert response.status_code == 200
        by_slot = {entry["slot"]: entry for entry in response.json()["data"]}
        assert by_slot["FLEX"]["eligible_positions"] == ["RB", "WR", "TE"]
        assert by_slot["FLEX"]["supported"] is True

    async def test_unsupported_slots_are_listed_rather_than_hidden(self, client):
        # A client builds its lineup editor from this. Omitting K would make the
        # editor unable to explain why the slot it renders cannot be filled.
        response = await client.get(f"{API_PREFIX}/meta/lineup-slots")
        by_slot = {entry["slot"]: entry for entry in response.json()["data"]}
        assert by_slot["K"]["supported"] is False
        assert by_slot["DST"]["supported"] is False

    async def test_the_formats_are_listed_in_notices(self, client):
        response = await client.get(f"{API_PREFIX}/meta/lineup-slots")
        assert any("1xQB" in notice for notice in response.json()["meta"]["notices"])
