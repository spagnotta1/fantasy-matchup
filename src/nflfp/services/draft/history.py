"""What a player has actually demonstrated, and how it is allowed to be used.

This module is the answer to a question the frozen foundation does not answer
and was never asked to: *how many games is this player likely to be available
for, how steady have they been, and which way are they trending?* The model
projects a week conditional on the player taking the field. It has no view on
whether they will, because availability is not in
``feat_training_dataset`` and never was.

The division of labour, restated because it is the thing most easily blurred
-----------------------------------------------------------------------------
============================  =========================  ==================
quantity                      source                     provenance
============================  =========================  ==================
points per game               published projection       ``model``
season totals, games, weekly  ``player_week``            ``actual``
  spread of past seasons
expected games played         shrunk from the above      ``derived``
consistency band, trend       ranked from the above      ``derived``
============================  =========================  ==================

Nothing in this module changes a projected points-per-game. History multiplies
the rate through availability and describes the risk around it; it is never
averaged into it. A player who scored 300 points last season and is projected
for 11 points per game is projected for 11 points per game here too.

Shrinkage, and why the constant is not a constant
-------------------------------------------------
A player with one observed season is not evidence of an availability rate; a
player with six is. Layer 3b already settled how this codebase resolves that
tension — empirical Bayes, ``shrunk = (n*player + k*prior) / (n + k)``, with
``k = sigma^2_within / sigma^2_between`` estimated from the data rather than
chosen. The same estimator is used here, on the availability panel, per
position:

* ``sigma^2_between`` is the variance across players of their mean availability;
* ``sigma^2_within`` is the mean across players of the variance of their own
  seasons.

``k`` then reads as *the number of seasons of evidence the position prior is
worth*, and nothing is hand-tuned. This is the same **estimator** as
``shrinkage_eb``, applied to a different quantity; it is emphatically not a
second projection model, and it never touches a projected point.

Leakage
-------
Every function here takes a ``before_season`` and refuses to look at or past it.
A draft for season S is a decision made before week 1 of season S, so seasons
< S are available and season S is not — not its actuals, not its totals, not its
rank. :func:`assert_no_future_seasons` is called on the way in rather than
trusted to the query, because the query is one place this could go wrong and the
consequence is a backtest that reports a strategy discovering players it could
not have known about.

What availability actually measures, and does not
-------------------------------------------------
``games_played / team_games`` counts weeks in which the player recorded a stat
line. It does not distinguish an injury from a healthy scratch, a benching, a
suspension or a late-season call-up, because ``player_week`` cannot: a row
exists when a player appeared and does not exist otherwise. So this is a
**historical availability rate**, which is what it is called throughout, and not
an injury forecast. A player whose role grew mid-season is penalised by it. That
limitation travels with the number.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

#: Seasons of history a player card shows and the trend is computed over. Three
#: is where the year-over-year signal is still about the same player: beyond it
#: a running back's fourth season back is describing a different athlete.
HISTORY_SEASONS = 3

#: Minimum games in a season before its weekly spread is treated as a measure of
#: consistency rather than of sample size. Below this the standard deviation of
#: four games is mostly noise and would label genuinely steady players erratic.
MIN_GAMES_FOR_CONSISTENCY = 8

#: Availability rate assigned when a position has no usable panel at all — an
#: impossible state with a loaded warehouse, and a defined one rather than a
#: division by zero.
FALLBACK_AVAILABILITY = 0.8

#: Bounds on ``k``. The estimator can produce absurd values when a position's
#: between-player variance is near zero (every quarterback plays every game),
#: and an unbounded ``k`` would shrink a ten-season veteran to the prior. The
#: clamp is on the estimator's output, not a replacement for it.
MIN_K = 0.5
MAX_K = 12.0


@dataclass(frozen=True)
class HistoricalSeason:
    """One completed season of a player's actual production.

    Every field here is a recorded outcome — ``provenance: actual``. Nothing is
    projected, smoothed or filled.
    """

    season: int
    games_played: int
    team_games: int
    total_points: float
    points_per_game: float
    #: Standard deviation of the player's weekly scores, or ``None`` below
    #: :data:`MIN_GAMES_FOR_CONSISTENCY` games.
    weekly_stdev: float | None
    #: Rank within position by total points that season, 1-based.
    position_rank: int | None = None
    #: Where that rank falls among players at the position who played that
    #: season, 0-1, higher is better.
    position_percentile: float | None = None

    @property
    def availability(self) -> float | None:
        if self.team_games <= 0:
            return None
        return min(1.0, self.games_played / self.team_games)


@dataclass(frozen=True)
class HistoricalEvidence:
    """Everything history says about one player, and how firmly it says it.

    Attributes:
        seasons: Up to :data:`HISTORY_SEASONS` completed seasons, most recent
            first. Empty for a player with no prior production.
        expected_games: Games the player is estimated to be available for in the
            drafted season. Shrunk toward the position prior — ``derived``.
        availability_rate: The player's own unshrunk rate, or ``None`` with no
            history. Kept beside the shrunk figure so a UI can show both and a
            reader can see how much of the estimate is the player and how much
            is the prior.
        availability_basis: ``"player_history"`` when the player contributed
            seasons, ``"position_prior"`` when the estimate is entirely the
            prior. The flag a card branches on rather than inferring from a
            count.
        consistency_percentile: Where the player's most recent qualifying
            season's coefficient of variation ranks among the pool at their
            position, 0-1, higher meaning steadier. ``None`` when no season
            qualified.
        consistency_label: ``"High"``/``"Moderate"``/``"Low"``, or ``None``.
            Bands are percentile cuts within position, so the label is always a
            relative claim and never an absolute one.
        trend: ``"rising"``/``"steady"``/``"declining"``, or ``None`` below two
            comparable seasons.
        trend_detail: The sentence behind the arrow, built from the actual
            percentile movement.
    """

    seasons: tuple[HistoricalSeason, ...]
    expected_games: float
    availability_rate: float | None
    availability_basis: str
    seasons_observed: int
    consistency_percentile: float | None = None
    consistency_label: str | None = None
    trend: str | None = None
    trend_detail: str | None = None

    @property
    def prior_season(self) -> HistoricalSeason | None:
        return self.seasons[0] if self.seasons else None

    @property
    def prior_season_points(self) -> float | None:
        season = self.prior_season
        return season.total_points if season else None


class LeakageError(AssertionError):
    """A historical row at or after the season being drafted reached the engine.

    An assertion rather than a service error: this cannot be caused by a
    request, only by a query or a test fixture that is wrong, and it must fail
    loudly in every environment rather than degrade into a slightly optimistic
    backtest.
    """


def assert_no_future_seasons(rows: Iterable[Mapping[str, object]], before_season: int) -> None:
    """Refuse any historical row from ``before_season`` or later.

    Called on the boundary of every path that turns rows into evidence. The
    check is cheap and the failure it prevents is invisible: a draft for 2025
    that quietly knew 2025's results would rank players almost perfectly and
    report a spectacular, meaningless backtest.
    """
    for row in rows:
        season = row.get("season")
        if season is not None and int(season) >= before_season:  # type: ignore[arg-type]
            raise LeakageError(
                f"historical row for season {season} reached a draft for season "
                f"{before_season}; only seasons strictly before it are available "
                "at draft time"
            )


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AvailabilityPrior:
    """The shrinkage prior for one position, estimated from the panel.

    Reported rather than hidden because it is the thing a sceptical reader
    should be able to check: ``k`` seasons of prior, a prior rate, and the
    sample both came from.
    """

    position: str
    prior_rate: float
    k: float
    players: int
    seasons: int


def estimate_availability_priors(
    panel: Sequence[Mapping[str, object]],
    game_counts: Mapping[int, int],
) -> dict[str, AvailabilityPrior]:
    """Fit the per-position availability prior from a player-season panel.

    Args:
        panel: Rows with ``player_id``, ``position``, ``season`` and
            ``games_played``, covering seasons strictly before the drafted one.
        game_counts: ``season -> regular-season games``, the denominator. Passed
            in rather than read off the panel row because it is a property of
            the schedule, not of the player, and a season that expands from 16
            games to 17 must change it in exactly one place.

    Returns:
        One :class:`AvailabilityPrior` per position present in the panel.

    The variance decomposition uses only players with at least two seasons,
    because a single season contributes nothing to ``sigma^2_within`` and
    including it would inflate ``sigma^2_between`` with pure sampling noise —
    which shows up as a ``k`` near zero and a shrinkage that does nothing.
    """
    by_position: dict[str, dict[str, list[float]]] = {}
    for row in panel:
        position = str(row.get("position") or "").strip().upper()
        season = row.get("season")
        if not position or season is None:
            continue
        team_games = int(game_counts.get(int(season), 0))  # type: ignore[arg-type]
        if team_games <= 0:
            continue
        rate = min(1.0, int(row.get("games_played") or 0) / team_games)
        player_id = str(row.get("player_id"))
        by_position.setdefault(position, {}).setdefault(player_id, []).append(rate)

    priors: dict[str, AvailabilityPrior] = {}
    for position, players in by_position.items():
        means = [statistics.fmean(rates) for rates in players.values()]
        repeated = [rates for rates in players.values() if len(rates) >= 2]

        prior_rate = statistics.fmean(means) if means else FALLBACK_AVAILABILITY

        between = (
            statistics.pvariance([statistics.fmean(r) for r in repeated])
            if len(repeated) >= 2
            else 0.0
        )
        within = (
            statistics.fmean([statistics.variance(r) for r in repeated])
            if repeated
            else 0.0
        )

        if between > 1e-9 and within > 0.0:
            k = min(MAX_K, max(MIN_K, within / between))
        else:
            # No usable between-player signal: every player at this position
            # looks the same, so the prior should dominate. MAX_K says exactly
            # that, and says it explicitly rather than by dividing by zero.
            k = MAX_K

        priors[position] = AvailabilityPrior(
            position=position,
            prior_rate=prior_rate,
            k=k,
            players=len(players),
            seasons=sum(len(rates) for rates in players.values()),
        )
    return priors


def expected_games(
    seasons: Sequence[HistoricalSeason],
    prior: AvailabilityPrior | None,
    *,
    season_games: int,
) -> tuple[float, float | None, str]:
    """Shrink a player's availability toward the position prior.

    Args:
        seasons: The player's completed seasons, most recent first.
        prior: The position's fitted prior, or ``None`` if the position had no
            panel at all.
        season_games: Regular-season games the drafted season schedules.

    Returns:
        ``(expected_games, raw_rate, basis)``. ``raw_rate`` is ``None`` when the
        player contributed no seasons, in which case ``basis`` is
        ``"position_prior"`` and the figure is the prior alone.
    """
    prior_rate = prior.prior_rate if prior else FALLBACK_AVAILABILITY
    k = prior.k if prior else MAX_K

    rates = [
        rate for rate in (season.availability for season in seasons) if rate is not None
    ]
    if not rates:
        return prior_rate * season_games, None, "position_prior"

    n = len(rates)
    raw = statistics.fmean(rates)
    shrunk = (n * raw + k * prior_rate) / (n + k)
    return shrunk * season_games, raw, "player_history"


# ---------------------------------------------------------------------------
# Consistency and trend
# ---------------------------------------------------------------------------


def coefficient_of_variation(seasons: Sequence[HistoricalSeason]) -> float | None:
    """Weekly spread relative to weekly level, from the most recent qualifying season.

    Relative rather than absolute, because a standard deviation of six points
    means something very different for a player averaging eight than for one
    averaging twenty-two, and a draft board holds both. ``None`` when no season
    reached :data:`MIN_GAMES_FOR_CONSISTENCY`.
    """
    for season in seasons:
        if (
            season.games_played >= MIN_GAMES_FOR_CONSISTENCY
            and season.weekly_stdev is not None
            and season.points_per_game > 0
        ):
            return season.weekly_stdev / season.points_per_game
    return None


def consistency_bands(
    values: Mapping[str, float | None],
) -> tuple[dict[str, float], dict[str, str]]:
    """Rank coefficients of variation within a group and band them.

    Args:
        values: ``player_id -> coefficient of variation``, ``None`` for players
            with no qualifying season. The caller passes one position at a time.

    Returns:
        ``(percentile, label)`` maps, containing only the players who had a
        value. Percentile is 0-1 with **1 meaning steadiest** — the ranking is
        inverted relative to the coefficient, because a reader expects a high
        consistency number to be good.

    Bands are terciles of the ranked group. That makes "High consistency" a
    claim about this player relative to others at their position in this pool,
    which is a claim the data supports; an absolute threshold would be a claim
    about football that nothing here has measured.
    """
    scored = {pid: value for pid, value in values.items() if value is not None}
    if not scored:
        return {}, {}

    ordered = sorted(scored.items(), key=lambda item: item[1])
    n = len(ordered)
    percentiles: dict[str, float] = {}
    labels: dict[str, str] = {}
    for index, (player_id, _) in enumerate(ordered):
        # Lowest coefficient of variation is steadiest, so it earns the highest
        # percentile. With one player the percentile is 1.0 and the label is the
        # top band, which is honest — they are the steadiest of the one player
        # measured — and the UI shows the sample beside it.
        percentile = 1.0 if n == 1 else 1.0 - index / (n - 1)
        percentiles[player_id] = percentile
        labels[player_id] = (
            "High" if percentile >= 2 / 3 else "Moderate" if percentile >= 1 / 3 else "Low"
        )
    return percentiles, labels


#: Percentile points of year-over-year movement below which a player is called
#: steady rather than rising or falling. Ten points on a within-position
#: percentile is roughly three or four places at the top of a board — small
#: enough to be one injury or one schedule, which is not a trend.
TREND_THRESHOLD = 0.10


def describe_trend(seasons: Sequence[HistoricalSeason]) -> tuple[str | None, str | None]:
    """Direction of a player's within-position standing, and the sentence for it.

    Compares the most recent season's percentile with the mean of the earlier
    ones held. Requires two seasons that both carry a percentile; below that the
    honest answer is that there is no trend to report, and ``None`` is returned
    rather than "steady", which would assert stability that has not been
    observed.
    """
    ranked = [s for s in seasons if s.position_percentile is not None]
    if len(ranked) < 2:
        return None, None

    latest = ranked[0]
    earlier = ranked[1:]
    baseline = statistics.fmean(
        [s.position_percentile for s in earlier]  # type: ignore[misc]
    )
    delta = latest.position_percentile - baseline  # type: ignore[operator]

    seasons_text = ", ".join(str(s.season) for s in earlier)
    moved = f"{abs(delta) * 100:.0f} percentile points"
    if delta >= TREND_THRESHOLD:
        return (
            "rising",
            f"Finished {moved} higher within {latest.season} than their "
            f"{seasons_text} average.",
        )
    if delta <= -TREND_THRESHOLD:
        return (
            "declining",
            f"Finished {moved} lower within {latest.season} than their "
            f"{seasons_text} average.",
        )
    return (
        "steady",
        f"Within-position standing moved less than "
        f"{TREND_THRESHOLD * 100:.0f} percentile points between {seasons_text} "
        f"and {latest.season}.",
    )


def rank_within_position(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, int], tuple[int, float]]:
    """Rank every player-season by total points inside its (position, season).

    Returns ``(player_id, season) -> (rank, percentile)``. Percentile is
    ``1 - (rank - 1) / (n - 1)``, so the leader is 1.0. Computed here rather
    than in SQL so that the ranking is over exactly the rows the engine holds,
    which is what makes it reproducible from a fixture without a database.
    """
    grouped: dict[tuple[str, int], list[tuple[str, float]]] = {}
    for row in rows:
        position = str(row.get("position") or "").strip().upper()
        season = row.get("season")
        if not position or season is None:
            continue
        grouped.setdefault((position, int(season)), []).append(  # type: ignore[arg-type]
            (str(row.get("player_id")), float(row.get("total_points") or 0.0))
        )

    ranked: dict[tuple[str, int], tuple[int, float]] = {}
    for (_, season), entries in grouped.items():
        entries.sort(key=lambda item: item[1], reverse=True)
        n = len(entries)
        for index, (player_id, _) in enumerate(entries):
            rank = index + 1
            percentile = 1.0 if n == 1 else 1.0 - index / (n - 1)
            ranked[(player_id, season)] = (rank, percentile)
    return ranked
