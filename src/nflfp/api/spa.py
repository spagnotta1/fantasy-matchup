"""Serve the built frontend from the API process.

Same origin, deliberately. The client calls a relative ``/api/v1`` — there is no
absolute base URL compiled into the bundle, no CORS preflight on every request,
and no second hostname to keep in step with the first. A frontend on its own
origin would need all three, and the failure mode is a deploy where the app
loads and every request in it fails.

This module is inert unless ``WEB_DIST_DIR`` points at a real build. The ETL,
projection, warmer and provider containers run the same image and have no
business serving a frontend; local development runs the Vite dev server, which
proxies ``/api`` here. In both cases ``mount_frontend`` returns immediately and
the API is exactly the JSON service it was before.

Three rules govern what a path resolves to, and the order matters:

1. ``/api``, ``/docs``, ``/redoc``, ``/openapi.json`` are never the frontend's.
   A wrong API path must return the API's JSON 404, not an HTML page — a client
   that receives ``<!doctype html>`` where it expected an error envelope fails
   with a parse error that names nothing useful.
2. A request for a real file gets that file.
3. Anything else gets ``index.html``, because the router owns it. ``/rankings/RB``
   is a real address a person can paste into a browser, and the server has no
   route for it by design.

The exception to rule 3 is a missing *asset*. A request for a hashed bundle that
is not on disk means the deploy is inconsistent; answering it with ``index.html``
would hand the browser HTML where it asked for JavaScript, and the console error
would blame a syntax error in a file that is actually a 200 for the wrong thing.
Those 404.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import Settings

logger = logging.getLogger(__name__)

#: Paths that belong to the API no matter what the frontend build contains.
RESERVED_PREFIXES = ("api", "docs", "redoc", "openapi.json")

#: Vite writes content-hashed filenames here, so the bytes at a given name can
#: never change. Anything that *can* change is excluded from this rule.
ASSET_DIR = "assets"

#: A year, the maximum any cache should hold something. Safe only because the
#: filename changes whenever the content does.
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"

#: `index.html` is the one file whose name is stable and whose content changes
#: every deploy. It must be revalidated or a browser will run last release's
#: HTML — pointing at asset filenames that no longer exist — until it expires.
NO_CACHE = "no-cache, must-revalidate"


def resolve_dist_dir(settings: Settings) -> Path | None:
    """Locate the built frontend, or ``None`` when there is not one.

    Configuration only. There is deliberately no "look for ``web/dist`` next to
    the source" fallback, tempting as it is: it would make what the API serves
    depend on whether a build artefact happens to be lying in the working tree.
    A developer running the Vite dev server with a stale ``dist`` from last
    month would be served the stale one at ``/`` and spend a while working out
    why their changes were not showing up — and the test suite would pass or
    fail on whether anyone had run ``npm run build``.

    To exercise the deployed same-origin shape locally, say so::

        npm --prefix web run build
        WEB_DIST_DIR=web/dist python -m nflfp.api --port 8010
    """
    if not settings.web_dist_dir:
        return None

    configured = Path(settings.web_dist_dir).expanduser()
    if (configured / "index.html").is_file():
        return configured

    logger.warning(
        "WEB_DIST_DIR is set to %s but holds no index.html; serving the API only",
        configured,
    )
    return None


def mount_frontend(app: FastAPI, settings: Settings) -> bool:
    """Attach the single-page app to ``app``. Returns whether anything mounted.

    Must be called *after* every API router is registered. The catch-all added
    here matches any path that earlier routes did not, and a route registered
    after it would be unreachable.
    """
    dist = resolve_dist_dir(settings)
    if dist is None:
        logger.info("no frontend build found; serving the API only")
        return False

    index = dist / "index.html"

    assets = dist / ASSET_DIR
    if assets.is_dir():
        # Mounted rather than routed through the catch-all so a hashed bundle is
        # streamed by Starlette's file server, with range requests and ETags,
        # instead of being read through Python on every request.
        app.mount(
            f"/{ASSET_DIR}",
            _ImmutableStatic(directory=assets),
            name="assets",
        )

    # HEAD as well as GET. Starlette derives HEAD from GET for plain routes but
    # FastAPI's router does not, and a bare `@app.get` here answers 405 to the
    # HEAD that uptime monitors, proxies and link checkers send at `/`.
    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        head = full_path.split("/", 1)[0]
        if head in RESERVED_PREFIXES:
            # Reachable only for a path no API route claimed. Raising here keeps
            # the response in the API's own error shape rather than inventing a
            # second one.
            raise HTTPException(status_code=404, detail="Not Found")

        candidate = _safe_join(dist, full_path)
        if candidate is not None and candidate.is_file():
            return FileResponse(candidate)

        if head == ASSET_DIR:
            raise HTTPException(status_code=404, detail="Not Found")

        return FileResponse(index, headers={"Cache-Control": NO_CACHE})

    logger.info("serving frontend from %s", dist)
    return True


def _safe_join(root: Path, relative: str) -> Path | None:
    """Resolve ``relative`` under ``root``, or ``None`` if it escapes.

    ``full_path`` arrives from the URL. Without this check a request for
    ``../../etc/passwd`` would be resolved and served: the path is attacker
    controlled and the process can read everything its user can.
    """
    try:
        resolved = (root / relative).resolve()
    except (OSError, ValueError):
        return None

    root_resolved = root.resolve()
    if resolved == root_resolved or root_resolved in resolved.parents:
        return resolved
    return None


class _ImmutableStatic(StaticFiles):
    """``StaticFiles`` that marks every response immutable.

    Correct only for content-addressed filenames, which is why it is used for
    the asset directory alone and never for the directory root.
    """

    def file_response(self, *args, **kwargs) -> FileResponse:  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = IMMUTABLE_CACHE
        return response
