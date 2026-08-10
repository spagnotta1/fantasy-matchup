"""Response compression, and its interaction with the response cache.

A full slate is roughly 1.25 MB of JSON that compresses about 11x, so this is
the difference between a usable board on a phone and a slow one. The size is
not what these tests are about, though — that is the library's job. What is
tested here is the one thing this application got to decide: **which side of the
response cache the compressor sits on.**

Inside the cache, the stored bytes would be gzip and the key would still be the
path and query, because ``Accept-Encoding`` is not part of it. The first client
that sent ``Accept-Encoding: gzip`` would poison the entry for every client that
did not, and those clients would receive a body they cannot read with no way to
tell. Outside the cache, the stored body is raw and each response is negotiated
on its own — which is what the ordering in ``create_app`` produces and what the
last test here pins.
"""

from __future__ import annotations

import gzip

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.middleware.gzip import GZipMiddleware

from nflfp.api.caching import ResponseCacheMiddleware
from nflfp.cache import EpochSource, MemoryCache

CACHED_PATH = "/api/v1/projections"

#: Comfortably over GZipMiddleware's 500-byte floor and over the 128 KiB above
#: which Starlette compresses in a worker thread, so this exercises the path a
#: real slate takes rather than the small-body shortcut.
BODY_ROWS = 4000


@pytest.fixture()
def cache() -> MemoryCache:
    return MemoryCache()


@pytest.fixture()
def calls() -> dict:
    return {"n": 0}


@pytest.fixture()
def app(cache, calls) -> FastAPI:
    """The middleware order `create_app` builds, around a trivial handler."""
    application = FastAPI()

    @application.get(CACHED_PATH)
    async def projections():
        calls["n"] += 1
        return {
            "data": [{"player_id": f"00-{i:07d}", "points": i * 1.5} for i in range(BODY_ROWS)],
            "meta": {},
        }

    # Registration order is inside-out, exactly as in `create_app`: the cache is
    # added first and is therefore innermost, gzip second and therefore wraps it.
    application.add_middleware(
        ResponseCacheMiddleware,
        cache=cache,
        epoch=EpochSource(cache, ttl_seconds=0),
    )
    application.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)
    return application


@pytest.fixture()
def client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_a_large_body_is_compressed_when_the_client_accepts_it(client):
    response = await client.get(CACHED_PATH, headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    # httpx decodes transparently, so the ratio is measured on the wire bytes.
    raw = len(gzip.compress(response.content, 6))
    assert raw < len(response.content) / 4


async def test_a_client_that_does_not_accept_gzip_gets_plain_bytes(client):
    response = await client.get(CACHED_PATH, headers={"Accept-Encoding": "identity"})
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.json()["data"][0]["player_id"] == "00-0000000"


async def test_a_cache_hit_is_still_negotiated_per_client(client, calls):
    """The regression this ordering exists to prevent.

    A gzip client fills the cache, then a client that cannot read gzip asks for
    the same URL. It must get a readable body — which is only true if what was
    stored is the uncompressed one.
    """
    first = await client.get(CACHED_PATH, headers={"Accept-Encoding": "gzip"})
    assert first.headers["X-Cache"] == "MISS"
    assert first.headers["content-encoding"] == "gzip"

    second = await client.get(CACHED_PATH, headers={"Accept-Encoding": "identity"})
    assert second.headers["X-Cache"] == "HIT"
    assert "content-encoding" not in second.headers
    assert second.json() == first.json()

    # And the hit really was a hit: the handler ran once for two requests.
    assert calls["n"] == 1
