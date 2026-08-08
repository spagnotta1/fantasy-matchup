"""External data providers.

Layer 2's extension point. The nflverse ETL in :mod:`nflfp.pipeline` covers
everything nflverse publishes; this package covers the two things it cannot,
because they are only knowable *before* a game is played:

* **weather forecasts** — nflverse's ``temp``/``wind`` are observed after the
  fact, so the 2026 schedule carries neither for any of its 272 games;
* **live betting markets** — nflverse's ``spread_line``/``total_line`` are
  closing lines, posted for only 52 of those games and stale once they are.

Everything downstream depends on the protocols and dataclasses in
:mod:`nflfp.providers.base` and resolves implementations through
:mod:`nflfp.providers.registry`. No feature, model or API code imports a
concrete provider.
"""

from __future__ import annotations

from .base import (
    GameRef,
    OddsProvider,
    OddsRecord,
    ProviderFetch,
    WeatherForecastRecord,
    WeatherProvider,
)
from .errors import (
    PermanentProviderError,
    ProviderError,
    ProviderValidationError,
    TransientProviderError,
)
from .http import JsonHttpClient, RetryPolicy
from .registry import get_odds_provider, get_weather_provider
from .stadiums import STADIUMS, Stadium, lookup as lookup_stadium

__all__ = [
    "GameRef",
    "JsonHttpClient",
    "OddsProvider",
    "OddsRecord",
    "PermanentProviderError",
    "ProviderError",
    "ProviderFetch",
    "ProviderValidationError",
    "RetryPolicy",
    "STADIUMS",
    "Stadium",
    "TransientProviderError",
    "WeatherForecastRecord",
    "WeatherProvider",
    "get_odds_provider",
    "get_weather_provider",
    "lookup_stadium",
]
