"""Betting market providers.

nflverse's ``spread_line`` and ``total_line`` are **closing** lines, written
once the market settles. For a Tuesday projection they are either absent (only
52 of the 272 games on the 2026 schedule carry one) or, later in the week,
stale. The market moves on injury news all week, and that movement is exactly
the information a Thursday projection wants.

Default implementation reads ESPN's public scoreboard, which carries DraftKings
spread, total and moneyline for future games with no API key. The obvious
alternative, The Odds API, gives multiple books and a documented contract but
requires a key and has a 500-request monthly free tier; it is a drop-in
replacement via the registry when that trade becomes worthwhile.

Records are **append-only snapshots**, never updates. "Timestamped updates" in
a market feed means history: line movement is a feature, and overwriting
Tuesday's number with Sunday's destroys it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from .base import GameRef, OddsRecord, ProviderFetch
from .http import JsonHttpClient

logger = logging.getLogger(__name__)

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# ESPN's abbreviations differ from nflverse's for a handful of teams. Mapping
# ESPN -> nflverse, since nflverse is the system of record everywhere else.
ESPN_TEAM_FIXUPS = {
    "WSH": "WAS",
    "LAR": "LA",
}

# Plausibility bounds. A spread outside this is a parsing bug, not a market.
SPREAD_RANGE = (-30.0, 30.0)
TOTAL_RANGE = (20.0, 80.0)


class NullOddsProvider:
    """Returns nothing, successfully. See :class:`~nflfp.providers.weather.NullWeatherProvider`."""

    name = "null"

    def fetch(self, games: list[GameRef]) -> ProviderFetch[OddsRecord]:
        return ProviderFetch(
            provider=self.name,
            fetched_at=datetime.now(timezone.utc),
            skipped={g.game_id: "odds provider disabled" for g in games},
        )


class EspnOddsProvider:
    """Forward-looking spread, total and moneyline from ESPN's scoreboard.

    One request per (season, week) rather than per game: the scoreboard returns
    a whole week, and 16 games for one request is the difference between a job
    that finishes in a second and one that hammers a public endpoint.

    Games are matched back to nflverse by ``(season, week, home_team,
    away_team)``. ESPN's own event ids are not stored as the join key — they are
    a second identifier space with its own drift, and nflverse's ``game_id`` is
    already the key every other table uses.
    """

    name = "espn"

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        url: str = ESPN_SCOREBOARD_URL,
        book: str = "DraftKings",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """
        Args:
            client: HTTP client, injectable for tests.
            url: Scoreboard endpoint.
            book: Preferred sportsbook; falls back to the highest-priority one.
            clock: Source of "now". Injectable because whether a game counts as
                upcoming is entirely a function of the current time.
        """
        self._client = client or JsonHttpClient(provider_name=self.name)
        self._url = url
        self._book = book
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch(self, games: list[GameRef]) -> ProviderFetch[OddsRecord]:
        """Fetch current markets for every upcoming game."""
        now = self._clock()
        result: ProviderFetch[OddsRecord] = ProviderFetch(provider=self.name, fetched_at=now)

        upcoming: dict[tuple[int, int], list[GameRef]] = {}
        for game in games:
            if game.kickoff is not None and _as_utc(game.kickoff) < now - timedelta(hours=6):
                result.skipped[game.game_id] = "game already played"
                continue
            upcoming.setdefault((game.season, game.week), []).append(game)

        for (season, week), week_games in sorted(upcoming.items()):
            try:
                payload = self._client.get_json(
                    self._url,
                    {"dates": season, "seasontype": 2, "week": week},
                )
            except Exception as exc:
                logger.warning("%s: %s week %s failed: %s", self.name, season, week, exc)
                for game in week_games:
                    result.skipped[game.game_id] = f"fetch failed: {exc}"
                result.warnings.append(f"{season} week {week}: {exc}")
                continue

            quotes = self._parse(payload, now)
            for game in week_games:
                quote = quotes.get((game.home_team, game.away_team))
                if quote is None:
                    result.skipped[game.game_id] = "no market posted for this game yet"
                    continue
                result.records.append(
                    OddsRecord(
                        game_id=game.game_id,
                        captured_at=now,
                        book=quote.book,
                        spread_home=quote.spread_home,
                        total=quote.total,
                        moneyline_home=quote.moneyline_home,
                        moneyline_away=quote.moneyline_away,
                        spread_home_open=quote.spread_home_open,
                        total_open=quote.total_open,
                    )
                )

        logger.info("%s", result.summary())
        return result

    # -- parsing -----------------------------------------------------------

    def _parse(self, payload: object, now: datetime) -> dict[tuple[str, str], OddsRecord]:
        """Extract one market per game, keyed by (home, away) nflverse abbrs."""
        if not isinstance(payload, dict):
            return {}
        quotes: dict[tuple[str, str], OddsRecord] = {}

        for event in payload.get("events") or []:
            competitions = event.get("competitions") or []
            if not competitions:
                continue
            competition = competitions[0]

            teams = {}
            for competitor in competition.get("competitors") or []:
                side = competitor.get("homeAway")
                abbr = (competitor.get("team") or {}).get("abbreviation")
                if side and abbr:
                    teams[side] = ESPN_TEAM_FIXUPS.get(abbr, abbr)
            if "home" not in teams or "away" not in teams:
                continue

            odds_blocks = competition.get("odds") or []
            block = _preferred_book(odds_blocks, self._book)
            if block is None:
                continue

            quotes[(teams["home"], teams["away"])] = OddsRecord(
                game_id="",  # filled in by the caller, which knows the nflverse id
                captured_at=now,
                book=(block.get("provider") or {}).get("name") or self._book,
                spread_home=_bounded(_as_float(block.get("spread")), SPREAD_RANGE, "spread"),
                total=_bounded(_as_float(block.get("overUnder")), TOTAL_RANGE, "total"),
                moneyline_home=_moneyline(block, "home"),
                moneyline_away=_moneyline(block, "away"),
                spread_home_open=_bounded(
                    _nested_line(block, "pointSpread", "home", "open"), SPREAD_RANGE, "open spread"
                ),
                total_open=_bounded(
                    _nested_line(block, "total", "over", "open"), TOTAL_RANGE, "open total"
                ),
            )
        return quotes


def _preferred_book(blocks: list, preferred: str) -> dict | None:
    """Pick the configured sportsbook, else the highest-priority one offered."""
    usable = [b for b in blocks if isinstance(b, dict)]
    if not usable:
        return None
    for block in usable:
        if ((block.get("provider") or {}).get("name") or "").lower() == preferred.lower():
            return block
    return min(usable, key=lambda b: (b.get("provider") or {}).get("priority", 999))


def _moneyline(block: dict, side: str) -> int | None:
    """American moneyline for one side, from the nested current-odds block."""
    raw = _nested(block, "moneyline", side, "close", "odds")
    if raw is None:
        raw = _nested(block, "moneyline", side, "open", "odds")
    if raw is None:
        return None
    try:
        # ESPN renders these as strings like "-185" or "+154".
        return int(str(raw).replace("+", "").strip())
    except ValueError:
        logger.debug("unparseable moneyline %r", raw)
        return None


def _nested_line(block: dict, market: str, side: str, phase: str) -> float | None:
    """A line value like "-3.5" or "o44.5" from a nested market block."""
    raw = _nested(block, market, side, phase, "line")
    if raw is None:
        return None
    try:
        return float(str(raw).lstrip("ou").strip())
    except ValueError:
        return None


def _nested(block: dict, *path: str) -> object | None:
    node: object = block
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded(value: float | None, bounds: tuple[float, float], label: str) -> float | None:
    """Reject a value outside plausible market range — see weather._validated."""
    if value is None:
        return None
    low, high = bounds
    if not low <= value <= high:
        logger.warning("discarding implausible %s value %.2f", label, value)
        return None
    return value


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
