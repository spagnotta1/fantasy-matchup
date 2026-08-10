"""How many times the read path talks to Postgres to answer one request.

Latency on a managed database is dominated by round-trips, not by the work in
any one of them, and the guards that make an unbuilt warehouse produce a fixable
error rather than a 500 used to be a separate ``SELECT`` each. Opening a cold
slate therefore spent eight sequential round-trips confirming that eight
relations existed before running the one query anybody wanted.

These tests count statements rather than measure milliseconds. A count is exact,
it is the same number on a laptop and on Railway, and it is the quantity that
actually scales with network latency — asserting a duration here would be
asserting how far this machine is from its database.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, text

from nflfp.services import repository

from .conftest import requires_db
from .warehouse_stub import SEASON, UPCOMING_WEEK, build_warehouse

pytestmark = [pytest.mark.integration, requires_db]


@pytest.fixture()
async def warehouse(async_db_session):
    """The same stub warehouse the repository's SQL tests run against.

    Needed because the guards under test are guards on *warehouse* relations:
    counting round-trips against a schema where the feature matviews genuinely
    do not exist would count the round-trips of an error path.
    """
    await build_warehouse(async_db_session)
    return async_db_session


class StatementCounter:
    """Counts statements issued on an async engine.

    Hooks the *sync* engine underneath, which is where SQLAlchemy emits cursor
    events for the async facade — and is the only level at which a round-trip
    is visible, because the async session batches nothing above it.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        # Stored whole. Truncating here once cost an afternoon: the projection
        # queries open with a CTE far longer than any sensible preview, so a
        # clipped statement matches nothing that appears after it.
        self.statements.append(" ".join(statement.split()))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def attach(self, async_engine):
        event.listen(async_engine.sync_engine, "before_cursor_execute", self._record)
        return self

    def detach(self, async_engine):
        event.remove(async_engine.sync_engine, "before_cursor_execute", self._record)

    def reset(self) -> None:
        self.statements.clear()

    @property
    def count(self) -> int:
        return len(self.statements)

    def regclass_statements(self) -> list[str]:
        return [s for s in self.statements if "to_regclass" in s]

    def count_statements(self) -> list[str]:
        """`count_projections` specifically, not any statement with a count in it."""
        return [s for s in self.statements if "SELECT count(*)" in s]


@pytest.fixture()
def counter(warehouse):
    probe = StatementCounter().attach(warehouse.bind)
    try:
        yield probe
    finally:
        probe.detach(warehouse.bind)


class TestRelationGuards:
    async def test_a_cold_guard_costs_one_round_trip_not_one_per_relation(
        self, warehouse, counter
    ):
        repository.clear_relation_cache()
        counter.reset()

        await repository.require_relations(
            warehouse,
            "projections",
            "projection_points",
            "model_runs",
            "feat_player_usage",
            "feat_defense_position",
            "feat_defense_game",
            "feat_game_context",
        )

        assert len(counter.regclass_statements()) == 1, (
            f"seven relations cost {len(counter.regclass_statements())} "
            f"round-trips: {counter.regclass_statements()}"
        )

    async def test_the_first_guard_warms_every_other_one(
        self, warehouse, counter
    ):
        """The point of refreshing the whole known set at once.

        A slate resolves its window (one guard) and then fetches projections
        (seven more). The second call must cost nothing — otherwise batching has
        only moved the round-trips around rather than removed them.
        """
        repository.clear_relation_cache()
        counter.reset()

        await repository.require_relations(warehouse, "upcoming_games")
        after_first = len(counter.regclass_statements())

        await repository.require_relations(
            warehouse, "projections", "model_runs", "feat_player_usage"
        )
        after_second = len(counter.regclass_statements())

        assert after_first == 1
        assert after_second == 1, "a second guard re-queried relations already known"

    async def test_a_warm_guard_costs_nothing(self, warehouse, counter):
        await repository.require_relations(warehouse, "projections")
        counter.reset()

        for _ in range(20):
            await repository.require_relations(warehouse, "projections")

        assert counter.regclass_statements() == []

    async def test_an_unknown_relation_is_still_answerable(self, warehouse):
        """Batching must not restrict the check to the expected vocabulary."""
        repository.clear_relation_cache()
        assert await repository.relation_exists(warehouse, "projections") is True
        assert (
            await repository.relation_exists(warehouse, "no_such_relation_here")
            is False
        )

    async def test_the_cache_still_expires(self, warehouse, counter, monkeypatch):
        """The TTL is what lets a rebuilt matview be noticed without a restart.

        Guarded here because "refresh everything at once" is one short step from
        "load it once at startup", and that version cannot recover from a
        ``pipeline full`` that dropped a matview thirty seconds ago.
        """
        await repository.require_relations(warehouse, "projections")
        counter.reset()

        monkeypatch.setattr(repository, "_RELATION_CACHE_TTL", -1.0)
        await repository.require_relations(warehouse, "projections")

        assert len(counter.regclass_statements()) == 1

    async def test_the_first_missing_relation_is_the_one_reported(
        self, warehouse
    ):
        """Order comes from the caller, not from the batch.

        The batch is sorted for a stable query; the error must still name the
        relation the caller listed first, because that is the one whose remedy
        is the right instruction.
        """
        from nflfp.services.errors import DataUnavailable

        repository.clear_relation_cache()
        with pytest.raises(DataUnavailable) as caught:
            await repository.require_relations(
                warehouse, "definitely_absent_a", "definitely_absent_b"
            )
        assert caught.value.relation == "definitely_absent_a"


