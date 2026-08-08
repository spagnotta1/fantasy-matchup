"""Request context: correlation ids, timing, and a single access log line.

Why this is not left to uvicorn's access log
--------------------------------------------
uvicorn logs a line per request with no correlation id, no duration in a form
you can aggregate, and no way to tie it to the ``job_runs`` row or the SQL that
ran underneath it. This middleware emits one structured line instead, and sets
the context variable that puts the same id on every log record the request
produces — including the ones from :mod:`nflfp.services`, which must not know
that HTTP exists.

An inbound ``X-Request-ID`` is honoured. Railway's edge and any proxy in front
of it already stamp one; generating a second means the id in the platform's log
and the id in ours cannot be joined, which defeats the purpose.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..logging import request_id

logger = logging.getLogger("nflfp.access")

REQUEST_ID_HEADER = "X-Request-ID"
RESPONSE_TIME_HEADER = "X-Response-Time-ms"

#: Paths that do not get an access line. A platform health check runs every few
#: seconds forever; logging it buries every real request in noise and is most of
#: the log volume of an idle service.
_QUIET_PATHS = ("/api/v1/health", "/health")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Stamp a correlation id, time the request, log one structured line."""

    def __init__(self, app, *, slow_request_ms: int = 1000) -> None:
        super().__init__(app)
        self._slow_ms = slow_request_ms

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        correlation = incoming or uuid.uuid4().hex
        token = request_id.set(correlation)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # The error handlers turn known failures into responses, so
            # anything arriving here is unhandled. It is logged with the same
            # correlation id and re-raised — swallowing it would return a 200
            # with no body, which is far harder to diagnose than a 500.
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "%s %s failed after %.1fms",
                request.method, request.url.path, elapsed_ms,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(elapsed_ms, 1),
                    "status": 500,
                },
            )
            raise
        finally:
            request_id.reset(token)

        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = correlation
        response.headers[RESPONSE_TIME_HEADER] = f"{elapsed_ms:.1f}"

        if not request.url.path.startswith(_QUIET_PATHS):
            level = logging.WARNING if elapsed_ms >= self._slow_ms else logging.INFO
            logger.log(
                level,
                "%s %s %d %.1fms",
                request.method, request.url.path, response.status_code, elapsed_ms,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(elapsed_ms, 1),
                    "cache": response.headers.get("X-Cache"),
                    "query": str(request.url.query) or None,
                },
            )
        return response
