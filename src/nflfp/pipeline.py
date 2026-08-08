"""nflverse -> Postgres pipeline.

Two phases, deliberately separated:

1. **Load** — DuckDB reads nflverse parquet over HTTP and writes it into
   Postgres staging tables via ATTACH. Slow, network-bound, and safe to fail:
   nothing user-visible has changed yet.
2. **Publish** — a single Postgres transaction swaps staging into the live
   tables, recreates indexes and rebuilds the views. Fast and atomic, so
   readers never see a half-updated warehouse.

Modes:
    refresh  (default) reload only the current season for season-partitioned
             datasets; reload single-file datasets whole. This is the weekly job.
    full     rebuild every table across the whole season window. Use on first
             run, after changing the season window, or to repair drift.

    python -m nflfp.pipeline refresh
    python -m nflfp.pipeline full
    python -m nflfp.pipeline refresh --seasons 2025 2026
    python -m nflfp.pipeline status
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback

import duckdb

from . import pg, warehouse
from .sources import (
    DATASETS,
    DATASETS_BY_NAME,
    DEFAULT_END_SEASON,
    DEFAULT_START_SEASON,
    Dataset,
    current_season,
    resolve_urls,
)

STAGING_PREFIX = "stg_"


# --------------------------------------------------------------------------
# phase 1: load into staging
# --------------------------------------------------------------------------

def duck() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with httpfs + postgres, attached to the warehouse."""
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute(f"ATTACH '{pg.dsn()}' AS pgdb (TYPE postgres)")
    return con


def load_staging(con, ds: Dataset, start: int, end: int) -> tuple[int, list[str]]:
    """Materialise one dataset into pgdb.stg_raw_<name>. Returns (rows, urls)."""
    urls, _missing = resolve_urls(ds, start, end)
    if not urls:
        return 0, []

    stg = f"{STAGING_PREFIX}raw_{ds.name}"
    url_list = ", ".join(f"'{u}'" for u in urls)

    con.execute(f"DROP TABLE IF EXISTS pgdb.{stg}")
    # union_by_name absorbs nflverse's schema drift across seasons; without it a
    # multi-year read fails whenever any season has a different column set.
    con.execute(
        f"CREATE TABLE pgdb.{stg} AS "
        f"SELECT * FROM read_parquet([{url_list}], union_by_name = true)"
    )
    rows = con.execute(f"SELECT count(*) FROM pgdb.{stg}").fetchone()[0]
    return rows, urls


# --------------------------------------------------------------------------
# phase 2: publish staging -> live
# --------------------------------------------------------------------------

def _staging_column_types(cur, stg: str) -> dict[str, str]:
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (stg,),
    )
    return dict(cur.fetchall())


def publish_full(cur, ds: Dataset) -> str:
    """Atomically swap staging in as the live table."""
    live, stg = f"raw_{ds.name}", f"{STAGING_PREFIX}raw_{ds.name}"
    cur.execute(f"DROP TABLE IF EXISTS {live} CASCADE")
    cur.execute(f"ALTER TABLE {stg} RENAME TO {live}")
    return "swap"


def publish_by_season(cur, ds: Dataset, seasons: list[int]) -> str:
    """Replace just `seasons` worth of rows, preserving the rest of history.

    Never falls back to a table swap: in refresh mode staging holds only the
    current season, so swapping would silently delete every prior year. If
    nflverse has added columns we widen the live table instead and insert on
    the shared column list.
    """
    live, stg = f"raw_{ds.name}", f"{STAGING_PREFIX}raw_{ds.name}"

    if not pg.table_exists(cur, live):
        return publish_full(cur, ds)

    live_cols = pg.columns(cur, live)
    stg_types = _staging_column_types(cur, stg)

    added = [c for c in stg_types if c not in live_cols]
    for col in added:
        cur.execute(f'ALTER TABLE {live} ADD COLUMN "{col}" {stg_types[col]}')
        live_cols.append(col)

    shared = [c for c in live_cols if c in stg_types]
    col_sql = ", ".join(f'"{c}"' for c in shared)

    cur.execute(f"DELETE FROM {live} WHERE season = ANY(%s)", (seasons,))
    deleted = cur.rowcount
    cur.execute(f"INSERT INTO {live} ({col_sql}) SELECT {col_sql} FROM {stg}")
    cur.execute(f"DROP TABLE {stg}")

    note = f"replaced {deleted:,} rows"
    if added:
        note += f", added cols: {','.join(added)}"
    return note


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------

