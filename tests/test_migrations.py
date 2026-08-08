"""Tests for the Alembic setup and the warehouse interlock.

The critical assertion is that :func:`nflfp.db.alembic_guard.include_object`
refuses to manage the warehouse. Without it, ``alembic revision --autogenerate``
would compare the live database against the application metadata, find eight
``raw_*`` tables it has never heard of, and emit ``op.drop_table`` for each.
That is a one-command way to destroy 182k player-weeks, so it is tested first
and without needing a database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, inspect, text

from nflfp.db.alembic_guard import include_object, is_warehouse_object
from nflfp.db.base import metadata

from .conftest import requires_db

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
VERSIONS_DIR = MIGRATIONS_DIR / "versions"


# ---------------------------------------------------------------------------
# the safety interlock
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    [
        "raw_player_week",
        "raw_schedules",
        "raw_players",
        "raw_snap_counts",
        "raw_injuries",
        "raw_rosters",
        "raw_teams",
        "raw_depth_charts",
        "stg_raw_player_week",
        "player_week",
        "game_team",
        "upcoming_games",
    ],
)
def test_warehouse_objects_are_excluded(name):
    assert is_warehouse_object(name) is True
    assert include_object(None, name, "table", True, None) is False


@pytest.mark.parametrize("name", sorted(metadata.tables))
def test_application_tables_are_included(name):
    assert is_warehouse_object(name) is False
    assert include_object(None, name, "table", True, None) is True


def test_unmanaged_reflected_tables_are_excluded():
    """A table added out-of-band — a dbt artefact, an extension's bookkeeping —
    must not be proposed for deletion."""
    assert include_object(None, "some_other_tool", "table", True, None) is False


def test_unreflected_new_tables_are_included():
    """A newly added model has not been reflected yet; it must still be
    creatable."""
    assert include_object(None, "brand_new_table", "table", False, None) is True


def test_child_objects_inherit_their_tables_verdict():
    scratch = MetaData()
    warehouse = Table("raw_player_week", scratch, Column("id", Integer))
    owned = Table("projections", MetaData(), Column("id", Integer))

    class Child:
        def __init__(self, table):
            self.table = table

    for type_ in ("index", "column", "unique_constraint"):
        assert include_object(Child(warehouse), "whatever", type_, True, None) is False
        assert include_object(Child(owned), "whatever", type_, True, None) is True


def test_guard_tolerates_objects_without_a_table():
    """Alembic passes ``None`` names and parentless objects for some
    constraints; the guard must not raise on them."""
    assert include_object(object(), "anything", "column", True, None) is True
    assert include_object(None, None, "unique_constraint", True, None) is True


# ---------------------------------------------------------------------------
# migration content
# ---------------------------------------------------------------------------

def test_alembic_ini_has_no_hardcoded_url():
    """A URL here would be a second source of truth — and the one that wins."""
    ini = (REPO_ROOT / "alembic.ini").read_text(encoding="utf-8")
    line = next(l for l in ini.splitlines() if l.startswith("sqlalchemy.url"))
    assert line.split("=", 1)[1].strip() == ""


def test_no_migration_touches_the_warehouse():
    for path in VERSIONS_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("raw_player_week", "raw_schedules", "raw_players", "stg_raw"):
            assert forbidden not in source, f"{path.name} references {forbidden}"


def test_baseline_migration_inlines_its_enum_values():
    """A migration is a historical record. Importing live enums would make it
    silently produce a different schema once the app's enums move on."""
    source = next(VERSIONS_DIR.glob("*baseline*.py")).read_text(encoding="utf-8")
    assert "from nflfp.db.enums import" not in source
    assert "MODEL_RUN_STATUSES" in source


