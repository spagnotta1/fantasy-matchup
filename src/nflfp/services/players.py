"""Player search and the player profile.

The profile is the screen a user spends the most time on, and it is the one
place where several datasets have to agree with each other: the projection for
this week, the weeks already played, and how the projections that were made for
those weeks actually turned out.

That last part is the interesting one. Recording projection accuracy *per
player* is unusual for a fantasy product and it is the honest thing to do — the
backtest reports a mean absolute error of 4.26 points for running backs, and a
user is entitled to know whether this particular running back is one of the
ones that number is being kind about. The stored projections make it free: they
were never overwritten, so "what did we say, and what happened?" is a join.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from . import assemble, repository
from .catalog import resolve_scoring_profile, resolve_window
from .dto import HistoricalWeek, PlayerProfile, PlayerRef, TrendSummary
from .errors import InvalidRequest, NotFound
from .positions import KNOWN_POSITIONS
from .projections import get_projection

logger = logging.getLogger(__name__)

#: Weeks of history a profile loads by default. Roughly a season and a third,
#: which is enough to show a full year plus the tail of the previous one — the
#: window that matters, since usage persists year over year (r = 0.63-0.73)
#: while efficiency does not.
DEFAULT_HISTORY_WEEKS = 24
MAX_HISTORY_WEEKS = 120

#: Shortest search term accepted. One character matches thousands of players
#: and answers nobody's question, while costing a full scan of the dimension.
MIN_SEARCH_LENGTH = 2
MAX_SEARCH_RESULTS = 50

#: Page size for browsing the dimension. Smaller than a slate page because a
#: player index is browsed, not consumed whole: there are ~20,000 rows and no
#: client wants them all.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


async def list_players(
    session: AsyncSession,
    *,
    positions: Sequence[str] | None = None,
    teams: Sequence[str] | None = None,
    active_only: bool = True,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> tuple[tuple[PlayerRef, ...], int]:
    """Browse the player dimension alphabetically.

    The index a roster picker is built from, and the answer to "who plays for
    this team?" — a question search cannot answer, because search needs a name
    and this is for when you do not have one.

    Like :func:`search`, this accepts *planned* positions such as K and DST.
    Listing a kicker is reasonable; only asking for a projection of one is not,
    and that refusal belongs to the endpoints that would have to invent a
    number.

    Returns:
        The page and the total number of matches before paging, so a client can
        render "showing 50 of 1,842" without a second call.

    Raises:
        InvalidRequest: for an unrecognised position or an out-of-range page.
    """
    if limit < 1 or limit > MAX_PAGE_SIZE:
        raise InvalidRequest(
            f"limit must be between 1 and {MAX_PAGE_SIZE}", field="limit"
        )
    if offset < 0:
        raise InvalidRequest("offset must not be negative", field="offset")

    wanted = None
    if positions:
        wanted = [p.strip().upper() for p in positions]
        unknown = [p for p in wanted if p not in KNOWN_POSITIONS]
        if unknown:
            raise InvalidRequest(
                f"unrecognised position(s) {unknown}; known positions are "
                f"{list(KNOWN_POSITIONS)}",
                field="positions",
            )

    wanted_teams = [t.strip().upper() for t in teams] if teams else None

    rows = await repository.list_players(
        session,
        positions=wanted,
        teams=wanted_teams,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    total = await repository.count_players(
        session, positions=wanted, teams=wanted_teams, active_only=active_only
    )
    return tuple(assemble.player_ref(row) for row in rows), total


async def search(
    session: AsyncSession,
    *,
    query: str,
    limit: int = 25,
    positions: Sequence[str] | None = None,
    active_only: bool = True,
) -> tuple[PlayerRef, ...]:
    """Find players by name.

    Args:
        session: Open async session.
        query: Partial name. Prefix matches rank above substring matches.
        limit: Maximum results, capped at :data:`MAX_SEARCH_RESULTS`.
        positions: Restrict to these positions.
        active_only: Exclude retired and inactive players. Default ``True``
            because a search box in a fantasy app is nearly always someone
            looking for a player they might start.

    Raises:
        InvalidRequest: for a term shorter than :data:`MIN_SEARCH_LENGTH`.
    """
    term = (query or "").strip()
    if len(term) < MIN_SEARCH_LENGTH:
        raise InvalidRequest(
            f"search term must be at least {MIN_SEARCH_LENGTH} characters",
            field="query",
        )
    if limit < 1 or limit > MAX_SEARCH_RESULTS:
        raise InvalidRequest(
            f"limit must be between 1 and {MAX_SEARCH_RESULTS}", field="limit"
        )

    # Search is the one place a *planned* position is a reasonable request:
    # looking up a kicker's name is fine even though nothing projects them. So
    # this checks recognition only, and leaves the projected/planned
    # distinction to the endpoints that would have to invent a number.
    wanted = None
    if positions:
        wanted = [p.strip().upper() for p in positions]
        unknown = [p for p in wanted if p not in KNOWN_POSITIONS]
        if unknown:
            raise InvalidRequest(
                f"unrecognised position(s) {unknown}; known positions are "
                f"{list(KNOWN_POSITIONS)}",
                field="positions",
            )

    rows = await repository.search_players(
        session, query=term, limit=limit, positions=wanted, active_only=active_only
    )
    return tuple(assemble.player_ref(row) for row in rows)


async def get_player(session: AsyncSession, player_id: str) -> PlayerRef:
    """One player's dimension record.

    Raises:
        NotFound: if the id is not in the player dimension.
    """
    row = await repository.fetch_player(session, player_id)
    if row is None:
        raise NotFound("player", player_id)
    return assemble.player_ref(row)


async def get_history(
    session: AsyncSession,
    *,
    player_id: str,
    scoring_profile: str | None = None,
    weeks: int = DEFAULT_HISTORY_WEEKS,
    seasons: Sequence[int] | None = None,
) -> tuple[tuple[HistoricalWeek, ...], TrendSummary]:
    """A player's completed weeks, newest first, plus the summary over them.

    Returns:
        The weeks and a :class:`~nflfp.services.dto.TrendSummary`. Accuracy
        figures in the summary cover only weeks that carried a stored
        projection, and ``graded_games`` says how many those were — averaging
        error over ungraded weeks would report a better model than exists.
    """
    if weeks < 1 or weeks > MAX_HISTORY_WEEKS:
        raise InvalidRequest(
            f"weeks must be between 1 and {MAX_HISTORY_WEEKS}", field="weeks"
        )
    profile = resolve_scoring_profile(scoring_profile)

    rows = await repository.fetch_player_history(
        session,
        player_id=player_id,
        scoring_profile=profile,
        limit=weeks,
        seasons=list(seasons) if seasons else None,
    )
    history = tuple(
        assemble.historical_week(row, points_column="actual_points") for row in rows
    )
    return history, assemble.summarise_history(history)


async def get_profile(
    session: AsyncSession,
    *,
    player_id: str,
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
    weeks: int = DEFAULT_HISTORY_WEEKS,
) -> PlayerProfile:
    """Everything the player page needs.

    The current week's projection is optional. A player can be in the
    dimension, have plenty of history, and legitimately have no projection —
    a bye week, an injury designation that kept them off the slate, or a week
    whose run has not been published yet. The profile renders in all of those
    cases with ``current`` set to ``None``, which is a much better page than a
    404.

    Raises:
        NotFound: only if the *player* does not exist.
    """
    player = await get_player(session, player_id)
    window = await resolve_window(session, season=season, week=week)
    profile_name = resolve_scoring_profile(scoring_profile)

    try:
        current = await get_projection(
            session,
            player_id=player_id,
            season=window.season,
            week=window.week,
            scoring_profile=profile_name,
        )
    except NotFound:
        logger.debug(
            "no projection for %s in %sw%s", player_id, window.season, window.week
        )
        current = None

    history, trend = await get_history(
        session, player_id=player_id, scoring_profile=profile_name, weeks=weeks
    )

    return PlayerProfile(
        player=player,
        scoring_profile=profile_name,
        current=current,
        history=history,
        trend=trend,
        window=window,
    )
