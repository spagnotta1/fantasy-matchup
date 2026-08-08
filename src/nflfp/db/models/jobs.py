"""Scheduled job execution log.

Separate from ``pipeline_runs``, which records nflverse loads specifically and
is written by a process that must not depend on migrations. This table records
*any* scheduled job — provider refreshes, feature builds, and later model
training — and is what makes failure recovery possible: a runner can ask "when
did this last succeed?" and pick up from there instead of reprocessing history
or, worse, silently skipping a window.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")

#: Terminal and in-flight states a job run can be in.
JOB_STATUSES = ("running", "ok", "failed", "skipped")


class JobRun(Base):
    """One execution of a registered job."""

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="running"
    )

    records_written: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    trigger: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="manual",
        doc="'schedule' or 'manual' — distinguishes a cron run from a human rerun.",
    )
    detail: Mapped[dict | None] = mapped_column(
        JSONType, doc="Per-job summary: counts, skipped games, provider warnings."
    )
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'ok', 'failed', 'skipped')", name="status_known"
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finished_after_started"
        ),
        # Serves "when did this job last succeed?", the question failure
        # recovery is built on.
        Index("ix_job_runs_name_started", "job_name", text("started_at DESC")),
    )

    @property
    def duration_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<JobRun {self.id} {self.job_name} {self.status}>"
