"""Engine construction, and the async path in particular.

Written after a bug that every other test missed: the server-side
``statement_timeout`` used to be installed by a ``connect`` event listener that
opened a cursor synchronously. On the async engine the raw connection is
SQLAlchemy's async adapter, whose ``cursor()`` is not a synchronous context
manager, so **every async connection raised ``AttributeError: __enter__``** —
the entire API failed at the database while the synchronous ETL worked
perfectly.

Nothing caught it because the integration fixtures build their own
``create_async_engine`` and never went through :func:`get_async_engine`. So the
test that matters here is the boring one: take a connection from the real
factory and run a query on it.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import text

from nflfp.config import Settings
from nflfp.db import engine as engine_module

from .conftest import requires_db


class TestConnectArgs:
    def test_the_statement_timeout_is_passed_to_libpq(self):
        args = engine_module._connect_args(Settings(db_statement_timeout_ms=9_000))
        assert args["options"] == "-c statement_timeout=9000"

    def test_zero_disables_it_without_sending_an_empty_option(self):
        # An empty `options` string is not the same as no options, and libpq
        # is entitled to be picky about it.
        args = engine_module._connect_args(Settings(db_statement_timeout_ms=0))
        assert "options" not in args

    def test_a_connect_timeout_is_always_present(self):
        # Without it, an unreachable database hangs a health check for over two
        # minutes instead of reporting degraded. Measured, then fixed.
        for timeout_ms in (0, 15_000):
            args = engine_module._connect_args(
                Settings(db_statement_timeout_ms=timeout_ms)
            )
            assert args["connect_timeout"] >= 1

    def test_it_is_shared_by_both_engines(self):
        # The whole point of the fix: one code path, no driver-shaped branches,
        # so sync and async cannot drift on connection semantics.
        settings = Settings(db_statement_timeout_ms=15_000)
        assert engine_module._connect_args(settings)["options"].startswith("-c ")


@pytest.mark.integration
@requires_db
class TestAsyncEngine:
    """The path the API actually uses."""

    @pytest.fixture(autouse=True)
    def _clean_engines(self):
        engine_module.dispose_engines()
        yield
        engine_module.dispose_engines()

    async def test_a_connection_from_the_real_factory_can_query(self):
        # This is the assertion that would have caught the bug.
        async with engine_module.get_async_engine().connect() as conn:
            assert (await conn.execute(text("SELECT 1"))).scalar_one() == 1

    async def test_the_statement_timeout_actually_reaches_the_server(self):
        settings = Settings(db_statement_timeout_ms=4_321)
        async with engine_module.get_async_engine(settings).connect() as conn:
            value = (await conn.execute(text("SHOW statement_timeout"))).scalar_one()
        # Postgres renders milliseconds with a unit suffix.
        assert value in ("4321ms", "4s")

    async def test_the_session_dependency_yields_a_working_session(self):
        agen = engine_module.get_db_session()
        session = await agen.__anext__()
        try:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
        finally:
            await agen.aclose()

    async def test_health_check_succeeds_against_a_live_database(self):
        assert await engine_module.check_database() is True

    async def test_health_check_reports_false_rather_than_raising(self):
        # A deploy that cannot reach Postgres must still answer /health.
        broken = Settings(
            database_url_override="postgresql://nobody@127.0.0.1:1/nothing",
            db_connect_timeout_seconds=2,
        )
        engine_module.dispose_engines()
        started = time.monotonic()
        assert await engine_module.check_database(broken) is False
        # Fast failure is the point. Before connect_timeout was set this took
        # over two minutes, which a platform health check reads as a hang.
        assert time.monotonic() - started < 30


@pytest.mark.integration
@requires_db
class TestSyncEngine:
    @pytest.fixture(autouse=True)
    def _clean_engines(self):
        engine_module.dispose_engines()
        yield
        engine_module.dispose_engines()

    def test_the_sync_engine_still_works_and_carries_the_timeout(self):
        settings = Settings(db_statement_timeout_ms=4_321)
        with engine_module.get_engine(settings).connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar_one() == 1
            assert conn.execute(text("SHOW statement_timeout")).scalar_one() in (
                "4321ms",
                "4s",
            )
