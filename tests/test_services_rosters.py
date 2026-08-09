"""Rosters — retrieving a named set of players and declaring what is missing.

The failure this module exists to prevent is silence. A comparison screen that
drops an unknown id is fine; a *roster* that drops one produces a team total
missing that player's entire contribution, and every probability derived from
that total is confidently wrong. So the tests here are mostly about absence:
that it is reported, that it is attributed to the right cause, and that the
permanent kind is distinguishable from the kind worth waiting out.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from nflfp.services import repository, rosters
from nflfp.services.dto import PlayerProjection, PlayerRef, PointDistribution
from nflfp.services.errors import InvalidRequest
from nflfp.services.rosters import (
    NO_PROJECTION,
    UNKNOWN_PLAYER,
    UNPROJECTED_POSITION,
    RosterProjections,
    UnavailablePlayer,
)

from .conftest import requires_db
from .warehouse_stub import PLAYERS, SEASON, UPCOMING_WEEK, build_warehouse


def player(
    player_id: str,
    *,
    position: str = "WR",
    team: str = "KC",
    game_id: str | None = "2025_10_KC_BUF",
    expected: float = 12.0,
) -> PlayerProjection:
    return PlayerProjection(
        player=PlayerRef(
            player_id=player_id, name=player_id.upper(), position=position, team=team
        ),
        season=2025,
        week=10,
        team=team,
        opponent="BUF",
        is_home=True,
        game_id=game_id,
        points=PointDistribution(
            scoring_profile="half_ppr",
            expected=expected,
            predicted=expected,
            floor=max(0.0, expected - 6.0),
            p25=max(0.0, expected - 3.0),
            median=expected - 0.4,
            p75=expected + 3.0,
            ceiling=expected + 10.0,
        ),
    )


def unavailable(player_id: str, reason: str, **kwargs) -> UnavailablePlayer:
    return UnavailablePlayer(
        player_id=player_id, reason=reason, detail="because", **kwargs
    )


def roster(
    entries=(), unavailable_players=(), requested=None
) -> RosterProjections:
    ids = requested or tuple(
        [e.player.player_id for e in entries] + [u.player_id for u in unavailable_players]
    )
    return RosterProjections(
        season=2025,
        week=10,
        scoring_profile="half_ppr",
        entries=tuple(entries),
        unavailable=tuple(unavailable_players),
        requested=tuple(ids),
    )


class TestTheCurveBridge:
    """One construction site for outcome curves, not three."""

    def test_a_distribution_builds_its_own_curve(self):
        curve = player("a", expected=12.0).points.curve()
        assert curve is not None
        # Passes through the stored percentiles exactly — the property the
        # whole reconstruction is built on.
        assert curve.quantile(0.50) == pytest.approx(11.6)
        assert curve.quantile(0.10) == pytest.approx(6.0)

    def test_thin_distributions_return_none_rather_than_a_line(self):
        thin = PointDistribution(
            scoring_profile="half_ppr", expected=8.0, predicted=8.0, floor=2.0
        )
        assert thin.curve() is None

    def test_provenance_survives_the_bridge(self):
        # The drift that motivated consolidating this: one of the two former
        # copies dropped `extrapolated` and `samples`, so the same projection
        # was honest about its thinness on one screen and not on another.
        dist = PointDistribution(
            scoring_profile="half_ppr",
            expected=30.0,
            predicted=30.0,
            floor=18.0,
            median=29.0,
            ceiling=48.0,
            extrapolated=True,
            samples=41,
        )
        curve = dist.curve()
        assert curve is not None
        assert curve.extrapolated is True
        assert curve.samples == 41


class TestCorrelationPredicates:
    def test_teammates_are_detected(self):
        assert player("a", team="KC").is_teammate_of(player("b", team="KC"))
        assert not player("a", team="KC").is_teammate_of(player("b", team="BUF"))

    def test_a_missing_team_is_not_a_match(self):
        # Two players with unknown teams are not thereby teammates. Treating
        # None as a joinable value would invent correlation between every
        # incomplete row on the board.
        nobody = player("a", team=None)  # type: ignore[arg-type]
        assert not nobody.is_teammate_of(player("b", team=None))  # type: ignore[arg-type]

    def test_shared_games_are_detected(self):
        assert player("a").shares_game_with(player("b"))
        assert not player("a").shares_game_with(player("b", game_id="2025_10_SF_SEA"))

    def test_a_missing_game_is_not_a_match(self):
        assert not player("a", game_id=None).shares_game_with(player("b", game_id=None))


class TestCorrelationGroups:
    def test_a_lone_player_is_not_a_group(self):
        assert rosters.correlation_groups([player("a")]) == ()

    def test_teammates_group_together(self):
        groups = rosters.correlation_groups(
            [player("a", team="KC"), player("b", team="KC"), player("c", team="SF",
                                                                   game_id="2025_10_SF_SEA")]
        )
        team_groups = [g for g in groups if g.kind == "team"]
        assert len(team_groups) == 1
        assert team_groups[0].key == "KC"
        assert team_groups[0].player_ids == ("a", "b")

    def test_a_game_group_needs_both_sidelines(self):
        # Two teammates share a game_id, but that fact says nothing the team
        # group did not already say. Emitting it would double-report one
        # correlation and bury the cross-team one that matters.
        groups = rosters.correlation_groups(
            [player("a", team="KC"), player("b", team="KC")]
        )
        assert [g.kind for g in groups] == ["team"]

    def test_opponents_in_one_game_are_a_game_group(self):
        groups = rosters.correlation_groups(
            [player("a", team="KC"), player("b", team="BUF")]
        )
        assert [g.kind for g in groups] == ["game"]
        assert groups[0].player_ids == ("a", "b")

    def test_a_player_can_be_in_both_kinds_at_once(self):
        # Correct, not a bug: their outcome is tied to their teammate one way
        # and to their opponent another.
        groups = rosters.correlation_groups(
            [player("a", team="KC"), player("b", team="KC"), player("c", team="BUF")]
        )
        assert {g.kind for g in groups} == {"team", "game"}

    def test_caveats_name_the_players_and_the_direction(self):
        caveats = rosters.lineup_caveats(
            [player("a", team="KC"), player("b", team="KC")]
        )
        assert len(caveats) == 1
        assert "share an offence" in caveats[0]
        assert "target competition" in caveats[0]

    def test_an_uncorrelated_lineup_owes_nothing(self):
        assert rosters.lineup_caveats(
            [
                player("a", team="KC", game_id="g1"),
                player("b", team="SF", game_id="g2"),
            ]
        ) == ()


class TestUnavailability:
    def test_an_unprojected_position_is_permanent(self):
        # The distinction a caller acts on: no amount of waiting produces a
        # kicker projection, but a bye week resolves itself.
        assert unavailable("k1", UNPROJECTED_POSITION).is_permanent
        assert unavailable("x1", UNKNOWN_PLAYER).is_permanent
        assert not unavailable("p1", NO_PROJECTION).is_permanent

    def test_a_full_roster_is_complete(self):
        assert roster(entries=[player("a"), player("b")]).complete

    def test_any_gap_makes_it_incomplete(self):
        assert not roster(
            entries=[player("a")],
            unavailable_players=[unavailable("k1", UNPROJECTED_POSITION)],
        ).complete

    def test_covered_positions_reports_only_what_was_found(self):
        found = roster(
            entries=[player("a", position="WR"), player("b", position="RB")],
            unavailable_players=[
                unavailable("k1", UNPROJECTED_POSITION, position="K")
            ],
        )
        assert found.covered_positions == ("RB", "WR")

    def test_an_unprojected_slot_caveat_says_the_total_is_partial(self):
        caveats = roster(
            entries=[player("a")],
            unavailable_players=[
                unavailable("k1", UNPROJECTED_POSITION, position="K", name="Kicker"),
                unavailable("d1", UNPROJECTED_POSITION, position="DST", name="Defense"),
            ],
        ).coverage_caveats
        assert any("not comparable to a full lineup score" in c for c in caveats)
        # Sorted, so the message is stable across runs rather than reflecting
        # whatever order the roster happened to be submitted in.
        assert any("DST, K" in c for c in caveats)
        assert any("2 roster slot(s)" in c for c in caveats)

    def test_a_bye_week_says_absent_not_zero(self):
        # The distinction that decides whether a team total is a lower bound or
        # a wrong number.
        caveats = roster(
            entries=[player("a")],
            unavailable_players=[
                unavailable("p1", NO_PROJECTION, name="Injured Guy")
            ],
        ).coverage_caveats
        assert any("not zero" in c for c in caveats)
        assert any("Injured Guy" in c for c in caveats)

    def test_correlation_caveats_travel_with_coverage_caveats(self):
        # A consumer reads one list. Splitting these would guarantee that some
        # screen shows the missing kicker and forgets the stack.
        caveats = roster(
            entries=[player("a", team="KC"), player("b", team="KC")]
        ).coverage_caveats
        assert any("share an offence" in c for c in caveats)


class TestRequestValidation:
    """These raise before any query, so they need no database."""

    async def test_an_empty_roster_is_rejected(self):
        with pytest.raises(InvalidRequest):
            await rosters.get_roster_projections(None, player_ids=[])  # type: ignore[arg-type]

    async def test_whitespace_only_ids_count_as_empty(self):
        with pytest.raises(InvalidRequest):
            await rosters.get_roster_projections(None, player_ids=["  ", ""])  # type: ignore[arg-type]

    async def test_an_oversized_roster_is_rejected(self):
        too_many = [f"p{i}" for i in range(rosters.MAX_ROSTER_SIZE + 1)]
        with pytest.raises(InvalidRequest) as caught:
            await rosters.get_roster_projections(None, player_ids=too_many)  # type: ignore[arg-type]
        assert caught.value.field == "player_ids"

    def test_duplicate_ids_collapse_preserving_order(self):
        assert rosters._distinct(["b", "a", "b", " a ", "c"]) == ["b", "a", "c"]


class TestExplainingGaps:
    """Attributing an absence to the right cause.

    Driven through a stubbed dimension read rather than a database, because the
    logic under test is the classification, not the SQL.
    """

    @staticmethod
    def _stub(monkeypatch, dimension: dict[str, dict]) -> None:
        async def fake(session, player_ids):
            return {k: v for k, v in dimension.items() if k in set(player_ids)}

        monkeypatch.setattr(rosters.repository, "fetch_player_dimensions", fake)

    async def test_an_unknown_id_is_named_as_such(self, monkeypatch):
        self._stub(monkeypatch, {})
        result = await rosters._explain_missing(None, ["nope"])  # type: ignore[arg-type]
        assert [u.reason for u in result] == [UNKNOWN_PLAYER]
        assert "nope" in result[0].detail

    async def test_a_kicker_is_unprojected_and_carries_its_blockers(self, monkeypatch):
        # The whole point of routing this through POSITION_SUPPORT: the answer
        # to "where is my kicker?" arrives with the reason attached, and adding
        # a kicker model later changes this message with no edit here.
        self._stub(
            monkeypatch,
            {"k1": {"player_id": "k1", "display_name": "Harrison Butker", "position": "K"}},
        )
        result = await rosters._explain_missing(None, ["k1"])  # type: ignore[arg-type]
        assert result[0].reason == UNPROJECTED_POSITION
        assert result[0].position == "K"
        assert "Blocked on:" in result[0].detail
        assert "Harrison Butker" in result[0].detail

    async def test_a_projectable_player_with_no_row_is_transient(self, monkeypatch):
        self._stub(
            monkeypatch,
            {"w1": {"player_id": "w1", "display_name": "Some Receiver", "position": "WR"}},
        )
        result = await rosters._explain_missing(None, ["w1"])  # type: ignore[arg-type]
        assert result[0].reason == NO_PROJECTION
        assert not result[0].is_permanent
        assert "bye" in result[0].detail

    async def test_a_non_fantasy_position_is_permanent_not_transient(self, monkeypatch):
        # An offensive lineman will never be projected either, so reporting him
        # as "nothing published this week" would invite an endless retry.
        self._stub(
            monkeypatch,
            {"g1": {"player_id": "g1", "display_name": "Some Guard", "position": "G"}},
        )
        result = await rosters._explain_missing(None, ["g1"])  # type: ignore[arg-type]
        assert result[0].reason == UNPROJECTED_POSITION
        assert result[0].is_permanent

    async def test_nothing_missing_needs_no_query(self, monkeypatch):
        def explode(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("dimension was queried for an empty gap list")

        monkeypatch.setattr(rosters.repository, "fetch_player_dimensions", explode)
        assert await rosters._explain_missing(None, []) == []  # type: ignore[arg-type]


class TestTheInvariant:
    def test_every_requested_id_is_accounted_for(self):
        # The property that makes this type worth having over a bare list:
        # nothing is dropped quietly.
        result = roster(
            entries=[player("a"), player("b")],
            unavailable_players=[
                unavailable("k1", UNPROJECTED_POSITION),
                unavailable("x1", UNKNOWN_PLAYER),
            ],
        )
        assert len(result.entries) + len(result.unavailable) == len(result.requested)


# ---------------------------------------------------------------------------
# Against a real Postgres
# ---------------------------------------------------------------------------


@pytest.mark.integration
@requires_db
class TestAgainstTheWarehouse:
    """The SQL and the assembly, which unit tests cannot reach.

    The stub warehouse carries four projected skill players. These tests add a
    kicker to the *dimension only* — a player who exists, is on a roster, and
    will never have a projection — because that is the exact shape of the gap
    the simulation engine has to survive and the one no unit test can prove the
    query handles.
    """

    KICKER = "00-0000009"

    @pytest.fixture()
    async def warehouse_with_kicker(self, async_db_session):
        await build_warehouse(async_db_session)
        await async_db_session.execute(
            text(
                "INSERT INTO raw_players (gsis_id, display_name, football_name,"
                " position, latest_team, status, last_season, years_of_experience)"
                " VALUES (:i, :n, :n, 'K', 'KC', 'ACT', :s, 5)"
            ),
            {"i": self.KICKER, "n": "Kilo Kicker", "s": SEASON},
        )
        return async_db_session

    async def test_a_full_roster_of_projected_players_is_complete(self, warehouse_with_kicker):
        result, window = await rosters.get_roster_projections(
            warehouse_with_kicker,
            player_ids=[p[0] for p in PLAYERS],
            season=SEASON,
            week=UPCOMING_WEEK,
            scoring_profile="half_ppr",
        )
        assert window.week == UPCOMING_WEEK
        assert result.complete
        assert len(result.entries) == len(PLAYERS)
        assert result.covered_positions == ("QB", "RB", "TE", "WR")

    async def test_a_kicker_is_reported_not_dropped(self, warehouse_with_kicker):
        # The regression that matters: before this module, the kicker simply
        # vanished and the caller had no way to know its team total was short.
        result, _ = await rosters.get_roster_projections(
            warehouse_with_kicker,
            player_ids=[PLAYERS[0][0], self.KICKER],
            season=SEASON,
            week=UPCOMING_WEEK,
            scoring_profile="half_ppr",
        )
        assert not result.complete
        assert len(result.entries) == 1
        assert [u.reason for u in result.unavailable] == [UNPROJECTED_POSITION]
        gap = result.unavailable[0]
        assert gap.name == "Kilo Kicker"
        assert gap.is_permanent
        assert "Blocked on:" in gap.detail
        assert any("not comparable to a full lineup" in c for c in result.coverage_caveats)

    async def test_every_requested_id_is_accounted_for(self, warehouse_with_kicker):
        requested = [PLAYERS[0][0], self.KICKER, "00-9999999"]
        result, _ = await rosters.get_roster_projections(
            warehouse_with_kicker,
            player_ids=requested,
            season=SEASON,
            week=UPCOMING_WEEK,
            scoring_profile="half_ppr",
        )
        assert len(result.entries) + len(result.unavailable) == len(requested)
        assert {u.reason for u in result.unavailable} == {
            UNPROJECTED_POSITION,
            UNKNOWN_PLAYER,
        }

    async def test_correlated_teammates_are_disclosed(self, warehouse_with_kicker):
        # Alpha Receiver and Bravo Back are both KC in the stub.
        result, _ = await rosters.get_roster_projections(
            warehouse_with_kicker,
            player_ids=[PLAYERS[0][0], PLAYERS[1][0]],
            season=SEASON,
            week=UPCOMING_WEEK,
            scoring_profile="half_ppr",
        )
        groups = rosters.correlation_groups(result.entries)
        assert [g.kind for g in groups] == ["team"]
        assert any("share an offence" in c for c in result.coverage_caveats)

    async def test_dimension_lookup_returns_only_known_ids(self, warehouse_with_kicker):
        found = await repository.fetch_player_dimensions(
            warehouse_with_kicker, [PLAYERS[0][0], "00-9999999"]
        )
        assert set(found) == {PLAYERS[0][0]}
        assert found[PLAYERS[0][0]]["position"] == "WR"

    async def test_an_empty_id_list_does_not_query(self, warehouse_with_kicker):
        assert await repository.fetch_player_dimensions(warehouse_with_kicker, []) == {}
