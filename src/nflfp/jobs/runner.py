"""Executing jobs, with logging and failure recovery.

Every run gets a ``job_runs`` row, opened before the work starts and closed
after. That ordering is what makes a crashed process visible: a row stuck in
``running`` with no ``finished_at`` is a job that died, which is information a
row that only appears on success cannot give you.

Transaction shape
-----------------
The run log is written on its **own** connection, committed independently of
the job's work. If they shared a transaction, a failing job would roll back the
record of its own failure — leaving no trace of the thing you most need to
debug.

The job's own work runs in a single transaction that commits on success and
rolls back on any exception. A half-written odds capture is worse than none.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import get_session_factory
from ..db.models.jobs import JobRun
from .registry import REGISTRY, Job, JobContext, JobRegistry

logger = logging.getLogger(__name__)


def run_job(
    name: str,
    *,
    options: dict | None = None,
    trigger: str = "manual",
    registry: JobRegistry = REGISTRY,
) -> JobRun:
    """Execute one registered job and record the outcome.

    Args:
        name: Registered job name.
        options: Passed through to the job as :attr:`JobContext.options`.
        trigger: ``"schedule"`` or ``"manual"`` — distinguishes a cron firing
            from a human rerun, which matters when reading the log after an
            incident.
        registry: Job registry, injectable for tests.

    Returns:
        The completed :class:`JobRun` row (detached from its session).

    Raises:
        KeyError: if `name` is not registered.
    """
    job = registry.get(name)
    run = _open_run(job, trigger)
    logger.info("job %s started (run %d, trigger=%s)", job.name, run.id, trigger)

    session_factory = get_session_factory()
    try:
        with session_factory() as session:
            try:
                outcome = job(JobContext(session=session, options=options or {}))
                session.commit()
            except Exception:
                session.rollback()
                raise
    except Exception as exc:
        _close_run(run.id, status="failed", error=traceback.format_exc())
        logger.exception("job %s failed: %s", job.name, exc)
        if job.critical:
            raise
        return _load_run(run.id)

    status = "skipped" if outcome.skipped else "ok"
    detail = dict(outcome.detail)
    if outcome.skipped:
        detail["skip_reason"] = outcome.skip_reason

    _close_run(run.id, status=status, records=outcome.records, detail=detail)
    logger.info(
        "job %s %s — %d record(s)", job.name, status, outcome.records
    )
    return _load_run(run.id)


def run_all(
    *, trigger: str = "schedule", registry: JobRegistry = REGISTRY
) -> list[JobRun]:
    """Run every **scheduled** job in declaration order.

    A non-critical failure is logged and the batch continues: an odds provider
    outage must not stop the feature build from running against data that is
    already in the warehouse. That is the failure-recovery property that makes
    a scheduled batch survivable.

    Manual-only jobs are excluded. ``invalidate_cache`` is registered so it can
    be run and logged like anything else, and sweeping it into every batch
    would throw the cache away on a cadence — the opposite of what it is for.
    """
    runs = []
    for job in registry.scheduled():
        try:
            runs.append(run_job(job.name, trigger=trigger, registry=registry))
        except Exception:
            logger.error("critical job %s failed; aborting batch", job.name)
            raise
    return runs


def last_successful_run(name: str) -> JobRun | None:
    """The most recent successful run of a job, or None.

    The basis of failure recovery: a job that needs to know how much ground to
    make up asks this rather than assuming it ran an hour ago.
    """
    with get_session_factory()() as session:
        return session.scalars(
            select(JobRun)
            .where(JobRun.job_name == name, JobRun.status == "ok")
            .order_by(JobRun.started_at.desc())
            .limit(1)
        ).first()


def recent_runs(limit: int = 20, name: str | None = None) -> list[JobRun]:
    """Most recent runs, newest first, for the status CLI."""
    with get_session_factory()() as session:
        statement = select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
        if name:
            statement = statement.where(JobRun.job_name == name)
        return list(session.scalars(statement).all())


# ---------------------------------------------------------------------------
# run-log bookkeeping, on its own transaction
# ---------------------------------------------------------------------------

def _open_run(job: Job, trigger: str) -> JobRun:
    with get_session_factory()() as session:
        run = JobRun(
            job_name=job.name,
            started_at=datetime.now(timezone.utc),
            status="running",
            trigger=trigger,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        session.expunge(run)
        return run


def _close_run(
    run_id: int,
    *,
    status: str,
    records: int = 0,
    detail: dict | None = None,
    error: str | None = None,
) -> None:
    with get_session_factory()() as session:
        run = session.get(JobRun, run_id)
        if run is None:  # pragma: no cover - only if the row was deleted mid-run
            logger.error("job run %d vanished before it could be closed", run_id)
            return
        run.finished_at = datetime.now(timezone.utc)
        run.status = status
        run.records_written = records
        run.detail = detail
        run.error = error
        session.commit()


def _load_run(run_id: int) -> JobRun:
    with get_session_factory()() as session:
        run = session.get(JobRun, run_id)
        session.expunge(run)
        return run
