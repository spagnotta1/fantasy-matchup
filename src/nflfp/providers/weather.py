"""Weather forecast providers.

nflverse's ``temp`` and ``wind`` are *observed* conditions, written after a game
is played — verified: the 2026 schedule has 272 games and zero of them carry
either field. They are useful for training and useless for projecting, which is
the entire reason this module exists.

Default implementation is Open-Meteo: no API key, no registration, and an
explicit free-for-non-commercial-use policy. If that changes, or a paid service
with better NFL-specific modelling is wanted, the swap is one registry entry —
downstream code depends on :class:`~nflfp.providers.base.WeatherProvider` and
never on this file.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from .base import GameRef, ProviderFetch, WeatherForecastRecord
from .errors import ProviderValidationError
from .http import JsonHttpClient
from .stadiums import lookup

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo publishes 16 days ahead. Beyond that it returns nothing useful, so
# there is no point spending a request — the NFL week is 7 days, which means a
# daily job always covers the upcoming slate comfortably.
FORECAST_HORIZON_DAYS = 16

# Sanity bounds. These are not "what the weather could be" — they are "what a
# number must look like to be a temperature at all". A provider changing units
# under us shows up here rather than as a mysteriously bad projection.
TEMP_RANGE_F = (-60.0, 130.0)
WIND_RANGE_MPH = (0.0, 120.0)


class NullWeatherProvider:
    """A provider that returns nothing, successfully.

    Not a test double — the deployed default when forecasts are switched off.
    A scheduled job that runs and reports "0 records, provider disabled" is
    operationally very different from one that crashes, and this makes the
    former the easy path.
    """

    name = "null"

    def fetch(self, games: list[GameRef]) -> ProviderFetch[WeatherForecastRecord]:
        return ProviderFetch(
            provider=self.name,
            fetched_at=datetime.now(timezone.utc),
            skipped={g.game_id: "weather provider disabled" for g in games},
        )


class OpenMeteoWeatherProvider:
    """Forecasts from Open-Meteo, one request per venue.

    Requests are per-stadium rather than per-game: a Sunday slate has 13 games
    at 13 venues, but a venue hosting a doubleheader week should not be fetched
    twice. Games are grouped by ``stadium_id`` and each response is sampled at
    each kickoff hour.
    """

    name = "open_meteo"

    #: Hourly variables requested. Ordered as they appear in the response for
    #: easier eyeballing against the API docs.
    HOURLY_VARIABLES = (
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation_probability",
        "precipitation",
        "snowfall",
        "cloud_cover",
        "wind_speed_10m",
        "wind_gusts_10m",
    )

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        url: str = OPEN_METEO_URL,
        horizon_days: int = FORECAST_HORIZON_DAYS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """
        Args:
            client: HTTP client, injectable for tests.
            url: Forecast endpoint.
            horizon_days: How far ahead the upstream publishes.
            clock: Source of "now". Injectable because eligibility is entirely a
                function of the current time, so without this seam every test
                would pass or fail depending on the date it ran.
        """
        self._client = client or JsonHttpClient(provider_name=self.name)
        self._url = url
        self._horizon_days = horizon_days
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch(self, games: list[GameRef]) -> ProviderFetch[WeatherForecastRecord]:
        """Fetch forecasts for every outdoor game within the horizon."""
        now = self._clock()
        result: ProviderFetch[WeatherForecastRecord] = ProviderFetch(
            provider=self.name, fetched_at=now
        )

        by_venue: dict[str, list[GameRef]] = {}
        for game in games:
            reason = self._ineligible(game, now)
            if reason is not None:
                # Indoor games are "handled", not "failed": a neutral record is
                # written so downstream joins do not have to special-case them.
                if reason == "indoor":
                    result.records.append(_indoor_record(game, now))
                else:
                    result.skipped[game.game_id] = reason
                continue
            by_venue.setdefault(game.stadium_id or "", []).append(game)

        for stadium_id, venue_games in by_venue.items():
            stadium = lookup(stadium_id)
            assert stadium is not None  # guaranteed by _ineligible
            try:
                payload = self._client.get_json(
                    self._url,
                    {
                        "latitude": stadium.latitude,
                        "longitude": stadium.longitude,
                        "hourly": ",".join(self.HOURLY_VARIABLES),
                        "temperature_unit": "fahrenheit",
                        "wind_speed_unit": "mph",
                        "precipitation_unit": "inch",
                        "timezone": "UTC",
                        "forecast_days": self._horizon_days,
                    },
                )
            except Exception as exc:
                # One venue failing must not lose the other twelve.
                logger.warning("%s: %s failed: %s", self.name, stadium.name, exc)
                for game in venue_games:
                    result.skipped[game.game_id] = f"fetch failed: {exc}"
                result.warnings.append(f"{stadium.name}: {exc}")
                continue

            try:
                series = _parse_hourly(payload)
            except ProviderValidationError as exc:
                logger.error("%s: %s returned an unusable payload: %s", self.name, stadium.name, exc)
                for game in venue_games:
                    result.skipped[game.game_id] = f"invalid payload: {exc}"
                result.warnings.append(f"{stadium.name}: {exc}")
                continue

            for game in venue_games:
                record = _sample(game, series, now, stadium.retractable)
                if record is None:
                    result.skipped[game.game_id] = "kickoff hour not in forecast range"
                    continue
                result.records.append(record)

        logger.info("%s", result.summary())
        return result

    # -- eligibility -------------------------------------------------------

    def _ineligible(self, game: GameRef, now: datetime) -> str | None:
        """Why this game cannot or need not be fetched, or None if it can."""
        if game.kickoff is None:
            return "no kickoff time on the schedule"

        kickoff = _as_utc(game.kickoff)
        if kickoff < now - timedelta(hours=6):
            return "game already played"
        if kickoff > now + timedelta(days=self._horizon_days):
            return f"kickoff beyond the {self._horizon_days}-day forecast horizon"

        stadium = lookup(game.stadium_id)
        if stadium is None:
            return f"unknown stadium_id {game.stadium_id!r}"
        # The schedule's own roof field wins when it is populated: nflverse
        # knows about a one-off closure that our static table cannot.
        if stadium.indoor or (game.roof or "").lower() in ("dome", "closed"):
            return "indoor"
        return None


# ---------------------------------------------------------------------------
# payload handling
# ---------------------------------------------------------------------------

def _indoor_record(game: GameRef, now: datetime) -> WeatherForecastRecord:
    """A neutral record for a game where weather cannot matter.

    Written rather than skipped so that every upcoming game has a weather row
    and the feature layer can inner-join without silently dropping dome games —
    which are ~30% of the slate.
    """
    return WeatherForecastRecord(
        game_id=game.game_id,
        captured_at=now,
        valid_at=_as_utc(game.kickoff) if game.kickoff else now,
        temperature_f=72.0,
        wind_mph=0.0,
        precipitation_probability=0.0,
        is_indoor=True,
    )


def _parse_hourly(payload: object) -> dict[datetime, dict[str, float | None]]:
    """Turn Open-Meteo's column-oriented response into time -> readings."""
    if not isinstance(payload, dict) or "hourly" not in payload:
        raise ProviderValidationError("response has no 'hourly' block")
    hourly = payload["hourly"]
    if not isinstance(hourly, dict) or "time" not in hourly:
        raise ProviderValidationError("'hourly' block has no 'time' series")

    times = hourly["time"]
    series: dict[datetime, dict[str, float | None]] = {}
    for index, stamp in enumerate(times):
        try:
            when = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError) as exc:
            raise ProviderValidationError(f"unparseable timestamp {stamp!r}: {exc}") from exc
        series[when] = {
            key: _at(hourly.get(key), index)
            for key in OpenMeteoWeatherProvider.HOURLY_VARIABLES
        }
    if not series:
        raise ProviderValidationError("'hourly' block was empty")
    return series


