"""Build the local DuckDB warehouse from nflverse parquet releases.

DuckDB reads the parquet straight off GitHub over httpfs, so there is no
intermediate download step and no pandas in the loop — the whole core build is
a few CREATE TABLE ... AS SELECT statements.

    python -m nflfp.ingest                 # core datasets, 2016-2026
    python -m nflfp.ingest --all           # + play-by-play, NGS, PFR, FTN
    python -m nflfp.ingest --only pbp --start 2023
    python -m nflfp.ingest --list          # show the manifest, build nothing
"""

from __future__ import annotations

import argparse
import sys
import time

from . import db
from .sources import (
    DATASETS,
    DATASETS_BY_NAME,
    DEFAULT_END_SEASON,
    DEFAULT_START_SEASON,
    Dataset,
    resolve_urls,
)
from .transform import build_views


def load_dataset(con, ds: Dataset, start: int, end: int) -> tuple[int, str]:
    """Materialise one dataset as raw_<name>. Returns (rows, note)."""
    urls, missing = resolve_urls(ds, start, end)
    if not urls:
        return 0, "no assets in range"

    table = f"raw_{ds.name}"
    url_list = ", ".join(f"'{u}'" for u in urls)
    # union_by_name absorbs nflverse's schema drift across seasons (columns get
    # added and occasionally renamed between years); without it a multi-year
    # read fails whenever any season has a different column set.
    con.execute(
        f"CREATE OR REPLACE TABLE {table} AS "
        f"SELECT * FROM read_parquet([{url_list}], union_by_name = true)"
    )
    rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    note = f"{len(urls)} file(s)"
    if missing and missing != [-1]:
        note += f", missing {','.join(str(m) for m in missing)}"
    return rows, note


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nflfp.ingest", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=int, default=DEFAULT_START_SEASON,
                   help=f"first season (default {DEFAULT_START_SEASON})")
    p.add_argument("--end", type=int, default=DEFAULT_END_SEASON,
                   help=f"last season (default {DEFAULT_END_SEASON})")
    p.add_argument("--all", action="store_true",
                   help="include non-core datasets (play-by-play, NGS, PFR, FTN)")
    p.add_argument("--only", nargs="+", metavar="NAME",
                   help="load just these datasets")
    p.add_argument("--list", action="store_true", help="print the manifest and exit")
    args = p.parse_args(argv)

    if args.list:
        width = max(len(d.name) for d in DATASETS)
        for d in DATASETS:
            tier = "core " if d.core else "extra"
            print(f"[{tier}] {d.name:<{width}}  {d.description}")
        return 0

    if args.only:
        unknown = [n for n in args.only if n not in DATASETS_BY_NAME]
        if unknown:
            print(f"unknown dataset(s): {', '.join(unknown)}", file=sys.stderr)
            print(f"available: {', '.join(DATASETS_BY_NAME)}", file=sys.stderr)
            return 2
        selected = [DATASETS_BY_NAME[n] for n in args.only]
    else:
        selected = [d for d in DATASETS if d.core or args.all]

    con = db.connect()
    print(f"database : {db.db_path()}")
    print(f"seasons  : {args.start}-{args.end}")
    print(f"datasets : {len(selected)}\n")

    total_rows = 0
    failures: list[tuple[str, str]] = []
    for ds in selected:
        t0 = time.time()
        label = f"  {ds.name:<16}"
        print(f"{label} ...", end="", flush=True)
        try:
            rows, note = load_dataset(con, ds, args.start, args.end)
        except Exception as exc:  # keep going; one bad feed shouldn't kill the build
            print(f"\r{label} FAILED  {str(exc)[:90]}")
            failures.append((ds.name, str(exc)))
            continue
        total_rows += rows
        print(f"\r{label} {rows:>10,} rows  ({time.time() - t0:5.1f}s, {note})")

    print("\nbuilding views ...")
    for v in build_views(con):
        n = con.execute(f"SELECT count(*) FROM {v}").fetchone()[0]
        print(f"  {v:<16} {n:>10,} rows")

    con.close()
    print(f"\ndone — {total_rows:,} raw rows")
    if failures:
        print(f"{len(failures)} dataset(s) failed: {', '.join(f for f, _ in failures)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
