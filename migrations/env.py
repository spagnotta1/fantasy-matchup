"""Alembic environment.

Deliberately thin. The two things that make this setup safe both live in the
importable package, where they have tests:

* :func:`nflfp.db.alembic_guard.include_object` keeps autogenerate away from the
  ETL-owned warehouse — see that module for why that matters.
* :class:`nflfp.config.Settings` resolves the database URL, so Alembic, the API
  and the workers cannot end up pointing at different databases.
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from nflfp.config import get_settings
from nflfp.db.alembic_guard import include_object
from nflfp.db.base import metadata

# Importing the models registers them on the metadata. Without this import
# autogenerate sees an empty schema and proposes dropping everything.
import nflfp.db.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

logger = logging.getLogger("alembic.env")

target_metadata = metadata


def _url() -> str:
    """Resolve the database URL from application settings.

    An explicit ``-x url=...`` wins, so a one-off migration against a copy of
    production does not require mutating the environment.
    """
    override = context.get_x_argument(as_dictionary=True).get("url")
    if override:
        return override
    return get_settings().sqlalchemy_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    Useful for review: `alembic upgrade head --sql` produces the exact DDL a
    deploy would run, which is the artefact to attach to a change request.
    """
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection, in one transaction."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
            # Postgres has transactional DDL, so a failed migration leaves no
            # half-applied schema behind.
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
