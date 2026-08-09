"""Domain errors to HTTP, in exactly one place.

The business layer raises :class:`~nflfp.services.errors.ServiceError`
subclasses and knows nothing about status codes. This module owns the mapping,
which means every endpoint fails the same way and adding an error type is one
line here rather than a try/except in thirty routes.

Two families of failure never reach a service and are handled here too: an
``HTTPException`` the framework raises for an unrouted path or a wrong method,
and a ``RequestValidationError`` for a request that failed schema validation.
Both arrive in Starlette's ``{"detail": ...}`` shape by default, which would
give the API a second, undocumented error contract — and it would be the one a
client meets first, since a typo'd path and a malformed parameter are the two
most common integration mistakes. They are re-shaped rather than left alone.

Anything that is *not* one of those is a bug. It becomes a 500 with a logged
traceback and a deliberately uninformative body — an unexpected exception's
message is as likely to contain a connection string as anything useful to a
client.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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


#: Status code to error code, for failures raised by the *framework* rather
#: than by a service: an unrouted path, a wrong method, a malformed body. These
#: never reach a service, so they would otherwise escape in Starlette's
#: ``{"detail": ...}`` shape — a second error contract, produced by exactly the
#: requests a client is most likely to get wrong while integrating.
_CODE_BY_STATUS: dict[int, str] = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "invalid_request",
    429: "rate_limited",
    500: "internal_error",
    503: "data_unavailable",
}

#: What to say for the statuses a client actually hits, in the API's own terms.
#: Starlette's stock phrasing ("Not Found") describes the protocol; this
#: describes the product.
_MESSAGE_BY_STATUS: dict[int, str] = {
    404: "No such endpoint or resource.",
    405: "That method is not allowed on this endpoint.",
}


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


#: Starlette's default detail for a status is the reason phrase, which says
#: nothing the status code did not. Replaced rather than echoed.
_STOCK_DETAIL = frozenset(
    {"Not Found", "Method Not Allowed", "Internal Server Error", "Forbidden"}
)


def _http_body(exc: StarletteHTTPException) -> ErrorOut:
    """An ``HTTPException`` in the API's error shape.

    A raiser that supplied its own ``detail`` keeps it; a stock reason phrase is
    replaced with something that tells the reader what to do.
    """
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail else None
    if detail in _STOCK_DETAIL:
        detail = None
    return ErrorOut(
        code=_CODE_BY_STATUS.get(exc.status_code, f"http_{exc.status_code}"),
        message=(
            detail
            or _MESSAGE_BY_STATUS.get(exc.status_code)
            or f"The request failed with status {exc.status_code}."
        ),
        remedy=(
            "See /docs for the endpoints this API serves."
            if exc.status_code in (404, 405)
            else None
        ),
    )


def _validation_body(exc: RequestValidationError) -> ErrorOut:
    """A request-schema failure in the API's error shape.

    FastAPI's default is a list of Pydantic issues under ``detail``, which is a
    second error contract for the case a client hits most often while
    integrating. The first issue is reported: a client fixes one thing at a
    time, and ``field`` is what the frontend highlights.

    The ``body``/``query``/``path`` prefix is dropped from the location. It
    names the transport, and the caller knows where they put the parameter.
    """
    errors = exc.errors()
    first = errors[0] if errors else {}
    location = [str(part) for part in first.get("loc", ())]
    if location and location[0] in ("body", "query", "path", "header", "cookie"):
        location = location[1:]
    field = ".".join(location) or None
    detail = first.get("msg") or "The request was not valid."
    message = detail if field is None else f"{field}: {detail}"
    if len(errors) > 1:
        message += f" ({len(errors) - 1} further problem(s) with this request.)"
    return ErrorOut(code="invalid_request", message=message, field=field)


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

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # Raised by the framework, not by us: an unrouted path, a wrong method,
        # the SPA catch-all refusing to answer an `/api` path with HTML. Without
        # this the API would have two error shapes, and the one a client meets
        # first while integrating would be the undocumented one.
        return JSONResponse(
            status_code=exc.status_code,
            content=_http_body(exc).model_dump(),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 422, matching InvalidRequest: a request that parsed but asks for
        # something impossible. Which of the two produced it is an internal
        # detail, so they answer identically.
        return JSONResponse(
            status_code=422, content=_validation_body(exc).model_dump()
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
