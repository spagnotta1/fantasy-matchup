"""Reading upcoming games out of the warehouse for providers to enrich.

This is the one place that translates warehouse rows into
:class:`~nflfp.providers.base.GameRef`. Providers never touch the database
themselves, so this module is the only coupling between the provider layer and
``raw_schedules`` — swapping a provider cannot break a query, and reshaping the
schedule cannot break a provider.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..providers.base import GameRef

logger = logging.getLogger(__name__)

# nflverse stores `gameday` and `gametime` as *text* ('2026-09-09', '20:20'),
# not as date/time types — they arrive that way in the parquet and the pipeline
# lands them verbatim. Hence the explicit casts: comparing the raw varchar to a
# date parameter is a type error, and relying on ISO strings sorting correctly
# would be a trap the first time nflverse changes the format.
#
# Neither field carries a zone. nflverse publishes kickoff in US Eastern, so it
# is interpreted as Eastern and converted to UTC here — once, at the boundary —
# rather than separately in each provider.
_UPCOMING_SQL = """
SELECT
    game_id,
    season,
    week,
    home_team,
    away_team,
    stadium_id,
    roof,
    ((gameday || ' ' || COALESCE(NULLIF(gametime, ''), '13:00'))::timestamp
        AT TIME ZONE 'America/New_York') AS kickoff_utc
FROM raw_schedules
WHERE game_type = 'REG'
  AND gameday IS NOT NULL
  AND gameday <> ''
  AND gameday::date >= :from_date
  AND gameday::date <= :to_date
ORDER BY gameday, game_id
"""


def upcoming_games(
    session: Session,
    *,
    horizon_days: int = 10,
    now: datetime | None = None,
    lookback_hours: int = 6,
) -> list[GameRef]:
    """Games kicking off inside the horizon, as provider-ready references.

    Args:
        session: An open SQLAlchemy session against the warehouse.
        horizon_days: How far ahead to look. Providers cap themselves too, but
            fetching a slate three months out just wastes requests.
        now: Injectable clock, so tests are not time-dependent.
        lookback_hours: How far back to still include a game. A Sunday-night
            job should still see the afternoon slate; without this, a run that
            fires an hour late silently drops every game it was meant to cover.

    Returns:
        Game references ordered by kickoff.
    """
    now = now or datetime.now(timezone.utc)
    rows = session.execute(
        text(_UPCOMING_SQL),
        {
            "from_date": (now - timedelta(hours=lookback_hours)).date(),
            "to_date": (now + timedelta(days=horizon_days)).date(),
        },
    ).mappings()

    games = [
        GameRef(
            game_id=row["game_id"],
            season=int(row["season"]),
            week=int(row["week"]),
            home_team=row["home_team"],
            away_team=row["away_team"],
            stadium_id=row["stadium_id"],
            roof=row["roof"],
            kickoff=_as_utc(row["kickoff_utc"]),
        )
        for row in rows
    ]
    logger.info("found %d upcoming game(s) within %d days", len(games), horizon_days)
    return games


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
