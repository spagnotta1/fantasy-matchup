"""Read queries for the business layer. The only module here that knows SQL.

Async, because the API process spends nearly all of a request waiting on
Postgres and a thread per request would cap a Railway instance well below what
it can serve. The engine already provides both shapes
(:mod:`nflfp.db.engine`); this module uses the async one exclusively, and the
synchronous callers that want the same data — a worker warming a cache, say —
go through :func:`nflfp.db.engine.session_scope` and the sync mirror in
:mod:`nflfp.services.sync`.

Nothing here returns a domain object
------------------------------------
These functions return row mappings. :mod:`nflfp.services.assemble` turns them
into dataclasses, and keeping that split is what lets the football logic be
tested without a database. The cost is one extra hop; the benefit is that the
tier boundaries and grade thresholds have unit tests instead of integration
tests.

Defensive strength is computed here, not read
---------------------------------------------
``feat_defense_position_rolling`` looks like the obvious source for a matchup
grade, and it is the wrong one for an upcoming week. It derives from
``feat_defense_position``, which is restricted to completed games, so **no row
exists for the week you are trying to project** — the one week anybody cares
about. Its latest available row is week N-1, whose trailing window covers weeks
N-5 to N-2 and is therefore a game staler than it needs to be.

So the queries below aggregate ``feat_defense_position`` directly with a
``week < :week`` cutoff, which produces the genuinely correct "last four games
before this one" for completed and upcoming weeks alike, and keeps the lag rule
that governs the whole feature layer: a window may only end at the previous
week. The cost is aggregating roughly 2,300 rows per season at read time, which
is nothing, and it is why the business layer does not need a new materialized
view to answer its headline question.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.enums import ScoringProfile, values as enum_values
from .errors import DataUnavailable, UnknownScoringProfile

logger = logging.getLogger(__name__)

Row = Mapping[str, Any]

#: Relations the business layer reads. Grouped by owner, because the owner
#: determines what a missing one means: an Alembic table missing is a failed
#: deploy, an ETL view missing is a pipeline that has never run, and a matview
#: missing is the ordinary aftermath of a ``pipeline full`` publish, which drops
#: ``raw_*`` with ``CASCADE``.
APP_RELATIONS = ("model_runs", "projections", "projection_points")
WAREHOUSE_RELATIONS = (
    "player_week",
    "game_team",
    "upcoming_games",
    "raw_players",
    "raw_teams",
)
FEATURE_RELATIONS = (
    "feat_player_usage",
    "feat_game_context",
    "feat_defense_position",
    "feat_defense_game",
    "feat_training_dataset",
)

#: Every relation the read path guards on, which is what makes one round-trip
#: enough. See :func:`_load_relations`.
KNOWN_RELATIONS = APP_RELATIONS + WAREHOUSE_RELATIONS + FEATURE_RELATIONS

#: How long a relation-existence check is trusted, in seconds. Existence changes
#: only when the pipeline runs, so re-asking on every request would be a
#: round-trip spent confirming something that changes weekly. A minute is short
#: enough that a rebuild is picked up before anyone files a bug.
#:
#: Deliberately still a TTL and not a process-lifetime answer. The states this
#: bounds are real and recoverable — a matview dropped by ``pipeline full`` and
#: rebuilt ten seconds later, a first deploy whose pipeline has not run yet —
#: and an API that had to be restarted to notice the fix would be worse than the
#: round-trip it saved.
_RELATION_CACHE_TTL = 60.0
_relation_cache: dict[str, tuple[float, bool]] = {}


def _profile_column(scoring_profile: str, prefix: str = "fp_") -> str:
    """The ``player_week`` column holding points for a scoring profile.

    Validated against the enum rather than escaped, because this value is
    interpolated into SQL. An allowlist of four known identifiers is the only
    version of this that is safe, and it is checked here so no caller has to
    remember to.

    Raises:
        UnknownScoringProfile: if the profile is not a published league format.
    """
    known = enum_values(ScoringProfile)
    if scoring_profile not in known:
        raise UnknownScoringProfile(scoring_profile, known)
    return f"{prefix}{scoring_profile}"


async def _load_relations(session: AsyncSession, wanted: Sequence[str]) -> None:
    """Refresh the existence cache for ``wanted``, in a single round-trip.

    Two things are going on here, and both are about round-trips rather than
    about the answer.

    **One query, not one per relation.** ``fetch_projections`` guards seven
    relations and the window resolution guards another, so the old
    one-``SELECT``-per-name loop opened a cold slate with eight sequential
    round-trips before the first useful byte of SQL — on a managed Postgres,
    more latency than the query they were protecting.

    **The whole known set, not just the ones asked for.** Checking thirteen
    names costs exactly what checking one costs: the work is a catalog lookup
    per name against pages already in shared buffers, and the round-trip is the
    price. So a miss on any relation refreshes all of them, which means the
    first request after the TTL expires pays one round-trip and every guard for
    the next minute — on that request and every other — is answered from memory.

    Names outside :data:`KNOWN_RELATIONS` are included too, so an ad-hoc check
    still works; it simply does not get the batching benefit of being expected.
    """
    now = time.monotonic()
    stale = [
        name
        for name in wanted
        if (cached := _relation_cache.get(name)) is None
        or now - cached[0] >= _RELATION_CACHE_TTL
    ]
    if not stale:
        return

    batch = sorted(set(stale) | set(KNOWN_RELATIONS))
    rows = await session.execute(
        text(
            "SELECT name, to_regclass(name) IS NOT NULL AS present "
            "FROM unnest(CAST(:names AS text[])) AS t(name)"
        ),
        {"names": batch},
    )
    for name, present in rows.all():
        _relation_cache[str(name)] = (now, bool(present))


async def relation_exists(session: AsyncSession, relation: str) -> bool:
    """Whether a table, view or matview is present in the search path.

    Uses ``to_regclass``, which returns NULL instead of raising for a missing
    relation — the only form of this check that does not abort the surrounding
    transaction on a miss.
    """
    await _load_relations(session, (relation,))
    cached = _relation_cache.get(relation)
    return cached[1] if cached is not None else False


async def require_relations(session: AsyncSession, *relations: str) -> None:
    """Assert that every named relation exists, or raise a fixable error.

    Raises:
        DataUnavailable: naming the first missing relation and the command
            that creates it. Reported in the order the caller listed them, not
            the order the batch happens to return: the caller lists the relation
            whose absence explains the most first, and an operator following the
            remedy for a dependent matview when the table under it is the thing
            that is missing has been sent the wrong way.
    """
    await _load_relations(session, relations)
    for relation in relations:
        cached = _relation_cache.get(relation)
        if cached is None or not cached[1]:
            raise DataUnavailable(relation)


def clear_relation_cache() -> None:
    """Forget cached existence checks. For tests and for post-pipeline hooks."""
    _relation_cache.clear()


# ---------------------------------------------------------------------------
# Shared SQL fragments
# ---------------------------------------------------------------------------

#: Defensive strength as of a week: trailing four completed games strictly
#: before it, ranked 1-32 within position. Rank 1 allows the fewest points and
#: is therefore the toughest matchup, matching
#: ``Projection.defense_rank_vs_position``.
_DEFENSE_FORM_CTE = """
    defense_recent AS (
        SELECT
            dp.defteam,
            dp.position,
            dp.fp_allowed,
            dp.targets_allowed,
            dp.carries_allowed,
            dp.total_yards_allowed,
            ROW_NUMBER() OVER (
                PARTITION BY dp.defteam, dp.position ORDER BY dp.week DESC
            ) AS recency
        FROM feat_defense_position AS dp
        WHERE dp.season = :season AND dp.week < :week
    ),
    defense_form AS (
        SELECT
            defteam,
            position,
            AVG(fp_allowed)          AS fp_allowed_l4,
            AVG(targets_allowed)     AS targets_allowed_l4,
            AVG(carries_allowed)     AS carries_allowed_l4,
            AVG(total_yards_allowed) AS yards_allowed_l4,
            COUNT(*)                 AS games_in_window
        FROM defense_recent
        WHERE recency <= 4
        GROUP BY defteam, position
    ),
    defense_ranked AS (
        SELECT
            f.*,
            RANK() OVER (PARTITION BY position ORDER BY fp_allowed_l4) AS fp_allowed_rank
        FROM defense_form AS f
    ),
    defense_overall_recent AS (
        SELECT
            dg.defteam,
            dg.fp_allowed,
            dg.plays_faced,
            ROW_NUMBER() OVER (PARTITION BY dg.defteam ORDER BY dg.week DESC) AS recency
        FROM feat_defense_game AS dg
        WHERE dg.season = :season AND dg.week < :week
    ),
    defense_overall AS (
        SELECT
            defteam,
            AVG(fp_allowed)  AS fp_allowed_l4,
            AVG(plays_faced) AS pace_l4,
            RANK() OVER (ORDER BY AVG(fp_allowed)) AS fp_allowed_rank
        FROM defense_overall_recent
        WHERE recency <= 4
        GROUP BY defteam
    )
