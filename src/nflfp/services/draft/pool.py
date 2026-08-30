"""The board: who can be drafted, what they are worth, and what is missing.

A draft pool is the one place in this package that touches a database, and it
exists to turn two very different reads — a published weekly board and ten
seasons of completed player-weeks — into a single sequence of plain frozen
dataclasses that the engine can run against without a session, a clock or a
network.

Why the board is week 1 and not "the season"
--------------------------------------------
There is no season-long projection in this system. The frozen model projects one
week from a trailing four-game usage window, and weeks 2-18 of a season are not
projectable before weeks 1-17 have happened — the feature layer has no row for a
game that has not been played. Building a season projection would mean building
a second model, which the frozen-foundation rule forbids and which would compete
with the one that has been validated.

Week 1 is also the one week of a season that is projectable *before the season
starts*, because its trailing window is the tail of the season before. That is
what makes an upcoming season draftable at all: :mod:`nflfp.features.preseason`
assembles those rows from the coming season's schedule and rosters, and a
published run over them reaches this module as an ordinary board. The pool does
not know or care which it was handed — the one visible difference is that a
board for an unplayed season has no rookies on it at all, and the notice below
says so whichever season is drafted.

So the published **week 1** board of the drafted season supplies a *rate*:
``expected_points`` for week 1 is read as this player's projected points in a
game they play. That run is fitted only on data strictly before week 1 of its
season — ``generate.py`` asserts it row by row — so it is exactly the
information a manager has on draft day and nothing more.

Season value is then::

    season_value = projected_points_per_game x expected_games_played

with the second factor coming from :mod:`~nflfp.services.draft.history`. The
multiplication is the whole methodology: the model's number is never averaged
with a historical one, only scaled by a quantity the model does not estimate.

What this means, stated because a user deserves it
--------------------------------------------------
Treating week 1's projection as a season-long rate assumes a player's role is
roughly the shape it is in week 1. It is a *rate at draft time*, not a forecast
of how a season unfolds — no injury, no trade, no breakout mid-season is in it.
:attr:`DraftPool.notices` carries that sentence, and the API puts it in
``meta.notices`` where a client cannot render the board without it.

Who is missing, and why that is declared rather than hidden
-----------------------------------------------------------
Two groups of real draftable players are absent, and both are absent for
structural reasons the product must state:

* **Kickers and team defences**, which have no projection model at all. Handled
  by the position registry, refused at configuration time, explained in the UI.
* **Rookies and anyone with no prior usage.** The model's features are a
  trailing four-game window; a player who has never played has no window and so
  gets no projection and no pool entry. In a real draft rookies go early and
  often, so this is a material gap — not a rounding error — and
  :attr:`DraftPool.notices` says so in as many words.

Neither is patched with an invented number.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .. import assemble, repository
from ..dto import ModelRef, PlayerRef
from ..errors import NoProjectionsPublished
from . import history
from .history import (
    AvailabilityPrior,
    HistoricalEvidence,
    HistoricalSeason,
)
from .settings import DraftSettings

logger = logging.getLogger(__name__)

#: The week whose published board supplies the per-game rate. Week 1 is the only
#: week that is knowable before a season starts, which is the point.
DRAFT_BOARD_WEEK = 1

#: Seasons of completed production the pool loads. Three feeds the trend and the
#: history card; the availability panel benefits from more, and gets it, because
#: the same query serves both.
PANEL_SEASONS = 6


@dataclass(frozen=True)
class DraftPlayer:
    """One draftable player, with every number the engine needs and its origin.

    The engine reads :attr:`season_value` and nothing else about worth. Every
    other field exists so a recommendation can be explained in terms of the
    quantities that produced it, which is what
    :mod:`~nflfp.services.draft.engine` builds its reasons from.

    Attributes:
        player: The player dimension entry.
        position: Normalised position code.
        team: Team abbreviation at the time of the board.
        projected_points_per_game: ``expected_points`` from the published week 1
            run — ``provenance: model``, and the only model number here.
        expected_games: Estimated games available — ``provenance: derived``.
        season_value: ``projected_points_per_game * expected_games`` —
            ``provenance: derived``.
        floor_per_game / ceiling_per_game: The published P10 and P90 for that
            week — ``provenance: model``. Used to describe risk, never to rank.
        historical: Completed-season evidence, or an empty record.
        extrapolated: The published interval was flagged as outside the fitted
            residual range. Carried through so a card can mark it.
    """

    player: PlayerRef
    position: str
    team: str | None
    projected_points_per_game: float
    expected_games: float
    season_value: float
    floor_per_game: float | None
    ceiling_per_game: float | None
    historical: HistoricalEvidence
    extrapolated: bool = False

    @property
    def player_id(self) -> str:
        return self.player.player_id

    @property
    def name(self) -> str:
        return self.player.name

    @property
    def season_floor(self) -> float | None:
        """A low-side season figure, for describing a pick's downside.

        The published P10 is a *weekly* percentile and multiplying it by a
        season's games would describe a player having their tenth-percentile
        week seventeen times running, which no player has ever done. It is
        therefore labelled a floor **rate** everywhere it is shown, and this
        property exists so that no caller is tempted to multiply it themselves.
        """
        return self.floor_per_game


@dataclass(frozen=True)
class DraftPool:
    """Every draftable player for one league configuration, plus its gaps.

    Attributes:
        players: Draftable players, best season value first.
        season: Season being drafted.
        board_week: Week whose published run supplied the rates.
        scoring_profile: League format.
        model: The published run behind every projected number.
        season_games: Regular-season games the drafted season schedules.
        availability_priors: The fitted per-position shrinkage priors, exposed
            so the estimate can be audited rather than taken on faith.
        history_seasons: Completed seasons the evidence was built from.
        notices: Sentences a client is obliged to surface with the board.
    """

    players: tuple[DraftPlayer, ...]
    season: int
    board_week: int
    scoring_profile: str
    model: ModelRef | None
    season_games: int
    availability_priors: Mapping[str, AvailabilityPrior]
    history_seasons: tuple[int, ...]
    notices: tuple[str, ...]

    def by_position(self, position: str) -> tuple[DraftPlayer, ...]:
        return tuple(p for p in self.players if p.position == position)

    @property
    def positions(self) -> tuple[str, ...]:
        seen: list[str] = []
        for player in self.players:
            if player.position not in seen:
                seen.append(player.position)
        return tuple(seen)

    def index(self) -> dict[str, DraftPlayer]:
        return {player.player_id: player for player in self.players}


async def build_pool(session: AsyncSession, settings: DraftSettings) -> DraftPool:
    """Assemble the draft pool for a league configuration.

    Three reads, none of them per-player: the published week 1 board, the
    completed-season panel, and the schedule's games-per-season. Everything
    after that is arithmetic on rows already in memory.

    Args:
        session: Open async session.
        settings: Validated league configuration.

    Returns:
        The pool, ordered by season value.

    Raises:
        NoProjectionsPublished: when the drafted season has no published week 1
            run. This is an operational state, not a client error — the season
            exists and the projection job has simply never covered it — and the
            API answers it with the reason and the command that fixes it.
    """
    season = settings.season
    positions = settings.draftable_positions

    rows = await repository.fetch_projections(
        session,
        season=season,
        week=DRAFT_BOARD_WEEK,
        scoring_profile=settings.scoring_profile,
        positions=positions,
    )
    if not rows:
        raise NoProjectionsPublished(
            season, DRAFT_BOARD_WEEK, scoring_profile=settings.scoring_profile
        )

    panel = await repository.fetch_season_totals(
        session,
        before_season=season,
        seasons_back=PANEL_SEASONS,
        scoring_profile=settings.scoring_profile,
        positions=positions,
    )
    history.assert_no_future_seasons(panel, season)

    game_counts = await repository.fetch_season_game_counts(session)
    season_games = game_counts.get(season) or max(game_counts.values(), default=17)

    pool = assemble_pool(
        board_rows=rows,
        panel_rows=panel,
        game_counts=game_counts,
        season=season,
        season_games=season_games,
        scoring_profile=settings.scoring_profile,
    )
    logger.info(
        "draft pool for %s: %d player(s) from %d board row(s), %d panel row(s)",
        season, len(pool.players), len(rows), len(panel),
    )
    return pool


def assemble_pool(
    *,
    board_rows: Sequence[Mapping[str, object]],
    panel_rows: Sequence[Mapping[str, object]],
    game_counts: Mapping[int, int],
    season: int,
    season_games: int,
    scoring_profile: str,
) -> DraftPool:
    """Turn raw rows into a pool. Pure, so the whole assembly is testable.

    Split from :func:`build_pool` for the same reason
    :func:`~nflfp.services.simulation.simulate` is split from its retrieval:
    the interesting behaviour — shrinkage, ranking, banding, the leakage guard —
    is arithmetic on rows, and a test that needs Postgres to check that a
    two-season player is shrunk further than a five-season one is a test nobody
    runs.
    """
    history.assert_no_future_seasons(panel_rows, season)

    ranked = history.rank_within_position(panel_rows)
    by_player = _group_panel(panel_rows, game_counts, ranked)

    # The prior is fitted on the *board's* players, not on the whole panel. The
    # panel holds every player who ever recorded a stat line, most of whom are
    # fourth-string and played two games; their availability rate is a fact
    # about depth-chart position, not about durability. Pooling them produces a
    # position prior near 0.45, which then pulls a proven every-week starter
    # down for no reason a football person would accept. Restricting to the
    # players who are actually draftable makes the prior a statement about the
    # reference class the shrinkage is applied to, which is what a prior is
    # supposed to be.
    board_ids = {str(row.get("player_id")) for row in board_rows}
    priors = history.estimate_availability_priors(
        [row for row in panel_rows if str(row.get("player_id")) in board_ids],
        game_counts,
    )

    # Consistency is a *within-position* ranking over the players actually on
    # this board, so it is computed after the board is known and before the
    # players are built. Ranking against the whole panel instead would compare a
    # drafted starter with a fourth-string tight end who played nine games.
    board_ids_by_position: dict[str, dict[str, float | None]] = {}
    for row in board_rows:
        position = _position_of(row)
        player_id = str(row.get("player_id"))
        seasons = by_player.get(player_id, ())
        board_ids_by_position.setdefault(position, {})[player_id] = (
            history.coefficient_of_variation(seasons)
        )

    percentiles: dict[str, float] = {}
    labels: dict[str, str] = {}
    for values in board_ids_by_position.values():
        position_percentiles, position_labels = history.consistency_bands(values)
        percentiles.update(position_percentiles)
        labels.update(position_labels)

    players: list[DraftPlayer] = []
    for row in board_rows:
        player_id = str(row.get("player_id"))
        position = _position_of(row)
        rate = _rate_of(row)
        if rate is None:
            # A published projection with no points row for this profile. Not a
            # draftable entry, and not an error either — it is the same absence
            # `rosters` reports as `no_projection`.
            continue

        seasons = by_player.get(player_id, ())
        games, raw_rate, basis = history.expected_games(
            seasons, priors.get(position), season_games=season_games
        )
        trend, trend_detail = history.describe_trend(seasons)

        evidence = HistoricalEvidence(
            seasons=seasons[:history.HISTORY_SEASONS],
            expected_games=games,
            availability_rate=raw_rate,
            availability_basis=basis,
            seasons_observed=len(seasons),
            consistency_percentile=percentiles.get(player_id),
            consistency_label=labels.get(player_id),
            trend=trend,
            trend_detail=trend_detail,
        )

        players.append(
            DraftPlayer(
                player=assemble.player_ref(row),
                position=position,
                team=_text(row.get("team")),
                projected_points_per_game=rate,
                expected_games=games,
                season_value=rate * games,
                floor_per_game=_float(row.get("floor_points")),
                ceiling_per_game=_float(row.get("ceiling_points")),
                historical=evidence,
                extrapolated=bool(row.get("extrapolated") or False),
            )
        )

    players.sort(key=lambda p: (-p.season_value, p.player_id))
    seasons_held = tuple(
        sorted({int(row["season"]) for row in panel_rows if row.get("season") is not None})
    )

    return DraftPool(
        players=tuple(players),
        season=season,
        board_week=DRAFT_BOARD_WEEK,
        scoring_profile=scoring_profile,
        model=assemble.model_ref(board_rows[0]) if board_rows else None,
        season_games=season_games,
        availability_priors=priors,
        history_seasons=seasons_held,
        notices=_notices(players, seasons_held, season, season_games),
    )


def _notices(
    players: Sequence[DraftPlayer],
    history_seasons: Sequence[int],
    season: int,
    season_games: int,
) -> tuple[str, ...]:
    """Disclosures owed by anything that renders this board."""
    notices: list[str] = [
        f"Season value is the published week {DRAFT_BOARD_WEEK} projection for "
        f"{season} read as a per-game rate and multiplied by an estimated games "
        f"played out of {season_games}. It is a draft-day rate, not a forecast "
        "of how the season unfolds: no in-season injury, trade or role change "
        "is modelled.",
        "Expected games played is estimated from historical availability and "
        "shrunk toward a position prior. It counts weeks in which a player "
        "recorded a stat line, so it cannot separate an injury from a healthy "
        "scratch or a growing role.",
        "No rookies are on this board, and the gap is a large one. The model "
        "projects from a trailing four-game usage window; a player who has "
        "never played has no window, so the incoming class is absent entirely "
        "rather than ranked low. Real drafts spend the first five rounds on "
        "it. Two things follow: every pick after the first round lands on a "
        "player a real draft would have taken earlier, and the late rounds "
        "look deeper than they are. This is the veteran board, and a real "
        "draft from the same seat will be harder than this one.",
    ]
    if not history_seasons:
        notices.append(
            "No completed seasons were available before "
            f"{season}, so every availability estimate is the position prior "
            "alone and no consistency or trend is reported."
        )
    else:
        notices.append(
            "Historical evidence covers "
            f"{min(history_seasons)}-{max(history_seasons)}. Nothing from "
            f"{season} is used: a draft is decided before the season starts."
        )
    no_history = sum(
        1 for p in players if p.historical.availability_basis == "position_prior"
    )
    if no_history:
        notices.append(
            f"{no_history} of {len(players)} players have no completed-season "
            "history in the window, so their expected games is the position "
            "prior rather than their own record."
        )
    return tuple(notices)


def _group_panel(
    panel_rows: Sequence[Mapping[str, object]],
    game_counts: Mapping[int, int],
    ranked: Mapping[tuple[str, int], tuple[int, float]],
) -> dict[str, tuple[HistoricalSeason, ...]]:
    """Index the panel by player, most recent season first."""
    grouped: dict[str, list[HistoricalSeason]] = {}
    for row in panel_rows:
        player_id = str(row.get("player_id"))
        season = int(row["season"])  # type: ignore[index,arg-type]
        games = int(row.get("games_played") or 0)
        rank, percentile = ranked.get((player_id, season), (None, None))
        grouped.setdefault(player_id, []).append(
            HistoricalSeason(
                season=season,
                games_played=games,
                team_games=int(game_counts.get(season, 17)),
                total_points=float(row.get("total_points") or 0.0),
                points_per_game=float(row.get("points_per_game") or 0.0),
                weekly_stdev=_float(row.get("weekly_stdev")),
                position_rank=rank,
                position_percentile=percentile,
            )
        )
    return {
        player_id: tuple(sorted(seasons, key=lambda s: s.season, reverse=True))
        for player_id, seasons in grouped.items()
    }


def _position_of(row: Mapping[str, object]) -> str:
    return str(row.get("position") or "").strip().upper()


def _rate_of(row: Mapping[str, object]) -> float | None:
    """The per-game rate: ``expected_points``, never ``predicted_points``.

    ``expected`` is the mean of the held-out distribution and the calibrated
    number; ``predicted`` is the raw model output and is conditionally biased by
    construction. The README documents ``predicted`` as not-for-display and this
    is a display, so the fallback is deliberately absent — a row with no
    expected value is skipped rather than ranked on a number known to be biased.
    """
    return _float(row.get("expected_points"))


def _float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
