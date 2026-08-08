"""Job definitions and their schedules.

Schedules live here, never inside a provider. A provider knows how to fetch;
how often it *should* be fetched is an operational decision that changes with
the season — hourly on a Sunday, daily in June — and baking it into the fetch
code means a cadence change is a code change to the thing that talks to the
network.

Each job is a plain callable taking a :class:`JobContext` and returning a
:class:`JobOutcome`. That keeps the runner ignorant of what any job does, and
lets a job be tested by calling it with a session and no scheduler at all.

The cron expressions here are the source of truth for the Railway scheduled
services; ``python -m nflfp.jobs schedule`` prints them in the form Railway
wants, so the two cannot silently disagree.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class JobContext:
    """What a job is given to do its work."""

    session: Session
    #: Extra arguments from the CLI, e.g. ``{"horizon_days": 3}``.
    options: dict = field(default_factory=dict)


@dataclass
class JobOutcome:
    """What a job reports back.

    ``records`` feeds the job log's row count; ``detail`` is stored as JSONB and
    is where a job puts whatever would otherwise be lost in a log line — which
    games were skipped, which provider warned, how long a build took.
    """

    records: int = 0
    detail: dict = field(default_factory=dict)
    #: Set when a job legitimately did nothing, e.g. no upcoming games in June.
    skipped: bool = False
    skip_reason: str = ""


JobFunc = Callable[[JobContext], JobOutcome]

#: A job that is registered and runnable but never fires on a timer.
#:
#: Not every operational action has a cadence. Invalidating the cache after a
#: manual data correction is a real job — it wants the same run log, the same
#: failure recording and the same CLI as everything else — but a cron that
#: periodically performed it would be actively harmful. Modelling that as a
#: schedule string rather than as a separate concept keeps one registry, and
#: :meth:`Job.is_scheduled` is the single place anything branches on it.
MANUAL = "manual"


@dataclass(frozen=True)
class Job:
    """One registered, schedulable unit of work."""

    name: str
    func: JobFunc
    #: A five-field cron expression, or :data:`MANUAL`.
    schedule: str
    description: str
    #: Whether a failure should fail the whole scheduled batch. A weather
    #: provider outage should not stop the feature build from running on data
    #: that is already there.
    critical: bool = False

    @property
    def is_scheduled(self) -> bool:
        """Whether this job fires on a timer.

        ``run-all`` and the Railway config generator both consult this, so a
        manual-only job cannot be swept into a batch by accident — which for
        ``invalidate_cache`` would mean discarding the cache on every run.
        """
        return self.schedule != MANUAL

    def __call__(self, context: JobContext) -> JobOutcome:
        return self.func(context)


class JobRegistry:
    """Name -> job. Small and explicit, like the provider registry."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def register(self, job: Job) -> Job:
        if job.name in self._jobs:
            raise ValueError(f"duplicate job {job.name!r}")
        self._jobs[job.name] = job
        return job

    def get(self, name: str) -> Job:
        try:
            return self._jobs[name]
        except KeyError:
            raise KeyError(
                f"unknown job {name!r}; registered: {sorted(self._jobs)}"
            ) from None

    def all(self) -> list[Job]:
        return list(self._jobs.values())

    def scheduled(self) -> list[Job]:
        """Jobs that fire on a timer, in declaration order."""
        return [job for job in self._jobs.values() if job.is_scheduled]

    def names(self) -> list[str]:
        return sorted(self._jobs)


REGISTRY = JobRegistry()
