"""Slates, rankings and a single player's week.

Every route here is four lines of work: unpack params, call one service, map
the result, attach meta. That is the shape the layering is for — if a route
ever needs a second service call to answer one question, the missing function
belongs in the business layer, not here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from ...services import projections as service
from .. import mappers, schemas
from ..dependencies import DbSession, PageQuery, SlateQuery

router = APIRouter(tags=["projections"])

Board = schemas.Envelope[list[schemas.RankedProjectionOut]]


def _meta(slate, window, page: PageQuery | None = None) -> schemas.MetaOut:
    """Build the response meta, including the notice for an unpublished week."""
    notices: list[str] = []
    if slate.model is None:
        notices.append(
            f"No projection run is published for {slate.season} week {slate.week}. "
            "This is an empty board, not an error — meta.model is null."
        )
    ungraded = sum(
        1
        for entry in slate.entries
        if entry.projection.matchup is None or not entry.projection.matchup.grade.graded
    )
    if ungraded:
        notices.append(
            f"{ungraded} of {len(slate.entries)} matchups could not be graded "
            "(fewer than three completed games of defensive history)."
        )
    return schemas.MetaOut(
        window=schemas.slate_window_out(window),
        scoring_profile=slate.scoring_profile,
        model=mappers.model_ref(slate.model),
        page=(
            None
            if page is None
            else schemas.PageOut(
                total=slate.total,
                limit=page.limit,
                offset=page.offset,
                returned=len(slate.entries),
            )
        ),
        notices=notices,
    )


@router.get(
    "/projections",
    response_model=Board,
    summary="The ranked board for a week",
    description=(
        "Projections from the published model run, ranked by calibrated "
        "expectation and grouped into tiers derived from the outcome "
        "distributions.\n\n"
        "Each entry separates **prediction** (model output), **matchup** and "
        "**usage** (derived above the model) and **context** (observed, not "
        "used by the model). Check `context.*.applied_to_projection` before "
        "implying the projection accounts for weather, market or injury.\n\n"
        "A week with nothing published returns an empty list with "
        "`meta.model = null` — an operational state, not an error."
    ),
)
async def list_projections(
    db: DbSession,
    slate_query: SlateQuery,
    page: PageQuery,
    positions: Annotated[
        list[str] | None,
        Query(description="Filter by position. See /meta/positions for what is projected."),
    ] = None,
    teams: Annotated[list[str] | None, Query(description="Filter by team abbreviation.")] = None,
    model_name: Annotated[
        str | None, Query(description="Pin to one model rather than whatever is published.")
    ] = None,
) -> Board:
    slate, window = await service.get_slate(
        db,
        season=slate_query.season,
        week=slate_query.week,
        scoring_profile=slate_query.scoring_profile,
        positions=positions,
        teams=teams,
        model_name=model_name,
        limit=page.limit,
        offset=page.offset,
    )
    return Board(
        data=[mappers.ranked(entry) for entry in slate.entries],
        meta=_meta(slate, window, page),
    )


@router.get(
    "/rankings/{position}",
    response_model=Board,
    summary="A single-position board",
    description=(
        "The QB/RB/WR/TE rankings screen. `positional_rank` runs 1..N within "
        "the filtered set.\n\n"
        "Requesting a recognised but unprojected position (K, DST) returns 422 "
        "with the reason and what it is blocked on — see /meta/positions."
    ),
)
async def position_rankings(
    db: DbSession,
    slate_query: SlateQuery,
    page: PageQuery,
    position: Annotated[str, Path(description="QB, RB, WR or TE.")],
) -> Board:
    slate, window = await service.get_position_rankings(
        db,
        position=position,
        season=slate_query.season,
        week=slate_query.week,
        scoring_profile=slate_query.scoring_profile,
        limit=page.limit,
    )
    return Board(
        data=[mappers.ranked(entry) for entry in slate.entries],
        meta=_meta(slate, window, page),
    )


@router.get(
    "/projections/{player_id}",
    response_model=schemas.Envelope[schemas.ProjectionOut],
    summary="One player's projection for one week",
    responses={404: {"model": schemas.ErrorOut}},
)
async def get_projection(
    db: DbSession,
    slate_query: SlateQuery,
    player_id: Annotated[str, Path(description="nflverse gsis id, e.g. 00-0036322.")],
) -> schemas.Envelope[schemas.ProjectionOut]:
    projection = await service.get_projection(
        db,
        player_id=player_id,
        season=slate_query.season,
        week=slate_query.week,
        scoring_profile=slate_query.scoring_profile,
    )
    return schemas.Envelope[schemas.ProjectionOut](
        data=mappers.projection(projection),
        meta=schemas.MetaOut(
            window=schemas.SlateWindowOut(
                season=projection.season,
                week=projection.week,
                resolution="explicit" if slate_query.week else "upcoming",
                is_upcoming=True,
            ),
            scoring_profile=projection.points.scoring_profile,
            model=mappers.model_ref(projection.model),
        ),
    )
