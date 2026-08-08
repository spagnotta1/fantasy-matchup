"""Declarative base for application-owned tables.

Scope, deliberately narrow
--------------------------
Only tables whose lifecycle *this application* controls are mapped here. The
warehouse is explicitly out of scope:

===========================  =====================  ==============================
object                       owner                  lifecycle
===========================  =====================  ==============================
``raw_*`` / ``stg_*``        ``nflfp.pipeline``     DROP/RENAME-swapped from
                                                    nflverse parquet each run;
                                                    columns follow the upstream
                                                    feed
``player_week``, ``game_team``,
``upcoming_games``           ``nflfp.transform``    dropped and recreated on
                                                    every publish
``projections``, ``model_runs``,
``pipeline_runs``, ...       **Alembic**            versioned migrations
===========================  =====================  ==============================

Mapping the warehouse here would be actively harmful: Alembic autogenerate
would see tables it does not own and emit migrations that drop or alter them
out from under the weekly load.

The same boundary forbids foreign keys pointing *into* the warehouse. A
``REFERENCES raw_players(gsis_id)`` would either block the weekly table swap or
be silently destroyed by the ``DROP TABLE ... CASCADE`` that performs it.
Warehouse entities are therefore referenced by natural key (``player_id``,
``game_id``) with no constraint, and referential drift is caught by a
reconciliation job rather than by the database.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names. Without these Postgres invents names, and
# Alembic downgrades cannot then find the constraint they are meant to drop.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: Tables Alembic is allowed to manage. Anything not registered against this
#: metadata is invisible to autogenerate — see ``migrations/env.py``.
metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base bound to the application-owned metadata."""

    metadata = metadata


class TimestampMixin:
    """``created_at`` / ``updated_at``, maintained by the database clock.

    Server-side defaults rather than Python ones: rows are also written by the
    ETL and by ad-hoc SQL, and a timestamp that only appears when the ORM
    happens to be in the call path is worse than no timestamp at all.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
