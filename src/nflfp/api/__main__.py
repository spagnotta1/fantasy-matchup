"""Run the API: ``python -m nflfp.api``.

This entry point exists for one reason, and it is a real one rather than a
convenience wrapper.

The Windows event-loop trap
---------------------------
psycopg's async implementation **refuses to run on ``ProactorEventLoop``**, and
uvicorn selects exactly that loop on Windows whenever it is not running under a
reloader — its loop factory returns ``ProactorEventLoop`` directly, bypassing
the event-loop policy, so setting the policy yourself has no effect. The result
is that ``uvicorn nflfp.api.main:app`` starts cleanly, serves ``/health`` as
``degraded``, and fails every database request with an ``InterfaceError`` that
mentions neither uvicorn nor Postgres.

``uvicorn ... --reload`` happens to work, because a reloader runs the server in
a subprocess and uvicorn switches to ``SelectorEventLoop`` for that case. That
is a trap: the documented development command works and the production-shaped
command silently does not.

So this module installs the selector policy and hands uvicorn ``loop="none"``,
which tells it to use the loop it is given instead of building its own. Railway
runs Linux, where none of this applies — but a local run that behaves
differently from the deployed one is worth eliminating rather than documenting.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ..config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m nflfp.api", description="Run the nflfp REST API."
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload", action="store_true", help="Reload on source changes (development)."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Worker processes. Size DB_POOL_SIZE against the Postgres "
            "connection limit divided by total workers across all services."
        ),
    )
    args = parser.parse_args(argv)

    import uvicorn

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    settings = get_settings()

    if args.reload or args.workers > 1:
        # Reload and multi-worker modes need an import string, because the app
        # is built inside each child process. uvicorn uses SelectorEventLoop for
        # subprocess modes already, so the guard above is redundant here.
        uvicorn.run(
            "nflfp.api.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            workers=None if args.reload else args.workers,
            log_level=settings.log_level.lower(),
        )
        return 0

    from .main import create_app

    config = uvicorn.Config(
        create_app(settings),
        host=args.host,
        port=args.port,
        # "none" leaves the loop alone, so the policy set above is the one used.
        loop="none",
        log_level=settings.log_level.lower(),
    )
    asyncio.run(uvicorn.Server(config).serve())
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
