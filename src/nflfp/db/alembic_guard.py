"""The interlock that stops Alembic from managing the warehouse.

This database has two owners. ``raw_*`` tables are swapped wholesale out of
nflverse parquet by :mod:`nflfp.pipeline` every week and their columns follow an
upstream feed; ``player_week``, ``game_team`` and ``upcoming_games`` are views
dropped and recreated on every publish. None of that is Alembic's to manage.

Without a filter, ``alembic revision --autogenerate`` compares the live database
against :data:`nflfp.db.base.metadata`, finds eight large tables it has never
heard of, and helpfully writes ``op.drop_table("raw_player_week")``. Someone
runs it. The warehouse is gone.

So this is a safety interlock rather than a tidiness measure, which is why it
lives in the importable package with its own tests instead of inside
``migrations/env.py`` where nothing could reach it.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import metadata

logger = logging.getLogger(__name__)

#: Tables written and swapped by the ETL. ``stg_`` holds a load in progress.
WAREHOUSE_TABLE_PREFIXES = ("raw_", "stg_")

#: Views rebuilt on every publish by :mod:`nflfp.transform`.
WAREHOUSE_VIEWS = frozenset({"player_week", "game_team", "upcoming_games"})


def is_warehouse_object(name: str) -> bool:
    """True if `name` belongs to the ETL-owned zone rather than to Alembic."""
    return name.startswith(WAREHOUSE_TABLE_PREFIXES) or name in WAREHOUSE_VIEWS


def include_object(
    obj: Any, name: str, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Alembic ``include_object`` hook restricting autogenerate to our tables.

    Two independent guards, because either alone has a failure mode:

    1. Anything in the warehouse zone is excluded by name. This catches
       reflected objects the models have never heard of.
    2. Anything *reflected* that is absent from our metadata is excluded. This
       catches tables added out-of-band — an extension's bookkeeping table, a
       dbt artefact — that would otherwise be proposed for deletion.

    Args:
        obj: The schema object under consideration.
        name: Its name, or ``None`` for some unnamed constraints.
        type_: ``"table"``, ``"column"``, ``"index"``, ``"unique_constraint"``, ...
        reflected: True if it came from the database, False if from metadata.
        compare_to: The corresponding object on the other side, if any.

    Returns:
        True if Alembic may manage this object.
    """
    if type_ == "table":
        if name and is_warehouse_object(name):
            logger.debug("alembic: skipping warehouse object %s", name)
            return False
        if reflected and name not in metadata.tables:
            logger.debug("alembic: skipping unmanaged table %s", name)
            return False
        return True

    # Indexes, columns and constraints inherit their table's verdict.
    parent = getattr(obj, "table", None)
    parent_name = getattr(parent, "name", None)
    if parent_name and is_warehouse_object(parent_name):
        return False
    return True
