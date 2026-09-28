"""What a starter already scored, for a matchup simulated after some games ended.

Provenance: ``actual``. A simulation run on a Sunday evening has two kinds of
player in it: those whose game is still to come, and those whose game is over.
Sampling the second kind from their projected distribution answers a question
nobody is asking — the week is partly decided, and the number that decided it
is on the scoreboard. So a player whose game is **final** enters the simulation
as the points they scored, and only the rest are sampled.

Two sources, in order of authority:

1. **The official line** — ``PlayerProjection.actual_points``, the nflverse stat
   line the pipeline loads once the week is in. Final and correct.
2. **ESPN's box score**, for a game that has ended but whose official line is
   not loaded yet. Scored with this app's own rules, and **unofficial** for the
   same reasons as :mod:`nflfp.services.live`: no two-point conversions, no
   Monday stat correction. Every such number says so.

What is deliberately *not* done:

* **A game in progress is not settled.** A partial score is not a result, and
  the model publishes no "rest of the game" distribution to add it to. Those
  players keep their full projected distribution, and the response says their
  game is under way.
* **No line is not zero.** A player whose game is final but who has no box-score
  line keeps their projection, with a caveat. The line may be missing because
  they recorded no stats, or because they were inactive, or because the id map
  has a gap; recording a zero would collapse the three into one invented number.
* **An upstream failure is a notice.** The simulation still runs, sampling the
  players it could not settle, and says which ones.

Fetching is bounded the way :mod:`nflfp.providers.live` is: the scoreboard is
cached for a minute, and a *final* game's box score for the life of the process
— it does not change until the official line replaces it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from ..providers.live import EspnLiveProvider, LiveGame, LiveLine
from ..scoring import PROFILES, points_for
from . import repository
from .dto import PlayerProjection

logger = logging.getLogger(__name__)

#: How long a scoreboard read is reused. Matches the live endpoint's cache rule.
SCOREBOARD_TTL_SECONDS = 60.0

#: Final box scores kept in memory. A week is sixteen games; this is a few weeks.
MAX_CACHED_BOXES = 64

#: ``FinalScore.source`` values.
SOURCE_OFFICIAL = "official"
SOURCE_LIVE_FINAL = "espn_box_score"


@dataclass(frozen=True)
class FinalScore:
    """What one player scored in a game that is over. Provenance ``actual``."""

    player_id: str
    points: float
    #: ``official`` (the nflverse line) or ``espn_box_score`` (unofficial).
    source: str

    @property
    def official(self) -> bool:
        return self.source == SOURCE_OFFICIAL


@dataclass(frozen=True)
class FinalScores:
    """Which starters are settled, and why each of the others is not."""

    scores: Mapping[str, FinalScore] = field(default_factory=dict)
    #: Players whose game is under way. Sampled in full; the partial is ignored.
    in_progress: tuple[str, ...] = ()
    #: Players whose game is final but who have no box-score line.
    no_line: tuple[str, ...] = ()
    #: Players whose game could not be checked because the upstream failed.
    unchecked: tuple[str, ...] = ()


class LiveScoreSource:
    """The ESPN provider behind a small cache. Blocking calls run in threads."""

    def __init__(
        self,
        provider_factory: Callable[[], EspnLiveProvider] = EspnLiveProvider,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider_factory = provider_factory
        self._provider: EspnLiveProvider | None = None
        self._clock = clock
        self._scoreboards: dict[tuple[int, int], tuple[float, list[LiveGame]]] = {}
        self._boxes: OrderedDict[str, list[LiveLine]] = OrderedDict()

    def _live(self) -> EspnLiveProvider:
        if self._provider is None:
            self._provider = self._provider_factory()
        return self._provider

    async def scoreboard(self, season: int, week: int) -> list[LiveGame]:
        key = (season, week)
        cached = self._scoreboards.get(key)
        now = self._clock()
        if cached is not None and now - cached[0] < SCOREBOARD_TTL_SECONDS:
            return cached[1]
        games = await asyncio.to_thread(self._live().fetch_scoreboard, season, week)
        self._scoreboards[key] = (now, games)
        return games

    async def final_box(self, event_id: str) -> list[LiveLine]:
        """A box score for a game already known to be final. Cached for good."""
        cached = self._boxes.get(event_id)
        if cached is not None:
            self._boxes.move_to_end(event_id)
            return cached
        lines = await asyncio.to_thread(self._live().fetch_box, event_id)
        self._boxes[event_id] = lines
        while len(self._boxes) > MAX_CACHED_BOXES:
            self._boxes.popitem(last=False)
        return lines


_default_source: LiveScoreSource | None = None


def default_source() -> LiveScoreSource:
    """The process-wide source, so its cache is shared across requests."""
    global _default_source
    if _default_source is None:
        _default_source = LiveScoreSource()
    return _default_source


async def resolve(
    session: AsyncSession,
    entries: Sequence[PlayerProjection],
    *,
    season: int,
    week: int,
    scoring_profile: str,
    source: LiveScoreSource | None = None,
) -> FinalScores:
    """Settle every player in ``entries`` whose game is over.

    The official line is used wherever it exists, and ESPN is only asked about
    the players still without one — so a week the pipeline has fully loaded
    makes no upstream call at all.
    """
    scores: dict[str, FinalScore] = {}
    pending: list[PlayerProjection] = []
    for entry in entries:
        if entry.actual_points is not None:
            scores[entry.player.player_id] = FinalScore(
                entry.player.player_id, float(entry.actual_points), SOURCE_OFFICIAL
            )
        elif entry.team:
            pending.append(entry)

    if not pending:
        return FinalScores(scores=scores)

    live = source or default_source()
    try:
        games = await live.scoreboard(season, week)
    except Exception as exc:  # noqa: BLE001 — an outage must not fail the simulation
        logger.warning("final scores: scoreboard %s week %s failed: %s", season, week, exc)
        return FinalScores(
            scores=scores, unchecked=tuple(e.player.player_id for e in pending)
        )

    game_by_team: dict[str, LiveGame] = {}
    for game in games:
        game_by_team[game.home] = game
        game_by_team[game.away] = game

    in_progress: list[str] = []
    finals: dict[str, list[PlayerProjection]] = {}
    for entry in pending:
        game = game_by_team.get(str(entry.team))
        if game is None:
            continue
        if game.state == "in":
            in_progress.append(entry.player.player_id)
        elif game.state == "post":
            finals.setdefault(game.event_id, []).append(entry)

    if not finals:
        return FinalScores(scores=scores, in_progress=tuple(in_progress))

    event_ids = list(finals)
    results = await asyncio.gather(
        *(live.final_box(event_id) for event_id in event_ids), return_exceptions=True
    )
    lines: list[LiveLine] = []
    unchecked: list[str] = []
    for event_id, result in zip(event_ids, results):
        if isinstance(result, BaseException):
            logger.warning("final scores: box score %s failed: %s", event_id, result)
            unchecked.extend(e.player.player_id for e in finals[event_id])
        else:
            lines.extend(result)

    by_player = await _lines_by_player(session, lines)
    rules = PROFILES[scoring_profile]
    no_line: list[str] = []
    for event_id, waiting in finals.items():
        if any(e.player.player_id in unchecked for e in waiting):
            continue
        for entry in waiting:
            player_id = entry.player.player_id
            line = by_player.get(player_id)
            if line is None or line.event_id != event_id:
                no_line.append(player_id)
                continue
            scores[player_id] = FinalScore(
                player_id,
                round(
                    points_for(dict(line.components), rules, entry.player.position or ""), 2
                ),
                SOURCE_LIVE_FINAL,
            )

    return FinalScores(
        scores=scores,
        in_progress=tuple(in_progress),
        no_line=tuple(no_line),
        unchecked=tuple(unchecked),
    )


async def _lines_by_player(
    session: AsyncSession, lines: Sequence[LiveLine]
) -> dict[str, LiveLine]:
    """Box-score lines keyed by gsis id, through the player dimension's espn_id."""
    if not lines:
        return {}
    rows = await repository.fetch_players_by_espn_id(
        session, sorted({line.espn_id for line in lines})
    )
    gsis_by_espn = {str(row["espn_id"]): str(row["player_id"]) for row in rows}
    return {
        gsis_by_espn[line.espn_id]: line for line in lines if line.espn_id in gsis_by_espn
    }