"""

#: The published run for a (season, week), optionally pinned to one model.
_PUBLISHED_RUN_CTE = """
    published AS (
        SELECT
            mr.id,
            mr.model_name,
            mr.model_version,
            mr.algorithm,
            mr.feature_schema_version,
            mr.published_at,
            mr.code_sha
        FROM model_runs AS mr
        WHERE mr.status = 'published'
          AND mr.season = :season
          AND mr.week = :week
          AND (CAST(:model_name AS text) IS NULL OR mr.model_name = CAST(:model_name AS text))
    )
"""

#: Columns selected for every projection row. Written out rather than ``p.*``
#: because ``position`` exists on the projection, the player dimension and the
#: feature table, and an unqualified star would resolve it by join order — a
#: bug that shows up as tight ends graded against cornerback coverage.
_PROJECTION_COLUMNS = """
        p.id                        AS projection_id,
        p.model_run_id,
        p.player_id,
        p.season,
        p.week,
        p.game_id,
        p.team,
        p.opponent,
        p.position,
        p.is_home,
        p.proj_snap_pct,
        p.proj_target_share,
        p.proj_rush_share,
        p.proj_redzone_touches,
        p.proj_team_plays,
        p.proj_targets,
        p.proj_receptions,
        p.proj_carries,
        p.proj_pass_attempts,
        p.proj_passing_yards,
        p.proj_passing_tds,
        p.proj_interceptions,
        p.proj_rushing_yards,
        p.proj_rushing_tds,
        p.proj_receiving_yards,
        p.proj_receiving_tds,
        p.matchup_score,
        p.injury_multiplier,
        p.weather_multiplier,

        pp.scoring_profile,
        pp.predicted_points,
        pp.expected_points,
        pp.floor_points,
        pp.p25_points,
        pp.median_points,
        pp.p75_points,
        pp.ceiling_points,
        pp.standard_deviation,
        pp.confidence,
        pp.boom_probability,
        pp.bust_probability,
        pp.boom_threshold,
        pp.bust_threshold,
        pp.calibration_method,
        pp.distribution_samples,
        pp.extrapolated,

        r.model_name,
        r.model_version,
        r.algorithm,
        r.feature_schema_version,
        r.published_at,
        r.code_sha,

        COALESCE(pl.display_name, u.player_name, p.player_id) AS player_name,
        pl.headshot,
        pl.jersey_number,
        pl.status,
        pl.years_of_experience,
        pl.college_name,

        u.snap_pct_l4,
        u.target_share_l4,
        u.targets_l4,
        u.carries_l4,
        u.receptions_l4,
        u.opportunities_l4,
        u.air_yards_share_l4,
        u.wopr_l4,
        u.snap_pct_season,
        u.games_played_season,
        u.games_in_window_l4,
        u.fp_half_ppr_l4,
        u.fp_half_ppr_season,
        u.fp_volatility_l4,
        u.snap_pct_l4 - u.snap_pct_prev           AS snap_pct_trend,
        u.target_share_l4 - u.target_share_prev   AS target_share_trend,
        u.injury_report_status,
        u.injury_practice_status,

        d.fp_allowed_rank        AS opp_defense_rank_vs_position,
        d.fp_allowed_l4          AS opp_fp_allowed_vs_position_l4,
        d.targets_allowed_l4     AS opp_targets_allowed_l4,
        d.carries_allowed_l4     AS opp_carries_allowed_l4,
        d.games_in_window        AS opp_defense_games_in_window,
        do_.fp_allowed_rank      AS opp_defense_rank_overall,
        do_.pace_l4              AS opp_pace_l4,

        c.team_spread,
        c.total_line,
        c.implied_team_total,
        c.implied_opp_total,
        c.spread_movement,
        c.spread_source,
        c.odds_book,
        c.odds_captured_at,
        c.rest_days,
        c.rest_advantage,
        c.div_game,
        c.temperature_f,
        c.wind_mph,
        c.wind_gust_mph,
        c.precipitation_probability,
        c.snowfall_in,
        c.is_indoor,
        c.roof_uncertain,
        c.weather_source,
        c.weather_captured_at,

        g.gameday,
        g.gametime,

        pw.{points_column} AS actual_points
