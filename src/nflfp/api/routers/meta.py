"""Capability and provenance endpoints, plus health.

These exist so a client is never hard-coded against facts that will change.
Which positions are projected, which scoring formats are published, what the
model was measured to do, and what the provenance labels mean are all served as
data. Shipping a kicker model or freezing a new foundation is then a server-side
change that a well-built client picks up without a release.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...cache import RULES, get_cache
from ...cache.backend import NullCache, RedisCache
from ...config import get_settings
from ...db.engine import check_database
from ...predict.foundation import foundation_summary
from ...services import catalog
from ...services.lineup import format_summary, slot_summary
from ...services.positions import support_summary
from .. import mappers, schemas
from ..dependencies import DbSession
from ..provenance import PROVENANCE_LEGEND

router = APIRouter(tags=["meta"])


async def _cache_state() -> str:
    """`ok`, `degraded` or `disabled`.

    ``disabled`` is a healthy state, not a failure: running without a cache is
    a supported configuration, and reporting it as unhealthy would fail
    readiness on every local run and every single-instance deploy.
    """
    cache = get_cache()
    if isinstance(cache, NullCache):
        return "disabled"
    if isinstance(cache, RedisCache) and cache.degraded:
        return "degraded"
    return "ok" if await cache.ping() else "degraded"


@router.get(
    "/health",
    response_model=schemas.HealthOut,
    summary="Liveness and dependency reachability",
    description=(
        "Returns 200 with `status: degraded` when the database is unreachable "
        "rather than failing. A platform health check that flaps on a "
        "momentary database blip takes the API down with it; reporting the "
        "state lets the operator decide.\n\n"
        "Use `/health/live` as the platform's health check and `/health/ready` "
        "as the load balancer's. This endpoint is the human-readable union of "
        "the two and is kept for compatibility."
    ),
)
async def health() -> schemas.HealthOut:
    settings = get_settings()
    database_ok = await check_database(settings)
    cache_state = await _cache_state()
    return schemas.HealthOut(
        status="ok" if database_ok else "degraded",
        database=database_ok,
        cache=cache_state,
        environment=settings.environment,
        version=schemas_version(),
        checks={
            "database": "ok" if database_ok else "unreachable",
            "cache": cache_state,
        },
    )


@router.get(
    "/health/live",
    response_model=schemas.HealthOut,
    summary="Is this process running",
    description=(
        "Checks **nothing external** — deliberately. This is what a platform "
        "restart policy should watch, and a liveness probe that consults "
        "Postgres restarts every healthy container in the fleet the moment the "
        "database fails over, turning a recoverable incident into an outage.\n\n"
        "It is also the only health endpoint guaranteed to answer in "
        "microseconds, which is what makes a two-second probe timeout safe."
    ),
)
async def health_live() -> schemas.HealthOut:
    settings = get_settings()
    return schemas.HealthOut(
        status="ok",
        environment=settings.environment,
        version=schemas_version(),
    )


@router.get(
    "/health/ready",
    response_model=schemas.HealthOut,
    summary="Can this instance serve traffic",
    description=(
        "Checks the database, because an instance that cannot reach Postgres "
        "cannot answer a single projection request and should be taken out of "
        "rotation rather than restarted.\n\n"
        "The cache is reported but never fails readiness: every cached read "
        "falls back to the query it replaced, so a Redis outage costs latency "
        "and nothing else. Failing readiness on it would take a working API "
        "offline to protect an optimisation."
    ),
)
async def health_ready() -> schemas.HealthOut:
    settings = get_settings()
    database_ok = await check_database(settings)
    cache_state = await _cache_state()
    return schemas.HealthOut(
        status="ok" if database_ok else "degraded",
        database=database_ok,
        cache=cache_state,
        environment=settings.environment,
        version=schemas_version(),
        checks={
            "database": "ok" if database_ok else "unreachable",
            "cache": cache_state,
        },
    )


@router.get(
    "/meta/cache",
    response_model=schemas.Envelope[list[dict]],
    summary="Which endpoints are cached, and for how long",
    description=(
        "The policy table, served as data. A client seeing an unexpected "
        "`Age` header can find out what the ceiling on staleness is without "
        "reading the source, and an operator can confirm a deploy actually "
        "carries the policy they think it does.\n\n"
        "Every response also carries `X-Cache: HIT | MISS | BYPASS`. Send "
        "`Cache-Control: no-cache` to bypass a single request — the way to "
        "check whether a wrong number is stale or genuinely wrong."
    ),
)
async def cache_policy() -> schemas.Envelope[list[dict]]:
    backend = get_cache().name
    return schemas.Envelope[list[dict]](
        data=[
            {
                "prefix": rule.prefix,
                "ttl_seconds": rule.ttl_seconds,
                "cached": rule.ttl_seconds > 0,
                "reason": rule.reason,
            }
            for rule in RULES
        ],
        meta=schemas.MetaOut(
            notices=[
                f"Cache backend: {backend}."
                if backend != "null"
                else "No cache is configured; every response is computed.",
                "A published model run never changes, so the only invalidation "
                "event is a publish. TTLs bound the one thing a publish does "
                "not cover: the default week resolving forward at kickoff.",
            ]
        ),
    )


def schemas_version() -> str:
    """The package version, resolved once at call time."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("nflfp")
    except PackageNotFoundError:  # pragma: no cover - editable install edge case
        return "unknown"


