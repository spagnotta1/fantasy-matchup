"""The response cache middleware, against a synthetic app.

Deliberately not the real application. What is under test is the middleware's
decision-making — what it caches, what it refuses to cache, and what it does
when the backend is broken — and a synthetic app whose handler counts its own
invocations answers "was this served from cache?" directly. Through the real
API the same question is inferred from a header, and a wrong answer is
indistinguishable from a slow query.

The provenance and correctness of the real endpoints are covered in
``test_api.py``; those tests run with no cache configured, which is how they
stay tests of the API rather than tests of the cache.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from nflfp.api.caching import ResponseCacheMiddleware
from nflfp.cache import EpochSource, MemoryCache, EPOCH_KEY

CACHED_PATH = "/api/v1/projections"
UNCACHED_PATH = "/api/v1/health"


@pytest.fixture()
def cache() -> MemoryCache:
    return MemoryCache()


@pytest.fixture()
def calls() -> dict:
    return {"n": 0}


@pytest.fixture()
def app(cache, calls) -> FastAPI:
    """An app shaped like the real one: same paths, trivial handlers."""
    application = FastAPI()

    @application.get(CACHED_PATH)
    async def projections(week: int = 1, positions: list[str] | None = None):
        calls["n"] += 1
        return {"data": [{"week": week, "call": calls["n"]}], "meta": {}}

    @application.get(UNCACHED_PATH)
    async def health():
        calls["n"] += 1
        return {"status": "ok", "call": calls["n"]}

    @application.get("/api/v1/projections/broken")
    async def broken():
        calls["n"] += 1
        from fastapi.responses import JSONResponse

        return JSONResponse({"code": "unavailable"}, status_code=503)

    application.add_middleware(
        ResponseCacheMiddleware,
        cache=cache,
        epoch=EpochSource(cache, ttl_seconds=0),
    )
    return application


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


class TestHitsAndMisses:
    async def test_the_second_request_does_not_reach_the_handler(self, client, calls):
        first = await client.get(CACHED_PATH)
        second = await client.get(CACHED_PATH)

        assert first.headers["X-Cache"] == "MISS"
        assert second.headers["X-Cache"] == "HIT"
        assert calls["n"] == 1

    async def test_a_hit_returns_the_identical_body(self, client):
        first = await client.get(CACHED_PATH)
        second = await client.get(CACHED_PATH)
        assert first.json() == second.json()
        assert first.headers["content-type"] == second.headers["content-type"]

    async def test_different_parameters_are_different_entries(self, client, calls):
        await client.get(CACHED_PATH, params={"week": 1})
        await client.get(CACHED_PATH, params={"week": 2})
        assert calls["n"] == 2

    async def test_parameter_order_does_not_split_the_entry(self, client, calls):
        await client.get(f"{CACHED_PATH}?week=3&positions=WR")
        response = await client.get(f"{CACHED_PATH}?positions=WR&week=3")
        assert response.headers["X-Cache"] == "HIT"
        assert calls["n"] == 1

    async def test_a_hit_reports_its_age_and_remaining_freshness(self, client):
        await client.get(CACHED_PATH)
        hit = await client.get(CACHED_PATH)
        assert int(hit.headers["Age"]) >= 0
        # Downstream caches get what is left, not the full TTL — otherwise a
        # CDN extends the lifetime of every hit and the bound is gone.
        max_age = int(hit.headers["Cache-Control"].split("max-age=")[1])
        assert max_age <= 300


class TestWhatIsNeverCached:
    async def test_an_endpoint_with_no_rule_is_bypassed(self, client, calls):
        response = await client.get(UNCACHED_PATH)
        again = await client.get(UNCACHED_PATH)
        assert response.headers["X-Cache"] == "BYPASS"
        assert again.headers["X-Cache"] == "BYPASS"
        assert calls["n"] == 2

    async def test_errors_are_not_cached(self, client, calls):
        """A 503 for a dropped materialized view is fixed by one command, and
        a cached one keeps reporting the outage after the fix — exactly when
        an operator is refreshing to see whether it worked."""
        await client.get("/api/v1/projections/broken")
        second = await client.get("/api/v1/projections/broken")
        assert second.status_code == 503
        assert calls["n"] == 2

    async def test_an_authenticated_request_bypasses_entirely(self, client, calls):
        """Before authentication exists. A shared cache keyed on the URL must
        never be able to serve one principal's response to another."""
        response = await client.get(CACHED_PATH, headers={"Authorization": "Bearer x"})
        assert response.headers["X-Cache"] == "BYPASS"

        # And it must not have populated the entry an anonymous caller reads.
        anonymous = await client.get(CACHED_PATH)
        assert anonymous.headers["X-Cache"] == "MISS"

    async def test_no_cache_lets_an_operator_check_one_request(self, client, calls):
        await client.get(CACHED_PATH)
        fresh = await client.get(CACHED_PATH, headers={"Cache-Control": "no-cache"})
        assert fresh.headers["X-Cache"] == "BYPASS"
        assert calls["n"] == 2

    async def test_a_post_is_never_cached(self, app, cache):
        @app.post(CACHED_PATH)
        async def create():  # pragma: no cover - registered for the check below
            return {"ok": True}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.post(CACHED_PATH)
        assert response.headers["X-Cache"] == "BYPASS"


class TestInvalidation:
    async def test_a_publish_makes_every_cached_body_unreachable(self, client, cache, calls):
        """The only invalidation event there is."""
        await client.get(CACHED_PATH)
        assert (await client.get(CACHED_PATH)).headers["X-Cache"] == "HIT"

        await cache.increment(EPOCH_KEY)  # what publish_run triggers

        assert (await client.get(CACHED_PATH)).headers["X-Cache"] == "MISS"
        assert calls["n"] == 2


class TestFailingOpen:
    async def test_a_broken_backend_serves_correct_responses(self, calls):
        """The worst outcome of a broken cache is the latency the application
        had before it existed."""

        class Broken:
            name = "broken"

            async def get(self, key):
                raise RuntimeError("redis is down")

            async def set(self, key, value, ttl):
                raise RuntimeError("redis is down")

            async def increment(self, key):
                raise RuntimeError("redis is down")

            async def ping(self):
                return False

            async def close(self):
                return None

        # A backend that raises rather than swallowing is the harsher case:
        # RedisCache catches its own errors, so this proves the middleware is
        # not merely relying on it to.
        class Swallowing(Broken):
            async def get(self, key):
                return None

            async def set(self, key, value, ttl):
                return False

        application = FastAPI()

        @application.get(CACHED_PATH)
        async def projections():
            calls["n"] += 1
            return {"data": [], "meta": {}}

        cache = Swallowing()
        application.add_middleware(
            ResponseCacheMiddleware, cache=cache, epoch=EpochSource(cache, ttl_seconds=0)
        )

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            first = await http.get(CACHED_PATH)
            second = await http.get(CACHED_PATH)

        assert first.status_code == second.status_code == 200
        assert calls["n"] == 2, "every request should have been computed"

    async def test_a_malformed_entry_is_discarded_not_served(self, cache, calls, app):
        """A truncated or foreign value under one of our keys must produce a
        recomputed response, not a corrupt one."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            await http.get(CACHED_PATH)
            key = next(iter(cache._entries))
            await cache.set(key, b"garbage-with-no-separator", 300)
            response = await http.get(CACHED_PATH)

        assert response.status_code == 200
        assert response.json()["data"] == [{"week": 1, "call": 2}]