"""

#: The joins those columns come from. ``do_`` is spelled with a trailing
#: underscore because ``do`` is a reserved word in SQL.
_PROJECTION_JOINS = """
    FROM projections AS p
    JOIN published AS r
      ON r.id = p.model_run_id
    JOIN projection_points AS pp
      ON pp.projection_id = p.id
     AND pp.scoring_profile = :scoring_profile
    LEFT JOIN raw_players AS pl
      ON pl.gsis_id = p.player_id
    LEFT JOIN feat_player_usage AS u
      ON u.player_id = p.player_id AND u.season = p.season AND u.week = p.week
    LEFT JOIN defense_ranked AS d
      ON d.defteam = p.opponent AND d.position = p.position
    LEFT JOIN defense_overall AS do_
      ON do_.defteam = p.opponent
    LEFT JOIN feat_game_context AS c
      ON c.game_id = p.game_id AND c.team = p.team
    LEFT JOIN game_team AS g
      ON g.game_id = p.game_id AND g.team = p.team
    LEFT JOIN player_week AS pw
      ON pw.player_id = p.player_id AND pw.season = p.season AND pw.week = p.week
"""


async def _rows(session: AsyncSession, sql: str, params: Mapping[str, Any]) -> list[dict]:
    result = await session.execute(text(sql), dict(params))
    return [dict(row) for row in result.mappings()]


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


async def first_upcoming_week(session: AsyncSession, season: int) -> int | None:
    """The earliest week of ``season`` with a game that has no result yet.

    Guarded, because this is what a defaulted week resolves against — so on a
    deployment whose warehouse has never been built, an unguarded version turns
    *every* endpoint into an unexplained 500 at once.
    """
    await require_relations(session, "upcoming_games")
    return (
        await session.execute(
            text("SELECT min(week) FROM upcoming_games WHERE season = :season"),
            {"season": season},
        )
    ).scalar()


async def latest_completed_week(session: AsyncSession, season: int) -> int | None:
    """The latest week of ``season`` with a final score."""
    await require_relations(session, "game_team")
    return (
        await session.execute(
            text(
                "SELECT max(week) FROM game_team "
                "WHERE season = :season AND team_score IS NOT NULL"
            ),
            {"season": season},
        )
    ).scalar()


async def published_season_weeks(session: AsyncSession) -> list[tuple[int, int]]:
    """Every ``(season, week)`` with a published model run, newest season first.

    One query for the whole picker. The alternative — list the seasons, then ask
    each for its weeks — is a request per season on the client's critical path
    before a single number is on screen, and the answer is a few dozen rows.
    """
    await require_relations(session, "model_runs")
    result = await session.execute(
        text(
            "SELECT DISTINCT season, week FROM model_runs "
            "WHERE status = 'published' AND season IS NOT NULL AND week IS NOT NULL "
            "ORDER BY season DESC, week"
        )
    )
    return [(int(season), int(week)) for season, week in result.all()]


async def published_weeks(session: AsyncSession, season: int) -> list[int]:
    """Weeks of ``season`` that have a published model run."""
    await require_relations(session, "model_runs")
    result = await session.execute(
        text(
            "SELECT DISTINCT week FROM model_runs "
            "WHERE status = 'published' AND season = :season AND week IS NOT NULL "
            "ORDER BY week"
        ),
        {"season": season},
    )
    return [int(value) for value in result.scalars()]


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


async def fetch_projections(
    session: AsyncSession,
    *,
    season: int,
    week: int,
    scoring_profile: str,
    positions: Sequence[str] | None = None,
    teams: Sequence[str] | None = None,
    player_ids: Sequence[str] | None = None,
    game_id: str | None = None,
    model_name: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """Projections for a week from the published run, with all their context.

    One query. The alternative — fetch projections, then usage, then defence,
    then market — is four round-trips per request and an N+1 waiting to happen
    the first time somebody loops over the result.

    Args:
        session: Open async session.
        season: Season.
        week: Week.
        scoring_profile: League format; validated against the enum.
        positions: Restrict to these positions.
        teams: Restrict to these teams.
        player_ids: Restrict to these players.
        game_id: Restrict to one game.
        model_name: Pin to one model, rather than whichever is published.
        limit: Maximum rows. Applied after ordering by expected points, so a
            limited request returns the *top* N and not an arbitrary N.
        offset: Rows to skip, for pagination.

    Returns:
        Row mappings ordered best-first.
    """
    points_column = _profile_column(scoring_profile)
    await require_relations(
        session,
        "projections",
        "projection_points",
        "model_runs",
        "feat_player_usage",
        "feat_defense_position",
        "feat_defense_game",
        "feat_game_context",
        "player_week",
    )

    clauses = ["p.season = :season", "p.week = :week"]
    params: dict[str, Any] = {
        "season": season,
        "week": week,
        "scoring_profile": scoring_profile,
        "model_name": model_name,
    }
    if positions:
        clauses.append("p.position = ANY(:positions)")
        params["positions"] = list(positions)
    if teams:
        clauses.append("p.team = ANY(:teams)")
        params["teams"] = list(teams)
    if player_ids:
        clauses.append("p.player_id = ANY(:player_ids)")
        params["player_ids"] = list(player_ids)
    if game_id:
        clauses.append("p.game_id = :game_id")
        params["game_id"] = game_id

    pagination = ""
    if limit is not None:
        pagination = " LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset

    sql = f"""
    WITH {_PUBLISHED_RUN_CTE},
    {_DEFENSE_FORM_CTE}
    SELECT
{_PROJECTION_COLUMNS.format(points_column=points_column)}
{_PROJECTION_JOINS}
    WHERE {' AND '.join(clauses)}
    ORDER BY COALESCE(pp.expected_points, pp.predicted_points) DESC,
             pp.ceiling_points DESC NULLS LAST,
             p.player_id
    {pagination}
    """
    return await _rows(session, sql, params)


async def count_projections(
    session: AsyncSession,
    *,
    season: int,
    week: int,
    scoring_profile: str,
    positions: Sequence[str] | None = None,
    teams: Sequence[str] | None = None,
    model_name: str | None = None,
) -> int:
    """Total matching projections, for pagination metadata.

    Deliberately does not join the feature or defence views: a count does not
    need them, and a count query that drags in four matviews is how a cheap
    endpoint becomes an expensive one.
    """
    _profile_column(scoring_profile)
    clauses = ["p.season = :season", "p.week = :week"]
    params: dict[str, Any] = {
        "season": season,
        "week": week,
        "scoring_profile": scoring_profile,
        "model_name": model_name,
    }
    if positions:
        clauses.append("p.position = ANY(:positions)")
        params["positions"] = list(positions)
    if teams:
        clauses.append("p.team = ANY(:teams)")
        params["teams"] = list(teams)

    sql = f"""
    WITH {_PUBLISHED_RUN_CTE}
    SELECT count(*)
    FROM projections AS p
    JOIN published AS r ON r.id = p.model_run_id
    JOIN projection_points AS pp
      ON pp.projection_id = p.id AND pp.scoring_profile = :scoring_profile
    WHERE {' AND '.join(clauses)}
    """
    return int((await session.execute(text(sql), params)).scalar() or 0)


async def fetch_published_model(
    session: AsyncSession, *, season: int, week: int, model_name: str | None = None
) -> dict | None:
    """Lineage for the run currently published for a week, if any."""
    sql = f"""
    WITH {_PUBLISHED_RUN_CTE}
    SELECT id AS model_run_id, model_name, model_version, algorithm,
           feature_schema_version, published_at, code_sha
    FROM published
    ORDER BY published_at DESC NULLS LAST
    LIMIT 1
    """
    rows = await _rows(
        session,
        sql,
        {"season": season, "week": week, "model_name": model_name},
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------


async def fetch_player(session: AsyncSession, player_id: str) -> dict | None:
    """The player dimension row for a gsis id."""
    await require_relations(session, "raw_players")
    rows = await _rows(
        session,
        """
        SELECT gsis_id AS player_id, display_name, position, position_group,
               latest_team, jersey_number, status, headshot, college_name,
               years_of_experience, rookie_season, last_season, height, weight,
               draft_year, draft_round, draft_pick, draft_team
        FROM raw_players
        WHERE gsis_id = :player_id
        """,
        {"player_id": player_id},
    )
    return rows[0] if rows else None


async def fetch_player_dimensions(
    session: AsyncSession, player_ids: Sequence[str]
) -> dict[str, dict]:
    """Player dimension rows for a set of gsis ids, keyed by id.

    The batched form of :func:`fetch_player`. It exists for the roster path,
    which needs a position for every id that produced *no* projection so it can
    say why — and doing that one id at a time would be a round-trip per gap on
    the exact request that already has the most gaps.

    Ids with no dimension row are simply absent from the mapping, so a caller
    can distinguish "unknown player" from "known player, nothing published"
    by membership rather than by a second query.
    """
    if not player_ids:
        return {}
    await require_relations(session, "raw_players")
    rows = await _rows(
        session,
        """
        SELECT gsis_id AS player_id, display_name, position, position_group,
               latest_team, jersey_number, status
        FROM raw_players
        WHERE gsis_id = ANY(:player_ids)
        """,
        {"player_ids": list(player_ids)},
    )
    return {str(row["player_id"]): row for row in rows}


#: Columns every player-dimension read returns, so `assemble.player_ref` sees
#: the same shape whether the row came from a search, a browse or a lookup. A
#: second column list is how one of the three quietly stops carrying headshots.
_PLAYER_COLUMNS = """
    p.gsis_id AS player_id,
    p.display_name,
    p.position,
    p.latest_team AS team,
    p.jersey_number,
    p.status,
    p.headshot,
    p.years_of_experience,
    p.college_name,
    p.last_season
