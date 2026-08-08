"""Resolving *when* and *what format* a request is about.

Almost every endpoint takes an optional season, an optional week and an
optional scoring profile, and almost every endpoint would otherwise resolve
them slightly differently. Centralising that here means "the current week"
means one thing across the whole API, and changing what it means — during the
playoffs, say — is one edit rather than a search.

What "current week" means
-------------------------
The upcoming slate, not the last completed one. A fantasy app is read on
Thursday and Saturday to decide a lineup, so the default has to be the week
being decided. Concretely: the earliest week of the season that still has a
game without a final score. Once the season ends there is no such week, and the
default falls back to the latest completed one so the app degrades into a
history browser rather than an error page.

The resolution is always reported back in a :class:`~nflfp.services.dto.SlateWindow`,
so a client never has to infer whether it is looking forward or backward.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.enums import ScoringProfile, values as enum_values
from ..sources import current_season
from . import repository
from .assemble import team_ref
from .dto import SlateWindow, TeamRef
from .errors import InvalidRequest, NotFound, UnknownScoringProfile

logger = logging.getLogger(__name__)

#: Weeks a request may name. 1-18 regular season plus four playoff rounds; the
#: database's own CHECK allows 1-25, and this narrower bound is the one a user
#: could plausibly type.
MIN_WEEK = 1
MAX_WEEK = 22


def scoring_profiles() -> tuple[str, ...]:
    """League formats projections are published for."""
    return enum_values(ScoringProfile)


def resolve_scoring_profile(scoring_profile: str | None) -> str:
    """Validate a requested format, or fall back to the configured default.

    Raises:
        UnknownScoringProfile: if the caller named a format that is not
            published. Deliberately not a silent fallback: a user who asked for
            PPR and quietly received half-PPR would make lineup decisions on
            numbers that are not the ones they asked for.
    """
    if scoring_profile is None:
        return get_settings().default_scoring_profile
    known = scoring_profiles()
    if scoring_profile not in known:
        raise UnknownScoringProfile(scoring_profile, known)
    return scoring_profile


async def resolve_window(
    session: AsyncSession, *, season: int | None = None, week: int | None = None
) -> SlateWindow:
    """Work out which season and week a request means.

    Args:
        session: Open async session.
        season: Explicit season, or ``None`` for the current league year.
        week: Explicit week, or ``None`` to resolve the upcoming slate.

    Returns:
        The resolved window, including how it was resolved.

    Raises:
        InvalidRequest: for a week outside the plausible range.
        NotFound: for a season with no games in the warehouse at all — which
            means the schedule has not been ingested, not that the caller is
            wrong, so the message says so.
    """
    if week is not None and not MIN_WEEK <= week <= MAX_WEEK:
        raise InvalidRequest(
            f"week must be between {MIN_WEEK} and {MAX_WEEK}, got {week}", field="week"
        )

    resolved_season = season if season is not None else current_season()

    if week is not None:
        upcoming = await repository.first_upcoming_week(session, resolved_season)
        return SlateWindow(
            season=resolved_season,
            week=week,
            resolution="explicit",
            is_upcoming=upcoming is not None and week >= upcoming,
        )

    upcoming = await repository.first_upcoming_week(session, resolved_season)
    if upcoming is not None:
        return SlateWindow(
            season=resolved_season,
            week=int(upcoming),
            resolution="upcoming",
            is_upcoming=True,
        )

    completed = await repository.latest_completed_week(session, resolved_season)
    if completed is not None:
        return SlateWindow(
            season=resolved_season,
            week=int(completed),
            resolution="latest_completed",
            is_upcoming=False,
        )

    raise NotFound("season", resolved_season)


async def list_teams(session: AsyncSession) -> tuple[TeamRef, ...]:
    """Every team, alphabetical.

    Returns an empty tuple rather than raising when the team dimension has not
    been ingested. It is a branding table: the app is degraded without it, not
    broken, and failing a whole request because a logo URL is missing would be
    the wrong trade.
    """
    rows = await repository.fetch_teams(session)
    return tuple(team_ref(row) for row in rows)


async def get_team(session: AsyncSession, abbr: str) -> TeamRef:
    """One team by abbreviation.

    Raises:
        NotFound: if no such team exists.
    """
    wanted = abbr.strip().upper()
    for team in await list_teams(session):
        if team.abbr.upper() == wanted:
            return team
    raise NotFound("team", abbr)


async def team_index(session: AsyncSession) -> dict[str, TeamRef]:
    """Teams keyed by abbreviation, for decorating a list of projections.

    One query for a whole board rather than one per row — the difference
    between a slate endpoint that does two queries and one that does 300.
    """
    return {team.abbr.upper(): team for team in await list_teams(session)}


async def list_seasons(session: AsyncSession) -> tuple[int, ...]:
    """Seasons in the warehouse, newest first."""
    return tuple(await repository.seasons_available(session))


async def list_published_weeks(session: AsyncSession, season: int) -> tuple[int, ...]:
    """Weeks of a season with a published projection run.

    What a week picker should be built from: a week with a schedule but no
    published run has no board to show, and offering it produces an empty
    screen with no explanation.
    """
    return tuple(await repository.published_weeks(session, season))
