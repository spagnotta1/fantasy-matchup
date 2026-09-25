"""Live scoring: this week's games in progress, and each player's points so far.

Provenance: ``actual`` — but **unofficial**. The numbers are ESPN's in-game box
score scored with this app's own rules (:mod:`nflfp.scoring`), which is the
same arithmetic the official line is scored with; what differs is the input.
ESPN's box score carries no two-point conversions, and a Monday stat
correction is not in it. The official nflverse line replaces all
of it once the week is loaded, and the response says so.

Each live line sits beside the player's published projection for the week,
unchanged. A live total is never blended into the projection or used to
"update" it: the projection is what the model said beforehand, and the two
answer different questions.

A failed upstream is a notice, not an error: the rest of the product does not
depend on live data, and a scoreboard outage must not turn a page into a 500.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..providers.live import EspnLiveProvider, LiveGame, LiveWeek
from ..scoring import PROFILES, points_for
from . import assemble, repository
from .catalog import resolve_scoring_profile, resolve_window
from .dto import SlateWindow

LIVE_POSITIONS = ("QB", "RB", "WR", "TE")

NOTICE_UNOFFICIAL = (
    "Live points come from ESPN's in-game box score, scored with your scoring "
    "settings. They are unofficial: two-point conversions and stat corrections are "
    "not included, and official numbers replace them once the week is final."
)


@dataclass(frozen=True)
class LivePlayer:
    player_id: str
    name: str
    position: str
    team: str
    headshot_url: str | None
    event_id: str
    live_points: float
    projected: float | None
    floor: float | None
    ceiling: float | None
    components: Mapping[str, float]


@dataclass(frozen=True)
class LiveSlate:
    season: int
    week: int
    scoring_profile: str
    games: tuple[LiveGame, ...]
    players: tuple[LivePlayer, ...]
    window: SlateWindow
    notices: tuple[str, ...]


def score_lines(
    week: LiveWeek,
    players_by_espn: Mapping[str, Mapping[str, object]],
    projections: Mapping[str, Mapping[str, object]],
    scoring_profile: str,
) -> list[LivePlayer]:
    """Score each box-score line and set it beside the projection. Pure.

    Lines for players the warehouse cannot identify, or at positions this app
    does not project, are dropped — a kicker's box score is not a fantasy line
    here, and an unmatched id has no projection to stand beside.
    """
    rules = PROFILES[scoring_profile]
    scored: list[LivePlayer] = []
    for line in week.lines:
        player = players_by_espn.get(line.espn_id)
        if not player:
            continue
        position = str(player.get("position") or "")
        if position not in LIVE_POSITIONS:
            continue
        player_id = str(player["player_id"])
        projection = projections.get(player_id, {})
        scored.append(
            LivePlayer(
                player_id=player_id,
                name=str(player.get("display_name") or line.name),
                position=position,
                team=line.team,
                headshot_url=(str(player["headshot"]) if player.get("headshot") else None),
                event_id=line.event_id,
                live_points=round(points_for(dict(line.components), rules, position), 2),
                projected=assemble.as_float(projection, "headline"),
                floor=assemble.as_float(projection, "floor_points"),
                ceiling=assemble.as_float(projection, "ceiling_points"),
                components=dict(line.components),
            )
        )
    scored.sort(key=lambda p: (-p.live_points, p.player_id))
    return scored


async def get_live(
    session: AsyncSession,
    *,
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
    provider_factory: Callable[[], EspnLiveProvider] = EspnLiveProvider,
) -> LiveSlate:
    """This week's live games and every started player's unofficial points."""
    window = await resolve_window(session, season=season, week=week)
    profile = resolve_scoring_profile(scoring_profile)

    provider = provider_factory()
    live = await asyncio.to_thread(provider.fetch_week, window.season, window.week)

    espn_ids = sorted({line.espn_id for line in live.lines})
    players = {
        str(row["espn_id"]): row
        for row in await repository.fetch_players_by_espn_id(session, espn_ids)
    }
    player_ids = sorted({str(row["player_id"]) for row in players.values()})
    projection_rows: Sequence[dict] = (
        await repository.fetch_projections(
            session,
            season=window.season,
            week=window.week,
            scoring_profile=profile,
            player_ids=player_ids,
        )
        if player_ids
        else []
    )
    projections = {
        str(row["player_id"]): {
            **row,
            "headline": row.get("expected_points")
            if row.get("expected_points") is not None
            else row.get("predicted_points"),
        }
        for row in projection_rows
    }

    notices = [NOTICE_UNOFFICIAL]
    if live.warnings:
        notices.append(
            "Some live data could not be loaded just now ("
            + "; ".join(live.warnings[:3])
            + "). Showing what did arrive."
        )
    if live.games and all(game.state == "pre" for game in live.games):
        notices.append("No game this week has kicked off yet.")

    return LiveSlate(
        season=window.season,
        week=window.week,
        scoring_profile=profile,
        games=tuple(live.games),
        players=tuple(score_lines(live, players, projections, profile)),
        window=window,
        notices=tuple(notices),
    )
