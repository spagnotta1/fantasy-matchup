"""Persisting provider output.

Providers fetch; this module writes. Keeping them apart means a provider can be
tested with no database and the persistence logic can be tested with no
network, which is the only way either gets tested honestly.

Change detection
----------------
Snapshots record *changes*, not polls. Before inserting, each record is compared
against the most recent stored snapshot for the same game and feed; identical
values are dropped.

Without this, hourly odds polling writes ~24 rows per game per day whether or
not the market moved — through an offseason that is thousands of identical rows
per game, and it turns "when did this line move?" into a query that has to
diff consecutive rows. With it, the table *is* the line-movement history, which
is what the feature layer actually wants.

``ON CONFLICT DO NOTHING`` on ``(game_id, provider[, book], captured_at)``
remains as a second guard. It catches a retry that replays the *same* fetch —
same ``captured_at`` — which change detection alone would not, since a
partially-written batch has nothing to compare against.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..db.models.external import OddsSnapshot, WeatherForecast
from ..providers.base import (
    GameRef,
    OddsProvider,
    OddsRecord,
    ProviderFetch,
    WeatherForecastRecord,
    WeatherProvider,
)

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """Outcome of one provider ingest, shaped for the job log."""

    provider: str
    fetched: int = 0
    written: int = 0
    skipped: int = 0
    warnings: list[str] | None = None

    def as_detail(self) -> dict:
        """JSON-serialisable summary stored on the job run."""
        return {
            "provider": self.provider,
            "fetched": self.fetched,
            "written": self.written,
            "skipped": self.skipped,
            "warnings": self.warnings or [],
        }

    def __str__(self) -> str:
        return (
            f"{self.provider}: fetched {self.fetched}, wrote {self.written}, "
            f"skipped {self.skipped}"
        )


def ingest_weather(
    session: Session, provider: WeatherProvider, games: list[GameRef]
) -> IngestResult:
    """Fetch forecasts for `games` and append them.

    Args:
        session: Open session; the caller owns the transaction.
        provider: Any :class:`~nflfp.providers.base.WeatherProvider`.
        games: Games to enrich, from :func:`nflfp.etl.games.upcoming_games`.

    Returns:
        Counts suitable for the job log.
    """
    fetch: ProviderFetch[WeatherForecastRecord] = provider.fetch(games)
    rows = [
        {
            "game_id": r.game_id,
            "provider": fetch.provider,
            "captured_at": r.captured_at,
            "valid_at": r.valid_at,
            "temperature_f": r.temperature_f,
            "wind_mph": r.wind_mph,
            "wind_gust_mph": r.wind_gust_mph,
            "precipitation_probability": r.precipitation_probability,
            "precipitation_in": r.precipitation_in,
            "snowfall_in": r.snowfall_in,
            "humidity_pct": r.humidity_pct,
            "cloud_cover_pct": r.cloud_cover_pct,
            "is_indoor": r.is_indoor,
            "roof_uncertain": r.roof_uncertain,
        }
        for r in fetch.records
    ]
    rows = _only_changed(
        session, WeatherForecast, rows, key=("game_id", "provider"),
        compare=(
            "temperature_f", "wind_mph", "wind_gust_mph", "precipitation_probability",
            "precipitation_in", "snowfall_in", "is_indoor", "roof_uncertain",
        ),
    )
    written = _append(session, WeatherForecast, rows, ("game_id", "provider", "captured_at"))
    return _result(fetch, written)


def ingest_odds(
    session: Session, provider: OddsProvider, games: list[GameRef]
) -> IngestResult:
    """Fetch current markets for `games` and append them."""
    fetch: ProviderFetch[OddsRecord] = provider.fetch(games)
    rows = [
        {
            "game_id": r.game_id,
            "provider": fetch.provider,
            "book": r.book,
            "captured_at": r.captured_at,
            "spread_home": r.spread_home,
            "total": r.total,
            "moneyline_home": r.moneyline_home,
            "moneyline_away": r.moneyline_away,
            "spread_home_open": r.spread_home_open,
            "total_open": r.total_open,
        }
        for r in fetch.records
    ]
    rows = _only_changed(
        session, OddsSnapshot, rows, key=("game_id", "provider", "book"),
        compare=(
            "spread_home", "total", "moneyline_home", "moneyline_away",
            "spread_home_open", "total_open",
        ),
    )
    written = _append(
        session, OddsSnapshot, rows, ("game_id", "provider", "book", "captured_at")
    )
    return _result(fetch, written)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _only_changed(
    session: Session,
    model,
    rows: list[dict],
    *,
    key: tuple[str, ...],
    compare: tuple[str, ...],
) -> list[dict]:
    """Drop rows whose values match the latest stored snapshot for that key.

    Args:
        session: Open session.
        model: The snapshot model being written.
        rows: Candidate rows, as dicts.
        key: Columns identifying a series, e.g. ``("game_id", "provider")``.
        compare: Value columns that constitute a change. ``captured_at`` is
            deliberately excluded — it differs on every fetch, which is exactly
            what makes naive comparison useless.

    Returns:
        The subset worth persisting.
    """
    if not rows:
        return rows

    latest = _latest_by_key(session, model, key, compare)
    changed = []
    for row in rows:
        identity = tuple(row[column] for column in key)
        previous = latest.get(identity)
        if previous is not None and all(
            _same(previous[column], row.get(column)) for column in compare
        ):
            continue
        changed.append(row)

    unchanged = len(rows) - len(changed)
    if unchanged:
        logger.info("%d snapshot(s) unchanged since last capture; not stored", unchanged)
    return changed


def _latest_by_key(session: Session, model, key: tuple[str, ...], compare: tuple[str, ...]) -> dict:
    """The most recent stored row per key, as {identity: {column: value}}."""
    key_sql = ", ".join(key)
    columns = ", ".join((*key, *compare))
    statement = sa_text(
        f"SELECT DISTINCT ON ({key_sql}) {columns} "
        f"FROM {model.__tablename__} ORDER BY {key_sql}, captured_at DESC"
    )
    return {
        tuple(row[column] for column in key): dict(row)
        for row in session.execute(statement).mappings()
    }


def _same(stored, incoming) -> bool:
    """Compare a stored value with a candidate, tolerating float noise.

    Postgres round-trips a Python float exactly for these magnitudes, but the
    tolerance costs nothing and stops a 0.1-degree representation difference
    from being recorded as a weather change.
    """
    if stored is None or incoming is None:
        return stored is None and incoming is None
    if isinstance(stored, float) or isinstance(incoming, float):
        return abs(float(stored) - float(incoming)) < 1e-9
    return stored == incoming


def _append(session: Session, model, rows: list[dict], conflict_cols: tuple[str, ...]) -> int:
    """Insert rows, ignoring ones already captured. Returns rows actually written."""
    if not rows:
        return 0
    statement = (
        insert(model)
        .values(rows)
        .on_conflict_do_nothing(index_elements=list(conflict_cols))
        .returning(model.id)
    )
    return len(session.execute(statement).scalars().all())


def _result(fetch: ProviderFetch, written: int) -> IngestResult:
    result = IngestResult(
        provider=fetch.provider,
        fetched=fetch.count,
        written=written,
        skipped=len(fetch.skipped),
        warnings=list(fetch.warnings),
    )
    if written < fetch.count:
        logger.info(
            "%s: %d of %d record(s) were already captured",
            fetch.provider, fetch.count - written, fetch.count,
        )
    logger.info("%s", result)
    return result