def run(mode: str, start: int, end: int, seasons: list[int], selected: list[Dataset]) -> int:
    print(f"warehouse : {pg.safe_dsn()}")
    print(f"mode      : {mode}")
    print(f"seasons   : {seasons if mode == 'refresh' else f'{start}-{end}'}")
    print(f"datasets  : {len(selected)}\n")

    with pg.connect(autocommit=True) as conn, conn.cursor() as cur:
        warehouse.ensure_run_log(cur)
        cur.execute(
            "INSERT INTO pipeline_runs (mode, seasons) VALUES (%s, %s) RETURNING run_id",
            (mode, ",".join(map(str, seasons)) if mode == "refresh" else f"{start}-{end}"),
        )
        run_id = cur.fetchone()[0]

    print(f"run_id    : {run_id}\n")
    results: list[tuple[Dataset, int, float, str]] = []
    failures: list[tuple[str, str]] = []

    # ---- phase 1: load ----------------------------------------------------
    con = duck()
    for ds in selected:
        incremental = mode == "refresh" and ds.refresh == "by_season"
        lo, hi = (min(seasons), max(seasons)) if incremental else (start, end)
        t0 = time.time()
        label = f"  {ds.name:<16}"
        print(f"{label} loading ...", end="", flush=True)
        try:
            rows, urls = load_staging(con, ds, lo, hi)
        except Exception as exc:
            print(f"\r{label} LOAD FAILED  {str(exc)[:80]}")
            failures.append((ds.name, traceback.format_exc()))
            continue
        dt = time.time() - t0
        if not urls:
            print(f"\r{label} skipped (no published data for {lo}-{hi})")
            results.append((ds, 0, dt, "skipped"))
            continue
        print(f"\r{label} staged {rows:>10,} rows  ({dt:5.1f}s, {len(urls)} file(s))")
        results.append((ds, rows, dt, "staged"))
    con.close()

    staged = [r for r in results if r[3] == "staged"]
    if not staged:
        print("\nnothing staged — nothing to publish")

    # ---- phase 2: publish (one transaction) -------------------------------
    total_rows = 0
    if staged:
        print("\npublishing ...")
        try:
            with pg.connect() as conn, conn.cursor() as cur:
                warehouse.drop_views(cur)
                for ds, rows, _dt, _ in staged:
                    if mode == "full" or ds.refresh == "full":
                        action = publish_full(cur, ds)
                    else:
                        action = publish_by_season(cur, ds, seasons)
                    warehouse.create_indexes(cur, f"raw_{ds.name}")
                    total_rows += rows
                    print(f"  {ds.name:<16} {rows:>10,} rows  ({action})")
                    cur.execute(
                        "INSERT INTO pipeline_run_datasets "
                        "(run_id, dataset, action, rows_loaded) VALUES (%s,%s,%s,%s)",
                        (run_id, ds.name, action, rows),
                    )
                views = warehouse.rebuild_views(cur)
                conn.commit()
            print(f"  views rebuilt: {', '.join(views)}")
        except Exception:
            failures.append(("publish", traceback.format_exc()))
            print("  PUBLISH FAILED — rolled back, live tables untouched")
            traceback.print_exc()

    # ---- finalise ---------------------------------------------------------
    status = "ok" if not failures else "failed"
    with pg.connect(autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE pipeline_runs SET finished_at = now(), status = %s, "
            "rows_loaded = %s, error = %s WHERE run_id = %s",
            (status, total_rows, "\n\n".join(f"{n}:\n{e}" for n, e in failures) or None, run_id),
        )

    print(f"\nrun {run_id} {status} — {total_rows:,} rows published")
    if failures:
        print(f"{len(failures)} failure(s): {', '.join(n for n, _ in failures)}")
        return 1
    return 0


def show_status(limit: int) -> int:
    with pg.connect() as conn, conn.cursor() as cur:
        if not pg.table_exists(cur, "pipeline_runs"):
            print("no pipeline_runs table — the pipeline has never run against this database")
            return 1
        cur.execute(
            "SELECT run_id, started_at, finished_at - started_at, mode, seasons, "
            "status, rows_loaded FROM pipeline_runs ORDER BY run_id DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()

    if not rows:
        print("no runs recorded yet")
        return 0
    print(f"{'run':>5} {'started':<20} {'took':<10} {'mode':<8} {'seasons':<12} {'status':<8} {'rows':>12}")
    print("-" * 82)
    for rid, started, took, mode, seasons, status, nrows in rows:
        secs = f"{took.total_seconds():.1f}s" if took else "-"
        print(
            f"{rid:>5} {started:%Y-%m-%d %H:%M:%S}  {secs:<10} "
            f"{mode:<8} {str(seasons or '-'):<12} {status:<8} {nrows:>12,}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nflfp.pipeline", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("mode", choices=("refresh", "full", "status"), nargs="?", default="refresh")
    p.add_argument("--seasons", type=int, nargs="+",
                   help="seasons to refresh (default: the current NFL season)")
    p.add_argument("--start", type=int, default=DEFAULT_START_SEASON)
    p.add_argument("--end", type=int, default=DEFAULT_END_SEASON)
    p.add_argument("--all", action="store_true", help="include non-core datasets")
    p.add_argument("--only", nargs="+", metavar="NAME", help="restrict to these datasets")
    p.add_argument("--limit", type=int, default=10, help="status: how many runs to show")
    args = p.parse_args(argv)

    try:
        pg.dsn()
    except pg.ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.mode == "status":
        return show_status(args.limit)

    if args.only:
        unknown = [n for n in args.only if n not in DATASETS_BY_NAME]
        if unknown:
            print(f"unknown dataset(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        selected = [DATASETS_BY_NAME[n] for n in args.only]
    else:
        selected = [d for d in DATASETS if d.core or args.all]

    seasons = args.seasons or [current_season()]
    return run(args.mode, args.start, args.end, seasons, selected)


if __name__ == "__main__":
    raise SystemExit(main())
