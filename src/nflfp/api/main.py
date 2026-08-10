"""The FastAPI application.

An app *factory* rather than a module-level singleton, because tests need to
build an app against a different configuration and a module-level instance
would bind whatever settings existed at import time.

Versioned from the first commit. ``/api/v1`` costs nothing today and is the
difference between shipping a breaking change and being unable to.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from ..cache import get_cache, get_epoch_source, reset_cache
from ..config import Settings, get_settings
from ..db.engine import dispose_async_engine
from ..logging import configure_logging
from ..predict.foundation import FOUNDATION_PHASE, FROZEN_MODEL
from .caching import ResponseCacheMiddleware
from .errors import install_error_handlers
from .middleware import RequestContextMiddleware
from .provenance import PROVENANCE_LEGEND
from .routers import (
    advice,
    draft,
    matchups,
    meta,
    players,
    projections,
    simulations,
)
from .spa import mount_frontend

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

DESCRIPTION = f"""
Weekly fantasy football projections with honest uncertainty.

### Read this before rendering a number

Every response separates three kinds of number, and they are not
interchangeable:

| provenance | what it is |
|---|---|
| `model` | {PROVENANCE_LEGEND['model']} |
| `derived` | {PROVENANCE_LEGEND['derived']} |
| `context` | {PROVENANCE_LEGEND['context']} |
| `actual` | {PROVENANCE_LEGEND['actual']} |

