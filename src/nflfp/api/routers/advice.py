"""Start/sit and comparison — the only endpoints that recommend.

Two properties of these responses are contractual and a client should not
paper over either:

* ``recommended`` is **null for a toss-up**, and a toss-up is a real answer.
  Below a 58% win probability the edge is smaller than the model's own error,
  and naming a starter would be false precision.
* ``caveats`` carries availability designations, correlation between players in
  the same game, and extrapolated intervals. A UI that drops them is
  presenting a more confident recommendation than the one the API made.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ...services import advice as service
from .. import mappers, schemas
from ..dependencies import DbSession, SlateQuery

router = APIRouter(tags=["advice"])


@router.get(
    "/start-sit",
    response_model=schemas.Envelope[schemas.StartSitOut],
    responses={404: {"model": schemas.ErrorOut}, 422: {"model": schemas.ErrorOut}},
    summary="Head-to-head start/sit call",
    description=(
        "`win_probability` is P(a outscores b), integrated over both stored "
        "outcome distributions — not a comparison of point estimates. Half a "
        "point of projection is not half a point of certainty, so a 12.4 "
        "versus 11.8 pairing returns roughly 52% and an explicit toss-up.\n\n"
        "The integral assumes independence. Players sharing a game are not "
        "independent and teammates especially so; both cases are detected and "
        "reported in `caveats` rather than silently ignored."
    ),
)
async def start_sit(
    db: DbSession,
    slate_query: SlateQuery,
    player_a: Annotated[str, Query(description="gsis id of the first player.")],
    player_b: Annotated[str, Query(description="gsis id of the second player.")],
) -> schemas.Envelope[schemas.StartSitOut]:
    result = await service.get_start_sit(
        db,
        player_a=player_a,
        player_b=player_b,
        season=slate_query.season,
        week=slate_query.week,
        scoring_profile=slate_query.scoring_profile,
    )
    return schemas.Envelope[schemas.StartSitOut](
        data=mappers.start_sit(result),
        meta=schemas.MetaOut(notices=list(result.caveats)),
    )


@router.get(
    "/compare",
    response_model=schemas.Envelope[schemas.ComparisonOut],
    responses={404: {"model": schemas.ErrorOut}, 422: {"model": schemas.ErrorOut}},
    summary="Compare up to six players",
    description=(
        "Entries are ordered by calibrated expectation, and each consecutive "
        "pair gets a head-to-head call. Consecutive rather than all pairs "
        "because that is the decision being made — 'is the next one down close "
        "enough to matter?' — and a six-player all-pairs table has fifteen "
        "verdicts nobody reads."
    ),
)
async def compare(
    db: DbSession,
    slate_query: SlateQuery,
    player_ids: Annotated[
        list[str],
        Query(description=f"2 to {service.MAX_COMPARISON_PLAYERS} gsis ids."),
    ],
) -> schemas.Envelope[schemas.ComparisonOut]:
    result = await service.compare_players(
        db,
        player_ids=player_ids,
        season=slate_query.season,
        week=slate_query.week,
        scoring_profile=slate_query.scoring_profile,
    )
    return schemas.Envelope[schemas.ComparisonOut](
        data=mappers.comparison(result),
        meta=schemas.MetaOut(scoring_profile=result.scoring_profile),
    )
