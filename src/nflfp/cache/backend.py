"""Cache backends.

Three implementations behind one protocol, resolved by configuration exactly
the way :mod:`nflfp.providers` resolves a weather feed. Nothing above this
module names Redis.

Why the protocol is async-only
------------------------------
The API is async and the job system is synchronous, so a naive design ends up
with two implementations of every backend and a way for them to drift. Instead
there is one async protocol, and the two synchronous callers that exist — a
publish invalidating the namespace, and the cache warmer — wrap it in
``asyncio.run``. Those calls are two round-trips at the end of a job that takes
minutes; the API path, which is the one under load, is native.

Failing open is the whole design
--------------------------------
Every method swallows backend errors and reports a miss. A cache is an
optimisation, and an optimisation that can take the site down when Redis
restarts is a liability — the read path behind it is a plain Postgres query
that was fast enough to ship before any of this existed. The one thing that is
*not* swallowed is a connection failure at startup: that is logged loudly and
latched, so a misconfigured ``REDIS_URL`` shows up in the logs and on
``/health/ready`` rather than as a silent 20x slowdown nobody notices.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class CacheBackend(Protocol):
    """What the application needs from a cache. Deliberately tiny.

    Values are ``bytes`` because the only thing cached is a serialised HTTP
    response body. Handing the backend an object to pickle would make the cache
    a second, invisible serialisation format that can disagree with the schemas
    — the thing Layer 5 exists to prevent.
    """

    name: str

    async def get(self, key: str) -> bytes | None:
        """Return the stored value, or None on a miss *or any failure*."""

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> bool:
        """Store a value with an expiry. Returns whether it was stored."""

    async def increment(self, key: str) -> int | None:
        """Atomically increment a counter and return the new value."""

    async def ping(self) -> bool:
        """Whether the backend is reachable. Never raises."""

    async def close(self) -> None:
        """Release connections. Called from the API lifespan shutdown."""


class NullCache:
    """The backend used when no ``REDIS_URL`` is configured.

    Usually not a degraded mode — it is the correct configuration for local
    development and for a single-instance deploy that does not need one. Every
    call is a miss, so the read path behaves exactly as it did before Layer 6,
    and no caller needs an ``if cache is not None`` branch.

    ``misconfigured`` separates the two ways of arriving here, which are not the
    same state and used to be indistinguishable. Asking for no cache
    (``CACHE_BACKEND=null``, or ``CACHE_ENABLED=false``) is a decision.
    Asking for Redis and not supplying a URL is a mistake, and one that costs
    roughly 20x on every uncached endpoint — which is exactly the kind of
    problem that reads as "the app is slow" rather than as a missing variable.
    Both run identically; only the health report differs.
    """

    name = "null"

    def __init__(self, *, misconfigured: bool = False) -> None:
        self.misconfigured = misconfigured

    async def get(self, key: str) -> bytes | None:
        return None

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> bool:
        return False

    async def increment(self, key: str) -> int | None:
        return None

    async def ping(self) -> bool:
        # True, and deliberately: "no cache configured" is a healthy state.
        # Reporting it as unhealthy would fail readiness on every local run.
        return True

    async def close(self) -> None:
        return None


class MemoryCache:
    """In-process cache with real expiry, for tests and single-process runs.

    It is genuinely useful — a one-instance deploy gets most of the benefit —
    but it is **not** a substitute for Redis once more than one instance is
    running, because each instance would hold its own copy and a namespace
    bump would only invalidate the instance that performed it. That is why the
    production path is Redis and this is not a fallback the code silently
    chooses.
    """

    name = "memory"

    def __init__(self, *, clock=None) -> None:
        import time

        self._clock = clock or time.monotonic
        #: One keyspace, because Redis has one. A counter written by
        #: :meth:`increment` must be readable by :meth:`get` — the epoch is
        #: incremented by a job and read by every request, and a fake that
        #: split those into two dictionaries would pass its own tests while
        #: hiding the fact that nothing ever observes a publish.
        self._entries: dict[str, tuple[float, bytes]] = {}

    async def get(self, key: str) -> bytes | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            self._entries.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            return False
        self._entries[key] = (self._clock() + ttl_seconds, value)
        return True

    async def increment(self, key: str) -> int | None:
        # No expiry, matching Redis: INCR on a missing key creates it at 1 and
        # leaves it persistent. An epoch that expired would silently reset the
        # namespace to one that already holds superseded bodies.
        current = await self.get(key)
        value = int(current) + 1 if current is not None else 1
        self._entries[key] = (float("inf"), str(value).encode("ascii"))
        return value

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._entries.clear()

    # -- test affordances ---------------------------------------------------
    def size(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()


class RedisCache:
    """Redis-backed cache.

    Connection settings that matter, and why:

    ``socket_timeout`` / ``socket_connect_timeout``
        A cache lookup must never be slower than the query it replaces. With no
        timeout, a stalled Redis turns every cached endpoint into a hang — the
        precise failure the fail-open design exists to avoid, arriving through
        the one door that stays open. Both default to well under a second.

    ``health_check_interval``
        Managed Redis drops idle connections. Without this the first request
        after a quiet period fails, which on an hourly-traffic endpoint is
        most requests.

    ``decode_responses=False``
        Values are response bodies. Decoding them to ``str`` and re-encoding on
        the way out is two wasted copies of every payload.
    """

    name = "redis"

    def __init__(self, url: str, *, timeout_seconds: float = 0.25) -> None:
        from redis import asyncio as aioredis

        self._url = url
        self._client = aioredis.from_url(
            url,
            decode_responses=False,
            socket_timeout=timeout_seconds,
            socket_connect_timeout=timeout_seconds,
            health_check_interval=30,
            retry_on_timeout=False,
        )
        #: Latched after the first failure so a dead Redis logs once, not once
        #: per request. Cleared by the next success.
        self._degraded = False

    def _failed(self, operation: str, exc: Exception) -> None:
        if not self._degraded:
            logger.warning(
                "redis %s failed (%s); serving uncached until it recovers",
                operation, exc,
            )
            self._degraded = True

    def _recovered(self) -> None:
        if self._degraded:
            logger.info("redis recovered")
            self._degraded = False

    async def get(self, key: str) -> bytes | None:
        try:
            value = await self._client.get(key)
        except Exception as exc:
            self._failed("get", exc)
            return None
        self._recovered()
        return value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            return False
        try:
            await self._client.set(key, value, ex=ttl_seconds)
        except Exception as exc:
            self._failed("set", exc)
            return False
        self._recovered()
        return True

    async def increment(self, key: str) -> int | None:
        try:
            value = int(await self._client.incr(key))
        except Exception as exc:
            self._failed("incr", exc)
            return None
        self._recovered()
        return value

    async def ping(self) -> bool:
        try:
            await self._client.ping()
        except Exception as exc:
            self._failed("ping", exc)
            return False
        self._recovered()
        return True

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:  # pragma: no cover - shutdown is best-effort
            logger.debug("redis close failed", exc_info=True)

    @property
    def degraded(self) -> bool:
        """Whether the last operation failed. Surfaced on ``/health/ready``."""
        return self._degraded
