"""DuckDB connection helpers."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nfl.duckdb"


def db_path() -> Path:
    return Path(os.environ.get("NFLFP_DB", DEFAULT_DB_PATH))


def connect(path: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(p), read_only=read_only)
    if not read_only:
        con.execute("INSTALL httpfs; LOAD httpfs;")
    return con