class TestSlateRoundTrips:
    async def test_a_cold_slate_pays_one_guard_round_trip(self, warehouse, counter):
        """Window resolution and the board share a single guard query."""
        from nflfp.services import projections as service

        repository.clear_relation_cache()
        counter.reset()

        await service.get_slate(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
        )

        regclass = len(counter.regclass_statements())
        assert regclass == 1, f"{regclass} guard round-trips: {counter.regclass_statements()}"

    async def test_a_warm_slate_is_two_statements(self, warehouse, counter):
        """The steady state: resolve the window, fetch the board. Nothing else.

        This is the number that matters, because the guard cache is warm for all
        but one request a minute. It was three — the third being a count of rows
        already in hand.
        """
        from nflfp.services import projections as service

        await service.get_slate(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
        )
        counter.reset()

        await service.get_slate(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
        )

        assert counter.count == 2, f"{counter.count} statements: {counter.statements}"


class TestPaginationTotals:
    """`meta.page.total` must not change now that it is usually derived."""

    async def test_a_short_page_reports_the_same_total_as_a_counted_one(
        self, warehouse
    ):
        from nflfp.services import projections as service

        slate, _ = await service.get_slate(
            warehouse, season=SEASON, week=UPCOMING_WEEK,
            scoring_profile="half_ppr", limit=500,
        )
        counted = await repository.count_projections(
            warehouse, season=SEASON, week=UPCOMING_WEEK, scoring_profile="half_ppr"
        )
        assert slate.total == counted
        assert slate.total == len(slate.entries)

    async def test_a_short_page_does_not_ask(self, warehouse, counter):
        from nflfp.services import projections as service

        counter.reset()
        await service.get_slate(
            warehouse, season=SEASON, week=UPCOMING_WEEK,
            scoring_profile="half_ppr", limit=500,
        )
        assert counter.count_statements() == []

    async def test_a_full_page_still_asks_the_database(self, warehouse, counter):
        """A page filled to the limit may have more behind it and must count.

        The stub warehouse holds four projections, so a limit of two is a full
        page with two more unseen — exactly the shape that would report a wrong
        total if the derivation were applied unconditionally.
        """
        from nflfp.services import projections as service

        counter.reset()
        slate, _ = await service.get_slate(
            warehouse, season=SEASON, week=UPCOMING_WEEK,
            scoring_profile="half_ppr", limit=2,
        )

        assert len(slate.entries) == 2
        assert slate.total == 4, "a truncated page reported its own length as the total"
        assert counter.count_statements(), "the count query was skipped on an ambiguous page"

    async def test_an_offset_page_counts_the_rows_before_it(self, warehouse):
        from nflfp.services import projections as service

        slate, _ = await service.get_slate(
            warehouse, season=SEASON, week=UPCOMING_WEEK,
            scoring_profile="half_ppr", limit=3, offset=2,
        )
        assert len(slate.entries) == 2
        assert slate.total == 4
