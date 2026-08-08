"""Cache keys, and the one event that invalidates them.

Invalidation is a configuration decision here, not a problem
-----------------------------------------------------------
Every cached response is a pure read keyed by ``(season, week,
scoring_profile, filters)`` against a **published model run**, and a published
run never changes — Layer 3 writes a new run and Layer 1's partial unique index
swaps a flag. So there is exactly one event that can make a cached body wrong:
a publish.

That means no per-key invalidation, no dependency tracking, and no ``SCAN``
storm. The namespace carries a monotonic **epoch**; publishing increments it;
every key minted afterwards lives in a new namespace and every key from the old
one becomes unreachable. Orphans expire on their own TTL, which is what stops
this being a memory leak.

Three things are baked into a key, and each has a failure it prevents:

``NAMESPACE``
    So a Redis shared with anything else cannot collide.

``RESPONSE_SCHEMA_VERSION``
    A deploy that changes a response body must not serve the previous shape
    from cache. Bumping this is part of changing a schema, and the test suite
    checks the constant is present in every key.

``epoch``
    The publish counter above.

Reading the epoch, without paying for it every request
-----------------------------------------------------
The epoch lives in Redis, and fetching it before every lookup would double the
round-trips the cache exists to save. It is therefore held in-process with a
short TTL (:class:`EpochSource`), which bounds how long an instance can keep
serving the previous namespace after a publish — seconds, by configuration,
and the same bound already applies to a client that fetched the page a moment
earlier. A cache that is at most ten seconds behind a Tuesday-morning publish
is not a correctness problem; a cache that doubles every request's latency is.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable, Mapping

logger = logging.getLogger(__name__)

#: Prefix for every key this application owns.
NAMESPACE = "nflfp"

#: Bump when a cached response body's *shape* changes.
#:
#: This is not the package version and not the model phase. It is the version
#: of the serialised envelope, and it exists so that a deploy which renames a
#: field cannot serve the old field name out of a warm cache to a client that
#: has already been updated.
RESPONSE_SCHEMA_VERSION = 1

#: Key holding the publish counter.
EPOCH_KEY = f"{NAMESPACE}:epoch"


def epoch_key() -> str:
    return EPOCH_KEY


def build_key(kind: str, epoch: int, parts: Iterable[str]) -> str:
    """Compose a cache key.

    Args:
        kind: What is being cached, e.g. ``"http"``. Keeps unrelated caches
            legible when someone runs ``KEYS nflfp:*`` during an incident.
        epoch: Current publish epoch.
        parts: The identifying components — for an HTTP response, the path and
            the normalised query string.

    Returns:
        ``nflfp:v1:<epoch>:<kind>:<digest>``. The identifying parts are hashed
        rather than embedded: a projections request carries repeated
        ``positions=`` parameters and a key built from them is unbounded in
        length, which Redis permits and nobody can read anyway.
    """
    digest = hashlib.blake2b(
        "\x1f".join(parts).encode("utf-8"), digest_size=16
    ).hexdigest()
    return f"{NAMESPACE}:v{RESPONSE_SCHEMA_VERSION}:{epoch}:{kind}:{digest}"


def normalise_query(params: Mapping[str, Iterable[str]] | Iterable[tuple[str, str]]) -> str:
    """Canonical form of a query string, so equivalent requests share a key.

    ``?week=5&season=2025`` and ``?season=2025&week=5`` are the same request and
    must not occupy two cache entries — otherwise the hit rate halves for no
    reason other than the order a client happened to build its URL. Repeated
    keys (``positions=WR&positions=TE``) keep every value, sorted, because those
    *do* change the answer.
    """
    if isinstance(params, Mapping):
        pairs: list[tuple[str, str]] = [
            (key, value) for key, values in params.items() for value in values
        ]
    else:
        pairs = list(params)
    return "&".join(f"{key}={value}" for key, value in sorted(pairs))


class EpochSource:
    """The publish epoch, cached in-process for a few seconds.

    Args:
        backend: Cache backend to read through.
        ttl_seconds: How long an instance may keep using a stale epoch. This is
            the upper bound on how long a publish takes to become visible.
        clock: Injectable for tests.
    """

    def __init__(self, backend, *, ttl_seconds: float = 10.0, clock=time.monotonic) -> None:
        self._backend = backend
        self._ttl = ttl_seconds
        self._clock = clock
        self._value: int = 0
        self._fetched_at: float = float("-inf")

    async def current(self) -> int:
        """The epoch to mint keys in.

        On any backend failure this returns the last known value — falling back
        to a *different* epoch would silently discard a warm cache every time
        Redis hiccuped, which is the opposite of what a fail-open cache should
        do.
        """
        now = self._clock()
        if now - self._fetched_at < self._ttl:
            return self._value

        raw = await self._backend.get(EPOCH_KEY)
        self._fetched_at = now
        if raw is None:
            # No epoch has ever been written: nothing has been published
            # through this cache yet. Epoch 0 is a valid namespace.
            return self._value
        try:
            self._value = int(raw)
        except (TypeError, ValueError):
            logger.warning("cache epoch %r is not an integer; keeping %d", raw, self._value)
        return self._value

    def invalidate_local(self) -> None:
        """Force the next :meth:`current` to re-read.

        Called by the process that performed the bump, so its own subsequent
        requests do not serve from the namespace it just retired.
        """
        self._fetched_at = float("-inf")
