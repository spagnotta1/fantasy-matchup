"""Response caching, applied as middleware rather than per route.

Where the cache sits, and why it is here
----------------------------------------
It caches the **serialised response body**, above the routers, not the service
functions below them. Three consequences follow, and all three are the reason:

* ``nflfp.services`` stays a pure read layer with no infrastructure in it. The
  business layer imports no web framework and now imports no cache either.
* A hit skips query, assembly, mapping *and* Pydantic serialisation. On a full
  slate the last of those is not a rounding error.
* No route changes. Caching an endpoint is a line in
  :mod:`nflfp.cache.policy`, which is also where somebody looks to find out
  whether an endpoint is cached — a decorator on each handler puts that answer
  in thirteen places.

What is deliberately never cached
---------------------------------
Only ``GET``, only ``200``, and only paths with a rule. Requests carrying
``Authorization`` or ``Cookie`` bypass entirely, before authentication exists,
so a shared cache keyed on the URL can never be the thing that serves one
principal's response to another.

Errors are not cached at all. A ``503`` for a dropped materialized view is
fixed by running one command, and a cached one would keep reporting the outage
for five minutes after the fix — which is exactly when an operator is
refreshing the page to see whether it worked.

Failure behaviour
-----------------
Every backend error is a miss. The worst outcome of a broken cache is the
latency the application had before Layer 6.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..cache import (
    CacheBackend,
    EpochSource,
    build_key,
    normalise_query,
    policy,
)

logger = logging.getLogger(__name__)

#: Response header stating what happened. ``HIT``, ``MISS``, ``BYPASS``.
#: Worth shipping to clients rather than keeping internal: a support question
#: about a stale number is answered by one header instead of a log dig.
CACHE_HEADER = "X-Cache"
#: Seconds the served body has been in the cache. Mirrors HTTP's ``Age``.
AGE_HEADER = "Age"

#: Body and metadata are stored as one blob with a tiny textual preamble
#: rather than as a Redis hash, because a hash is two round-trips (or a
#: pipeline that has to be kept in sync) for a value that is always read whole.
_SEPARATOR = b"\n\n"


def _encode(body: bytes, *, media_type: str, stored_at: float) -> bytes:
    header = f"{int(stored_at)}\x1f{media_type}".encode("utf-8")
    return header + _SEPARATOR + body


def _decode(blob: bytes) -> tuple[bytes, str, float] | None:
    head, separator, body = blob.partition(_SEPARATOR)
    if not separator:
        return None
    try:
        stored_at_raw, _, media_type = head.decode("utf-8").partition("\x1f")
        return body, media_type or "application/json", float(stored_at_raw)
    except ValueError:
        return None


class ResponseCacheMiddleware(BaseHTTPMiddleware):
    """Serve and store whole response bodies according to the policy table.

    Args:
        app: The ASGI app.
        cache: Backend, injected so a test can pass
            :class:`~nflfp.cache.backend.MemoryCache` without touching Redis.
        epoch: Publish-epoch source; keys are minted inside its namespace.
        clock: Injectable for tests that assert on ``Age``.
    """

    def __init__(
        self,
        app,
        *,
        cache: CacheBackend,
        epoch: EpochSource,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(app)
        self._cache = cache
        self._epoch = epoch
        self._clock = clock

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        ttl = self._ttl_for(request)
        if ttl <= 0:
            response = await call_next(request)
            response.headers[CACHE_HEADER] = "BYPASS"
            return response

        key = await self._key_for(request)

        blob = await self._cache.get(key)
        if blob is not None:
            decoded = _decode(blob)
            if decoded is not None:
                body, media_type, stored_at = decoded
                age = max(0, int(self._clock() - stored_at))
                return Response(
                    content=body,
                    media_type=media_type,
                    headers={
                        CACHE_HEADER: "HIT",
                        AGE_HEADER: str(age),
                        # Downstream caches get the *remaining* freshness, not
                        # the full TTL — otherwise a CDN extends the lifetime of
                        # every hit and the five-minute bound quietly becomes
                        # unbounded.
                        "Cache-Control": f"public, max-age={max(0, ttl - age)}",
                    },
                )
            logger.warning("discarding malformed cache entry for %s", request.url.path)

        response = await call_next(request)
        response.headers[CACHE_HEADER] = "MISS"

        if response.status_code == 200:
            body = await _drain(response)
            response.headers["Cache-Control"] = f"public, max-age={ttl}"
            await self._cache.set(
                key,
                _encode(
                    body,
                    # Read from the header rather than ``response.media_type``:
                    # the object BaseHTTPMiddleware returns is a streaming
                    # response whose ``media_type`` attribute is None, and a
                    # cached entry that lost its charset would be served back
                    # as a different content type than the miss produced.
                    media_type=response.headers.get("content-type", "application/json"),
                    stored_at=self._clock(),
                ),
                ttl,
            )
        return response

    # -- decisions ----------------------------------------------------------

    def _ttl_for(self, request: Request) -> int:
        if request.method != "GET":
            return 0
        if any(header in request.headers for header in policy.PRIVATE_REQUEST_HEADERS):
            return 0
        # An explicit `Cache-Control: no-cache` is how an operator checks
        # whether a wrong number is stale or genuinely wrong, without turning
        # the cache off for everyone.
        if "no-cache" in request.headers.get("cache-control", "").lower():
            return 0
        return policy.ttl_for(request.url.path)

    async def _key_for(self, request: Request) -> str:
        epoch = await self._epoch.current()
        return build_key(
            "http",
            epoch,
            (request.url.path, normalise_query(request.query_params.multi_items())),
        )


async def _drain(response: Response) -> bytes:
    """Read a streamed response body and make it replayable.

    ``BaseHTTPMiddleware`` hands back a streaming response whose iterator can
    be consumed exactly once. Reading it to cache the body would leave nothing
    for the client, so the drained bytes are put back as a fresh iterator. This
    is the standard cost of body-level middleware in Starlette, and it is
    bounded here: the only cached endpoints are JSON envelopes, the largest of
    which is a full slate.
    """
    chunks = [chunk async for chunk in response.body_iterator]  # type: ignore[attr-defined]
    body = b"".join(chunks)

    async def replay():
        yield body

    response.body_iterator = replay()  # type: ignore[attr-defined]
    return body
