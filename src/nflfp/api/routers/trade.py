"""Trade values — rest-of-season worth above the waiver wire, for the trade analyzer.

Every number here is ``derived``: this week's published projection read as a
rate, carried over the games left and scaled by historical availability, then
measured from the waiver wire. It is not a rest-of-season forecast and the
response says so in ``meta.notices``. A trade verdict is the client's arithmetic
on these values, and it inherits all of their limits.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ...services import trade as trade_service
from ...services.draft.settings import MAX_TEAMS, MIN_TEAMS
from .. import mappers, schemas
from ..dependencies import DbSession, SlateQuery

router = APIRouter(tags=["trade"], prefix="/trade")


@router.get(
    "/values",
    response_model=schemas.Envelope[schemas.TradeValuesOut],
    summary="Rest-of-season trade value for every projected player",
    description=(
        "One number per player that can be added up across a trade: "
        "rest-of-season points above the waiver wire.\n\n"
        "`rest_of_season` is the week's published expected points (`model`) "
        "used as a per-game rate, times the games the team has left counting "
        "this week, times the player's historical availability (`derived`). "
        "It is a rate carried forward, not a forecast: no injury, role change "
        "or trade from here on is in it.\n\n"
        "`trade_value` subtracts the best unrostered player at the position "
        "for a `teams`-team league on the default roster, with benches assumed "
        "to hold positions in the lineup's proportions, and floors at zero. "
        "A player on a bye-week team is valued from their most recent "
        "published week and carries `on_bye`. A player with no projection this "
        "week for any other reason is absent. An unpublished week is an empty "
        "list with a notice."
    ),
)
async def trade_values(
    db: DbSession,
    slate_query: SlateQuery,
    teams: Annotated[
        int,
        Query(ge=MIN_TEAMS, le=MAX_TEAMS, description="Managers in the league."),
    ] = trade_service.DEFAULT_TEAMS,
) -> schemas.Envelope[schemas.TradeValuesOut]:
    result = await trade_service.get_trade_values(
        db,
        season=slate_query.season,
        week=slate_query.week,
        scoring_profile=slate_query.scoring_profile,
        teams=teams,
    )
    return schemas.Envelope[schemas.TradeValuesOut](
        data=mappers.trade_values(result),
        meta=schemas.MetaOut(
            window=schemas.slate_window_out(result.window),
            scoring_profile=result.scoring_profile,
            model=mappers.model_ref(result.model),
            notices=list(result.notices),
        ),
    )
