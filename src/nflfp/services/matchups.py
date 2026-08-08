"""Matchup analysis and team outlook — a game and a team, viewed as football.

Both of these are assemblies rather than computations: the numbers already
exist, and the value is in putting the right ones next to each other. A matchup
screen that shows a defence's overall rank is nearly useless, because "good
defence" is not one number — a front seven that erases running backs can be a
smash spot for tight ends, and that split is most of what a matchup is worth.
So the analysis is always **per position**, from both sides of the game.

Every defensive number here is a trailing average over completed games strictly
before the week in question. That is not a detail: it is what makes the screen
usable on a Thursday, and it is why the repository computes the window at read
time instead of reading ``feat_defense_position_rolling``, which has no row for
a game that has not been played.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from . import assemble, grading, repository
from .assemble import SUPPORTED_POSITIONS
from .catalog import resolve_scoring_profile, resolve_window, team_index
from .dto import (
    GameContext,
    MatchupAnalysis,
    PositionMatchup,
    SlateWindow,
    TeamOutlook,
    TeamRef,
    WeatherContext,
)
from .errors import NotFound
from .projections import get_game_board, get_slate

logger = logging.getLogger(__name__)

#: Players shown on a matchup screen. Enough for both teams' relevant starters
#: without turning a game page into a slate.
MATCHUP_BOARD_SIZE = 24


def _position_matchups(rows: Sequence[dict]) -> tuple[PositionMatchup, ...]:
    """Grade one defence across every position it has faced."""
    graded = []
    for row in rows:
        grade = grading.grade_matchup(
            defense_rank=assemble.as_int(row, "fp_allowed_rank"),
            sample_games=assemble.as_int(row, "games_in_window"),
        )
        graded.append(
            PositionMatchup(
                position=str(row["position"]),
                grade=grade,
                fp_allowed_l4=assemble.as_float(row, "fp_allowed_l4"),
                targets_allowed_l4=assemble.as_float(row, "targets_allowed_l4"),
                carries_allowed_l4=assemble.as_float(row, "carries_allowed_l4"),
                yards_allowed_l4=assemble.as_float(row, "yards_allowed_l4"),
            )
        )
    order = {position: index for index, position in enumerate(SUPPORTED_POSITIONS)}
    return tuple(sorted(graded, key=lambda m: order.get(m.position, 99)))


def _contexts(rows: Sequence[dict], team: str) -> tuple[GameContext | None, WeatherContext | None]:
    """Pull one team's game and weather context out of a per-team result set."""
    for row in rows:
        if str(row.get("team")) == team:
            weather = (
                assemble.weather_context(row)
                if row.get("weather_source") not in (None, "none")
                else None
            )
            return assemble.game_context(row), weather
    return None, None


async def get_matchup(
    session: AsyncSession,
    *,
    game_id: str,
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
) -> MatchupAnalysis:
    """Analyse one game from both sides.

    Raises:
        NotFound: if the game is not on the schedule for the resolved window.
    """
    window = await resolve_window(session, season=season, week=week)
    profile = resolve_scoring_profile(scoring_profile)

    games = await repository.fetch_games(session, season=window.season, week=window.week)
    game = next((g for g in games if str(g["game_id"]) == game_id), None)
    if game is None:
        raise NotFound("game", game_id)

    home_abbr = str(game["home_team"])
    away_abbr = str(game["away_team"])
    teams = await team_index(session)

    context_rows = await repository.fetch_game_context(
        session, season=window.season, week=window.week, game_id=game_id
    )
    home_game, home_weather = _contexts(context_rows, home_abbr)

    defense_rows = await repository.fetch_defense_form(
        session,
        season=window.season,
        week=window.week,
        defteams=[home_abbr, away_abbr],
    )
    defense: dict[str, tuple[PositionMatchup, ...]] = {}
    for abbr in (home_abbr, away_abbr):
        defense[abbr] = _position_matchups(
            [row for row in defense_rows if str(row["defteam"]) == abbr]
        )

    board = await get_game_board(
        session,
        game_id=game_id,
        season=window.season,
        week=window.week,
        scoring_profile=profile,
    )

    return MatchupAnalysis(
        game_id=game_id,
        season=window.season,
        week=window.week,
        home=teams.get(home_abbr.upper(), TeamRef(abbr=home_abbr)),
        away=teams.get(away_abbr.upper(), TeamRef(abbr=away_abbr)),
        game=home_game,
        # Weather belongs to the venue, so the home side's row describes both.
        weather=home_weather,
        defense=defense,
        top_projections=board[:MATCHUP_BOARD_SIZE],
    )


