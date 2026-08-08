"""Poke at the warehouse without writing boilerplate.

Runs against the local DuckDB file by default, or the Postgres warehouse with
--pg. The probe SQL is deliberately portable — `round(x::numeric, n)` and
ordered-set `percentile_cont(...) WITHIN GROUP (...)` rather than the DuckDB
shorthands — so the same question gets the same answer from either engine.

    python -m nflfp.explore --tables
    python -m nflfp.explore --schema player_week
    python -m nflfp.explore --probe context
    python -m nflfp.explore --probe context --pg
    python -m nflfp.explore --sql "SELECT * FROM player_week LIMIT 5"
"""

from __future__ import annotations

import argparse
import sys

from . import db

# Canned queries that answer the questions worth asking before you commit to a
# feature set. Each one is meant to be read, edited, and re-run.
PROBES: dict[str, tuple[str, str]] = {
    "coverage": (
        "Which seasons/weeks landed, and how complete are they",
        """
        SELECT season,
               count(DISTINCT week)      AS weeks,
               count(DISTINCT game_id)   AS games,
               count(DISTINCT player_id) AS players,
               count(*)                  AS player_weeks
        FROM player_week
        GROUP BY season ORDER BY season
        """,
    ),
    "scoring_check": (
        "Scoring self-test. parity_max_diff must be 0.0; the standard/ppr columns "
        "differ only on return fumbles (see ScoringRules.count_return_fumbles)",
        """
        SELECT season,
               round(max(abs(fp_nflverse_parity - nflverse_fp_standard))::numeric, 6)
                   AS parity_max_diff,
               round(max(abs(fp_standard - nflverse_fp_standard))::numeric, 4) AS diff_standard,
               round(max(abs(fp_ppr - nflverse_fp_ppr))::numeric, 4)           AS diff_ppr,
               sum(CASE WHEN abs(fp_standard - nflverse_fp_standard) > 0.001
                        THEN 1 ELSE 0 END) AS rows_w_return_fumble
        FROM player_week
        WHERE nflverse_fp_standard IS NOT NULL
        GROUP BY season ORDER BY season
        """,
    ),
    "context": (
        "How much do game-context factors actually move fantasy points?",
        """
        SELECT position,
               count(*) AS n,
               round(corr(implied_team_total, fp_half_ppr)::numeric, 3) AS r_implied_total,
               round(corr(team_spread, fp_half_ppr)::numeric, 3)        AS r_spread,
               round((avg(CASE WHEN is_home THEN fp_half_ppr END)
                    - avg(CASE WHEN NOT is_home THEN fp_half_ppr END))::numeric, 3)
                   AS home_edge_pts
        FROM player_week
        WHERE position IN ('QB','RB','WR','TE')
          AND season_type = 'REG'
          AND implied_team_total IS NOT NULL
        GROUP BY position ORDER BY position
        """,
    ),
    "usage": (
        "Usage vs points — is snap share or target share the better signal?",
        """
        SELECT position,
               count(*) AS n,
               round(corr(offense_pct, fp_half_ppr)::numeric, 3)  AS r_snap_pct,
               round(corr(target_share, fp_half_ppr)::numeric, 3) AS r_target_share,
               round(corr(wopr, fp_half_ppr)::numeric, 3)         AS r_wopr
        FROM player_week
        WHERE position IN ('QB','RB','WR','TE')
          AND season_type = 'REG' AND offense_pct IS NOT NULL
        GROUP BY position ORDER BY position
        """,
    ),
    "boom": (
        "Ceiling vs consistency: boom/bust rates by position (2024-2025 starters)",
        """
        SELECT position,
               count(*) AS games,
               round(avg(fp_half_ppr)::numeric, 2) AS mean_fp,
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY fp_half_ppr)::numeric, 2)
                   AS median_fp,
               round(percentile_cont(0.9) WITHIN GROUP (ORDER BY fp_half_ppr)::numeric, 2)
                   AS p90_fp,
               round(100 * avg(CASE WHEN fp_half_ppr >= 20 THEN 1.0 ELSE 0 END)::numeric, 1)
                   AS pct_20plus,
               round(100 * avg(CASE WHEN fp_half_ppr < 5 THEN 1.0 ELSE 0 END)::numeric, 1)
                   AS pct_bust
        FROM player_week
        WHERE position IN ('QB','RB','WR','TE')
          AND season >= 2024 AND season_type = 'REG'
          AND offense_pct >= 0.5  -- nflverse snap pcts are 0-1 fractions, not 0-100
        GROUP BY position ORDER BY mean_fp DESC
        """,
    ),
    "upcoming": (
        "What the 2026 slate looks like (week 1 sample)",
        """
        SELECT season, week, team, opponent, is_home, team_spread,
               total_line, round(implied_team_total::numeric, 1) AS implied_total,
               roof, surface
        FROM upcoming_games
        WHERE week = 1
        ORDER BY season, game_id, is_home DESC
        LIMIT 20
        """,
    ),
    "stability": (
        "Season-over-season stability of usage vs efficiency (what's predictable)",
        """
        WITH s AS (
            SELECT player_id, season, position,
                   sum(fp_half_ppr) / count(*) AS fppg,
                   avg(offense_pct)            AS snap_pct,
                   sum(receiving_yards + rushing_yards)
                       / nullif(sum(targets + carries), 0) AS yds_per_opp,
                   count(*) AS g
            FROM player_week
            WHERE season_type = 'REG' AND position IN ('RB','WR','TE')
            GROUP BY player_id, season, position
            HAVING count(*) >= 8
        )
        SELECT a.position, count(*) AS pairs,
               round(corr(a.snap_pct, b.snap_pct)::numeric, 3)       AS r_snap_yoy,
               round(corr(a.yds_per_opp, b.yds_per_opp)::numeric, 3) AS r_efficiency_yoy,
               round(corr(a.fppg, b.fppg)::numeric, 3)               AS r_fppg_yoy
        FROM s a JOIN s b ON a.player_id = b.player_id AND b.season = a.season + 1
        GROUP BY a.position ORDER BY a.position
        """,
    ),
    "pipeline": (
        "Recent pipeline runs (Postgres only)",
        """
        SELECT run_id, started_at, status, mode, seasons, rows_loaded
        FROM pipeline_runs ORDER BY run_id DESC LIMIT 10
        """,
    ),
}


