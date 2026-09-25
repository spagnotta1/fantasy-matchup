"""Live game state and box scores from ESPN's public site API.

The one provider the read path calls at request time rather than from a job.
Everything else in this package writes snapshots a job refreshes on a cadence;
a live score refreshed hourly is not a live score. The API bounds the cost the
same way it bounds everything else — a 60-second response-cache rule — so a
Sunday's traffic costs ESPN one scoreboard read a minute, not one per viewer.

What comes back is **unofficial**: ESPN's in-game box score, not the nflverse
stat line the warehouse loads after the week. It carries no two-point
conversions, and a stat correction on Monday is not in it.
The service says so beside every number; the official line replaces it when
the week is loaded.

Parsing is split from fetching so the shape assumptions — which key holds
receiving yards, how "26/38" is split — are tested on fixtures, not on a
network.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .http import JsonHttpClient
from .odds import ESPN_SCOREBOARD_URL, ESPN_TEAM_FIXUPS

logger = logging.getLogger(__name__)

ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"

#: Box scores fetched at once. A slate is sixteen games; eight in flight keeps a
#: cold fetch near two round-trips without looking like a burst to the upstream.
MAX_PARALLEL = 8


@dataclass(frozen=True)
class LiveGame:
    event_id: str
    home: str
    away: str
    state: str  # "pre" | "in" | "post"
    detail: str | None
    clock: str | None
    period: int | None
    home_score: int | None
    away_score: int | None
    kickoff: str | None


@dataclass(frozen=True)
class LiveLine:
    """One player's box-score line, in the scoring module's component names."""

    espn_id: str
    name: str
    team: str
    event_id: str
    components: Mapping[str, float]


@dataclass
class LiveWeek:
    games: list[LiveGame] = field(default_factory=list)
    lines: list[LiveLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _num(value: object) -> float:
    """A box-score cell as a number. ESPN writes a missing stat as "--"."""
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _team(abbr: object) -> str:
    text = str(abbr or "")
    return ESPN_TEAM_FIXUPS.get(text, text)


def parse_scoreboard(payload: object) -> list[LiveGame]:
    """Games and their state from a scoreboard response. Pure."""
    games: list[LiveGame] = []
    events = payload.get("events") if isinstance(payload, dict) else None
    for event in events or []:
        competition = (event.get("competitions") or [{}])[0]
        status = competition.get("status") or event.get("status") or {}
        kind = status.get("type") or {}
        sides: dict[str, dict] = {}
        for competitor in competition.get("competitors") or []:
            sides[str(competitor.get("homeAway"))] = competitor
        home, away = sides.get("home"), sides.get("away")
        if not home or not away:
            continue
        games.append(
            LiveGame(
                event_id=str(event.get("id")),
                home=_team((home.get("team") or {}).get("abbreviation")),
                away=_team((away.get("team") or {}).get("abbreviation")),
                state=str(kind.get("state") or "pre"),
                detail=kind.get("shortDetail") or kind.get("detail"),
                clock=status.get("displayClock"),
                period=_int(status.get("period")),
                home_score=_int(home.get("score")),
                away_score=_int(away.get("score")),
                kickoff=event.get("date"),
            )
        )
    return games


#: ESPN stat category and key -> the scoring module's component name.
_FIELDS: dict[str, dict[str, str]] = {
    "passing": {
        "passingYards": "passing_yards",
        "passingTouchdowns": "passing_tds",
        "interceptions": "passing_interceptions",
    },
    "rushing": {
        "rushingAttempts": "carries",
        "rushingYards": "rushing_yards",
        "rushingTouchdowns": "rushing_tds",
    },
    "receiving": {
        "receptions": "receptions",
        "receivingYards": "receiving_yards",
        "receivingTouchdowns": "receiving_tds",
        "receivingTargets": "targets",
    },
    "fumbles": {"fumblesLost": "fumbles_lost_total"},
    # Return touchdowns score as special-teams TDs; both categories add to one
    # component, which is why components accumulate rather than assign.
    "kickReturns": {"kickReturnTouchdowns": "special_teams_tds"},
    "puntReturns": {"puntReturnTouchdowns": "special_teams_tds"},
}


def parse_boxscore(payload: object, event_id: str) -> list[LiveLine]:
    """Per-player offensive components from a game summary. Pure.

    A player appears once per category he recorded a stat in; the categories
    are merged into one line per player. Keys are read by name, not position,
    because ESPN has reordered columns before and a positional read would
    silently turn yards into attempts.
    """
    box = payload.get("boxscore") if isinstance(payload, dict) else None
    lines: dict[str, dict] = {}
    for team_block in (box or {}).get("players") or []:
        team = _team((team_block.get("team") or {}).get("abbreviation"))
        for category in team_block.get("statistics") or []:
            mapping = _FIELDS.get(str(category.get("name")))
            if not mapping:
                continue
            keys = [str(k) for k in category.get("keys") or []]
            for athlete in category.get("athletes") or []:
                person = athlete.get("athlete") or {}
                espn_id = str(person.get("id") or "")
                if not espn_id:
                    continue
                entry = lines.setdefault(
                    espn_id,
                    {"name": person.get("displayName") or espn_id, "team": team, "components": {}},
                )
                stats = athlete.get("stats") or []
                for key, value in zip(keys, stats):
                    component = mapping.get(key)
                    if component:
                        components = entry["components"]
                        components[component] = components.get(component, 0.0) + _num(value)
    return [
        LiveLine(
            espn_id=espn_id,
            name=str(entry["name"]),
            team=str(entry["team"]),
            event_id=event_id,
            components=entry["components"],
        )
        for espn_id, entry in lines.items()
    ]


class EspnLiveProvider:
    """Scoreboard plus a box score for every game that has kicked off."""

    name = "espn-live"

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        scoreboard_url: str = ESPN_SCOREBOARD_URL,
        summary_url: str = ESPN_SUMMARY_URL,
    ) -> None:
        self._client = client or JsonHttpClient(provider_name=self.name)
        self._scoreboard_url = scoreboard_url
        self._summary_url = summary_url

    def fetch_week(self, season: int, week: int) -> LiveWeek:
        """Blocking. Call from a worker thread, never from the event loop."""
        result = LiveWeek()
        try:
            payload = self._client.get_json(
                self._scoreboard_url, {"dates": season, "seasontype": 2, "week": week}
            )
        except Exception as exc:
            logger.warning("%s: scoreboard %s week %s failed: %s", self.name, season, week, exc)
            result.warnings.append(f"scoreboard unavailable: {exc}")
            return result

        result.games = parse_scoreboard(payload)
        started = [game for game in result.games if game.state in ("in", "post")]

        def box(game: LiveGame) -> list[LiveLine]:
            summary = self._client.get_json(self._summary_url, {"event": game.event_id})
            return parse_boxscore(summary, game.event_id)

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
            futures = {game.event_id: pool.submit(box, game) for game in started}
            for event_id, future in futures.items():
                try:
                    result.lines.extend(future.result())
                except Exception as exc:
                    logger.warning("%s: box score %s failed: %s", self.name, event_id, exc)
                    result.warnings.append(f"box score for game {event_id} unavailable")
        return result
