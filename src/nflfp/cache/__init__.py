"""Layer 6 caching.

Resolution follows the same shape as :mod:`nflfp.providers`: nothing outside
this package names a concrete backend, and swapping Redis for something else is
one branch in :func:`build_backend`. Setting ``REDIS_URL`` to nothing at all
selects :class:`~nflfp.cache.backend.NullCache`, which makes the cache
disappear without any caller acquiring an ``if`` — the same property that lets
``WEATHER_PROVIDER=null`` disable a feed without removing its job.

Public surface::

    get_cache()            the process-wide backend
    get_epoch_source()     the publish counter, cached in-process
    invalidate_all()       called on publish; async
    invalidate_all_sync()  the same, for the synchronous job path
    reset_cache()          drop the process-wide instances (tests, forks)
"""

from __future__ import annotations

import asyncio
import logging

from ..config import Settings, get_settings
from .backend import CacheBackend, MemoryCache, NullCache, RedisCache
from .keys import (
    EPOCH_KEY,
    NAMESPACE,
    RESPONSE_SCHEMA_VERSION,
    EpochSource,
    build_key,
    normalise_query,
)
from .policy import RULES, CacheRule, rule_for, ttl_for, warmable_paths

logger = logging.getLogger(__name__)

__all__ = [
    "CacheBackend",
    "CacheRule",
    "EpochSource",
    "MemoryCache",
    "NullCache",
    "RedisCache",
    "RULES",
    "EPOCH_KEY",
    "NAMESPACE",
    "RESPONSE_SCHEMA_VERSION",
    "build_backend",
    "build_key",
    "get_cache",
    "get_epoch_source",
    "invalidate_all",
    "invalidate_all_sync",
    "normalise_query",
    "reset_cache",
    "rule_for",
    "ttl_for",
    "warmable_paths",
]

_backend: CacheBackend | None = None
_epoch: EpochSource | None = None


def build_backend(settings: Settings | None = None) -> CacheBackend:
    """Construct the configured backend without caching it.

    A backend name of ``memory`` exists for tests and for a deliberately
    single-instance deploy; it is never chosen as a *fallback* when Redis is
    unreachable, because an in-process cache silently ignores the epoch bumps
    that other instances perform and would serve superseded projections with no
    signal that anything was wrong.
    """
    settings = settings or get_settings()

    if not settings.cache_enabled:
        logger.info("cache disabled by configuration")
        return NullCache()

    backend = settings.cache_backend
    if backend == "memory":
        return MemoryCache()
    if backend == "null":
        return NullCache()
    if backend == "redis":
        if not settings.redis_url:
            logger.warning(
                "CACHE_BACKEND=redis but REDIS_URL is unset; running uncached"
            )
            return NullCache()
        logger.info("redis cache enabled")
        return RedisCache(
            settings.redis_url, timeout_seconds=settings.cache_timeout_seconds
        )
    raise ValueError(f"unknown cache_backend {backend!r}")


def get_cache(settings: Settings | None = None) -> CacheBackend:
    """Process-wide cache backend, created on first use."""
    global _backend
    if _backend is None:
        _backend = build_backend(settings)
    return _backend


def get_epoch_source(settings: Settings | None = None) -> EpochSource:
    """Process-wide epoch source."""
    global _epoch
    if _epoch is None:
        settings = settings or get_settings()
        _epoch = EpochSource(
            get_cache(settings), ttl_seconds=settings.cache_epoch_ttl_seconds
        )
    return _epoch


async def invalidate_all(settings: Settings | None = None) -> int | None:
    """Retire the current namespace. Call after publishing a model run.

    Returns:
        The new epoch, or None if the backend could not be reached — in which
        case the caller has a decision to make and should log it, but must not
        fail the publish. A stale cache is bounded by its TTL; a projection run
        that reports failure because Redis was restarting is a false alarm at
        the end of a job that did its work.
    """
    cache = get_cache(settings)
    epoch = await cache.increment(EPOCH_KEY)
    get_epoch_source(settings).invalidate_local()
    if epoch is None:
        logger.warning(
            "could not bump the cache epoch; cached responses will expire on TTL "
            "(at most %ds) instead of immediately",
            max(rule.ttl_seconds for rule in RULES),
        )
    else:
        logger.info("cache epoch bumped to %d", epoch)
    return epoch


def invalidate_all_sync(settings: Settings | None = None) -> int | None:
    """Synchronous wrapper for the job and CLI paths.

    Two round-trips at the end of a run that took minutes. Keeping one async
    implementation and paying for an event loop here is cheaper than
    maintaining a second backend for the sync side, which is where the two
    would eventually disagree about timeouts or key format.
    """
    try:
        return asyncio.run(invalidate_all(settings))
    except RuntimeError:  # pragma: no cover - only inside a running loop
        logger.warning("invalidate_all_sync called from an async context; skipping")
        return None


def reset_cache() -> None:
    """Drop the process-wide instances.

    Needed between tests, and after forking a worker — a Redis connection
    inherited across a fork is shared by two processes that will interleave
    their protocol traffic on it.
    """
    global _backend, _epoch
    _backend = None
    _epoch = None
