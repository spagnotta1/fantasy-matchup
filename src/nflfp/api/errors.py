"""Domain errors to HTTP, in exactly one place.

The business layer raises :class:`~nflfp.services.errors.ServiceError`
subclasses and knows nothing about status codes. This module owns the mapping,
which means every endpoint fails the same way and adding an error type is one
line here rather than a try/except in thirty routes.

Anything that is *not* a ``ServiceError`` is a bug. It becomes a 500 with a
logged traceback and a deliberately uninformative body — an unexpected
exception's message is as likely to contain a connection string as anything
useful to a client.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from ..services.errors import (
    DataUnavailable,
    InvalidRequest,
    NoProjectionsPublished,
    NotFound,
    ServiceError,
)
from .schemas import ErrorOut

logger = logging.getLogger(__name__)

#: Domain error to status code. Order matters: the most specific class wins, so
#: this is walked as a sequence rather than looked up by type.
_STATUS_BY_ERROR: tuple[tuple[type[ServiceError], int], ...] = (
    (NotFound, status.HTTP_404_NOT_FOUND),
    # A missing relation is a server-side operational state, not a
    # client mistake. 503 with a Retry-After is the honest answer: the fix is
    # a job run, and the request will succeed unchanged afterwards.
    (DataUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE),
    (NoProjectionsPublished, status.HTTP_404_NOT_FOUND),
    # 422 rather than 400: the request was syntactically fine and semantically
    # impossible, which is the same distinction FastAPI already draws for
    # schema validation failures. Spelled numerically because Starlette renamed
    # the constant (ENTITY -> CONTENT) and importing either name pins us to a
    # version range for no benefit.
    (InvalidRequest, 422),
)


def status_for(error: ServiceError) -> int:
    """The status code for a domain error, defaulting to 400."""
    for error_type, code in _STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return code
    return status.HTTP_400_BAD_REQUEST


def _body(error: ServiceError) -> ErrorOut:
    return ErrorOut(
        code=error.code,
        message=str(error),
        field=getattr(error, "field", None),
        remedy=getattr(error, "remedy", None),
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register the handlers. Called by the app factory."""

    @app.exception_handler(ServiceError)
    async def _service_error(request: Request, exc: ServiceError) -> JSONResponse:
        code = status_for(exc)
        # A 5xx is an operational problem worth a stack trace; a 4xx is a
        # client asking for something reasonable that does not exist, and
        # logging those at warning would drown the signal.
        log = logger.error if code >= 500 else logger.info
        log(
            "%s %s -> %d %s: %s",
            request.method, request.url.path, code, exc.code, exc,
        )
        headers = {"Retry-After": "60"} if code == 503 else None
        return JSONResponse(
            status_code=code, content=_body(exc).model_dump(), headers=headers
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorOut(
                code="internal_error",
                message="An unexpected error occurred.",
            ).model_dump(),
        )
