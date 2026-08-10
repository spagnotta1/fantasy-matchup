"""Weekly boards: the slate, position rankings, and a single player's week.

This is the service the API's busiest endpoints call. Its shape is dictated by
one fact about the read path: **projections are generated in advance and the
API never invokes a model.** Everything here is a read of a published run,
which is what makes these endpoints answerable in milliseconds on a Sunday
morning and what makes a model rollout a one-row ``UPDATE`` rather than a cache
stampede.

Ranking happens above the database
----------------------------------
Postgres orders the rows; the ranks, positional ranks and tiers are assigned in
:mod:`nflfp.services.assemble`. That is not an efficiency oversight — the tier
boundaries are derived from the projected *distributions*, which means they are
a football decision with a threshold that belongs somewhere unit-testable, not
inside a window function.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from . import assemble, repository
from .catalog import resolve_scoring_profile, resolve_window
from .dto import PlayerProjection, RankedProjection, Slate, SlateWindow
from .errors import InvalidRequest, NotFound
from .positions import PROJECTED_POSITIONS, validate_positions

logger = logging.getLogger(__name__)

#: Rows a single request may return. High enough that an entire slate
#: (roughly 400 projected skill players) fits in one page, low enough that a
#: careless client cannot ask for a season.
MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100


#: Position filters are validated by the support registry, which owns both the
#: list and the explanation for anything absent from it. Kept as a module-level
#: alias so the call sites read the same as they did before the registry
#: existed.
_validate_positions = validate_positions


async def get_slate(
    session: AsyncSession,
    *,
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
    positions: Sequence[str] | None = None,
    teams: Sequence[str] | None = None,
    model_name: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> tuple[Slate, SlateWindow]:
    """The ranked board for a week.

    Args:
        session: Open async session.
        season: Season, defaulting to the current league year.
        week: Week, defaulting to the upcoming slate.
        scoring_profile: League format, defaulting to the configured one.
        positions: Restrict to these positions.
        teams: Restrict to these teams.
        model_name: Pin to a specific model instead of whatever is published.
        limit: Page size, capped at :data:`MAX_PAGE_SIZE`.
        offset: Rows to skip.

    Returns:
        The slate and the window it resolved to.

    Note:
        A week with nothing published returns an **empty slate**, not an error.
        The projection job not having run is an operational state the UI should
        render as "projections coming Thursday", and a 404 would make that
        indistinguishable from a bad URL. ``Slate.model`` is ``None`` in that
        case, which is the flag to branch on.
    """
    if limit < 1 or limit > MAX_PAGE_SIZE:
        raise InvalidRequest(
            f"limit must be between 1 and {MAX_PAGE_SIZE}, got {limit}", field="limit"
        )
    if offset < 0:
        raise InvalidRequest("offset must not be negative", field="offset")

    # Everything cheap and local is validated *before* the first query. A
    # request for kickers is rejectable without knowing what week it is, and
    # spending a database round-trip to resolve a window we are about to throw
    # away is both slower and, when the database is down, a 500 where a 422 was
    # the correct answer.
    profile = resolve_scoring_profile(scoring_profile)
    wanted_positions = _validate_positions(positions)

    window = await resolve_window(session, season=season, week=week)

    rows = await repository.fetch_projections(
        session,
        season=window.season,
        week=window.week,
        scoring_profile=profile,
        positions=wanted_positions,
        teams=[t.strip().upper() for t in teams] if teams else None,
        model_name=model_name,
        limit=limit,
        offset=offset,
    )

    if not rows:
        logger.info(
            "no published projections for %s week %s (%s)",
            window.season, window.week, profile,
        )
        return (
            Slate(
                season=window.season,
                week=window.week,
                scoring_profile=profile,
                entries=(),
                model=None,
                total=0,
                positions=wanted_positions or PROJECTED_POSITIONS,
            ),
            window,
        )

    projections = [assemble.player_projection(row) for row in rows]

    # A short page is its own count.
    #
    # The rows come back ordered and then limited, so fewer rows than the limit
    # means the end of the result set was reached and the total is what has
    # already been read. The count query is then a second full pass over
    # `projections` joined to `projection_points` to be told a number this
    # process is holding — and it is the *usual* case, not an edge one: the web
    # client asks for 500 and a slate is about 400, so every board on the site
    # was paying for it.
    #
    # A full page is genuinely ambiguous — there may or may not be more behind
    # it — and still asks. So does an empty one, further up: zero rows cannot
    # distinguish an empty slate from an offset past the end, and inventing
    # `offset + 0` for it would answer the second case wrongly.
    if len(rows) < limit:
        total = offset + len(rows)
    else:
        total = await repository.count_projections(
            session,
            season=window.season,
            week=window.week,
            scoring_profile=profile,
            positions=wanted_positions,
            teams=[t.strip().upper() for t in teams] if teams else None,
            model_name=model_name,
        )

    return (
        Slate(
            season=window.season,
            week=window.week,
            scoring_profile=profile,
            entries=tuple(assemble.rank_board(projections)),
            model=projections[0].model,
            total=total,
            positions=wanted_positions or PROJECTED_POSITIONS,
        ),
        window,
    )


async def get_position_rankings(
    session: AsyncSession,
    *,
    position: str,
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[Slate, SlateWindow]:
    """A single-position board — the QB/RB/WR/TE rankings screen.

    A thin specialisation of :func:`get_slate`, and deliberately so: a separate
    query would drift from the general one the first time a filter is added,
    and the ranks would stop agreeing between the two screens.
    """
    return await get_slate(
        session,
        season=season,
        week=week,
        scoring_profile=scoring_profile,
        positions=[position],
        limit=limit,
    )


async def get_projection(
    session: AsyncSession,
    *,
    player_id: str,
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
    model_name: str | None = None,
) -> PlayerProjection:
    """One player's projection for one week.

    Raises:
        NotFound: when no published projection exists for that player-week.
            Unlike a slate, a single projection genuinely is absent rather than
            merely empty, and the caller asked for a specific thing.
    """
    window = await resolve_window(session, season=season, week=week)
    profile = resolve_scoring_profile(scoring_profile)

    rows = await repository.fetch_projections(
        session,
        season=window.season,
        week=window.week,
        scoring_profile=profile,
        player_ids=[player_id],
        model_name=model_name,
        limit=1,
    )
    if not rows:
        raise NotFound("projection", f"{player_id} {window.season}w{window.week}")
    return assemble.player_projection(rows[0])


async def get_projections_for_players(
    session: AsyncSession,
    *,
    player_ids: Sequence[str],
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
) -> tuple[list[PlayerProjection], SlateWindow]:
    """Projections for a specific set of players, in one query.

    The primitive behind comparison and lineup screens. Players with nothing
    published are simply absent from the result; the caller knows which ids it
    asked for and is better placed to decide whether a gap is an error.
    """
    if not player_ids:
        raise InvalidRequest("at least one player id is required", field="player_ids")

    window = await resolve_window(session, season=season, week=week)
    profile = resolve_scoring_profile(scoring_profile)
    rows = await repository.fetch_projections(
        session,
        season=window.season,
        week=window.week,
        scoring_profile=profile,
        player_ids=list(player_ids),
    )
    return [assemble.player_projection(row) for row in rows], window


async def get_game_board(
    session: AsyncSession,
    *,
    game_id: str,
    season: int,
    week: int,
    scoring_profile: str | None = None,
) -> tuple[RankedProjection, ...]:
    """Every projected player in one game, ranked.

    Used by the matchup screen. Both teams are included, which is why the
    ranking is across the game rather than within a team.
    """
    profile = resolve_scoring_profile(scoring_profile)
    rows = await repository.fetch_projections(
        session,
        season=season,
        week=week,
        scoring_profile=profile,
        game_id=game_id,
    )
    projections = [assemble.player_projection(row) for row in rows]
    return tuple(assemble.rank_board(projections))