@router.get(
    "/meta/model",
    response_model=schemas.Envelope[dict],
    summary="The frozen prediction foundation and what it was measured to do",
    description=(
        "Phase 3b is frozen. This returns the model behind every "
        "`model`-provenance number in the API, the walk-forward measurements "
        "it produced (interval coverage, calibration, conditional bias), the "
        "naive bar it had to beat, the acceptance criteria a successor must "
        "clear, and the inputs deliberately excluded from it.\n\n"
        "A client displaying projections is entitled to show this; a reviewer "
        "is entitled to audit it."
    ),
)
async def model_foundation() -> schemas.Envelope[dict]:
    return schemas.Envelope[dict](data=foundation_summary())


@router.get(
    "/meta/positions",
    response_model=schemas.Envelope[list[schemas.PositionSupportOut]],
    summary="Which positions are projected, and why the others are not",
    description=(
        "`status` is `projected` or `planned`. Planned positions carry the "
        "reason and what they are blocked on — kickers need a distance-bucketed "
        "component vocabulary, team defences need a team-week fact table and a "
        "discrete outcome model.\n\n"
        "Build position filters from this rather than a hard-coded list."
    ),
)
async def positions() -> schemas.Envelope[list[schemas.PositionSupportOut]]:
    return schemas.Envelope[list[schemas.PositionSupportOut]](
        data=[schemas.PositionSupportOut.model_validate(entry) for entry in support_summary()]
    )


@router.get(
    "/meta/lineup-slots",
    response_model=schemas.Envelope[list[schemas.LineupSlotOut]],
    summary="Lineup slots, what fills them, and which are simulable",
    description=(
        "The slot vocabulary `POST /simulations` validates against. FLEX "
        "accepts RB/WR/TE; quarterbacks are excluded, because a format that "
        "admits one is a superflex league and is a separate lineup format "
        "rather than a change to what FLEX means.\n\n"
        "K and DST appear with `supported: false`. They are recognised slots in "
        "every real league and refusing them as *unknown* would misrepresent a "
        "missing model as a typo; `/meta/positions` carries what each is "
        "blocked on.\n\n"
        "`meta.notices` lists the lineup formats a simulation may be run "
        "against."
    ),
)
async def lineup_slots() -> schemas.Envelope[list[schemas.LineupSlotOut]]:
    return schemas.Envelope[list[schemas.LineupSlotOut]](
        data=[
            schemas.LineupSlotOut.model_validate(entry) for entry in slot_summary()
        ],
        meta=schemas.MetaOut(
            notices=[
                f"{entry['label']} ({entry['name']}): "
                + ", ".join(
                    f"{r['count']}x{r['slot']}" for r in entry["requirements"]
                )
                for entry in format_summary()
            ]
        ),
    )


@router.get(
    "/meta/provenance",
    response_model=schemas.Envelope[dict[str, str]],
    summary="What each provenance label means",
    description=(
        "Every block of numbers in a response carries a `provenance` "
        "discriminator: `model` for the frozen model's output, `derived` for "
        "analysis computed above it, `context` for observed facts it does not "
        "consume, `actual` for recorded outcomes."
    ),
)
async def provenance() -> schemas.Envelope[dict[str, str]]:
    return schemas.Envelope[dict[str, str]](data=PROVENANCE_LEGEND)


@router.get(
    "/meta/scoring-profiles",
    response_model=schemas.Envelope[list[str]],
    summary="League formats projections are published for",
)
async def scoring_profiles() -> schemas.Envelope[list[str]]:
    return schemas.Envelope[list[str]](
        data=list(catalog.scoring_profiles()),
        meta=schemas.MetaOut(
            scoring_profile=get_settings().default_scoring_profile,
            notices=[
                "meta.scoring_profile is the default used when a request names none."
            ],
        ),
    )


@router.get(
    "/seasons",
    response_model=schemas.Envelope[list[schemas.SeasonOut]],
    summary="Seasons with a published board, newest first",
    description=(
        "Availability, not history. The warehouse holds every season nflverse "
        "publishes; this returns only the ones a published projection run "
        "covers, because a season the deployment has never projected has no "
        "screen to show and offering it in a picker makes a working install "
        "look broken.\n\n"
        "Each entry carries its published weeks, so a client builds the season "
        "*and* week selectors — and resolves which slate to open on — from this "
        "one response. `data[0].latest_published_week` is the newest board in "
        "the deployment.\n\n"
        "An empty list is the honest answer for an install whose projection job "
        "has not run; `meta.notices` says so."
    ),
)
async def seasons(db: DbSession) -> schemas.Envelope[list[schemas.SeasonOut]]:
    found = await catalog.list_published_seasons(db)
    return schemas.Envelope[list[schemas.SeasonOut]](
        data=[mappers.season(entry) for entry in found],
        meta=schemas.MetaOut(
            notices=(
                []
                if found
                else [
                    "No projection run has been published, so no season has a "
                    "board to show."
                ]
            )
        ),
    )


@router.get(
    "/seasons/{season}/weeks",
    response_model=schemas.Envelope[list[int]],
    summary="Weeks of a season with a published projection run",
    description=(
        "What a week picker should be built from. A week with a schedule but "
        "no published run has no board to show, and offering it produces an "
        "empty screen with no explanation."
    ),
)
async def weeks(db: DbSession, season: int) -> schemas.Envelope[list[int]]:
    return schemas.Envelope[list[int]](
        data=list(await catalog.list_published_weeks(db, season))
    )


@router.get(
    "/teams",
    response_model=schemas.Envelope[list[schemas.TeamOut]],
    summary="The team dimension",
)
async def teams(db: DbSession) -> schemas.Envelope[list[schemas.TeamOut]]:
    found = await catalog.list_teams(db)
    return schemas.Envelope[list[schemas.TeamOut]](
        data=[schemas.TeamOut.model_validate(entry) for entry in found],
        meta=schemas.MetaOut(
            notices=(
                []
                if found
                else ["The team dimension has not been ingested; branding is unavailable."]
            )
        ),
    )
