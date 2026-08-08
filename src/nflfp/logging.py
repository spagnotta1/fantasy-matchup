"""Logging configuration, shared by every process shape.

The API, the workers, the scheduled jobs and the ETL all run from the same
image, and their logs land in the same place. If each configured logging its
own way, "find every log line for the request that produced this wrong number"
would require three different queries and would still miss the job that wrote
the row. So there is one configuration function and one format.

Two formats, one decision
-------------------------
Locally a human reads the stream, so lines are aligned text. Deployed,
Railway's log pipeline indexes JSON fields, and a message like
``job refresh_odds ok — 17 records`` is a string you can only grep, whereas
``{"job":"refresh_odds","records":17}`` is a field you can filter and chart.
``LOG_JSON`` follows ``ENVIRONMENT`` by default for that reason.

Request correlation
-------------------
:data:`request_id` is a context variable, set by the API middleware and read by
the formatter. That is what makes one field connect a slow response to the
query that caused it, and it works without threading an id through every
function signature — including the ones in ``nflfp.services``, which must not
know a request exists.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

#: Correlation id for the request currently being served, or None outside one.
request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

#: Correlation id for the job run currently executing. The job equivalent of
#: the above, so a projection's log lines can be tied to the ``job_runs`` row
#: that recorded them.
job_run_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "job_run_id", default=None
)

#: Fields the JSON formatter never copies from a LogRecord — they are either
#: already emitted under another name or are noise in a log pipeline.
_RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    ``extra={...}`` on any log call is copied into the object, so a caller adds
    a queryable field without a formatter change::

        logger.info("job finished", extra={"job": name, "records": n})
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        current_request = request_id.get()
        if current_request:
            payload["request_id"] = current_request
        current_job = job_run_id.get()
        if current_job is not None:
            payload["job_run_id"] = current_job
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        # default=str so an unexpected object in `extra` degrades to its repr
        # instead of raising inside the logging call that was trying to report
        # a problem.
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """Aligned text with the request id appended when there is one."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        current = request_id.get()
        return f"{line}  [{current[:8]}]" if current else line


def configure_logging(settings=None, *, force: bool = True) -> None:
    """Install the root handler for this process.

    Args:
        settings: :class:`~nflfp.config.Settings`; read from the environment
            when omitted.
        force: Replace existing handlers. True by default because uvicorn and
            ``logging.basicConfig`` both install their own, and two handlers on
            the root logger means every line is emitted twice — which in a
            deployed environment doubles the log bill and makes a count of
            errors wrong.
    """
    from .config import get_settings

    settings = settings or get_settings()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_json else TextFormatter())

    root = logging.getLogger()
    if force or not root.handlers:
        root.handlers = [handler]
    root.setLevel(settings.log_level)

    # uvicorn installs its own handlers on these before the app is imported.
    # Left alone, access lines bypass the formatter above and arrive as plain
    # text in the middle of a JSON stream, which breaks the log parser for
    # every line — not just uvicorn's.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    # SQLAlchemy's engine logger is chatty at INFO when echo is on and silent
    # otherwise; pinning it stops a global DEBUG level dumping every statement
    # and its parameters — which for this application would include a full
    # feature vector per projection.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.db_echo else logging.WARNING
    )