"""


def _player_filters(
    *,
    positions: Sequence[str] | None,
    teams: Sequence[str] | None,
    active_only: bool,
) -> tuple[list[str], dict[str, Any]]:
    """Shared WHERE clauses for browsing the dimension.

    Extracted so the page query and the count query cannot diverge — a count
    that filters differently from the rows it counts produces pagination that
    promises a page which does not exist.
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if positions:
        clauses.append("p.position = ANY(:positions)")
        params["positions"] = list(positions)
    if teams:
        clauses.append("upper(p.latest_team) = ANY(:teams)")
        params["teams"] = [team.upper() for team in teams]
    if active_only:
        clauses.append("p.status = 'ACT'")
    return clauses, params


async def list_players(
    session: AsyncSession,
    *,
    positions: Sequence[str] | None = None,
    teams: Sequence[str] | None = None,
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Browse the player dimension, alphabetically.

    The index behind a roster picker. Ordering is by name rather than by
    anything derived, because this is the one listing whose job is to be
    predictable — a board that reorders itself between page 1 and page 2 makes
    paging skip players, and every ranked listing in the API already exists
    elsewhere.
    """
    await require_relations(session, "raw_players")
    clauses, params = _player_filters(
        positions=positions, teams=teams, active_only=active_only
    )
    params.update({"limit": limit, "offset": offset})
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return await _rows(
        session,
        f"""
        SELECT {_PLAYER_COLUMNS}
        FROM raw_players AS p
        {where}
        ORDER BY p.display_name, p.gsis_id
        LIMIT :limit OFFSET :offset
        """,
        params,
    )


async def count_players(
    session: AsyncSession,
    *,
    positions: Sequence[str] | None = None,
    teams: Sequence[str] | None = None,
    active_only: bool = True,
) -> int:
    """How many players match, before paging."""
    await require_relations(session, "raw_players")
    clauses, params = _player_filters(
        positions=positions, teams=teams, active_only=active_only
    )
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    result = await session.execute(
        text(f"SELECT count(*) FROM raw_players AS p {where}"), params
    )
    return int(result.scalar() or 0)


async def published_run_for_week(
    session: AsyncSession, *, season: int, week: int, model_name: str | None = None
) -> dict | None:
    """The live run for a week, with how many projections it holds.

    One query rather than a run lookup followed by a count. The count is the
    part that makes it useful: a published run with zero projections is a real
    and confusing state — the job succeeded, the flag is set, and the board is
    empty — and it should be visible without anyone reading the database.
    """
    await require_relations(session, "model_runs", "projections")
    clauses = ["r.status = 'published'", "r.season = :season", "r.week = :week"]
    params: dict[str, Any] = {"season": season, "week": week}
    if model_name:
        clauses.append("r.model_name = :model_name")
        params["model_name"] = model_name

    rows = await _rows(
        session,
        f"""
        SELECT
            r.id AS model_run_id, r.model_name, r.model_version, r.algorithm,
            r.feature_schema_version, r.published_at, r.code_sha,
            count(p.id) AS projection_count
        FROM model_runs AS r
        LEFT JOIN projections AS p ON p.model_run_id = r.id
        WHERE {' AND '.join(clauses)}
        GROUP BY r.id
        ORDER BY r.published_at DESC NULLS LAST
        LIMIT 1
        """,
        params,
    )
    return rows[0] if rows else None


async def search_players(
    session: AsyncSession,
    *,
    query: str,
    limit: int = 25,
    positions: Sequence[str] | None = None,
    active_only: bool = True,
) -> list[dict]:
    """Name search over the player dimension.

    Ranked by how the match was made — prefix beats substring — and then by
    recency of last season, because typing "jo" should surface players who are
    currently on a roster rather than the alphabetically luckiest retiree.

    ``ILIKE`` with a leading wildcard cannot use a btree index. At roughly
    20,000 player rows that is a sequential scan of a small table and measures
    in single-digit milliseconds; a trigram index is the fix if it ever stops
    being, and it would be a migration, not a redesign.
    """
    if not query or not query.strip():
        raise ValueError("search query must not be empty")
    term = query.strip()

    clauses = ["(p.display_name ILIKE :contains OR p.football_name ILIKE :contains)"]
    params: dict[str, Any] = {
        "contains": f"%{term}%",
        "prefix": f"{term}%",
        "limit": limit,
    }
    if positions:
        clauses.append("p.position = ANY(:positions)")
        params["positions"] = list(positions)
    if active_only:
        clauses.append("p.status = 'ACT'")

    return await _rows(
        session,
        f"""
        SELECT {_PLAYER_COLUMNS},
            CASE WHEN p.display_name ILIKE :prefix THEN 0 ELSE 1 END AS match_rank
        FROM raw_players AS p
        WHERE {' AND '.join(clauses)}
        ORDER BY match_rank, p.last_season DESC NULLS LAST, p.display_name
        LIMIT :limit
        """,
        params,
    )


async def fetch_player_history(
    session: AsyncSession,
    *,
    player_id: str,
    scoring_profile: str,
    limit: int = 24,
    seasons: Sequence[int] | None = None,
) -> list[dict]:
    """A player's completed weeks with the projection that was made for each.

    The projection is read from storage rather than regenerated. "What did we
    say at the time, and were we right?" is the question worth answering;
    re-scoring history with today's model answers a different one and always
    flatters it.
    """
    points_column = _profile_column(scoring_profile)
    await require_relations(session, "player_week", "projections", "projection_points")

    clauses = ["pw.player_id = :player_id", f"pw.{points_column} IS NOT NULL"]
    params: dict[str, Any] = {
        "player_id": player_id,
        "scoring_profile": scoring_profile,
        "limit": limit,
    }
    if seasons:
        clauses.append("pw.season = ANY(:seasons)")
        params["seasons"] = list(seasons)

    return await _rows(
        session,
        f"""
        SELECT
            pw.season,
            pw.week,
            pw.team,
            pw.opponent,
            pw.is_home,
            pw.{points_column} AS actual_points,
            pw.offense_pct,
            pw.targets,
            pw.carries,
            pw.receptions,
            pw.receiving_yards,
            pw.rushing_yards,
            pw.passing_yards,
            pw.receiving_tds,
            pw.rushing_tds,
            pw.passing_tds,
            pw.injury_report_status,
            COALESCE(pp.expected_points, pp.predicted_points) AS projected_points
        FROM player_week AS pw
        LEFT JOIN (
            SELECT DISTINCT ON (p.player_id, p.season, p.week)
                p.id, p.player_id, p.season, p.week
            FROM projections AS p
            JOIN model_runs AS mr
              ON mr.id = p.model_run_id
             AND mr.status IN ('published', 'superseded')
            ORDER BY p.player_id, p.season, p.week,
                     mr.status = 'published' DESC,
                     mr.published_at DESC NULLS LAST
        ) AS p
               ON p.player_id = pw.player_id
              AND p.season = pw.season
              AND p.week = pw.week
        LEFT JOIN projection_points AS pp
               ON pp.projection_id = p.id
              AND pp.scoring_profile = :scoring_profile
        WHERE {' AND '.join(clauses)}
        ORDER BY pw.season DESC, pw.week DESC
        LIMIT :limit
        """,
        params,
    )


# ---------------------------------------------------------------------------
# Teams, games, defences
# ---------------------------------------------------------------------------


async def fetch_teams(session: AsyncSession) -> list[dict]:
    """The team dimension, alphabetical by abbreviation."""
    if not await relation_exists(session, "raw_teams"):
        return []
    return await _rows(
        session,
        """
        SELECT team_abbr, team_name, team_nick, team_conf, team_division,
               team_color, team_color2, team_logo_espn, team_logo_wikipedia
        FROM raw_teams
        ORDER BY team_abbr
        """,
        {},
    )


async def fetch_games(
    session: AsyncSession, *, season: int, week: int | None = None
) -> list[dict]:
    """Scheduled games, one row per game (not per team).

    ``game_team`` holds two rows per game by design; this collapses them back
    by taking the home side, which carries the canonical home/away labelling.
    """
    await require_relations(session, "game_team")
    clauses = ["g.season = :season", "g.is_home"]
    params: dict[str, Any] = {"season": season}
    if week is not None:
        clauses.append("g.week = :week")
        params["week"] = week

    return await _rows(
        session,
        f"""
        SELECT
            g.game_id, g.season, g.week, g.game_type, g.gameday, g.weekday,
            g.gametime, g.div_game, g.roof, g.surface, g.stadium,
            g.team AS home_team, g.opponent AS away_team,
            g.team_score AS home_score, g.opp_score AS away_score,
            g.team_spread AS home_spread, g.total_line,
            g.implied_team_total AS home_implied_total,
            g.implied_opp_total  AS away_implied_total,
            g.team_score IS NULL AS is_upcoming
        FROM game_team AS g
        WHERE {' AND '.join(clauses)}
        ORDER BY g.gameday NULLS LAST, g.gametime NULLS LAST, g.game_id
        """,
        params,
    )


async def fetch_game_context(
    session: AsyncSession,
    *,
    season: int,
    week: int,
    teams: Sequence[str] | None = None,
    game_id: str | None = None,
) -> list[dict]:
    """Market and weather context, one row per (game, team)."""
    await require_relations(session, "feat_game_context")
    clauses = ["c.season = :season", "c.week = :week"]
    params: dict[str, Any] = {"season": season, "week": week}
    if teams:
        clauses.append("c.team = ANY(:teams)")
        params["teams"] = list(teams)
    if game_id:
        clauses.append("c.game_id = :game_id")
        params["game_id"] = game_id

    return await _rows(
        session,
        f"""
        SELECT c.*, g.gameday, g.gametime, g.stadium
        FROM feat_game_context AS c
        LEFT JOIN game_team AS g ON g.game_id = c.game_id AND g.team = c.team
        WHERE {' AND '.join(clauses)}
        ORDER BY c.game_id, c.team
        """,
        params,
    )


async def fetch_defense_form(
    session: AsyncSession,
    *,
    season: int,
    week: int,
    defteams: Sequence[str] | None = None,
    positions: Sequence[str] | None = None,
) -> list[dict]:
    """Defensive strength as of a week, by team and position.

    The same computation the projection query uses, exposed on its own for the
    matchup endpoints. See the module docstring for why this is aggregated at
    read time instead of read from ``feat_defense_position_rolling``.
    """
    await require_relations(session, "feat_defense_position", "feat_defense_game")
    clauses = ["1 = 1"]
    params: dict[str, Any] = {"season": season, "week": week}
    if defteams:
        clauses.append("d.defteam = ANY(:defteams)")
        params["defteams"] = list(defteams)
    if positions:
        clauses.append("d.position = ANY(:positions)")
        params["positions"] = list(positions)

    return await _rows(
        session,
        f"""
        WITH {_DEFENSE_FORM_CTE}
        SELECT
            d.defteam,
            d.position,
            d.fp_allowed_l4,
            d.targets_allowed_l4,
            d.carries_allowed_l4,
            d.yards_allowed_l4,
            d.games_in_window,
            d.fp_allowed_rank,
            do_.fp_allowed_rank AS overall_rank,
            do_.pace_l4
        FROM defense_ranked AS d
        LEFT JOIN defense_overall AS do_ ON do_.defteam = d.defteam
        WHERE {' AND '.join(clauses)}
        ORDER BY d.position, d.fp_allowed_rank
        """,
        params,
    )


# ---------------------------------------------------------------------------
# Season history — what the draft engine reads
# ---------------------------------------------------------------------------


async def fetch_season_totals(
    session: AsyncSession,
    *,
    before_season: int,
    seasons_back: int,
    scoring_profile: str,
    positions: Sequence[str] | None = None,
) -> list[dict]:
    """Completed-season production per player, for seasons before a draft.

    The single query behind every historical number the Mock Draft shows.
    Aggregating in SQL rather than pulling ~19,000 player-weeks per season and
    summing them in Python is the difference between one round-trip and a
    hundred thousand rows crossing the wire for a screen that renders eight.

    ``before_season`` is exclusive and is the leakage boundary: a draft for
    season S may see S-1 and earlier and nothing else. It is expressed as a
    ``<`` in the WHERE clause *and* re-asserted above the database by
    :func:`~nflfp.services.draft.history.assert_no_future_seasons`, because a
    silent off-by-one here produces a backtest that looks excellent and means
    nothing.

    Regular season only. Postseason weeks are not part of a fantasy season, and
    including them would credit points to players on good teams that no fantasy
    manager ever scored.

    Args:
        session: Open async session.
        before_season: Exclusive upper bound — the season being drafted.
        seasons_back: How many seasons before it to include.
        scoring_profile: League format, selecting the ``fp_*`` column.
        positions: Restrict to these positions.

    Returns:
        One row per (player, season): games played, total and mean points, the
        weekly standard deviation, and the player's position that season.
    """
    points_column = _profile_column(scoring_profile)
    await require_relations(session, "player_week")

    clauses = [
        "pw.season < :before_season",
        "pw.season >= :from_season",
        "pw.season_type = 'REG'",
        f"pw.{points_column} IS NOT NULL",
    ]
    params: dict[str, Any] = {
        "before_season": before_season,
        "from_season": before_season - seasons_back,
    }
    if positions:
        clauses.append("pw.position = ANY(:positions)")
        params["positions"] = list(positions)

    return await _rows(
        session,
        f"""
        SELECT
            pw.player_id,
            max(pw.player_name)                     AS player_name,
            max(pw.position)                        AS position,
            pw.season,
            count(*)                                AS games_played,
            sum(pw.{points_column})                 AS total_points,
            avg(pw.{points_column})                 AS points_per_game,
            stddev_samp(pw.{points_column})         AS weekly_stdev
        FROM player_week AS pw
        WHERE {' AND '.join(clauses)}
        GROUP BY pw.player_id, pw.season
        ORDER BY pw.season DESC, sum(pw.{points_column}) DESC
        """,
        params,
    )


async def fetch_season_game_counts(session: AsyncSession) -> dict[int, int]:
    """Regular-season games each team plays, by season.

    Availability is games played over games *available to play*, and that
    denominator is 16 before 2021 and 17 after. Reading it from the schedule
    rather than hard-coding the rule means the seventeenth game arriving —
    or an eighteenth — is a data change and not a code change, and it means the
    number is right for the drafted season even when that season has not been
    played, because ``game_team`` is built from the schedule.
    """
    await require_relations(session, "game_team")
    rows = await _rows(
        session,
        """
        SELECT season, max(games) AS games
        FROM (
            SELECT season, team, count(*) AS games
            FROM game_team
            WHERE game_type = 'REG'
            GROUP BY season, team
        ) AS per_team
        GROUP BY season
        """,
        {},
    )
    return {int(row["season"]): int(row["games"]) for row in rows}
