"""Engine and session management.

Two engines, one configuration
------------------------------
The application runs in two shapes and they need different concurrency models:

* **async** — the FastAPI process, where a request spends most of its life
  waiting on Postgres and blocking a thread per request would cap throughput
  well below what a single Railway instance can serve.
* **sync** — Alembic, the ETL pipeline and the background workers, where the
  work is CPU- or network-bound in ways async does not help, and blocking code
  is simply easier to read.

Both are built from the same :class:`~nflfp.config.Settings` and the same
psycopg 3 driver, so pooling and TLS behaviour cannot drift between them.

Engines are created lazily and cached per process. Creating one is cheap, but a
pool is not: forking a worker after an engine exists hands the child a copy of
live sockets. :func:`dispose_engines` exists for that case and for tests.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_async_engine: AsyncEngine | None = None
_session_factory: sessionmaker[Session] | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _pool_kwargs(settings: Settings) -> dict[str, object]:
    """Pool options shared by both engines."""
    return {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle,
        # Verifies a pooled connection before handing it out. Costs one
        # round-trip; saves every deploy-time and failover-time connection from
        # surfacing as a user-visible 500.
        "pool_pre_ping": True,
        "echo": settings.db_echo,
    }


def _connect_args(settings: Settings) -> dict[str, object]:
    """Driver-level connection arguments shared by both engines.

    The server-side ``statement_timeout`` is set here, through libpq's
    ``options`` parameter, rather than by a ``connect`` event listener that
    opens a cursor. That is not a style preference — it is a correctness fix.

    A listener receives the raw DBAPI connection, and on the **async** engine
    that object is SQLAlchemy's async adapter, whose ``cursor()`` is not a
    synchronous context manager. The listener therefore raised
    ``AttributeError: __enter__`` on every async connection attempt, which
    meant every API database request failed while the synchronous ETL path
    worked perfectly. Passing the setting to libpq applies it identically to
    both engines with no driver-shaped code at all.

    A runaway query holds a pooled connection, and a pool starved of
    connections turns one slow endpoint into a total outage — so the timeout
    itself matters. The database is the only place that can enforce it, since a
    client-side cancellation leaves the server still working.

    ``connect_timeout`` is here for a related reason. libpq waits effectively
    forever for an unreachable host, so without it :func:`check_database` took
    over two minutes to report failure — a health endpoint that hangs is worse
    than one that says "degraded", because a platform health check cannot tell
    a hang from a slow start and will keep the bad instance in rotation.

    Note:
        This sets libpq ``options``. A DSN that already carries its own
        ``options`` query parameter would be overridden; nothing in this
        project sets one, and the timeout is worth the narrow conflict.
    """
    args: dict[str, object] = {"connect_timeout": settings.db_connect_timeout_seconds}
    if settings.db_statement_timeout_ms > 0:
        args["options"] = f"-c statement_timeout={int(settings.db_statement_timeout_ms)}"
    return args


def get_engine(settings: Settings | None = None) -> Engine:
    """Return the process-wide synchronous engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = settings or get_settings()
        _engine = create_engine(
            settings.sqlalchemy_url,
            connect_args=_connect_args(settings),
            **_pool_kwargs(settings),
        )
        logger.info("sync engine created for %s", settings.safe_dsn())
    return _engine


def get_async_engine(settings: Settings | None = None) -> AsyncEngine:
    """Return the process-wide asynchronous engine, creating it on first use."""
    global _async_engine
    if _async_engine is None:
        settings = settings or get_settings()
        _async_engine = create_async_engine(
            settings.sqlalchemy_async_url,
            connect_args=_connect_args(settings),
            **_pool_kwargs(settings),
        )
        logger.info("async engine created for %s", settings.safe_dsn())
    return _async_engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    """Session factory for synchronous callers (workers, ETL, Alembic)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(settings),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


def get_async_session_factory(
    settings: Settings | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Session factory for the API.

    ``expire_on_commit=False`` because response serialisation happens after the
    session closes; with expiry on, every attribute access would trigger a
    refresh against a dead connection.
    """
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=get_async_engine(settings),
            expire_on_commit=False,
            autoflush=False,
        )
    return _async_session_factory


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    """Transactional scope around a series of synchronous operations.

    Commits on clean exit, rolls back on any exception, always closes.
    """
    session = get_session_factory(settings)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@asynccontextmanager
async def async_session_scope(
    settings: Settings | None = None,
) -> AsyncIterator[AsyncSession]:
    """Async equivalent of :func:`session_scope`."""
    session = get_async_session_factory(settings)()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped :class:`AsyncSession`.

    Read endpoints do not commit, so this deliberately does *not* commit on
    exit; a service that writes opens its own transaction explicitly. Making
    the write path visible at the call site beats an implicit commit that fires
    on every request whether or not anything changed.

    Usage::

        @router.get("/players")
        async def list_players(db: AsyncSession = Depends(get_db_session)): ...
    """
    async with get_async_session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_database(settings: Settings | None = None) -> bool:
    """Liveness probe for the health endpoint. Never raises."""
    try:
        async with get_async_engine(settings).connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("database health check failed")
        return False


def dispose_engines() -> None:
    """Drop both engines and their pools.

    Call after forking a worker process, and between tests that swap the
    configured database. Async disposal is left to garbage collection here
    because this function must be callable from synchronous shutdown paths.
    """
    global _engine, _async_engine, _session_factory, _async_session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _async_engine = None
    _session_factory = None
    _async_session_factory = None


async def dispose_async_engine() -> None:
    """Close the async pool cleanly. Call from the FastAPI lifespan shutdown."""
    global _async_engine, _async_session_factory
    if _async_engine is not None:
        await _async_engine.dispose()
    _async_engine = None
    _async_session_factory = None