def _print_rows(headers, rows, max_rows: int = 60) -> None:
    """Minimal table printer, so Postgres output looks like DuckDB's."""
    shown = rows[:max_rows]
    cells = [[("" if v is None else str(v)) for v in r] for r in shown]
    widths = [
        max(len(h), *(len(c[i]) for c in cells)) if cells else len(h)
        for i, h in enumerate(headers)
    ]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for c in cells:
        print("  ".join(v.ljust(w) for v, w in zip(c, widths)))
    if len(rows) > max_rows:
        print(f"... {len(rows) - max_rows} more rows")
    print(f"\n{len(rows)} row(s)")


def run_pg(sql: str) -> None:
    from . import pg

    with pg.connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        if cur.description is None:
            return
        _print_rows([d[0] for d in cur.description], cur.fetchall())


def run_duck(sql: str) -> None:
    con = db.connect(read_only=True)
    rel = con.sql(sql)
    if rel is not None:
        rel.show(max_rows=60)
    con.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nflfp.explore", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pg", action="store_true",
                   help="query the Postgres warehouse instead of the local DuckDB file")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--tables", action="store_true", help="list tables/views with row counts")
    g.add_argument("--schema", metavar="TABLE", help="describe a table or view")
    g.add_argument("--probe", metavar="NAME", nargs="?", const="__list__",
                   help=f"run a canned probe ({', '.join(PROBES)}); omit name to list")
    g.add_argument("--sql", metavar="QUERY", help="run arbitrary SQL")
    args = p.parse_args(argv)

    if not args.pg and not db.db_path().exists():
        print(f"no database at {db.db_path()} — run: python -m nflfp.ingest", file=sys.stderr)
        return 1

    run = run_pg if args.pg else run_duck

    if args.tables:
        run(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema " + ("= current_schema()" if args.pg else "= 'main'") +
            " ORDER BY table_type, table_name"
        )
    elif args.schema:
        if args.pg:
            run(
                "SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_name = '{args.schema}' ORDER BY ordinal_position"
            )
        else:
            run(f'DESCRIBE SELECT * FROM "{args.schema}"')
    elif args.probe:
        if args.probe == "__list__":
            width = max(len(k) for k in PROBES)
            for k, (desc, _) in PROBES.items():
                print(f"  {k:<{width}}  {desc}")
            return 0
        if args.probe not in PROBES:
            print(f"unknown probe '{args.probe}'. available: {', '.join(PROBES)}", file=sys.stderr)
            return 2
        desc, sql = PROBES[args.probe]
        print(f"# {desc}\n")
        run(sql)
    elif args.sql:
        run(args.sql)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
