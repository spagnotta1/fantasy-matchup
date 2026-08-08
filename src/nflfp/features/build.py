"""Building and refreshing the feature matviews.

Two operations, because the warehouse has two update modes:

``build``
    Drop and recreate every feature view. Needed after a ``pipeline full``,
    which swaps ``raw_*`` tables and takes dependent matviews down with them,
    and whenever a definition changes.

``refresh``
    ``REFRESH MATERIALIZED VIEW CONCURRENTLY``. Needed after a ``pipeline
    refresh``, which replaces rows in place and leaves the matviews intact but
    stale.

Concurrent refresh is the default and matters: the non-concurrent form takes an
``ACCESS EXCLUSIVE`` lock, so every reader blocks until it finishes. On a Sunday
morning that is an outage. It requires a unique index, which every
:class:`~nflfp.features.base.FeatureView` declares — and it cannot run against a
view that has never been populated, so :func:`refresh_features` falls back to a
build for those.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from .base import REGISTRY, FeatureRegistry, FeatureView

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """Outcome of a build or refresh, shaped for the job log."""

    built: list[str]
    skipped: dict[str, str]
    rows: dict[str, int]
    duration_seconds: float

    def as_detail(self) -> dict:
        return {
            "built": self.built,
            "skipped": self.skipped,
            "rows": self.rows,
            "duration_seconds": round(self.duration_seconds, 2),
        }

    @property
    def total_rows(self) -> int:
        return sum(self.rows.values())

    def __str__(self) -> str:
        return (
            f"{len(self.built)} view(s), {self.total_rows:,} rows, "
            f"{self.duration_seconds:.1f}s"
            + (f", {len(self.skipped)} skipped" if self.skipped else "")
        )


def available_relations(session: Session) -> set[str]:
    """Every table, view and matview currently in the schema.

    Matviews live in ``pg_matviews``, not ``information_schema.tables`` — a
    detail that silently breaks dependency resolution if missed, since a
    feature depending on another feature would look unbuildable.
    """
    rows = session.execute(
        text(
            """
            SELECT table_name AS name FROM information_schema.tables
             WHERE table_schema = current_schema()
            UNION
            SELECT matviewname FROM pg_matviews WHERE schemaname = current_schema()
            """
        )
    ).scalars()
    return set(rows)


def build_features(
    session: Session,
    registry: FeatureRegistry = REGISTRY,
    only: list[str] | None = None,
) -> BuildResult:
    """Drop and recreate feature views, in dependency order.

    Args:
        session: Open session. The caller owns the transaction, so a failure
            part-way through rolls back and leaves the previous views in place.
        registry: Views to build. Defaults to every registered view.
        only: Restrict to these names, still respecting dependency order.

    Returns:
        What was built, what was skipped and why, and row counts.
    """
    registry.validate()
    started = time.monotonic()
    available = available_relations(session)
    ready = registry.buildable(available)
    if only:
        wanted = set(only)
        ready = [v for v in ready if v.name in wanted]

    skipped = {
        v.name: "missing " + ", ".join(d for d in v.requires if d not in available)
        for v in registry.views
        if v not in ready and not v.buildable(available)
    }

    built: list[str] = []
    rows: dict[str, int] = {}
    # Reverse order so a view is dropped before whatever it depends on.
    for view in reversed(ready):
        session.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS {view.name} CASCADE"))

    for view in ready:
        logger.info("building %s", view.name)
        session.execute(text(view.create_sql()))
        for statement in view.index_statements():
            session.execute(text(statement))
        rows[view.name] = session.execute(
            text(f"SELECT count(*) FROM {view.name}")
        ).scalar_one()
        built.append(view.name)

    result = BuildResult(built, skipped, rows, time.monotonic() - started)
    logger.info("feature build: %s", result)
    return result


def refresh_features(
    session: Session,
    registry: FeatureRegistry = REGISTRY,
    concurrently: bool = True,
) -> BuildResult:
    """Refresh populated feature views in place.

    Falls back to a full build for any view that does not exist yet, since
    ``REFRESH`` on a missing or never-populated matview is an error rather than
    a no-op.
    """
    started = time.monotonic()
    available = available_relations(session)
    ready = registry.buildable(available)

    missing = [v for v in ready if v.name not in available]
    if missing:
        logger.info(
            "%d view(s) not yet materialised (%s); building instead of refreshing",
            len(missing), ", ".join(v.name for v in missing),
        )
        return build_features(session, registry)

    refreshed: list[str] = []
    rows: dict[str, int] = {}
    for view in ready:
        mode = "CONCURRENTLY " if concurrently else ""
        logger.info("refreshing %s", view.name)
        session.execute(text(f"REFRESH MATERIALIZED VIEW {mode}{view.name}"))
        rows[view.name] = session.execute(
            text(f"SELECT count(*) FROM {view.name}")
        ).scalar_one()
        refreshed.append(view.name)

    result = BuildResult(refreshed, {}, rows, time.monotonic() - started)
    logger.info("feature refresh: %s", result)
    return result


def drop_features(session: Session, registry: FeatureRegistry = REGISTRY) -> list[str]:
    """Drop every feature view, in reverse dependency order.

    Called by the nflverse publish step: a ``full`` publish swaps ``raw_*``
    tables, and Postgres refuses to drop a table a matview depends on unless the
    drop cascades. Dropping ours first keeps that cascade from being a surprise.
    """
    dropped = []
    for view in reversed(registry.views):
        session.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS {view.name} CASCADE"))
        dropped.append(view.name)
    return dropped