def test_run_log_ddl_matches_the_pipelines_own():
    """The ETL creates its run log imperatively so the Railway cron image does
    not depend on migrations having run. That duplication is deliberate, but it
    must not drift — this is the assertion that keeps it honest."""
    import importlib.util

    from nflfp.warehouse import RUN_LOG_DDL as pipeline_ddl

    path = next(VERSIONS_DIR.glob("*baseline*.py"))
    spec = importlib.util.spec_from_file_location("baseline_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.RUN_LOG_DDL.strip() == pipeline_ddl.strip()


def test_every_migration_has_a_downgrade():
    """A downgrade that does not exist is a rollback plan that does not exist."""
    for path in VERSIONS_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        body = source.split("def downgrade()", 1)[1]
        assert "raise NotImplementedError" not in body, path.name


def test_single_migration_head():
    """Branched heads make `alembic upgrade head` ambiguous at deploy time."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1


# ---------------------------------------------------------------------------
# integration: a real upgrade against a real server
# ---------------------------------------------------------------------------

def _run_migration(conn, schema: str, direction: str) -> None:
    """Apply the whole migration chain in an isolated schema.

    Walks every revision rather than just one: the moment a second migration
    existed, a single-revision harness silently stopped testing the current
    schema and started reporting drift that was really its own incompleteness.
    """
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))

    script = ScriptDirectory.from_config(config)
    migration_context = MigrationContext.configure(
        conn,
        opts={
            "version_table_schema": schema,
            # Mirrors migrations/env.py. Alembic applies the metadata's naming
            # convention to constraints created by op.create_table, so omitting
            # this would give the test schema different constraint names than a
            # real `alembic upgrade` produces — and the drift check below would
            # then be testing the harness rather than the migration.
            "target_metadata": metadata,
        },
    )
    # walk_revisions() yields newest first. Upgrades apply oldest -> newest;
    # downgrades reverse that.
    revisions = list(script.walk_revisions())
    ordered = list(reversed(revisions)) if direction == "upgrade" else revisions

    # Operations.context() takes the MigrationContext and yields the `op` proxy
    # the migration module calls into.
    with migration_context.begin_transaction():
        with Operations.context(migration_context):
            for revision in ordered:
                getattr(revision.module, direction)()


@requires_db
@pytest.mark.integration
def test_upgrade_and_downgrade_round_trip(pg_engine, db_schema):
    with pg_engine.connect() as conn:
        conn.execute(text(f'SET search_path TO "{db_schema}"'))

        _run_migration(conn, db_schema, "upgrade")
        conn.commit()

        tables = set(inspect(conn).get_table_names(schema=db_schema))
        assert {"model_runs", "projections", "projection_points"} <= tables
        # Adoption path: the run log is created when absent.
        assert {"pipeline_runs", "pipeline_run_datasets"} <= tables

        _run_migration(conn, db_schema, "downgrade")
        conn.commit()

        after = set(inspect(conn).get_table_names(schema=db_schema))
        assert not {"model_runs", "projections", "projection_points"} & after
        # The ETL audit trail deliberately survives a schema rollback.
        assert "pipeline_runs" in after


@requires_db
@pytest.mark.integration
def test_baseline_adopts_an_existing_run_log(pg_engine, db_schema):
    """Adoption, not creation: a warehouse the pipeline has already run against
    must upgrade without a 'table already exists' failure."""
    from nflfp.warehouse import RUN_LOG_DDL

    with pg_engine.connect() as conn:
        conn.execute(text(f'SET search_path TO "{db_schema}"'))
        conn.execute(text(RUN_LOG_DDL))
        conn.commit()

        _run_migration(conn, db_schema, "upgrade")
        conn.commit()

        assert "model_runs" in inspect(conn).get_table_names(schema=db_schema)


@requires_db
@pytest.mark.integration
def test_migrated_schema_matches_the_orm_models(pg_engine, db_schema):
    """The migration and the models must agree.

    They are written by hand and independently, which is the point — but it
    means nothing catches a column added to one and not the other except this.
    """
    with pg_engine.connect() as conn:
        conn.execute(text(f'SET search_path TO "{db_schema}"'))
        _run_migration(conn, db_schema, "upgrade")
        conn.commit()

        inspector = inspect(conn)
        for name, table in metadata.tables.items():
            actual = {c["name"] for c in inspector.get_columns(name, schema=db_schema)}
            expected = set(table.c.keys())
            assert expected == actual, f"{name}: model {expected ^ actual} differs"


@requires_db
@pytest.mark.integration
def test_autogenerate_proposes_nothing_after_upgrade(pg_engine, db_schema):
    """The strongest statement available: after migrating, the models and the
    database agree, and Alembic would emit an empty revision.

    This is also the test that would fail loudly if the guard ever stopped
    working — a warehouse table in ``public`` would show up as a diff.
    """
    from alembic.autogenerate import produce_migrations
    from alembic.migration import MigrationContext

    with pg_engine.connect() as conn:
        conn.execute(text(f'SET search_path TO "{db_schema}"'))
        _run_migration(conn, db_schema, "upgrade")
        conn.commit()

        context = MigrationContext.configure(
            conn,
            opts={
                "include_object": include_object,
                "compare_type": True,
                "version_table_schema": db_schema,
            },
        )
        diffs = produce_migrations(context, metadata).upgrade_ops.as_diffs()
        assert diffs == [], f"unexpected schema drift: {diffs}"
