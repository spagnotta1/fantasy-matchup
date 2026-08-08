"""Storage for external provider output.

These tables are **application-owned** and therefore Alembic's: unlike
``raw_*``, nothing swaps them out of parquet, and their shape is our contract
rather than nflverse's. They still reference games by ``game_id`` with no
foreign key, for the reason given in :mod:`nflfp.db.base`.

Append-only, deliberately
-------------------------
Both tables record *snapshots*, never current state. A market moves all week on
injury news, and a forecast three days out differs from Sunday morning's; line
movement and forecast revision are themselves predictive features. Overwriting
would throw that away to save a few megabytes a season — roughly 285 games times
a handful of captures, which is nothing.

"Latest known" is a read concern, served by a ``DISTINCT ON`` against the
covering indexes below, not a storage concern.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class WeatherForecast(Base):
    """One forecast capture for one game.

    Indoor games get a row too, with :attr:`is_indoor` set and neutral values,
    so the feature layer can join without special-casing roughly 30% of the
    slate into NULLs.
    """

    __tablename__ = "weather_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        doc="When the forecast was produced — what makes this a snapshot.",
    )
    valid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, doc="The kickoff hour it describes."
    )

    temperature_f: Mapped[float | None] = mapped_column(Float)
    wind_mph: Mapped[float | None] = mapped_column(Float)
    wind_gust_mph: Mapped[float | None] = mapped_column(Float)
    precipitation_probability: Mapped[float | None] = mapped_column(Float, doc="0-100")
    precipitation_in: Mapped[float | None] = mapped_column(Float)
    snowfall_in: Mapped[float | None] = mapped_column(Float)
    humidity_pct: Mapped[float | None] = mapped_column(Float)
    cloud_cover_pct: Mapped[float | None] = mapped_column(Float)

    is_indoor: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    roof_uncertain: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
        doc="Retractable roof whose state is not known before kickoff.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        # One capture per game per provider per instant. Makes re-running a job
        # idempotent instead of doubling the history.
        Index(
            "uq_weather_forecasts_capture",
            "game_id", "provider", "captured_at",
            unique=True,
        ),
        # Serves the DISTINCT ON (game_id) ... ORDER BY captured_at DESC that
        # resolves the latest forecast.
        Index("ix_weather_forecasts_latest", "game_id", text("captured_at DESC")),
        CheckConstraint(
            "temperature_f IS NULL OR temperature_f BETWEEN -60 AND 130",
            name="temperature_plausible",
        ),
        CheckConstraint(
            "wind_mph IS NULL OR wind_mph BETWEEN 0 AND 120", name="wind_plausible"
        ),
        CheckConstraint(
            "precipitation_probability IS NULL "
            "OR precipitation_probability BETWEEN 0 AND 100",
            name="precip_probability_range",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WeatherForecast {self.game_id} @{self.captured_at:%Y-%m-%d %H:%M}>"


class OddsSnapshot(Base):
    """One market capture for one game from one sportsbook.

    Implied team totals are *derived*, not stored: they are exactly
    ``total/2 -/+ spread/2``, and storing a derivable value is how two columns
    end up disagreeing. The feature layer computes them once, in SQL, with the
    same sign convention :mod:`nflfp.transform` already uses for nflverse.
    """

    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, doc="Feed, e.g. 'espn'.")
    book: Mapped[str] = mapped_column(String(48), nullable=False, doc="Sportsbook, e.g. 'DraftKings'.")

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    spread_home: Mapped[float | None] = mapped_column(
        Float, doc="Market convention: negative means the home team lays points."
    )
    total: Mapped[float | None] = mapped_column(Float)
    moneyline_home: Mapped[int | None] = mapped_column(SmallInteger, doc="American odds.")
    moneyline_away: Mapped[int | None] = mapped_column(SmallInteger)
    spread_home_open: Mapped[float | None] = mapped_column(Float)
    total_open: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index(
            "uq_odds_snapshots_capture",
            "game_id", "provider", "book", "captured_at",
            unique=True,
        ),
        Index("ix_odds_snapshots_latest", "game_id", text("captured_at DESC")),
        CheckConstraint(
            "spread_home IS NULL OR spread_home BETWEEN -30 AND 30", name="spread_plausible"
        ),
        CheckConstraint("total IS NULL OR total BETWEEN 20 AND 80", name="total_plausible"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<OddsSnapshot {self.game_id} {self.book} {self.spread_home}/{self.total}>"
