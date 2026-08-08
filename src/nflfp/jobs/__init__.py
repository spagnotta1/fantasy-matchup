"""Background job system.

Long-running work happens here, never inside an API request. The API's only
relationship to this package is that it reads what these jobs have already
written.

Three properties the design is built around:

* **Schedules are declared, not hard-coded.** A provider knows how to fetch;
  the registry knows how often. Changing cadence never touches provider code.
* **Manual execution is a first-class path.** The first thing anyone does after
  a failed run is rerun it by hand, and that path logs identically.
* **Failure is survivable.** Non-critical jobs that fail are recorded and the
  batch continues, so an odds provider outage cannot stop the feature build
  from running on data already in the warehouse.
* **Not every job has a cadence.** A job whose schedule is :data:`MANUAL` is
  registered, runnable and logged like the rest, but never swept into a batch —
  which is what stops ``invalidate_cache`` discarding the cache on a timer.

The expensive work — fitting a model over ten seasons and writing a slate — is
here rather than behind an endpoint for the obvious reason and one less
obvious one: a request-time projection would hold a database connection for
minutes, and a pool starved of connections turns one slow endpoint into a total
outage.
"""

from __future__ import annotations

from . import definitions  # noqa: F401  (registers the jobs on import)
from .registry import MANUAL, REGISTRY, Job, JobContext, JobOutcome, JobRegistry
from .runner import last_successful_run, recent_runs, run_all, run_job

__all__ = [
    "MANUAL",
    "Job",
    "JobContext",
    "JobOutcome",
    "JobRegistry",
    "REGISTRY",
    "last_successful_run",
    "recent_runs",
    "run_all",
    "run_job",
]
