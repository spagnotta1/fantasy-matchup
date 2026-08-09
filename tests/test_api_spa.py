"""Serving the built frontend from the API process.

These tests exist because the routing rules are the kind that look obviously
right and are wrong in production. A catch-all that returns ``index.html`` is
one line; a catch-all that returns ``index.html`` for a *mistyped API path* is
the same line, and it turns a clean 404 into a JSON parse error in the client
with nothing in it that names the real problem.

No database is needed: none of this touches the warehouse, which is the point —
the app must serve the frontend whether or not Postgres is reachable, because a
browser that cannot load the page cannot show the user that the API is down.
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from nflfp.api.main import API_PREFIX, create_app
from nflfp.api.spa import IMMUTABLE_CACHE, NO_CACHE, _safe_join, resolve_dist_dir
from nflfp.config import Settings

INDEX_HTML = "<!doctype html><html lang='en'><body><div id='root'></div></body></html>"
BUNDLE_JS = "console.log('bundle')"


@pytest.fixture()
def dist(tmp_path):
    """A minimal build tree with the shape Vite produces."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (root / "assets" / "index-abc123.js").write_text(BUNDLE_JS, encoding="utf-8")
    (root / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return root


def app_for(dist_dir) -> object:
    return create_app(Settings(web_dist_dir=str(dist_dir) if dist_dir else None))


async def get(app, path: str, method: str = "GET"):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.request(method, path)


class TestResolution:
    """What counts as a build worth serving."""

    def test_unset_serves_no_frontend(self):
        assert resolve_dist_dir(Settings(web_dist_dir=None)) is None

    def test_a_directory_without_an_index_is_not_a_build(self, tmp_path):
        empty = tmp_path / "nothing"
        empty.mkdir()
        assert resolve_dist_dir(Settings(web_dist_dir=str(empty))) is None

    def test_a_missing_directory_is_not_an_error(self, tmp_path):
        assert resolve_dist_dir(Settings(web_dist_dir=str(tmp_path / "absent"))) is None

    def test_there_is_no_implicit_discovery(self, tmp_path, monkeypatch):
        """Behaviour must not depend on a stray build in the working tree.

        A repository-relative fallback would make the API serve whatever
        ``web/dist`` happened to contain — including a month-old build sitting
        beside a running dev server — and would make this suite pass or fail on
        whether anyone had run ``npm run build``.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "web" / "dist").mkdir(parents=True)
        (tmp_path / "web" / "dist" / "index.html").write_text(INDEX_HTML, encoding="utf-8")

        assert resolve_dist_dir(Settings(web_dist_dir=None)) is None


class TestWithoutABuild:
    """The API alone — every worker container, and local development."""

    async def test_the_root_still_describes_the_service(self):
        response = await get(app_for(None), "/")
        body = response.json()

        assert response.status_code == 200
        assert body["api"] == API_PREFIX

    async def test_an_unknown_path_is_a_json_404(self):
        response = await get(app_for(None), "/rankings/RB")

        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")


class TestWithABuild:
    """The deployed shape: one origin serving both the app and the API."""

    async def test_the_root_serves_the_application(self, dist):
        response = await get(app_for(dist), "/")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "id='root'" in response.text

    @pytest.mark.parametrize(
        "path",
        ["/rankings/RB", "/players/00-0036971", "/simulation", "/compare", "/settings"],
    )
    async def test_client_routes_resolve_to_the_application(self, dist, path):
        """Deep links are real addresses. The server has no route for them by
        design — the browser's router does — so each must return the shell."""
        response = await get(app_for(dist), path)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    async def test_the_shell_is_revalidated(self, dist):
        """`index.html` keeps its name across deploys but not its content. A
        cached copy would reference asset filenames that no longer exist."""
        response = await get(app_for(dist), "/")

        assert response.headers["cache-control"] == NO_CACHE

    async def test_hashed_assets_are_immutable(self, dist):
        response = await get(app_for(dist), "/assets/index-abc123.js")

        assert response.status_code == 200
        assert response.text == BUNDLE_JS
        assert response.headers["cache-control"] == IMMUTABLE_CACHE

    async def test_a_missing_asset_is_a_404_not_the_shell(self, dist):
        """The single most confusing failure this design can produce. Answering
        a missing bundle with HTML makes the browser report a syntax error in a
        file that returned 200, and names nothing that leads to the real cause:
        an inconsistent deploy."""
        response = await get(app_for(dist), "/assets/gone-999.js")

        assert response.status_code == 404
        assert not response.headers["content-type"].startswith("text/html")

    async def test_a_root_level_file_is_served(self, dist):
        response = await get(app_for(dist), "/favicon.svg")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg")

    async def test_head_is_answered(self, dist):
        """Uptime monitors and proxies send HEAD. FastAPI does not derive it
        from GET, so a bare `@app.get` catch-all answers 405."""
        response = await get(app_for(dist), "/", method="HEAD")

        assert response.status_code == 200


class TestTheApiIsNeverShadowed:
    """The rules that keep a frontend from swallowing the service under it."""

    async def test_an_unknown_api_path_stays_json(self, dist):
        response = await get(app_for(dist), f"{API_PREFIX}/not-a-real-endpoint")

        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        json.loads(response.text)

    async def test_the_openapi_document_is_reachable(self, dist):
        response = await get(app_for(dist), "/openapi.json")

        assert response.status_code == 200
        assert response.json()["info"]["title"].startswith("nflfp")

    async def test_the_docs_are_reachable(self, dist):
        response = await get(app_for(dist), "/docs")

        assert response.status_code == 200

    @pytest.mark.parametrize("path", ["/../pyproject.toml", "/assets/../../pyproject.toml"])
    async def test_traversal_cannot_escape_the_build(self, dist, path):
        """`full_path` is attacker controlled and the process can read whatever
        its user can. Anything that resolves outside the build must not be
        served as a file."""
        response = await get(app_for(dist), path)

        assert "[project]" not in response.text


class TestSafeJoin:
    """The traversal guard, tested directly.

    The HTTP tests above are worth keeping but are not sufficient on their own:
    an HTTP client is entitled to normalise ``..`` out of a path before it ever
    reaches the application, which would leave those tests passing against a
    guard that did nothing. These call it with the strings the guard actually
    has to reject.
    """

    @pytest.mark.parametrize(
        "relative",
        ["../pyproject.toml", "../../etc/passwd", "a/../../pyproject.toml", "/etc/passwd"],
    )
    def test_paths_outside_the_build_are_refused(self, dist, relative):
        assert _safe_join(dist, relative) is None

    @pytest.mark.parametrize("relative", ["index.html", "assets/index-abc123.js", ""])
    def test_paths_inside_the_build_resolve(self, dist, relative):
        resolved = _safe_join(dist, relative)

        assert resolved is not None
        assert dist.resolve() in {resolved, *resolved.parents}
