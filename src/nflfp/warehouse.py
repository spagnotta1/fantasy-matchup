"""Postgres schema concerns: indexes, the run log, and view (re)creation."""

from __future__ import annotations

from . import pg
from .transform import VIEW_NAMES, view_definitions

# Indexes worth having on the raw tables. Each is (suffix, columns) and is only
# created if every column actually exists — nflverse changes schemas between
# seasons (depth_charts most notably), and a missing column shouldn't fail a run.
INDEXES: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "raw_player_week": [
        ("season_week", ("season", "week")),
        ("player", ("player_id",)),
        ("game", ("game_id",)),
        ("team_season", ("team", "season")),
    ],
    "raw_snap_counts": [
        ("game_player", ("game_id", "pfr_player_id")),
        ("season_week", ("season", "week")),
    ],
    "raw_schedules": [
        ("game", ("game_id",)),
        ("season_week", ("season", "week")),
    ],
    "raw_players": [
        ("gsis", ("gsis_id",)),
        ("pfr", ("pfr_id",)),
    ],
    "raw_injuries": [
        ("lookup", ("season", "week", "team", "gsis_id")),
    ],
    "raw_rosters": [
        ("season_player", ("season", "gsis_id")),
    ],
    "raw_teams": [],
    "raw_depth_charts": [],
}

RUN_LOG_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id       BIGSERIAL PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    mode         TEXT    NOT NULL,
    seasons      TEXT,
    status       TEXT    NOT NULL DEFAULT 'running',
    rows_loaded  BIGINT  NOT NULL DEFAULT 0,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_run_datasets (
    run_id       BIGINT  NOT NULL REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
    dataset      TEXT    NOT NULL,
    action       TEXT    NOT NULL,
    rows_loaded  BIGINT  NOT NULL DEFAULT 0,
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    PRIMARY KEY (run_id, dataset)
);

CREATE INDEX IF NOT EXISTS pipeline_runs_started_idx ON pipeline_runs (started_at DESC);
"""


def ensure_run_log(cur) -> None:
    cur.execute(RUN_LOG_DDL)


def drop_views(cur) -> None:
    """Drop derived views in reverse dependency order.

    Publishing swaps whole tables, which Postgres refuses while a view depends
    on them. Views are cheap to rebuild, so we drop and recreate every run
    rather than reasoning about which ones a given dataset touches.
    """
    for name in VIEW_NAMES:
        cur.execute(f"DROP VIEW IF EXISTS {name} CASCADE")


def rebuild_views(cur) -> list[str]:
    """Recreate every view buildable from the tables currently present."""
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
    )
    tables = {r[0] for r in cur.fetchall()}

    created = []
    for name, body in view_definitions(tables):
        # Postgres only allows CREATE OR REPLACE VIEW when the column list is
        # unchanged; adding a scoring profile would break that. Drop first.
        cur.execute(f"DROP VIEW IF EXISTS {name} CASCADE")
        cur.execute(f"CREATE VIEW {name} AS {body}")
        created.append(name)
    return created


def create_indexes(cur, table: str) -> list[str]:
    """Create the configured indexes for a table, skipping any whose columns are absent."""
    present = set(pg.columns(cur, table))
    made = []
    for suffix, cols in INDEXES.get(table, []):
        if not set(cols).issubset(present):
            continue
        name = f"{table}_{suffix}_idx"
        col_sql = ", ".join(f'"{c}"' for c in cols)
        cur.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({col_sql})')
        made.append(name)
    return made
