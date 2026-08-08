"""ORM mapping for the ETL run log.

These two tables already exist and are created imperatively by
:func:`nflfp.warehouse.ensure_run_log`. That is deliberate and stays: the
Railway cron image runs the pipeline and exits, and making a data load depend on
Alembic being installed and up to date would couple a job that must keep working
to a migration chain it has no business knowing about.

So the DDL exists in two places. The duplication is bounded — these tables are
append-only, they have no application semantics beyond observability, and
``tests/test_models.py`` asserts that the mapping matches the live schema
column for column. The alternative, a cron container that fails because
migrations have not run, is worse.

Alembic's baseline migration adopts the tables if they are already present
rather than recreating them, so an existing warehouse upgrades without
downtime.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base


class PipelineRun(Base):
    """One execution of ``python -m nflfp.pipeline``."""

    __tablename__ = "pipeline_runs"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mode: Mapped[str] = mapped_column(Text, nullable=False, doc="'refresh' or 'full'")
    seasons: Mapped[str | None] = mapped_column(
        Text, doc="Season list or range covered, as displayed."
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="running", doc="running | ok | failed"
    )
    rows_loaded: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text)

    datasets: Mapped[list["PipelineRunDataset"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (Index("pipeline_runs_started_idx", started_at.desc()),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PipelineRun {self.run_id} {self.mode} {self.status}>"


class PipelineRunDataset(Base):
    """Per-dataset outcome within one pipeline run."""

    __tablename__ = "pipeline_run_datasets"

    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("pipeline_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    dataset: Mapped[str] = mapped_column(Text, primary_key=True)
    action: Mapped[str] = mapped_column(
        Text, nullable=False, doc="'swap', 'skipped', or a 'replaced N rows' note."
    )
    rows_loaded: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[PipelineRun] = relationship(back_populates="datasets")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PipelineRunDataset run={self.run_id} {self.dataset} {self.rows_loaded}>"
