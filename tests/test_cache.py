"""The cache: keys, invalidation, and failing open.

None of these need a database or a Redis. The properties worth pinning are all
decisions the cache makes on its own, and the two that matter most are
negative: a cache must never change an answer, and a broken cache must never
change an answer *either*.
"""

from __future__ import annotations

import pytest

from nflfp.cache import (
    EPOCH_KEY,
    RESPONSE_SCHEMA_VERSION,
    EpochSource,
    MemoryCache,
    NullCache,
    build_backend,
    build_key,
    normalise_query,
    policy,
)


# ---------------------------------------------------------------------------
# keys
# ---------------------------------------------------------------------------


class TestKeys:
    def test_the_schema_version_is_in_every_key(self):
        """A deploy that changes a response body must not serve the previous
        shape out of a warm cache."""
        key = build_key("http", 0, ("/api/v1/projections", ""))
        assert f":v{RESPONSE_SCHEMA_VERSION}:" in key

    def test_the_epoch_is_in_every_key(self):
        before = build_key("http", 1, ("/x", ""))
        after = build_key("http", 2, ("/x", ""))
        assert before != after

    def test_different_paths_never_collide(self):
        assert build_key("http", 0, ("/a", "")) != build_key("http", 0, ("/b", ""))

    def test_parameter_order_does_not_change_the_key(self):
        """Otherwise the hit rate halves for no reason other than the order a
        client happened to build its URL."""
        one = normalise_query([("season", "2025"), ("week", "5")])
        two = normalise_query([("week", "5"), ("season", "2025")])
        assert one == two
        assert build_key("http", 0, ("/p", one)) == build_key("http", 0, ("/p", two))

    def test_repeated_parameters_are_all_kept(self):
        """`positions=WR&positions=TE` is a different board from `positions=WR`."""
        one = normalise_query([("positions", "WR")])
        two = normalise_query([("positions", "WR"), ("positions", "TE")])
        assert one != two

    def test_a_key_is_bounded_in_length(self):
        """A projections request can carry dozens of repeated parameters; a key
        built from them verbatim is unbounded and unreadable."""
        query = normalise_query([("positions", f"P{i}") for i in range(200)])
        assert len(build_key("http", 0, ("/api/v1/projections", query))) < 100


# ---------------------------------------------------------------------------
# backends
# ---------------------------------------------------------------------------


class TestBackends:
    async def test_null_cache_is_always_a_miss(self):
        cache = NullCache()
        assert await cache.set("k", b"v", 60) is False
        assert await cache.get("k") is None

    async def test_null_cache_is_healthy(self):
        """"No cache configured" is a supported deployment, not a degraded one.
        Reporting it as unhealthy would fail readiness on every local run."""
        assert await NullCache().ping() is True

    async def test_memory_cache_round_trips(self):
        cache = MemoryCache()
        await cache.set("k", b"value", 60)
        assert await cache.get("k") == b"value"

    async def test_memory_cache_expires(self):
        now = [0.0]
        cache = MemoryCache(clock=lambda: now[0])
        await cache.set("k", b"v", 10)
        now[0] = 9.0
        assert await cache.get("k") == b"v"
        now[0] = 10.1
        assert await cache.get("k") is None

    async def test_a_zero_ttl_is_never_stored(self):
        cache = MemoryCache()
        assert await cache.set("k", b"v", 0) is False
        assert await cache.get("k") is None


class TestBackendResolution:
    def test_no_redis_url_resolves_to_no_cache_rather_than_failing(self, monkeypatch):
        from nflfp.config import Settings

        settings = Settings(cache_backend="redis", redis_url=None)
        assert isinstance(build_backend(settings), NullCache)

    def test_a_missing_redis_url_is_marked_as_a_mistake_not_a_choice(self):
        """The two ways to end up uncached are not the same state.

        They run identically — every call is a miss either way — which is
        exactly why the difference has to be recorded here rather than inferred
        later. An install that asked for Redis and never got a URL pays full
        price on every request and looks, from the outside, like one that opted
        out on purpose.
        """
        from nflfp.config import Settings

        accident = build_backend(Settings(cache_backend="redis", redis_url=None))
        assert isinstance(accident, NullCache) and accident.misconfigured

        deliberate = build_backend(Settings(cache_backend="null"))
        assert isinstance(deliberate, NullCache) and not deliberate.misconfigured

    def test_the_master_switch_wins(self):
        from nflfp.config import Settings

        settings = Settings(cache_enabled=False, cache_backend="memory")
        cache = build_backend(settings)
        assert isinstance(cache, NullCache)
        # Turning the cache off is a decision, even when the backend was left
        # at `redis` — the switch is the more specific instruction.
        assert not cache.misconfigured

    def test_memory_is_selectable_but_never_a_fallback(self):
        """An in-process cache silently ignores epoch bumps from other
        instances, so it must be chosen deliberately and never substituted for
        an unreachable Redis."""
        from nflfp.config import Settings

        assert isinstance(build_backend(Settings(cache_backend="memory")), MemoryCache)

    def test_an_unknown_backend_fails_loudly(self):
        from nflfp.config import Settings

        settings = Settings(cache_backend="memory")
        object.__setattr__(settings, "cache_backend", "carrier-pigeon")
        with pytest.raises(ValueError, match="unknown cache_backend"):
            build_backend(settings)


