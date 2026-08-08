"""Shared test fixtures.

Tests come in two flavours:

* **unit** — no database. They exercise configuration, enums and the ORM
  *metadata* (constraints, indexes, column types), which is where most schema
  mistakes actually live. These run everywhere, including CI without services.
* **integration** — marked ``@pytest.mark.integration`` and skipped unless
  ``DATABASE_URL`` (or ``NFLFP_PG_URL``) is set. They run real migrations and
  real inserts, because a ``CHECK`` constraint that is never exercised against
  Postgres is a comment.

Integration tests build their schema in a **dedicated Postgres schema**
(``test_<pid>``) rather than in ``public``. The developer database holds a
182k-row warehouse that took real time to build; a test suite that can drop it
is a test suite nobody runs twice.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import Iterator

import pytest


# psycopg's async implementation refuses to run on ``ProactorEventLoop``, which
# is the default on Windows from Python 3.8 onward: every async database call
# fails with an ``InterfaceError`` before it reaches a query. Deployment is
# Linux, so this is purely a local-development concern — but it is the kind of
# thing that costs an afternoon the first time somebody runs the async tests on
# a laptop, so it is fixed here rather than documented as a gotcha.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _dsn_available() -> bool:
    return any(
        os.environ.get(key)
        for key in ("DATABASE_URL", "NFLFP_PG_URL", "DATABASE_PUBLIC_URL")
    )


requires_db = pytest.mark.skipif(
    not _dsn_available(),
    reason="no DATABASE_URL / NFLFP_PG_URL set; skipping integration tests",
)


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Keep the settings singleton from leaking between tests."""
    from nflfp.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def pg_engine():
    """Session-scoped engine for integration tests."""
    if not _dsn_available():
        pytest.skip("no database configured")

    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from nflfp.config import Settings

    # NullPool, deliberately. The throwaway-schema fixtures below issue
    # `SET search_path` on their connection, and a pooled connection carries
    # that setting back into the pool. A later test then runs against a schema
    # that has since been dropped and fails with a confusing "relation does not
    # exist" nowhere near the fixture that caused it. A fresh connection per
    # checkout costs microseconds and removes the whole class of problem.
    engine = create_engine(Settings().sqlalchemy_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def db_schema(pg_engine) -> Iterator[str]:
    """A throwaway Postgres schema, dropped when the test finishes.

    Yields the schema name. The connection's ``search_path`` is set to it, so
    unqualified DDL lands inside and cannot touch the warehouse in ``public``.
    """
    from sqlalchemy import text

    name = f"test_{uuid.uuid4().hex[:12]}"
    with pg_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{name}"'))
    try:
        yield name
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))


@pytest.fixture()
def db_session(pg_engine, db_schema):
    """A session whose ``search_path`` points at the throwaway schema, with the
    application tables created in it."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from nflfp.db.base import metadata

    connection = pg_engine.connect()
    connection.execute(text(f'SET search_path TO "{db_schema}"'))
    metadata.create_all(bind=connection)
    connection.commit()

    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        connection.close()


@pytest.fixture()
async def async_db_session(pg_engine, db_schema):
    """An :class:`AsyncSession` pointed at a throwaway schema.

    The business layer's read path is async, so testing its SQL needs an async
    session — and the throwaway-schema trick has to survive the move. It does,
    via libpq's ``options`` connection parameter: ``-csearch_path=<schema>``
    applies to every connection the engine opens, rather than to one connection
    that a pool could hand back with the setting still attached.

    Application tables are created synchronously first. Creating them through
    the async engine would work too, and would mean two code paths for the same
    DDL; reusing ``metadata.create_all`` keeps the schema under test identical
    to the one the other integration tests build.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    from nflfp.config import Settings
    from nflfp.db.base import metadata
    from nflfp.services.repository import clear_relation_cache

    with pg_engine.begin() as conn:
        conn.execute(text(f'SET search_path TO "{db_schema}"'))
        metadata.create_all(bind=conn)

    engine = create_async_engine(
        Settings().sqlalchemy_async_url,
        poolclass=NullPool,
        connect_args={"options": f"-csearch_path={db_schema}"},
    )
    # Relation existence is cached process-wide for a minute. Between throwaway
    # schemas that cache is actively wrong, so it is cleared on both sides.
    clear_relation_cache()
    session = AsyncSession(bind=engine, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()
        clear_relation_cache()
