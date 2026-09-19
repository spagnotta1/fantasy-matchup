"""Guards on the weekly path.

`pipeline.py` had no test module at all, which is how a dataset nflverse had
not published yet became a silent skip that still exited 0. These cover the
parts that can be exercised without a live warehouse; `run()` itself is
integration-only.
"""

from __future__ import annotations

import pytest

from nflfp import pipeline
from nflfp.etl import IngestResult
from nflfp.jobs.definitions import _assert_provider_reached


class _FakeCursor:
    """Enough of a psycopg cursor for the publish paths."""

    def __init__(self, deleted: int = 0, inserted: int = 0) -> None:
        self._deleted, self._inserted = deleted, inserted
        self.rowcount = 0
        self.statements: list[str] = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if sql.lstrip().startswith("DELETE"):
            self.rowcount = self._deleted
        elif sql.lstrip().startswith("INSERT"):
            self.rowcount = self._inserted

    def fetchall(self):
        return []


class TestPublishRetention:
    """A partial upstream build must not be swapped over good data."""

    def _counts(self, monkeypatch, *, live: int, staging: int, exists: bool = True):
        monkeypatch.setattr(pipeline.pg, "table_exists", lambda cur, t: exists)
        monkeypatch.setattr(
            pipeline,
            "_row_count",
            lambda cur, table: staging if table.startswith("stg_") else live,
        )

    def test_a_truncated_swap_is_refused(self, monkeypatch):
        """The failure this exists for: nflverse regenerating a parquet from an
        incomplete build, and the swap committing cleanly over the good table."""
        self._counts(monkeypatch, live=182_252, staging=40_000)
        with pytest.raises(RuntimeError, match="refusing to publish"):
            pipeline._assert_retains_rows(
                None, "player_week", "raw_player_week", "stg_raw_player_week"
            )

    def test_a_growing_table_publishes(self, monkeypatch):
        """The ordinary in-season case: a week of games has been added."""
        self._counts(monkeypatch, live=182_252, staging=183_100)
        pipeline._assert_retains_rows(
            None, "player_week", "raw_player_week", "stg_raw_player_week"
        )

    def test_small_shrinkage_is_tolerated(self, monkeypatch):
        """Upstream withdrawing a handful of rows is a correction, not an outage."""
        self._counts(monkeypatch, live=1_000, staging=960)
        pipeline._assert_retains_rows(None, "x", "raw_x", "stg_raw_x")

    def test_a_first_run_has_nothing_to_protect(self, monkeypatch):
        self._counts(monkeypatch, live=0, staging=0, exists=False)
        pipeline._assert_retains_rows(None, "x", "raw_x", "stg_raw_x")

    def test_an_empty_live_table_does_not_block_a_first_load(self, monkeypatch):
        self._counts(monkeypatch, live=0, staging=5_000)
        pipeline._assert_retains_rows(None, "x", "raw_x", "stg_raw_x")


class TestPublishBySeason:
    def _patch(self, monkeypatch):
        monkeypatch.setattr(pipeline.pg, "table_exists", lambda cur, t: True)
        monkeypatch.setattr(pipeline.pg, "columns", lambda cur, t: ["season", "x"])
        monkeypatch.setattr(
            pipeline, "_staging_column_types", lambda cur, t: {"season": "int", "x": "int"}
        )

    def _dataset(self):
        return pipeline.DATASETS_BY_NAME["player_week"]

    def test_replacing_a_season_with_far_fewer_rows_is_refused(self, monkeypatch):
        self._patch(monkeypatch)
        cur = _FakeCursor(deleted=5_000, inserted=800)
        with pytest.raises(RuntimeError, match="refusing to publish"):
            pipeline.publish_by_season(cur, self._dataset(), [2026])

    def test_a_season_that_grew_publishes(self, monkeypatch):
        self._patch(monkeypatch)
        cur = _FakeCursor(deleted=5_000, inserted=5_400)
        note = pipeline.publish_by_season(cur, self._dataset(), [2026])
        assert "replaced 5,000 rows" in note

    def test_a_first_season_load_deletes_nothing_and_is_allowed(self, monkeypatch):
        self._patch(monkeypatch)
        cur = _FakeCursor(deleted=0, inserted=1_200)
        pipeline.publish_by_season(cur, self._dataset(), [2026])


class TestProviderReached:
    """Per-game skips are the contract. Every game skipped is an outage.

    These build a real :class:`~nflfp.etl.IngestResult` rather than a stub. The
    previous local fake gave ``skipped`` a dict, copying ``ProviderFetch`` and
    not the type the jobs actually pass, so every case here exercised a branch
    that could not run in production -- and the guard raised `TypeError` on the
    live path for an hourly cron while these stayed green.
    """

    def _games(self, n: int) -> list[object]:
        return [object() for _ in range(n)]

    def _result(self, *, fetched: int, written: int, skipped: int) -> IngestResult:
        return IngestResult(
            provider="espn",
            fetched=fetched,
            written=written,
            skipped=skipped,
            warnings=["2026 week 3: no markets parsed from the response"],
        )

    def test_every_game_skipped_and_nothing_fetched_raises(self):
        games = self._games(16)
        result = self._result(fetched=0, written=0, skipped=16)
        with pytest.raises(RuntimeError, match="outage, not an empty slate"):
            _assert_provider_reached("refresh_odds", result, games)

    def test_the_outage_message_names_the_provider_warning(self):
        games = self._games(16)
        result = self._result(fetched=0, written=0, skipped=16)
        with pytest.raises(RuntimeError, match="no markets parsed"):
            _assert_provider_reached("refresh_odds", result, games)

    def test_an_unchanged_market_is_not_an_outage(self):
        """The regression. A quiet hour fetches every game and writes none.

        Change detection drops snapshots identical to the last capture, so
        ``written == 0`` is the ordinary outcome on a slate whose line has not
        moved -- the exact shape that crashed `refresh-odds` hourly: 31 games
        up, 30 fetched, 1 already played, nothing new to store.
        """
        games = self._games(31)
        result = self._result(fetched=30, written=0, skipped=1)
        _assert_provider_reached("refresh_odds", result, games)

    def test_an_unpriced_august_slate_is_not_an_outage_if_anything_landed(self):
        games = self._games(16)
        result = self._result(fetched=3, written=3, skipped=13)
        _assert_provider_reached("refresh_odds", result, games)

    def test_a_partially_skipped_week_is_allowed(self):
        games = self._games(16)
        result = self._result(fetched=7, written=0, skipped=9)
        _assert_provider_reached("refresh_odds", result, games)

    def test_no_games_is_not_an_outage(self):
        result = self._result(fetched=0, written=0, skipped=0)
        _assert_provider_reached("refresh_odds", result, [])

    def test_an_outage_with_no_warnings_still_raises(self):
        games = self._games(16)
        result = IngestResult(provider="espn", fetched=0, written=0, skipped=16)
        with pytest.raises(RuntimeError, match="outage, not an empty slate"):
            _assert_provider_reached("refresh_odds", result, games)