def _at(column: object, index: int) -> float | None:
    if not isinstance(column, list) or index >= len(column):
        return None
    value = column[index]
    return None if value is None else float(value)


def _sample(
    game: GameRef,
    series: dict[datetime, dict[str, float | None]],
    now: datetime,
    retractable: bool,
) -> WeatherForecastRecord | None:
    """Pick the forecast hour nearest kickoff and validate it."""
    kickoff = _as_utc(game.kickoff)  # type: ignore[arg-type]
    hour = kickoff.replace(minute=0, second=0, microsecond=0)
    readings = series.get(hour)
    if readings is None:
        # Kickoff can fall outside the returned window at the horizon edge.
        candidates = [t for t in series if abs((t - kickoff).total_seconds()) <= 3600]
        if not candidates:
            return None
        readings = series[min(candidates, key=lambda t: abs((t - kickoff).total_seconds()))]

    return WeatherForecastRecord(
        game_id=game.game_id,
        captured_at=now,
        valid_at=kickoff,
        temperature_f=_validated(readings.get("temperature_2m"), TEMP_RANGE_F, "temperature"),
        wind_mph=_validated(readings.get("wind_speed_10m"), WIND_RANGE_MPH, "wind"),
        wind_gust_mph=_validated(readings.get("wind_gusts_10m"), WIND_RANGE_MPH, "gust"),
        precipitation_probability=_validated(readings.get("precipitation_probability"), (0.0, 100.0), "precip prob"),
        precipitation_in=_validated(readings.get("precipitation"), (0.0, 20.0), "precip"),
        snowfall_in=_validated(readings.get("snowfall"), (0.0, 60.0), "snowfall"),
        humidity_pct=_validated(readings.get("relative_humidity_2m"), (0.0, 100.0), "humidity"),
        cloud_cover_pct=_validated(readings.get("cloud_cover"), (0.0, 100.0), "cloud cover"),
        is_indoor=False,
        roof_uncertain=retractable,
    )


def _validated(value: float | None, bounds: tuple[float, float], label: str) -> float | None:
    """Drop a reading that is outside physical plausibility.

    Dropping beats storing: a nonsense value propagates into a feature, a
    projection and a lineup decision, whereas a null is visibly missing. The
    log line is what tells you the provider changed units.
    """
    if value is None:
        return None
    low, high = bounds
    if not low <= value <= high:
        logger.warning("discarding implausible %s value %.2f (expected %.0f..%.0f)", label, value, low, high)
        return None
    return value


def _as_utc(value: datetime) -> datetime:
    """Treat naive timestamps as UTC.

    nflverse gameday/gametime are naive; the pipeline stores them without a
    zone. Assuming UTC consistently is what keeps forecast sampling aligned
    with what gets written to the database.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
