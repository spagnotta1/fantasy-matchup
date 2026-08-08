"""Feature view definitions and the build contract.

Why materialized views, and why the ETL owns them
-------------------------------------------------
The brief calls for feature tables rather than recomputation per request, and
that is right: a rolling 4-game opponent-adjusted aggregate over 182k
player-weeks is not something to run inside a 50 ms API budget.

They are **materialized views, owned by the ETL, not by Alembic**. That follows
from the ownership boundary in :mod:`nflfp.db.base`: every feature here reads
``raw_*`` tables, and the weekly publish does ``DROP TABLE ... CASCADE`` on
those. Postgres cascades that drop into any dependent matview. So a feature
matview cannot be a migration artefact — it would vanish on the next Tuesday
and Alembic would believe it still existed. Instead the build is idempotent and
runs after each publish, exactly like the plain views in
:mod:`nflfp.transform`.

Leakage
-------
The single most important rule in this package: **a feature may only use
information available before kickoff.** Every rolling window therefore ends at
the *previous* week (``ROWS BETWEEN n PRECEDING AND 1 PRECEDING``), never the
current one. A same-week aggregate would score brilliantly in backtesting and
be worthless in production, because on Thursday the current week has not
happened yet. :func:`nflfp.features.registry.lagged_window` exists so that no
feature has to re-derive this, and ``tests/test_features.py`` asserts no
definition contains an unlagged window.

Concurrency
-----------
Each view declares a unique index. That is not decoration: Postgres only allows
``REFRESH MATERIALIZED VIEW CONCURRENTLY`` when one exists, and a
non-concurrent refresh takes an ``ACCESS EXCLUSIVE`` lock that blocks every
reader for its duration. On a Sunday morning that is an outage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeatureView:
    """One materialized feature set.

    Attributes:
        name: Object name in Postgres. Conventionally ``feat_*``.
        sql: The ``SELECT`` body. No trailing semicolon.
        requires: Tables/views that must exist for this to build. A feature
            whose inputs are absent is skipped rather than failing the run —
            the same tolerance :mod:`nflfp.transform` applies, and what lets
            ``raw_pbp`` be optional.
        unique_index: Columns forming a unique key. Required, because it is
            what makes a concurrent refresh possible.
        indexes: Additional lookup indexes, as (suffix, columns).
        description: What the feature means, for the lineage documentation.
    """

    name: str
    sql: str
    requires: tuple[str, ...]
    unique_index: tuple[str, ...]
    indexes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    description: str = ""

    def create_sql(self) -> str:
        return f"CREATE MATERIALIZED VIEW {self.name} AS\n{self.sql}"

    def index_statements(self) -> list[str]:
        """Unique index first — a concurrent refresh depends on it existing."""
        statements = [
            f"CREATE UNIQUE INDEX IF NOT EXISTS {self.name}_key_idx "
            f"ON {self.name} ({', '.join(self.unique_index)})"
        ]
        statements.extend(
            f"CREATE INDEX IF NOT EXISTS {self.name}_{suffix}_idx "
            f"ON {self.name} ({', '.join(cols)})"
            for suffix, cols in self.indexes
        )
        return statements

    def buildable(self, available: set[str]) -> bool:
        return all(dependency in available for dependency in self.requires)


@dataclass
class FeatureRegistry:
    """Ordered collection of feature views.

    Order is dependency order and is maintained by hand. With fewer than a
    dozen views that is clearer than a topological sort over declared edges,
    and :func:`validate` catches a definition that references something built
    later.
    """

    views: list[FeatureView] = field(default_factory=list)

    def register(self, view: FeatureView) -> FeatureView:
        if any(v.name == view.name for v in self.views):
            raise ValueError(f"duplicate feature view {view.name!r}")
        self.views.append(view)
        return view

    def names(self) -> list[str]:
        return [v.name for v in self.views]

    def get(self, name: str) -> FeatureView:
        for view in self.views:
            if view.name == name:
                return view
        raise KeyError(f"unknown feature view {name!r}; known: {self.names()}")

    def buildable(self, available: set[str]) -> list[FeatureView]:
        """Views whose inputs all exist, in build order.

        A view may depend on an earlier feature view, so the available set
        grows as we walk the list.
        """
        present = set(available)
        ready = []
        for view in self.views:
            if view.buildable(present):
                ready.append(view)
                present.add(view.name)
            else:
                missing = [d for d in view.requires if d not in present]
                logger.info("skipping %s — missing %s", view.name, ", ".join(missing))
        return ready

    def validate(self) -> None:
        """Fail loudly if a view references one declared after it."""
        seen: set[str] = set()
        for view in self.views:
            for dependency in view.requires:
                if dependency.startswith("feat_") and dependency not in seen:
                    raise ValueError(
                        f"{view.name} depends on {dependency}, which is registered later"
                    )
            seen.add(view.name)


#: The process-wide registry. Feature modules append to it at import time.
REGISTRY = FeatureRegistry()


def lagged_window(
    partition: str, order: str = "season, week", preceding: int = 4
) -> str:
    """A window frame that ends *before* the current row.

    This is the anti-leakage primitive. ``ROWS BETWEEN n PRECEDING AND 1
    PRECEDING`` means a week-8 row sees weeks 4-7 and never week 8 — which is
    exactly what is known when the projection is generated on Thursday.

    Args:
        partition: PARTITION BY expression, e.g. ``"player_id"``.
        order: ORDER BY expression. Must be chronological.
        preceding: Window length in games.
    """
    return (
        f"OVER (PARTITION BY {partition} ORDER BY {order} "
        f"ROWS BETWEEN {preceding} PRECEDING AND 1 PRECEDING)"
    )


def register(factory: Callable[[], FeatureView]) -> FeatureView:
    """Decorator-friendly registration helper."""
    return REGISTRY.register(factory())