async def list_matchups(
    session: AsyncSession, *, season: int | None = None, week: int | None = None
) -> tuple[tuple[dict, ...], SlateWindow]:
    """Every game in a week, with scores or market as available.

    Returns raw game rows rather than a dataclass: this feeds a schedule grid,
    which needs the schedule and nothing derived, and inventing a DTO for it
    would be ceremony.
    """
    window = await resolve_window(session, season=season, week=week)
    games = await repository.fetch_games(
        session, season=window.season, week=window.week
    )
    return tuple(games), window


async def get_week(
    session: AsyncSession, *, week: int | None = None, season: int | None = None
) -> tuple[dict, SlateWindow]:
    """One week's summary: the schedule, and whether it has a board yet.

    The landing screen for a week, and the endpoint that answers the question a
    client otherwise has to infer from an empty list: *is there nothing here,
    or has the projection job simply not run?* Those are the same 200 with the
    same empty array, and telling them apart by guessing is how a UI ends up
    reporting an outage that is really a Tuesday.

    So the summary states it directly — ``projections_published``,
    ``projection_count``, and the run behind them — alongside the schedule and
    how many games have already been played.

    Returns:
        The summary and the resolved window. Never raises for an unprojected
        week; a week that is merely on the schedule is a valid answer.
    """
    window = await resolve_window(session, season=season, week=week)
    games = await repository.fetch_games(
        session, season=window.season, week=window.week
    )
    run = await repository.published_run_for_week(
        session, season=window.season, week=window.week
    )

    completed = sum(1 for game in games if not game.get("is_upcoming"))
    summary = {
        "season": window.season,
        "week": window.week,
        "games": tuple(games),
        "game_count": len(games),
        "completed_games": completed,
        "upcoming_games": len(games) - completed,
        "projections_published": run is not None,
        "projection_count": int(run["projection_count"]) if run else 0,
        "model": assemble.model_ref(run) if run else None,
    }
    return summary, window


async def get_defense_rankings(
    session: AsyncSession,
    *,
    position: str | None = None,
    season: int | None = None,
    week: int | None = None,
) -> tuple[dict[str, tuple[PositionMatchup, ...]], SlateWindow]:
    """Every defence's form as of a week, keyed by team.

    The "which defences should I attack?" screen. Ranks are computed within
    position over the trailing four completed games, so rank 1 is the toughest
    defence against that position — the same convention as
    ``Projection.defense_rank_vs_position``.
    """
    window = await resolve_window(session, season=season, week=week)
    rows = await repository.fetch_defense_form(
        session,
        season=window.season,
        week=window.week,
        positions=[position.strip().upper()] if position else None,
    )
    by_team: dict[str, list[dict]] = {}
    for row in rows:
        by_team.setdefault(str(row["defteam"]), []).append(row)
    return (
        {team: _position_matchups(team_rows) for team, team_rows in by_team.items()},
        window,
    )


async def get_team_outlook(
    session: AsyncSession,
    *,
    team: str,
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
) -> TeamOutlook:
    """A team's week: the game, the market, and its projected skill players.

    ``projected_points`` sums the calibrated expectations of the team's
    projected players. It is **not** a projected team score: it excludes
    kickers, defensive scoring and every unprojected player, and it is in
    fantasy points rather than real ones. It is useful for comparing offences
    against each other, which is what it is there for.
    """
    window = await resolve_window(session, season=season, week=week)
    profile = resolve_scoring_profile(scoring_profile)
    abbr = team.strip().upper()

    teams = await team_index(session)
    if abbr not in teams:
        # The dimension may simply not be ingested; fall back to a bare
        # reference rather than 404-ing a team that plainly exists in the
        # schedule.
        logger.info("team %s not in the team dimension", abbr)

    slate, _ = await get_slate(
        session,
        season=window.season,
        week=window.week,
        scoring_profile=profile,
        teams=[abbr],
        limit=64,
    )
    if not slate.entries and abbr not in teams:
        raise NotFound("team", team)

    context_rows = await repository.fetch_game_context(
        session, season=window.season, week=window.week, teams=[abbr]
    )
    game, weather = _contexts(context_rows, abbr)

    expectations = [
        entry.projection.points.headline
        for entry in slate.entries
        if entry.projection.points.headline is not None
    ]

    return TeamOutlook(
        team=teams.get(abbr, TeamRef(abbr=abbr)),
        season=window.season,
        week=window.week,
        game=game,
        weather=weather,
        players=slate.entries,
        projected_points=sum(expectations) if expectations else None,
        scoring_profile=profile,
    )
