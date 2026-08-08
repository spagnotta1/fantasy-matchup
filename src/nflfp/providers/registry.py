"""Provider selection, driven by configuration rather than imports.

This is the seam that makes providers swappable. Callers ask for "the weather
provider" and get whatever ``WEATHER_PROVIDER`` names; no ETL, feature or API
module imports :mod:`nflfp.providers.weather` directly. Replacing Open-Meteo
with a paid service is then a new file plus one line here.

Registration is a plain dict of factories rather than entry points or dynamic
import: the set of providers is small, known at build time, and being able to
read the whole list in one screen is worth more than plugin machinery.
"""

from __future__ import annotations

import logging
from typing import Callable

from ..config import Settings, get_settings
from .base import OddsProvider, WeatherProvider
from .errors import ProviderError
from .odds import EspnOddsProvider, NullOddsProvider
from .weather import NullWeatherProvider, OpenMeteoWeatherProvider

logger = logging.getLogger(__name__)

WEATHER_PROVIDERS: dict[str, Callable[[], WeatherProvider]] = {
    "open_meteo": OpenMeteoWeatherProvider,
    "null": NullWeatherProvider,
}

ODDS_PROVIDERS: dict[str, Callable[[], OddsProvider]] = {
    "espn": EspnOddsProvider,
    "null": NullOddsProvider,
}


class UnknownProviderError(ProviderError):
    """The configured provider name is not registered."""


def _build(
    registry: dict[str, Callable[[], object]], name: str, kind: str
) -> object:
    try:
        factory = registry[name]
    except KeyError:
        raise UnknownProviderError(
            f"unknown {kind} provider {name!r}; registered: {sorted(registry)}"
        ) from None
    provider = factory()
    logger.debug("resolved %s provider -> %s", kind, name)
    return provider


def get_weather_provider(settings: Settings | None = None) -> WeatherProvider:
    """The configured weather provider."""
    settings = settings or get_settings()
    return _build(WEATHER_PROVIDERS, settings.weather_provider, "weather")  # type: ignore[return-value]


def get_odds_provider(settings: Settings | None = None) -> OddsProvider:
    """The configured odds provider."""
    settings = settings or get_settings()
    return _build(ODDS_PROVIDERS, settings.odds_provider, "odds")  # type: ignore[return-value]
