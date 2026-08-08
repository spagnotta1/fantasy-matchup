"""Shared request plumbing.

Query parameters that appear on more than one endpoint are declared once here
and injected, so ``?season=&week=&scoring_profile=`` means the same thing and
validates the same way everywhere. An endpoint that re-declared them would
drift the first time a bound changed.

Authentication is not implemented, and the shape below is why it will not
require touching every route when it is: :func:`current_principal` already
exists as a dependency and already returns an anonymous principal. Adding real
auth is an implementation change inside one function plus a router-level
dependency, not a signature change across thirty endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db.engine import get_db_session
from ..services import catalog, projections

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class SlateParams:
    """Season, week and scoring format — the arguments almost everything takes.

    All three are optional at the edge and resolved inside the service layer,
    which is what keeps "what does the current week mean?" a single decision
    rather than one per endpoint.
    """

    season: int | None
    week: int | None
    scoring_profile: str | None


def slate_params(
    season: Annotated[
        int | None,
        Query(
            ge=1999,
            le=2200,
            description="Season. Defaults to the current league year, which rolls over in March.",
        ),
    ] = None,
    week: Annotated[
        int | None,
        Query(
            ge=catalog.MIN_WEEK,
            le=catalog.MAX_WEEK,
            description=(
                "Week. Defaults to the upcoming slate — the earliest week with "
                "a game that has no result — falling back to the latest "
                "completed week once the season ends. The response reports "
                "which in meta.window.resolution."
            ),
        ),
    ] = None,
    scoring_profile: Annotated[
        str | None,
        Query(
            description=(
                "League format: standard, half_ppr, ppr, ppr_te_premium. "
                "Defaults to the configured profile. An unknown value is "
                "refused rather than silently defaulted."
            )
        ),
    ] = None,
) -> SlateParams:
    return SlateParams(season=season, week=week, scoring_profile=scoring_profile)


SlateQuery = Annotated[SlateParams, Depends(slate_params)]


@dataclass(frozen=True)
class PageParams:
    """Limit and offset, bounded at the edge as well as in the service."""

    limit: int
    offset: int


def page_params(
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=projections.MAX_PAGE_SIZE,
            description="Rows to return. An entire slate fits in one page.",
        ),
    ] = projections.DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, description="Rows to skip.")] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


PageQuery = Annotated[PageParams, Depends(page_params)]


@dataclass(frozen=True)
class Principal:
    """Who is making the request.

    Anonymous for now. It exists so that endpoints already accept a principal
    and per-user features — saved lineups, league-specific scoring, rate limits
    — arrive without a signature change everywhere.
    """

    subject: str = "anonymous"
    authenticated: bool = False
    scopes: tuple[str, ...] = ()


async def current_principal() -> Principal:
    """Resolve the caller. Anonymous until authentication is implemented."""
    return Principal()


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
