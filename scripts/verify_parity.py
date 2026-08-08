"""Cross-engine parity check: DuckDB vs Postgres.

The migration is only trustworthy if the Postgres warehouse answers the same
questions the DuckDB exploration database does. This runs identical SQL against
both and diffs the results, so a porting mistake in a view surfaces as a number
that moved rather than as a silent wrong projection three weeks from now.

    python scripts/verify_parity.py
"""

from __future__ import annotations

import sys
from decimal import Decimal

import duckdb

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from nflfp import db, pg  # noqa: E402

# name -> (sql, tolerance). Tolerance is 0 for anything that must match bit for
# bit: row counts, join coverage, sums. Floating-point aggregates like corr()
# get a small one — the two engines sum in different orders, so they disagree
# in the ~4th decimal. That's arithmetic, not a porting bug, and it's far below
# anything that could change a lineup decision.
CHECKS: dict[str, tuple[str, float]] = {
    "row_count": "SELECT count(*) FROM player_week",
    "game_team_rows": "SELECT count(*) FROM game_team",
    "upcoming_rows": "SELECT count(*) FROM upcoming_games",
    "distinct_players": "SELECT count(DISTINCT player_id) FROM player_week",
    "seasons": "SELECT min(season), max(season) FROM player_week",
    "scoring_parity": (
        "SELECT round(max(abs(fp_nflverse_parity - nflverse_fp_standard))::numeric, 6) "
        "FROM player_week WHERE nflverse_fp_standard IS NOT NULL"
    ),
    "total_half_ppr": (
        "SELECT round(sum(fp_half_ppr)::numeric, 2) FROM player_week"
    ),
    "snap_join_coverage": (
        "SELECT count(*) FROM player_week WHERE offense_pct IS NOT NULL"
    ),
    "injury_join_coverage": (
        "SELECT count(*) FROM player_week WHERE injury_report_status IS NOT NULL"
    ),
    "wr_target_share_corr": (
        "SELECT round(corr(target_share, fp_half_ppr)::numeric, 4) FROM player_week "
        "WHERE position = 'WR' AND season_type = 'REG' AND target_share IS NOT NULL",
        1e-3,
    ),
    "rb_snap_corr": (
        "SELECT round(corr(offense_pct, fp_half_ppr)::numeric, 4) FROM player_week "
        "WHERE position = 'RB' AND season_type = 'REG' AND offense_pct IS NOT NULL",
        1e-3,
    ),
    "implied_total_check": (
        "SELECT round(sum(implied_team_total)::numeric, 1) FROM game_team "
        "WHERE total_line IS NOT NULL"
    ),
    "home_away_balance": (
        "SELECT count(*) FILTER (WHERE is_home), count(*) FILTER (WHERE NOT is_home) "
        "FROM game_team"
    ),
}


def norm(value):
    """Make DuckDB and psycopg results comparable (Decimal vs float, etc.)."""
    if isinstance(value, tuple):
        return tuple(norm(v) for v in value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float):
        return round(value, 6)
    return value


def matches(a, b, tol: float) -> bool:
    """Equality, with `tol` slack on numeric fields."""
    if a == b:
        return True
    if not tol or not isinstance(a, tuple) or not isinstance(b, tuple) or len(a) != len(b):
        return False
    return all(
        x == y or (isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(x - y) <= tol)
        for x, y in zip(a, b)
    )


def main() -> int:
    duck = duckdb.connect(str(db.db_path()), read_only=True)
    failures = 0

    print(f"duckdb   : {db.db_path()}")
    print(f"postgres : {pg.safe_dsn()}\n")
    print(f"{'check':<24} {'duckdb':<26} {'postgres':<26} ok")
    print("-" * 84)

    with pg.connect() as conn, conn.cursor() as cur:
        for name, spec in CHECKS.items():
            sql, tol = spec if isinstance(spec, tuple) else (spec, 0.0)
            try:
                d = norm(duck.execute(sql).fetchone())
            except Exception as exc:
                d = f"ERR {str(exc)[:18]}"
            try:
                cur.execute(sql)
                p = norm(cur.fetchone())
            except Exception as exc:
                conn.rollback()
                p = f"ERR {str(exc)[:18]}"

            ok = matches(d, p, tol)
            failures += not ok
            mark = "yes" if ok else "NO"
            if ok and d != p:
                mark = f"~{tol:g}"
            print(f"{name:<24} {str(d):<26} {str(p):<26} {mark}")

    duck.close()
    print()
    if failures:
        print(f"{failures} check(s) DIFFER — the Postgres warehouse is not equivalent")
        return 1
    print(f"all {len(CHECKS)} checks match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
