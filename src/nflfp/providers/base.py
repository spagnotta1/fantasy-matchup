"""Provider contracts.

The whole point of this module is that **nothing downstream imports a concrete
provider**. Feature code, the prediction engine and the API depend on the
dataclasses defined here; the ETL depends on the protocols. Swapping Open-Meteo
for a paid forecast service, or ESPN for The Odds API, is then a change to one
registry entry and one new file — nothing else moves.

Two shapes are defined:

* :class:`GameRef` — the minimum a provider needs to know about a game to fetch
  something for it. Providers never query the database themselves; the ETL
  hands them the games. That keeps providers pure, trivially testable, and
  incapable of coupling themselves to the warehouse schema.
* :class:`ProviderFetch` — a fetch result plus the diagnostics needed to
  understand a partial success, since "we got 12 of 16 games" is the normal
  outcome for a live sports feed, not an exception.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Generic, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


@dataclass(frozen=True)
class GameRef:
    """Identifies one game to a provider.

    Deliberately a plain value object rather than an ORM row: providers must
    not be able to touch the database, and a frozen dataclass makes that
    structural rather than a rule people remember.
    """

    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    kickoff: datetime | None = None
    stadium_id: str | None = None
    roof: str | None = None

    @property
    def matchup(self) -> str:
        return f"{self.away_team}@{self.home_team}"


@dataclass
class ProviderFetch(Generic[T]):
    """What a provider returns: the records plus why the rest are missing.

    A live feed routinely has no line for a Thursday game in August or no
    forecast beyond 16 days. Treating that as an exception would mean one
    unavailable game aborts the whole run, so it is reported as data instead.
    """

    provider: str
    fetched_at: datetime
    records: list[T] = field(default_factory=list)
    #: game_id -> human-readable reason nothing was returned for it.
    skipped: dict[str, str] = field(default_factory=dict)
    #: Non-fatal problems worth a log line and a metric.
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)

    def summary(self) -> str:
        parts = [f"{self.provider}: {self.count} record(s)"]
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s)")
        return ", ".join(parts)


@dataclass(frozen=True)
class WeatherForecastRecord:
    """A forecast for one game, normalised across providers.

    Units are fixed at the boundary — Fahrenheit and miles per hour — because
    every provider has its own defaults and a silent unit mismatch is the kind
    of bug that survives to production looking merely like a bad model.
    """

    game_id: str
    #: When the forecast was produced. Forecasts are append-only history, so
    #: this is what distinguishes Tuesday's outlook from Sunday morning's.
    captured_at: datetime
    #: The kickoff hour this forecast describes.
    valid_at: datetime
    temperature_f: float | None = None
    wind_mph: float | None = None
    wind_gust_mph: float | None = None
    precipitation_probability: float | None = None
    precipitation_in: float | None = None
    snowfall_in: float | None = None
    humidity_pct: float | None = None
    cloud_cover_pct: float | None = None
    #: True when the venue's roof makes conditions irrelevant.
    is_indoor: bool = False
    #: True when the roof is retractable and its state is not yet known.
    roof_uncertain: bool = False


@dataclass(frozen=True)
class OddsRecord:
    """A market snapshot for one game from one sportsbook.

    ``spread_home`` follows the *market* convention — negative means the home
    team is laying points. :mod:`nflfp.transform` already normalises nflverse's
    equivalent into "points this team is favoured by", and the feature layer
    does the same here, so the two sources cannot disagree about sign.
    """

    game_id: str
    captured_at: datetime
    book: str
    spread_home: float | None = None
    total: float | None = None
    moneyline_home: int | None = None
    moneyline_away: int | None = None
    #: Opening line where the provider exposes it, for line-movement features.
    spread_home_open: float | None = None
    total_open: float | None = None

    @property
    def implied_home_total(self) -> float | None:
        """Points the market expects the home team to score.

        total/2 - spread_home/2: with the home team favoured (spread_home
        negative) this correctly resolves to more than half the total.
        """
        if self.total is None or self.spread_home is None:
            return None
        return self.total / 2.0 - self.spread_home / 2.0

    @property
    def implied_away_total(self) -> float | None:
        if self.total is None or self.spread_home is None:
            return None
        return self.total / 2.0 + self.spread_home / 2.0


@runtime_checkable
class WeatherProvider(Protocol):
    """Fetches forecasts for upcoming games."""

    name: str

    def fetch(self, games: list[GameRef]) -> ProviderFetch[WeatherForecastRecord]:
        """Return a forecast for each game it can serve.

        Implementations must not raise for individual unavailable games —
        record them in :attr:`ProviderFetch.skipped` instead. Raising is
        reserved for failures that make the whole fetch meaningless.
        """
        ...


@runtime_checkable
class OddsProvider(Protocol):
    """Fetches current betting markets for upcoming games."""

    name: str

    def fetch(self, games: list[GameRef]) -> ProviderFetch[OddsRecord]:
        """Return the latest market for each game it can serve."""
        ...