Concretely, a projection has a `prediction` block (the frozen model's output),
`matchup` and `usage` blocks (computed above the model from data it never saw),
and a `context` block (weather, market, injury — observed and **not** consumed).
Before implying a projection accounts for the wind, check
`context.weather.applied_to_projection`. It is `false` today, and
`unapplied_reason` says why.

### The headline number is `expected`, not `predicted`

`prediction.points.expected` is the mean of the calibrated held-out
distribution. `predicted` is the model's raw output, kept for lineage; it is
conditionally biased by construction because shrinkage trades bias for
variance. Do not display `predicted`.

### The model is frozen

`{FROZEN_MODEL}` (phase {FOUNDATION_PHASE}) is the validated foundation.
`GET {API_PREFIX}/meta/model` returns what it was measured to do — interval
coverage, calibration error, conditional bias — and the criteria a successor
must clear.

### Known limits, stated rather than hidden

- **Kickers and team defences are not projected.** See
  `GET {API_PREFIX}/meta/positions` for why and what each is blocked on.
- **Matchup grades are percentiles.** About 2.5 defences hold each letter every
  week, so an "A" means "top few matchups this week", not "good in absolute
  terms". The magnitude claim travels beside it in points.
- **Grades are withheld below three games** of defensive history rather than
  softened. Week 1 is legitimately ungraded.
- **Start/sit declines to call a toss-up.** Below a 58% win probability no
  player is named, because the edge is smaller than the model's own error.
- **Matchup simulation assumes player independence.** `POST
  {API_PREFIX}/simulations` draws each player from their own distribution.
  Teammates and opposing players are correlated, so the reported intervals are
  too narrow and the win probability sits further from 50% than the evidence
  supports. The assumption is a field on the response, not a footnote.

### Errors

One shape for every failure: `{{"code", "message", "field", "remedy"}}`.
`404` not found, `422` semantically impossible, `503` a recoverable server
state (a materialized view awaiting a rebuild) with a `Retry-After` header.

*Every* failure, including the ones the framework raises: an unrouted path, a
wrong method and a schema validation error all answer in this shape rather than
in Starlette's `detail`.

### Which seasons and weeks exist

`GET {API_PREFIX}/seasons` returns the seasons a run has actually been
published for, each with its published weeks — not every season in the
warehouse. Build both selectors from it. `data[0].latest_published_week` is the
newest board in the deployment, and an empty list means nothing is published at
all.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown.

    Neither the engine nor the cache is eagerly connected. A deploy that cannot
    reach Postgres should still start and report `degraded` on ``/health``,
    because a container that refuses to boot cannot tell anyone why — and a
    deploy that cannot reach Redis should not fail at all, since the cache is an
    optimisation.

    Disposal is not optional in either direction: leaked pooled connections
    outlive the process and consume a managed database's limited connection
    budget, and a Redis connection left open across a restart loop exhausts its
    client limit just as effectively.
    """
    settings = get_settings()
    configure_logging(settings)
    logger.info(
        "starting nflfp api",
        extra={
            "environment": settings.environment,
            "model": FROZEN_MODEL,
            "phase": FOUNDATION_PHASE,
            "database": settings.safe_dsn(),
            "cache": get_cache(settings).name,
        },
    )
    try:
        yield
    finally:
        await dispose_async_engine()
        await get_cache(settings).close()
        reset_cache()
        logger.info("nflfp api stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Args:
        settings: Override configuration. Tests use this; production reads the
            environment.
    """
    settings = settings or get_settings()

    app = FastAPI(
        title="nflfp — NFL fantasy projections",
        version=FOUNDATION_PHASE,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Middleware order is the reverse of registration: the last one added is
    # the outermost. The stack that produces is deliberate.
    #
    #   RequestContext  <- outermost: every response gets a correlation id and
    #                      a duration, including cache hits, which are exactly
    #                      the responses you want to see the latency of
    #     CORS          <- applied to hits and misses alike; the cache stores
    #                      only a body, so an origin header can never be baked
    #                      into a cached entry
    #       GZip        <- outside the cache, deliberately: see below
    #         ResponseCache
    #           routes
    app.add_middleware(
        ResponseCacheMiddleware,
        cache=get_cache(settings),
        epoch=get_epoch_source(settings),
    )

    # A full slate is roughly 1.25 MB of JSON and compresses about 11x. The
    # frontend bundle is served through here too, so this covers the 450 KB
    # entry chunk and the 370 KB charting chunk in the same line.
    #
    # It sits *outside* the response cache, which is the only correct side. The
    # cache key is the path and query — it does not include `Accept-Encoding` —
    # so caching compressed bytes would serve a gzip body to a client that never
    # asked for one. Storing the body raw and negotiating per request costs one
    # compression per hit and cannot produce that failure.
    #
    # Level 6 rather than Starlette's default 9. Measured on a 400-player
    # slate: 1282 KiB raw, 113 KiB at level 6 in 17 ms, 108 KiB at level 9 in
    # 24 ms. Level 9 buys 5 KiB for 40% more CPU on the response that runs
    # most often, and 6 is what every reverse proxy in front of this would
    # have chosen anyway. Starlette compresses anything above
    # `thread_minimum_size` (128 KiB) in a worker thread, so a slate does not
    # occupy the event loop while it happens.
    app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)

    # Permissive locally so a frontend on another port can develop against
    # this; deployed environments must name their origins, because a public
    # API with `*` and credentials enabled is a vulnerability rather than a
    # convenience.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_deployed else [],
        allow_credentials=False,
        # POST is here for `/simulations` alone, which takes two lineups in a
        # body because fourteen ids do not belong in a query string. It writes
        # nothing, so the method is a transport choice rather than a mutation —
        # and with `allow_credentials=False` a cross-origin POST carries no
        # ambient authority regardless.
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["X-Cache", "X-Request-ID", "X-Response-Time-ms", "Age"],
    )

    app.add_middleware(RequestContextMiddleware)

    install_error_handlers(app)

    for router in (
        meta.router,
        projections.router,
        players.router,
        matchups.router,
        advice.router,
        simulations.router,
        draft.router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    # Registered before the frontend so that a deployment *without* a build
    # still answers `/` with something that identifies the service. When a build
    # is present the catch-all below never sees `/`, and the browser gets the
    # app instead — which is the right answer at the root of a product.
    if not mount_frontend(app, settings):

        @app.get("/", include_in_schema=False)
        async def root() -> dict:
            return {
                "name": "nflfp",
                "api": API_PREFIX,
                "docs": "/docs",
                "model": FROZEN_MODEL,
                "phase": FOUNDATION_PHASE,
            }

    return app


#: ASGI entry point for `uvicorn nflfp.api.main:app`.
app = create_app()
