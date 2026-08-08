"""Player search, dimension records, history and the assembled profile."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from ...services import players as service
from .. import mappers, schemas
from ..dependencies import DbSession, SlateQuery

router = APIRouter(tags=["players"])


@router.get(
    "/players",
    response_model=schemas.Envelope[list[schemas.PlayerOut]],
    summary="Browse the player index",
    description=(
        "Alphabetical, paginated, filterable by position and team. This is the "
        "listing to build a roster picker from; `/search` needs a name, and "
        "this is for when you do not have one — \"who plays for KC?\" has no "
        "search term.\n\n"
        "Ordering is by name rather than by anything derived, deliberately: a "
        "listing that reorders itself between page 1 and page 2 makes paging "
        "skip players. Every *ranked* listing already exists elsewhere.\n\n"
        "Unprojected positions (K, DST) are accepted here — listing a kicker "
        "is reasonable, and only asking for a projection of one is refused."
    ),
)
async def list_players(
    db: DbSession,
    positions: Annotated[
        list[str] | None, Query(description="Filter by position, e.g. WR.")
    ] = None,
    teams: Annotated[
        list[str] | None, Query(description="Filter by team abbreviation, e.g. KC.")
    ] = None,
    active_only: Annotated[
        bool, Query(description="Exclude retired and inactive players.")
    ] = True,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE_SIZE)] = service.DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.Envelope[list[schemas.PlayerOut]]:
    found, total = await service.list_players(
        db,
        positions=positions,
        teams=teams,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return schemas.Envelope[list[schemas.PlayerOut]](
        data=[mappers.player(ref) for ref in found],
        meta=schemas.MetaOut(
            page=schemas.PageOut(
                total=total, limit=limit, offset=offset, returned=len(found)
            )
        ),
    )


@router.get(
    "/search",
    response_model=schemas.Envelope[list[schemas.PlayerOut]],
    summary="Find players by name",
    description=(
        "Prefix matches rank above substring matches, then by recency of last "
        "season. Search accepts unprojected positions (K, DST) — looking a "
        "kicker up is reasonable even though nothing projects them."
    ),
)
async def search_players(
    db: DbSession,
    q: Annotated[str, Query(min_length=service.MIN_SEARCH_LENGTH, description="Partial name.")],
    limit: Annotated[int, Query(ge=1, le=service.MAX_SEARCH_RESULTS)] = 25,
    positions: Annotated[list[str] | None, Query()] = None,
    active_only: Annotated[
        bool, Query(description="Exclude retired and inactive players.")
    ] = True,
) -> schemas.Envelope[list[schemas.PlayerOut]]:
    found = await service.search(
        db, query=q, limit=limit, positions=positions, active_only=active_only
    )
    return schemas.Envelope[list[schemas.PlayerOut]](
        data=[mappers.player(ref) for ref in found]
    )


@router.get(
    "/players/{player_id}",
    response_model=schemas.Envelope[schemas.PlayerOut],
    responses={404: {"model": schemas.ErrorOut}},
    summary="One player's dimension record",
)
async def get_player(
    db: DbSession, player_id: Annotated[str, Path()]
) -> schemas.Envelope[schemas.PlayerOut]:
    return schemas.Envelope[schemas.PlayerOut](
        data=mappers.player(await service.get_player(db, player_id))
    )


@router.get(
    "/players/{player_id}/history",
    response_model=schemas.Envelope[list[schemas.HistoricalWeekOut]],
    summary="Completed weeks, with the projection made for each",
    description=(
        "`projected_points` is what was stored at the time, not a "
        "regeneration — re-scoring history with today's model answers a "
        "different question and always flatters it. Null where no published "
        "run covered the week."
    ),
)
async def player_history(
    db: DbSession,
    player_id: Annotated[str, Path()],
    scoring_profile: Annotated[str | None, Query()] = None,
    weeks: Annotated[
        int, Query(ge=1, le=service.MAX_HISTORY_WEEKS)
    ] = service.DEFAULT_HISTORY_WEEKS,
) -> schemas.Envelope[list[schemas.HistoricalWeekOut]]:
    history, trend = await service.get_history(
        db, player_id=player_id, scoring_profile=scoring_profile, weeks=weeks
    )
    return schemas.Envelope[list[schemas.HistoricalWeekOut]](
        data=[mappers.historical_week(week) for week in history],
        meta=schemas.MetaOut(
            notices=(
                []
                if trend.graded_games
                else [
                    "No stored projections cover these weeks, so accuracy "
                    "figures are unavailable rather than zero."
                ]
            )
        ),
    )


@router.get(
    "/players/{player_id}/profile",
    response_model=schemas.Envelope[schemas.PlayerProfileOut],
    responses={404: {"model": schemas.ErrorOut}},
    summary="Everything the player page needs, in one call",
    description=(
        "`current` is null when the player has no projection for the resolved "
        "week — a bye, or a run not yet published. The profile still renders; "
        "only an unknown player is a 404."
    ),
)
async def player_profile(
    db: DbSession,
    slate_query: SlateQuery,
    player_id: Annotated[str, Path()],
    weeks: Annotated[
        int, Query(ge=1, le=service.MAX_HISTORY_WEEKS)
    ] = service.DEFAULT_HISTORY_WEEKS,
) -> schemas.Envelope[schemas.PlayerProfileOut]:
    profile = await service.get_profile(
        db,
        player_id=player_id,
        season=slate_query.season,
        week=slate_query.week,
        scoring_profile=slate_query.scoring_profile,
        weeks=weeks,
    )
    return schemas.Envelope[schemas.PlayerProfileOut](
        data=mappers.profile(profile),
        meta=schemas.MetaOut(
            window=schemas.slate_window_out(profile.window),
            scoring_profile=profile.scoring_profile,
            model=mappers.model_ref(profile.current.model if profile.current else None),
            notices=(
                []
                if profile.current
                else [
                    f"No projection published for {profile.player.name} in "
                    f"{profile.window.season} week {profile.window.week}."
                ]
            ),
        ),
    )
