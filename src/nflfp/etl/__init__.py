"""Provider ingestion.

Complements :mod:`nflfp.pipeline`, which owns the nflverse load, rather than
replacing it. The split follows the data's shape, not taste:

* ``nflfp.pipeline`` — bulk historical parquet, loaded by DuckDB straight into
  Postgres, published by an atomic table swap. Millions of rows, weekly.
* ``nflfp.etl`` — small, live, forward-looking JSON feeds, appended as
  timestamped snapshots. Hundreds of rows, hourly.

A table swap is the wrong tool for a feed you sample every hour, and an
append-only snapshot table is the wrong tool for ten seasons of play-by-play.

Neither contains prediction logic. Both stop at "validated data in Postgres".
"""

from __future__ import annotations

from .external import IngestResult, ingest_odds, ingest_weather
from .games import upcoming_games

__all__ = ["IngestResult", "ingest_odds", "ingest_weather", "upcoming_games"]
