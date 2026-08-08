"""Postgres connection handling.

One DSN drives two clients:

* psycopg — schema, DDL, indexes, the run log, and the atomic publish step.
* DuckDB's `postgres` extension — bulk data movement, via ATTACH. DuckDB
  already reads nflverse parquet, so attaching Postgres lets the whole
  extract-load run inside one engine with no pandas and no row-by-row inserts.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import psycopg

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


class ConfigError(RuntimeError):
    pass


def dsn() -> str:
    """Resolve the Postgres DSN from the environment, normalised.

    Railway exposes DATABASE_URL on the private network and DATABASE_PUBLIC_URL
    for external access; we prefer whichever is set, private first.
    """
    raw = (
        os.environ.get("NFLFP_PG_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("DATABASE_PUBLIC_URL")
    )
    if not raw:
        raise ConfigError(
            "No Postgres DSN found. Set DATABASE_URL (or NFLFP_PG_URL), e.g.\n"
            "  $env:DATABASE_URL = 'postgresql://user:pass@host:5432/dbname'"
        )
    return normalize_dsn(raw)


def normalize_dsn(raw: str) -> str:
    """Normalise a Postgres URL's scheme and sslmode.

    Split out from :func:`dsn` so that a DSN supplied programmatically — from
    application settings, a test, or a one-off run against a copy of production
    — gets exactly the same treatment as one read from the environment. A
    caller that skips this is a caller that talks to managed Postgres without
    TLS.
    """
    parts = urlsplit(raw)
    # Railway and Heroku both hand out postgres:// ; libpq wants postgresql://
    scheme = "postgresql" if parts.scheme in ("postgres", "postgresql") else parts.scheme

    query = dict(parse_qsl(parts.query))
    if "sslmode" not in query:
        explicit = os.environ.get("NFLFP_PG_SSLMODE")
        host = (parts.hostname or "").lower()
        # Managed Postgres (Railway et al.) needs TLS; a local dev container
        # has no certificate and would refuse it.
        query["sslmode"] = explicit or ("disable" if host in LOCAL_HOSTS else "require")

    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def safe_dsn(d: str | None = None) -> str:
    """DSN with the password redacted, for logging."""
    parts = urlsplit(d or dsn())
    if parts.password:
        netloc = parts.netloc.replace(f":{parts.password}@", ":***@")
        parts = parts._replace(netloc=netloc)
    return urlunsplit(parts)


@contextmanager
def connect(autocommit: bool = False):
    """psycopg connection as a context manager."""
    conn = psycopg.connect(dsn(), autocommit=autocommit)
    try:
        yield conn
    finally:
        conn.close()


def table_exists(cur, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (name,),
    )
    return cur.fetchone() is not None


def columns(cur, name: str) -> list[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s "
        "ORDER BY ordinal_position",
        (name,),
    )
    return [r[0] for r in cur.fetchall()]
