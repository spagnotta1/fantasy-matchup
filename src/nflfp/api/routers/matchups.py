"""Games, matchup analysis, defensive rankings and team outlook.

Everything here carries ``derived`` provenance: it is computed above the model
from trailing defensive aggregates the model never consumed. The endpoints say
so in their schemas rather than only in this docstring, because a client reads
fields and not module comments.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from ...services import matchups as service
from .. import mappers, schemas
from ..dependencies import DbSession, SlateQuery

router = APIRouter(tags=["matchups"])


@router.get(
    "/games",
    response_model=schemas.Envelope[list[schemas.GameOut]],
    summary="The schedule for a week",
)
async def list_games(
    db: DbSession, slate_query: SlateQuery
) -> schemas.Envelope[list[schemas.GameOut]]:
    games, window = await service.list_matchups(
        db, season=slate_query.season, week=slate_query.week
    )
    return schemas.Envelope[list[schemas.GameOut]](
        data=[mappers.game(row) for row in games],
        meta=schemas.MetaOut(window=schemas.slate_window_out(window)),
    )


@router.get(
    "/weeks/{week}",
    response_model=schemas.Envelope[schemas.WeekOut],
    summary="One week: the schedule, and whether it has a board yet",
    description=(
        "The landing call for a week. It answers the question an empty "
        "projections list cannot: *is there nothing here, or has the "
        "projection job simply not run?* Those produce the same `200` with the "
        "same empty array, and a client that guesses reports an outage that is "
        "really a Tuesday.\n\n"
        "`projections_published` is the flag to branch on; `model` names the "
        "run behind the numbers, and `projection_count` catches the state "
        "where a run is published but empty."
    ),
)
async def get_week(
    db: DbSession,
    week: Annotated[int, Path(ge=1, le=22, description="Week of the season.")],
    season: Annotated[int | None, Query(ge=1999, le=2200)] = None,
) -> schemas.Envelope[schemas.WeekOut]:
    summary, window = await service.get_week(db, week=week, season=season)
    return schemas.Envelope[schemas.WeekOut](
        data=mappers.week(summary),
        meta=schemas.MetaOut(
            window=schemas.slate_window_out(window),
            model=mappers.model_ref(summary["model"]),
            notices=(
                []
                if summary["projections_published"]
                else [
                    f"No projection run is published for {window.season} week "
                    f"{window.week}. The schedule is final; the board is not "
                    "generated until the weekly job runs."
                ]
            ),
        ),
    )


@router.get(
    "/matchups/{game_id}",
    response_model=schemas.Envelope[schemas.MatchupAnalysisOut],
    responses={404: {"model": schemas.ErrorOut}},
    summary="One game, analysed from both sides",
    description=(
        "Defensive strength is split **per position**, because 'good defence' "
        "is not one number — a front seven that erases running backs can be a "
        "smash spot for tight ends, and that split is most of what a matchup "
        "is worth.\n\n"
        "Every defensive figure is a trailing average over completed games "
        "strictly before this week, which is what makes the screen usable on a "
        "Thursday. Provenance is `derived`: the model does not consume it."
    ),
)
async def get_matchup(
    db: DbSession,
    slate_query: SlateQuery,
    game_id: Annotated[str, Path(description="nflverse game id, e.g. 2025_10_KC_BUF.")],
) -> schemas.Envelope[schemas.MatchupAnalysisOut]:
    analysis = await service.get_matchup(
        db,
        game_id=game_id,
        season=slate_query.season,
        week=slate_query.week,
        scoring_profile=slate_query.scoring_profile,
    )
    return schemas.Envelope[schemas.MatchupAnalysisOut](
        data=mappers.matchup_analysis(analysis),
        meta=schemas.MetaOut(
            window=schemas.SlateWindowOut(
                season=analysis.season,
                week=analysis.week,
                resolution="explicit" if slate_query.week else "upcoming",
                is_upcoming=True,
            )
        ),
    )


@router.get(
    "/defense-rankings",
    response_model=schemas.Envelope[dict[str, list[schemas.PositionMatchupOut]]],
    summary="Every defence's form as of a week, keyed by team",
    description=(
        "The 'which defences should I attack?' screen. Rank 1 is the "
        "**toughest** defence against that position, matching the convention "
        "used everywhere else. Grades are withheld below three completed games "
        "of history rather than softened — Week 1 is legitimately ungraded."
    ),
)
async def defense_rankings(
    db: DbSession,
    slate_query: SlateQuery,
    position: Annotated[str | None, Query(description="Restrict to one position.")] = None,
) -> schemas.Envelope[dict[str, list[schemas.PositionMatchupOut]]]:
    rankings, window = await service.get_defense_rankings(
        db, position=position, season=slate_query.season, week=slate_query.week
    )
    return schemas.Envelope[dict[str, list[schemas.PositionMatchupOut]]](
        data={
            abbr: [mappers.position_matchup(entry) for entry in entries]
            for abbr, entries in rankings.items()
        },
        meta=schemas.MetaOut(
            window=schemas.slate_window_out(window),
            notices=(
                []
                if rankings
                else [
                    "No completed defensive history before this week, so no "
                    "defence can be ranked."
                ]
            ),
        ),
    )


@router.get(
    "/teams/{team}/outlook",
    response_model=schemas.Envelope[schemas.TeamOutlookOut],
    responses={404: {"model": schemas.ErrorOut}},
    summary="A team's week: the game, the market, and its projected players",
    description=(
        "`projected_points` sums the calibrated expectations of projected "
        "skill players. It is **not** a projected team score: no kickers, no "
        "defensive scoring, and in fantasy points rather than real ones."
    ),
)
async def team_outlook(
    db: DbSession,
    slate_query: SlateQuery,
    team: Annotated[str, Path(description="Team abbreviation, e.g. KC.")],
) -> schemas.Envelope[schemas.TeamOutlookOut]:
    outlook = await service.get_team_outlook(
        db,
        team=team,
        season=slate_query.season,
        week=slate_query.week,
        scoring_profile=slate_query.scoring_profile,
    )
    return schemas.Envelope[schemas.TeamOutlookOut](
        data=mappers.team_outlook(outlook),
        meta=schemas.MetaOut(scoring_profile=outlook.scoring_profile),
    )
