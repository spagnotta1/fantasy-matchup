"""Logging configuration.

The property under test is correlation: one field connecting a slow response to
the query underneath it, set without threading an id through every function
signature — including the ones in ``nflfp.services``, which must not know that
HTTP exists.
"""

from __future__ import annotations

import json
import logging

import pytest

from nflfp.config import Settings
from nflfp.logging import (
    JsonFormatter,
    TextFormatter,
    configure_logging,
    job_run_id,
    request_id,
)


def _record(message: str = "hello", **extra) -> logging.LogRecord:
    record = logging.LogRecord("nflfp.test", logging.INFO, __file__, 1, message, (), None)
    record.__dict__.update(extra)
    return record


@pytest.fixture(autouse=True)
def _clean_context():
    request_token = request_id.set(None)
    job_token = job_run_id.set(None)
    yield
    request_id.reset(request_token)
    job_run_id.reset(job_token)


class TestJsonFormatter:
    def test_emits_one_parseable_object_per_line(self):
        payload = json.loads(JsonFormatter().format(_record()))
        assert payload["message"] == "hello"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "nflfp.test"
        assert "\n" not in JsonFormatter().format(_record())

    def test_extra_fields_become_queryable_fields(self):
        """`extra={...}` on any log call must arrive as a field, so a caller
        adds something filterable without a formatter change."""
        payload = json.loads(JsonFormatter().format(_record(job="refresh_odds", records=17)))
        assert payload["job"] == "refresh_odds"
        assert payload["records"] == 17

    def test_the_request_id_is_attached_without_the_caller_passing_it(self):
        request_id.set("abc123")
        payload = json.loads(JsonFormatter().format(_record()))
        assert payload["request_id"] == "abc123"

    def test_the_job_run_id_ties_a_line_to_its_run_row(self):
        job_run_id.set(42)
        payload = json.loads(JsonFormatter().format(_record()))
        assert payload["job_run_id"] == 42

    def test_no_correlation_id_means_no_empty_field(self):
        payload = json.loads(JsonFormatter().format(_record()))
        assert "request_id" not in payload

    def test_an_unserialisable_extra_degrades_rather_than_raising(self):
        """A formatter that raises inside the log call trying to report a
        problem loses the problem."""
        payload = json.loads(JsonFormatter().format(_record(obj=object())))
        assert isinstance(payload["obj"], str)

    def test_an_exception_is_captured(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = _record()
            record.exc_info = sys.exc_info()
        payload = json.loads(JsonFormatter().format(record))
        assert "ValueError: boom" in payload["exception"]


class TestTextFormatter:
    def test_appends_a_short_request_id_when_there_is_one(self):
        request_id.set("abcdef0123456789")
        assert TextFormatter().format(_record()).endswith("[abcdef01]")

    def test_stays_clean_outside_a_request(self):
        assert "[" not in TextFormatter().format(_record()).split(": ", 1)[1]


class TestConfigure:
    def test_installs_exactly_one_handler(self):
        """Two handlers on the root logger emits every line twice, which
        doubles the log bill and makes a count of errors wrong."""
        root = logging.getLogger()
        original = root.handlers[:]
        try:
            configure_logging(Settings())
            configure_logging(Settings())
            assert len(root.handlers) == 1
        finally:
            root.handlers = original

    def test_json_in_deployed_environments_text_locally(self):
        root = logging.getLogger()
        original = root.handlers[:]
        try:
            configure_logging(Settings(log_json=True))
            assert isinstance(root.handlers[0].formatter, JsonFormatter)
            configure_logging(Settings(log_json=False))
            assert isinstance(root.handlers[0].formatter, TextFormatter)
        finally:
            root.handlers = original

    def test_uvicorn_loggers_are_made_to_propagate(self):
        """Left alone, uvicorn's own handlers emit plain text into the middle
        of a JSON stream, which breaks the parser for every line."""
        root = logging.getLogger()
        original = root.handlers[:]
        try:
            logging.getLogger("uvicorn.access").addHandler(logging.NullHandler())
            configure_logging(Settings(log_json=True))
            access = logging.getLogger("uvicorn.access")
            assert access.handlers == []
            assert access.propagate is True
        finally:
            root.handlers = original

    def test_sqlalchemy_is_pinned_so_a_global_debug_does_not_dump_every_query(self):
        root = logging.getLogger()
        original = root.handlers[:]
        try:
            configure_logging(Settings(log_level="DEBUG", db_echo=False))
            assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING
        finally:
            root.handlers = original