class _BrokenCache:
    """Every operation fails, the way a restarting Redis does."""

    name = "broken"

    async def get(self, key):
        return None

    async def set(self, key, value, ttl_seconds):
        return False

    async def increment(self, key):
        return None

    async def ping(self):
        return False

    async def close(self):
        return None


# ---------------------------------------------------------------------------
# the epoch: the only invalidation event there is
# ---------------------------------------------------------------------------


class TestEpoch:
    async def test_starts_at_zero_when_nothing_has_been_published(self):
        assert await EpochSource(MemoryCache()).current() == 0

    async def test_a_bump_moves_every_key_into_a_new_namespace(self):
        cache = MemoryCache()
        source = EpochSource(cache, ttl_seconds=0)

        before = build_key("http", await source.current(), ("/p", ""))
        await cache.increment(EPOCH_KEY)
        after = build_key("http", await source.current(), ("/p", ""))

        assert before != after

    async def test_the_epoch_is_not_re_read_on_every_lookup(self):
        """Reading it per request would double the round-trips the cache
        exists to save."""
        now = [0.0]
        cache = MemoryCache()
        source = EpochSource(cache, ttl_seconds=10, clock=lambda: now[0])

        assert await source.current() == 0
        await cache.increment(EPOCH_KEY)
        assert await source.current() == 0, "should still be serving the held value"

        now[0] = 11.0
        assert await source.current() == 1

    async def test_the_bumping_process_sees_its_own_bump_immediately(self):
        cache = MemoryCache()
        source = EpochSource(cache, ttl_seconds=3600)
        await source.current()

        await cache.increment(EPOCH_KEY)
        source.invalidate_local()

        assert await source.current() == 1

    async def test_a_backend_failure_keeps_the_last_known_epoch(self):
        """Falling back to a different epoch would discard a warm cache every
        time Redis hiccuped — the opposite of failing open."""
        source = EpochSource(_BrokenCache(), ttl_seconds=0)
        source._value = 7  # as if a bump had been observed before the outage
        assert await source.current() == 7

    async def test_a_corrupt_epoch_value_is_ignored_not_fatal(self):
        cache = MemoryCache()
        await cache.set(EPOCH_KEY, b"not-a-number", 60)
        source = EpochSource(cache, ttl_seconds=0)
        assert await source.current() == 0


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------


class TestPolicy:
    def test_caching_is_opt_in(self):
        """A path with no rule is not cached. Forgetting to add a rule must
        cost latency, never correctness."""
        assert policy.ttl_for("/api/v1/some-new-endpoint") == 0

    def test_health_is_never_cached(self):
        for path in ("/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready"):
            assert policy.ttl_for(path) == 0, path

    @pytest.mark.parametrize(
        "path",
        ["/api/v1/projections", "/api/v1/rankings/WR", "/api/v1/start-sit", "/api/v1/compare"],
    )
    def test_slate_endpoints_are_bounded_by_forward_week_resolution(self, path):
        """The default week rolls over at kickoff with no publish to signal it,
        so no slate response may outlive five minutes."""
        ttl = policy.ttl_for(path)
        assert 0 < ttl <= 300

    def test_more_specific_prefixes_win(self):
        # /api/v1/health must not be shadowed by a broader rule added later.
        assert policy.RULES[0].prefix == "/api/v1/health"

    def test_every_rule_states_a_reason(self):
        """A TTL with no reasoning attached is a number nobody can safely
        change later."""
        for rule in policy.RULES:
            assert rule.reason.strip(), rule.prefix

    def test_authenticated_requests_are_excluded_before_auth_exists(self):
        """A shared cache keyed on the URL must not be able to serve one
        principal's response to another — by construction, not by a review
        catching it later."""
        assert "authorization" in policy.PRIVATE_REQUEST_HEADERS
        assert "cookie" in policy.PRIVATE_REQUEST_HEADERS

    def test_every_warmable_path_is_actually_cached(self):
        """Warming a path the policy does not cache is pure wasted work."""
        for path in policy.warmable_paths():
            assert policy.ttl_for(path) > 0, path
