"""Enumerations shared by the persistence layer and the services above it.

These are stored as ``TEXT`` with a ``CHECK`` constraint rather than as native
Postgres ``ENUM`` types. Adding a value to a native enum requires ``ALTER TYPE``
which cannot run inside a transaction alongside other DDL on older servers, and
removing one is not supported at all. A ``CHECK`` constraint is a plain,
reversible migration — worth the marginal storage.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """``str`` subclass enum.

    Python 3.11 ships ``enum.StrEnum``; the project targets 3.10, so this is the
    two-line equivalent. Members compare equal to their value, which is what
    makes them transparent to SQLAlchemy and to Pydantic serialisation.
    """

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


class ModelRunStatus(StrEnum):
    """Lifecycle of one execution of the prediction engine.

    ``PUBLISHED`` is the only status the read path considers. Promotion is a
    single ``UPDATE`` guarded by a partial unique index, so a model rollout —
    and its rollback — is one atomic transaction rather than a data migration.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class Algorithm(StrEnum):
    """Estimator family behind a model run.

    Recorded for lineage and for slicing backtest metrics; the prediction engine
    dispatches on the registered model name, not on this value.
    """

    BASELINE = "baseline"
    RIDGE = "ridge"
    RANDOM_FOREST = "random_forest"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    NEURAL_NET = "neural_net"
    ENSEMBLE = "ensemble"


class ScoringProfile(StrEnum):
    """League scoring formats projections are published for.

    Mirrors the keys of :data:`nflfp.scoring.PROFILES`, which remains the single
    definition of the rules themselves. ``tests/test_enums.py`` fails if the two
    drift apart, so this list cannot silently fall behind.

    ``nflverse_parity`` is intentionally absent: it is a regression fixture for
    the scoring maths, not a format anyone plays, and publishing projections for
    it would be meaningless.
    """

    STANDARD = "standard"
    HALF_PPR = "half_ppr"
    PPR = "ppr"
    PPR_TE_PREMIUM = "ppr_te_premium"


class SeasonType(StrEnum):
    """nflverse ``season_type`` values."""

    REGULAR = "REG"
    POST = "POST"


def values(enum_cls: type[Enum]) -> tuple[str, ...]:
    """The wire values of an enum, in declaration order."""
    return tuple(str(member.value) for member in enum_cls)


def sql_in_list(enum_cls: type[Enum]) -> str:
    """Render an enum as a SQL ``IN`` list, e.g. ``('a', 'b')``.

    Built explicitly rather than via ``str(tuple(...))`` because Python renders
    a one-element tuple as ``('a',)``, and that trailing comma is a syntax error
    in SQL — a bug that would only appear the day an enum is reduced to a single
    member.
    """
    escaped = ", ".join("'" + v.replace("'", "''") + "'" for v in values(enum_cls))
    return f"({escaped})"
