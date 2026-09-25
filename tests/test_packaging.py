"""The declared dependencies, checked against the ways they have broken prod.

A developer machine keeps whatever it installed months ago; the image resolves
every range fresh on each build. So a dependency the code needs but the package
does not declare passes every local test and crashes in production — which is
exactly how SQLAlchemy 2.1, which stopped installing greenlet by default,
crashed every Railway service rebuilt after it was released (the API kept
serving only because its last good deploy stayed live). These tests read the
declarations themselves, so the gap shows up here instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Standard library from 3.11; the production image is 3.12. On a 3.10 dev venv
# these checks skip rather than error.
tomllib = pytest.importorskip("tomllib")

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_dependencies() -> list[str]:
    with open(ROOT / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)["project"]["dependencies"]


def _requirement_names(lines: list[str]) -> dict[str, str]:
    specs: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[\[<>=!~ ]", line, maxsplit=1)[0].lower()
        specs[name] = line.replace(" ", "")
    return specs


def test_sqlalchemy_is_declared_with_its_asyncio_extra():
    """The API, the warmer and every service use the async engine."""
    (spec,) = [d for d in _pyproject_dependencies() if d.lower().startswith("sqlalchemy")]
    assert "[asyncio]" in spec, spec


def test_sqlalchemy_stays_on_the_series_the_suite_runs_against():
    (spec,) = [d for d in _pyproject_dependencies() if d.lower().startswith("sqlalchemy")]
    assert "<2.1" in spec.replace(" ", ""), spec


def test_requirements_txt_matches_pyproject():
    """requirements.txt says it is kept in sync; hold it to that."""
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert _requirement_names(lines) == _requirement_names(_pyproject_dependencies())
