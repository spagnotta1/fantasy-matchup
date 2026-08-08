"""Unit tests for the provider layer. No network, no database.

Providers are pure functions of an HTTP payload, which is the point of the
design — every behaviour below is asserted against a recorded response rather
than a live API, so these tests do not fail when ESPN has an outage or the
weather changes.
"""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from nflfp.providers.base import GameRef, OddsRecord
from nflfp.providers.errors import (
    PermanentProviderError,
    ProviderValidationError,
    TransientProviderError,
)
from nflfp.providers.http import JsonHttpClient, RetryPolicy, _redact
from nflfp.providers.odds import EspnOddsProvider, NullOddsProvider
from nflfp.providers.registry import (
    UnknownProviderError,
    get_odds_provider,
    get_weather_provider,
)
from nflfp.providers.stadiums import STADIUMS, lookup
from nflfp.providers.weather import NullWeatherProvider, OpenMeteoWeatherProvider

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# fake transport
# ---------------------------------------------------------------------------

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeOpener:
    """Replays a scripted sequence of responses or exceptions."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def urlopen(self, request, timeout=None):
        self.calls.append(request.full_url)
        outcome = self.outcomes.pop(0) if self.outcomes else self.outcomes
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(json.dumps(outcome).encode())


def _http(*outcomes, attempts=4) -> tuple[JsonHttpClient, FakeOpener]:
    opener = FakeOpener(*outcomes)
    client = JsonHttpClient(
        opener=opener,
        sleeper=lambda _: None,  # no real waiting in tests
        retry=RetryPolicy(attempts=attempts, jitter=False),
        provider_name="test",
    )
    return client, opener


def _http_error(code: int, headers: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.test", code, "err", headers or {}, None
    )


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

class TestJsonHttpClient:
    def test_returns_parsed_json(self):
        client, _ = _http({"ok": True})
        assert client.get_json("https://example.test") == {"ok": True}

    def test_retries_transient_status_then_succeeds(self):
        client, opener = _http(_http_error(503), _http_error(502), {"ok": 1})
        assert client.get_json("https://example.test") == {"ok": 1}
        assert len(opener.calls) == 3

    @pytest.mark.parametrize("code", [500, 502, 503, 504, 429, 408])
    def test_transient_statuses_are_retried(self, code):
        client, opener = _http(_http_error(code), {"ok": 1})
        client.get_json("https://example.test")
        assert len(opener.calls) == 2

    @pytest.mark.parametrize("code", [400, 401, 403, 404])
    def test_permanent_statuses_are_not_retried(self, code):
        """Retrying a 401 burns quota and delays the log line that explains it."""
        client, opener = _http(_http_error(code), {"ok": 1})
        with pytest.raises(PermanentProviderError):
            client.get_json("https://example.test")
        assert len(opener.calls) == 1

    def test_gives_up_after_the_attempt_budget(self):
        client, opener = _http(*[_http_error(503)] * 6, attempts=3)
        with pytest.raises(TransientProviderError, match="giving up after 3"):
            client.get_json("https://example.test")
        assert len(opener.calls) == 3

    def test_connection_errors_are_transient(self):
        client, _ = _http(urllib.error.URLError("connection reset"), {"ok": 1})
        assert client.get_json("https://example.test") == {"ok": 1}

    def test_invalid_json_is_a_validation_error_not_a_retry(self):
        """A malformed body means the contract changed; retrying cannot fix it."""
        opener = FakeOpener()
        opener.urlopen = lambda request, timeout=None: FakeResponse(b"<html>nope")
        client = JsonHttpClient(opener=opener, sleeper=lambda _: None, provider_name="test")
        with pytest.raises(ProviderValidationError):
            client.get_json("https://example.test")

    def test_retry_after_header_is_honoured(self):
        policy = RetryPolicy(jitter=False, backoff_base=10.0)
        assert policy.sleep_for(1, retry_after=2.0) == 2.0

    def test_backoff_is_bounded(self):
        policy = RetryPolicy(jitter=False, backoff_base=1.0, backoff_max=8.0)
        assert policy.sleep_for(10) == 8.0

    def test_params_are_merged_into_the_url(self):
        client, opener = _http({"ok": 1})
        client.get_json("https://example.test?a=1", {"b": 2})
        assert "a=1" in opener.calls[0] and "b=2" in opener.calls[0]

    def test_credentials_are_redacted_from_logged_urls(self):
        """Logs get shipped somewhere less trusted than the process."""
        redacted = _redact("https://x.test/v1?apiKey=abc123&region=us")
        assert "abc123" not in redacted
        assert "region=us" in redacted


# ---------------------------------------------------------------------------
# stadiums
# ---------------------------------------------------------------------------

class TestStadiums:
    def test_lookup_is_case_insensitive_and_tolerates_none(self):
        assert lookup("gnb00") is STADIUMS["GNB00"]
        assert lookup(None) is None
        assert lookup("NOPE99") is None

    def test_coordinates_are_plausible(self):
        for stadium in STADIUMS.values():
            assert -90 <= stadium.latitude <= 90, stadium.name
            assert -180 <= stadium.longitude <= 180, stadium.name

    def test_indoor_venues_are_not_weather_relevant(self):
        assert STADIUMS["DET00"].indoor is True
        assert STADIUMS["DET00"].weather_relevant is False

    def test_retractable_roofs_still_get_a_forecast(self):
        """The roof is often open in September and shut in December; a real
        forecast plus an uncertainty flag beats a fabricated neutral one."""
        dallas = STADIUMS["DAL00"]
        assert dallas.retractable is True
        assert dallas.weather_relevant is True


# ---------------------------------------------------------------------------
# weather
# ---------------------------------------------------------------------------

def _hourly_payload(hours: list[datetime], **series) -> dict:
    return {
        "hourly": {
            "time": [h.strftime("%Y-%m-%dT%H:%M") for h in hours],
            **{key: list(values) for key, values in series.items()},
        }
    }


class TestOpenMeteoWeatherProvider:
    def _game(self, **kw) -> GameRef:
        defaults = dict(
            game_id="G1", season=2026, week=1, home_team="GB", away_team="CHI",
            kickoff=NOW + timedelta(days=2), stadium_id="GNB00", roof="outdoors",
        )
        defaults.update(kw)
        return GameRef(**defaults)

    def _provider(self, payload):
        client, _ = _http(payload)
        return OpenMeteoWeatherProvider(client=client, clock=lambda: NOW)

    def test_parses_a_forecast_at_the_kickoff_hour(self):
        kickoff = NOW + timedelta(days=2)
        hour = kickoff.replace(minute=0, second=0, microsecond=0)
        payload = _hourly_payload(
            [hour - timedelta(hours=1), hour, hour + timedelta(hours=1)],
            temperature_2m=[10, 41.5, 12],
            wind_speed_10m=[3, 12.5, 4],
            precipitation_probability=[0, 55, 10],
        )
        result = self._provider(payload).fetch([self._game(kickoff=kickoff)])
        assert result.count == 1
        record = result.records[0]
        assert record.temperature_f == 41.5
        assert record.wind_mph == 12.5
        assert record.precipitation_probability == 55
        assert record.is_indoor is False

    def test_indoor_games_get_a_neutral_record_not_a_skip(self):
        """Dome games are ~30% of the slate; skipping them would make the
        feature join silently drop them."""
        provider = OpenMeteoWeatherProvider(client=_http()[0], clock=lambda: NOW)
        result = provider.fetch([self._game(stadium_id="DET00", roof="dome")])
        assert result.count == 1
        assert result.records[0].is_indoor is True
        assert result.records[0].wind_mph == 0.0

    def test_schedule_roof_overrides_the_static_table(self):
        """nflverse knows about a one-off closure our static data cannot."""
        provider = OpenMeteoWeatherProvider(client=_http()[0], clock=lambda: NOW)
        result = provider.fetch([self._game(stadium_id="DAL00", roof="closed")])
        assert result.records[0].is_indoor is True

    def test_retractable_roof_is_flagged_uncertain(self):
        kickoff = NOW + timedelta(days=2)
        hour = kickoff.replace(minute=0, second=0, microsecond=0)
        payload = _hourly_payload([hour], temperature_2m=[70], wind_speed_10m=[5])
        provider = self._provider(payload)
        result = provider.fetch([self._game(stadium_id="DAL00", roof="", kickoff=kickoff)])
        assert result.records[0].roof_uncertain is True
        assert result.records[0].is_indoor is False

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({"kickoff": NOW + timedelta(days=200)}, "horizon"),
            ({"kickoff": NOW - timedelta(days=3)}, "already played"),
            ({"stadium_id": "ZZZ99"}, "unknown stadium_id"),
            ({"kickoff": None}, "no kickoff time"),
        ],
    )
    def test_ineligible_games_are_skipped_with_a_reason(self, kwargs, expected):
        provider = OpenMeteoWeatherProvider(client=_http()[0], clock=lambda: NOW)
        result = provider.fetch([self._game(**kwargs)])
        assert result.count == 0
        assert expected in result.skipped["G1"]

    def test_implausible_values_are_discarded_not_stored(self):
        """A unit change upstream must surface as a null, not as a bad feature."""
        kickoff = NOW + timedelta(days=2)
        hour = kickoff.replace(minute=0, second=0, microsecond=0)
        payload = _hourly_payload(
            [hour], temperature_2m=[999.0], wind_speed_10m=[4000.0],
        )
        result = self._provider(payload).fetch([self._game(kickoff=kickoff)])
        assert result.records[0].temperature_f is None
        assert result.records[0].wind_mph is None

    def test_one_venue_failing_does_not_lose_the_others(self):
        kickoff = NOW + timedelta(days=2)
        hour = kickoff.replace(minute=0, second=0, microsecond=0)
        good = _hourly_payload([hour], temperature_2m=[50], wind_speed_10m=[5])
        client, _ = _http(_http_error(404), good)
        provider = OpenMeteoWeatherProvider(client=client, clock=lambda: NOW)
        result = provider.fetch([
            self._game(game_id="BAD", stadium_id="GNB00", kickoff=kickoff),
            self._game(game_id="GOOD", stadium_id="SEA00", kickoff=kickoff),
        ])
        assert result.count == 1
        assert result.records[0].game_id == "GOOD"
        assert "BAD" in result.skipped

    def test_malformed_payload_skips_rather_than_raises(self):
        result = self._provider({"nope": True}).fetch([self._game()])
        assert result.count == 0
        assert "invalid payload" in result.skipped["G1"]


class TestNullProviders:
    def test_null_weather_returns_nothing_successfully(self):
        game = GameRef("G1", 2026, 1, "GB", "CHI")
        result = NullWeatherProvider().fetch([game])
        assert result.count == 0
        assert "disabled" in result.skipped["G1"]

    def test_null_odds_returns_nothing_successfully(self):
        game = GameRef("G1", 2026, 1, "GB", "CHI")
        result = NullOddsProvider().fetch([game])
        assert result.count == 0


# ---------------------------------------------------------------------------
# odds
# ---------------------------------------------------------------------------

def _espn_payload(home="SEA", away="NE", spread=-3.5, total=44.5, provider="DraftKings"):
    """Shaped like the real ESPN scoreboard response, trimmed to what we read."""
    return {
        "events": [
            {
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "home", "team": {"abbreviation": home}},
                            {"homeAway": "away", "team": {"abbreviation": away}},
                        ],
                        "odds": [
                            {
                                "provider": {"name": provider, "priority": 1},
                                "spread": spread,
                                "overUnder": total,
                                "moneyline": {
                                    "home": {"close": {"odds": "-185"}},
                                    "away": {"close": {"odds": "+154"}},
                                },
                                "pointSpread": {"home": {"open": {"line": "-2.5"}}},
                                "total": {"over": {"open": {"line": "o43.5"}}},
                            }
                        ],
                    }
                ]
            }
        ]
    }


class TestEspnOddsProvider:
    def _game(self, **kw) -> GameRef:
        defaults = dict(
            game_id="2026_01_NE_SEA", season=2026, week=1,
            home_team="SEA", away_team="NE", kickoff=NOW + timedelta(days=5),
        )
        defaults.update(kw)
        return GameRef(**defaults)

    def test_parses_spread_total_and_moneyline(self):
        client, _ = _http(_espn_payload())
        result = EspnOddsProvider(client=client, clock=lambda: NOW).fetch([self._game()])
        assert result.count == 1
        record = result.records[0]
        assert record.game_id == "2026_01_NE_SEA"
        assert record.spread_home == -3.5
        assert record.total == 44.5
        assert record.moneyline_home == -185
        assert record.moneyline_away == 154
        assert record.spread_home_open == -2.5
        assert record.total_open == 43.5

    def test_espn_abbreviations_are_mapped_to_nflverse(self):
        """ESPN says WSH and LAR; nflverse says WAS and LA."""
        client, _ = _http(_espn_payload(home="WSH", away="LAR"))
        result = EspnOddsProvider(client=client, clock=lambda: NOW).fetch(
            [self._game(home_team="WAS", away_team="LA")]
        )
        assert result.count == 1

    def test_games_without_a_posted_market_are_skipped(self):
        client, _ = _http({"events": []})
        result = EspnOddsProvider(client=client, clock=lambda: NOW).fetch([self._game()])
        assert result.count == 0
        assert "no market posted" in result.skipped["2026_01_NE_SEA"]

    def test_completed_games_are_not_fetched(self):
        client, opener = _http({"events": []})
        result = EspnOddsProvider(client=client, clock=lambda: NOW).fetch(
            [self._game(kickoff=NOW - timedelta(days=2))]
        )
        assert result.skipped["2026_01_NE_SEA"] == "game already played"
        assert opener.calls == []

    def test_implausible_lines_are_discarded(self):
        client, _ = _http(_espn_payload(spread=-99.0, total=500.0))
        record = EspnOddsProvider(client=client, clock=lambda: NOW).fetch([self._game()]).records[0]
        assert record.spread_home is None
        assert record.total is None

    def test_preferred_book_is_selected(self):
        payload = _espn_payload(provider="Caesars")
        payload["events"][0]["competitions"][0]["odds"].append(
            {"provider": {"name": "DraftKings", "priority": 2}, "spread": -7.0, "overUnder": 50.0}
        )
        client, _ = _http(payload)
        record = EspnOddsProvider(client=client, clock=lambda: NOW).fetch([self._game()]).records[0]
        assert record.book == "DraftKings"
        assert record.spread_home == -7.0

    def test_fetch_failure_skips_rather_than_raises(self):
        client, _ = _http(*[_http_error(503)] * 5)
        result = EspnOddsProvider(client=client, clock=lambda: NOW).fetch([self._game()])
        assert result.count == 0
        assert "fetch failed" in result.skipped["2026_01_NE_SEA"]
        assert result.warnings


class TestImpliedTotals:
    """The sign convention, which is easy to invert and impossible to spot later."""

    def test_home_favourite_has_the_higher_implied_total(self):
        record = OddsRecord("G", NOW, "DK", spread_home=-7.0, total=47.0)
        assert record.implied_home_total == 27.0
        assert record.implied_away_total == 20.0
        assert record.implied_home_total + record.implied_away_total == 47.0

    def test_home_underdog_has_the_lower_implied_total(self):
        record = OddsRecord("G", NOW, "DK", spread_home=3.0, total=41.0)
        assert record.implied_home_total == 19.0
        assert record.implied_away_total == 22.0

    def test_missing_inputs_give_none(self):
        assert OddsRecord("G", NOW, "DK", total=44.0).implied_home_total is None
        assert OddsRecord("G", NOW, "DK", spread_home=-3.0).implied_home_total is None


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_resolves_configured_providers(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        monkeypatch.setenv("WEATHER_PROVIDER", "open_meteo")
        monkeypatch.setenv("ODDS_PROVIDER", "espn")
        from nflfp.config import Settings

        settings = Settings()
        assert isinstance(get_weather_provider(settings), OpenMeteoWeatherProvider)
        assert isinstance(get_odds_provider(settings), EspnOddsProvider)

    def test_null_disables_a_feed_without_removing_the_job(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        from nflfp.config import Settings

        settings = Settings(weather_provider="null", odds_provider="null")
        assert isinstance(get_weather_provider(settings), NullWeatherProvider)
        assert isinstance(get_odds_provider(settings), NullOddsProvider)

    def test_unknown_provider_fails_loudly_and_lists_options(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        from nflfp.config import Settings

        settings = Settings(weather_provider="accuweather")
        with pytest.raises(UnknownProviderError, match="registered:"):
            get_weather_provider(settings)
