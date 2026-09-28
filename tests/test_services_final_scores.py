"""Settling a starter whose game is over.

The rules under test are the ones that separate "what they scored" from an
invented number: the official line wins, a game in progress is never settled,
and a final game with no box-score line keeps its projection rather than
becoming a zero. None of it touches the network — the ESPN source is faked at
the provider seam and the id map at the repository.
"""

from __future__ import annotations

import pytest

from nflfp.providers.live import LiveGame, LiveLine
from nflfp.services import final_scores
from nflfp.services.dto import PlayerProjection, PlayerRef, PointDistribution
from nflfp.services.final_scores import (
    SOURCE_LIVE_FINAL,
    SOURCE_OFFICIAL,
    LiveScoreSource,
)


def projection(
    player_id: str, team: str, *, actual: float | None = None
) -> PlayerProjection:
    return PlayerProjection(
        player=PlayerRef(player_id=player_id, name=player_id.upper(), position="WR", team=team),
        season=2026,
        week=3,
        team=team,
        opponent=None,
        is_home=None,
        game_id=None,
        points=PointDistribution(
            scoring_profile="half_ppr",
            expected=12.0,
            predicted=12.0,
            floor=4.0,
            p25=8.0,
            median=11.5,
            p75=15.0,
            ceiling=22.0,
        ),
        actual_points=actual,
    )


def game(event_id: str, home: str, away: str, state: str) -> LiveGame:
    return LiveGame(event_id, home, away, state, None, None, None, None, None, None)


class FakeProvider:
    """The two blocking calls the source makes, with a count of each."""

    def __init__(self, games, boxes, *, fail_scoreboard=False, fail_boxes=()):
        self.games = games
        self.boxes = boxes
        self.fail_scoreboard = fail_scoreboard
        self.fail_boxes = set(fail_boxes)
        self.scoreboard_calls = 0
        self.box_calls: list[str] = []

    def fetch_scoreboard(self, season, week):
        self.scoreboard_calls += 1
        if self.fail_scoreboard:
            raise RuntimeError("timeout")
        return self.games

    def fetch_box(self, event_id):
        self.box_calls.append(event_id)
        if event_id in self.fail_boxes:
            raise RuntimeError("timeout")
        return self.boxes.get(event_id, [])


@pytest.fixture()
def espn_ids(monkeypatch):
    """gsis id == "p" + espn id, served by the repository seam."""

    async def fake(session, ids):
        return [{"espn_id": i, "player_id": f"p{i}"} for i in ids]

    monkeypatch.setattr(final_scores.repository, "fetch_players_by_espn_id", fake)


async def resolve(entries, provider):
    return await final_scores.resolve(
        None,
        entries,
        season=2026,
        week=3,
        scoring_profile="half_ppr",
        source=LiveScoreSource(lambda: provider),
    )


RECEIVING = {"receptions": 6.0, "receiving_yards": 94.0, "receiving_tds": 1.0}
# 6 * 0.5 + 9.4 + 6 = 18.4 in half-PPR.
RECEIVING_HALF_PPR = 18.4


class TestResolve:
    async def test_the_official_line_is_used_without_asking_espn(self, espn_ids):
        provider = FakeProvider([], {})
        result = await resolve([projection("p1", "GB", actual=21.3)], provider)
        assert result.scores["p1"].points == pytest.approx(21.3)
        assert result.scores["p1"].source == SOURCE_OFFICIAL
        assert result.scores["p1"].official
        # A fully loaded week makes no upstream call at all.
        assert provider.scoreboard_calls == 0

    async def test_a_final_game_is_scored_from_the_box_score(self, espn_ids):
        provider = FakeProvider(
            [game("e1", "GB", "ATL", "post")],
            {"e1": [LiveLine("1", "P1", "GB", "e1", RECEIVING)]},
        )
        result = await resolve([projection("p1", "GB")], provider)
        final = result.scores["p1"]
        assert final.points == pytest.approx(RECEIVING_HALF_PPR)
        assert final.source == SOURCE_LIVE_FINAL
        assert not final.official

    async def test_a_game_in_progress_is_not_settled(self, espn_ids):
        provider = FakeProvider(
            [game("e1", "GB", "ATL", "in")],
            {"e1": [LiveLine("1", "P1", "GB", "e1", RECEIVING)]},
        )
        result = await resolve([projection("p1", "GB")], provider)
        assert "p1" not in result.scores
        assert result.in_progress == ("p1",)
        # A partial score is not a result, so its box score is not even read.
        assert provider.box_calls == []

    async def test_a_game_not_started_is_left_alone(self, espn_ids):
        provider = FakeProvider([game("e1", "GB", "ATL", "pre")], {})
        result = await resolve([projection("p1", "GB")], provider)
        assert result.scores == {}
        assert result.in_progress == result.no_line == result.unchecked == ()

    async def test_a_final_game_with_no_line_is_not_a_zero(self, espn_ids):
        provider = FakeProvider([game("e1", "GB", "ATL", "post")], {"e1": []})
        result = await resolve([projection("p1", "GB")], provider)
        assert "p1" not in result.scores
        assert result.no_line == ("p1",)

    async def test_espn_team_codes_are_normalised(self, espn_ids):
        # The provider maps LAR -> LA before the service ever sees it; the
        # projection's nflverse code must meet it there.
        provider = FakeProvider(
            [game("e1", "LA", "SF", "post")],
            {"e1": [LiveLine("7", "P7", "LA", "e1", RECEIVING)]},
        )
        result = await resolve([projection("p7", "LA")], provider)
        assert "p7" in result.scores

    async def test_an_unreachable_scoreboard_leaves_everyone_unchecked(self, espn_ids):
        provider = FakeProvider([], {}, fail_scoreboard=True)
        result = await resolve(
            [projection("p1", "GB"), projection("p2", "KC", actual=9.0)], provider
        )
        # The official line needs no upstream and survives the outage.
        assert set(result.scores) == {"p2"}
        assert result.unchecked == ("p1",)

    async def test_a_failed_box_score_leaves_only_that_game_unchecked(self, espn_ids):
        provider = FakeProvider(
            [game("e1", "GB", "ATL", "post"), game("e2", "KC", "DEN", "post")],
            {"e2": [LiveLine("2", "P2", "KC", "e2", RECEIVING)]},
            fail_boxes={"e1"},
        )
        result = await resolve([projection("p1", "GB"), projection("p2", "KC")], provider)
        assert set(result.scores) == {"p2"}
        assert result.unchecked == ("p1",)


class TestCaching:
    async def test_a_final_box_score_is_fetched_once(self, espn_ids):
        provider = FakeProvider(
            [game("e1", "GB", "ATL", "post")],
            {"e1": [LiveLine("1", "P1", "GB", "e1", RECEIVING)]},
        )
        source = LiveScoreSource(lambda: provider)
        for _ in range(3):
            await final_scores.resolve(
                None, [projection("p1", "GB")],
                season=2026, week=3, scoring_profile="half_ppr", source=source,
            )
        assert provider.box_calls == ["e1"]
        assert provider.scoreboard_calls == 1

    async def test_the_scoreboard_expires(self, espn_ids):
        now = [0.0]
        provider = FakeProvider([game("e1", "GB", "ATL", "in")], {})
        source = LiveScoreSource(lambda: provider, clock=lambda: now[0])
        await source.scoreboard(2026, 3)
        now[0] = final_scores.SCOREBOARD_TTL_SECONDS + 1
        await source.scoreboard(2026, 3)
        assert provider.scoreboard_calls == 2
