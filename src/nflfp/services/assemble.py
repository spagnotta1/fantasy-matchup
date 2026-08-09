"""Turning database rows into domain objects, with no database in sight.

Every function here is **pure**: rows in, dataclasses out, no session, no I/O,
no clock. That is what makes the interesting parts of the business layer
testable without Postgres — the tier boundaries, the grade thresholds, the
fallbacks when a feature view has a hole in it — which are precisely the parts
where a mistake is silent and expensive.

The split is: :mod:`nflfp.services.repository` knows SQL and nothing about
football; this module knows football and nothing about SQL; the service modules
compose the two and own nothing but the composition.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence

from . import grading
from .distributions import probability_beats
from .dto import (
    GameContext,
    HistoricalWeek,
    InjuryContext,
    MatchupContext,
    ModelRef,
    PlayerProjection,
    PlayerRef,
    PointDistribution,
    ProjectedComponents,
    RankedProjection,
    TeamRef,
    TrendSummary,
    UsageOutlook,
    WeatherContext,
)
from .positions import PROJECTED_POSITIONS

Row = Mapping[str, object]

#: Positions a published model covers, derived from the support registry so
#: that adding a kicker model is one entry there and nothing here. Asserted
#: against ``nflfp.predict.base.POSITIONS`` in the tests rather than imported,
#: so the business layer does not take a dependency on the prediction engine to
#: answer a question about its own request validation.
SUPPORTED_POSITIONS: tuple[str, ...] = PROJECTED_POSITIONS

#: Below this probability, the next player down is no longer a realistic
#: alternative to the one above and a tier boundary is drawn. 0.45 rather than
#: 0.50 because consecutive players are almost always within a coin flip of each
#: other; a 0.50 threshold would put every player in their own tier and say
#: nothing.
TIER_BREAK_PROBABILITY = 0.45


# ---------------------------------------------------------------------------
# Small field readers
# ---------------------------------------------------------------------------


def as_float(row: Row, key: str) -> float | None:
    """Read a column as a float, preserving SQL ``NULL`` as ``None``.

    Postgres hands back ``Decimal`` for ``numeric`` aggregates and ``int`` for
    counts, and a dataclass typed ``float | None`` that sometimes holds a
    ``Decimal`` serialises differently depending on which query filled it. These
    four readers are where that gets normalised, once.
    """
    value = row.get(key)
    return None if value is None else float(value)  # type: ignore[arg-type]


def as_int(row: Row, key: str) -> int | None:
    """Read a column as an int, preserving SQL ``NULL`` as ``None``."""
    value = row.get(key)
    return None if value is None else int(value)  # type: ignore[arg-type]


def as_str(row: Row, key: str) -> str | None:
    """Read a column as a string, preserving SQL ``NULL`` as ``None``."""
    value = row.get(key)
    return None if value is None else str(value)


def as_bool(row: Row, key: str) -> bool | None:
    """Read a column as a bool, preserving SQL ``NULL`` as ``None``.

    The ``None`` case matters: ``is_home`` being unknown because a game has no
    schedule row is a different fact from a player being on the road.
    """
    value = row.get(key)
    return None if value is None else bool(value)


# Terse aliases for the mapping functions below, which read a lot of columns.
_f, _i, _s, _b = as_float, as_int, as_str, as_bool


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def player_ref(row: Row) -> PlayerRef:
    """Build a player reference, tolerating a missing dimension row.

    The name falls back to the id rather than to ``None``. A projection whose
    player row has not landed yet — a mid-week signing, a practice-squad
    elevation — should still appear on the board as *something*, because the
    projection itself is valid and a hole in a list is harder to notice than an
    ugly label.
    """
    player_id = str(row.get("player_id"))
    return PlayerRef(
        player_id=player_id,
        name=_s(row, "player_name") or _s(row, "display_name") or player_id,
        position=_s(row, "position"),
        team=_s(row, "team") or _s(row, "latest_team"),
        jersey_number=_i(row, "jersey_number"),
        status=_s(row, "status"),
        headshot_url=_s(row, "headshot"),
        years_of_experience=_i(row, "years_of_experience"),
        college=_s(row, "college_name"),
    )


def team_ref(row: Row | None, abbr: str | None = None) -> TeamRef:
    """Build a team reference, or a bare one from just an abbreviation."""
    if row is None:
        return TeamRef(abbr=abbr or "")
    return TeamRef(
        abbr=str(row.get("team_abbr") or abbr or ""),
        name=_s(row, "team_name"),
        nickname=_s(row, "team_nick"),
        conference=_s(row, "team_conf"),
        division=_s(row, "team_division"),
        primary_color=_s(row, "team_color"),
        secondary_color=_s(row, "team_color2"),
        logo_url=_s(row, "team_logo_espn") or _s(row, "team_logo_wikipedia"),
    )


def model_ref(row: Row) -> ModelRef | None:
    """Build the lineage reference from a joined ``model_runs`` row."""
    run_id = _i(row, "model_run_id")
    if run_id is None:
        return None
    return ModelRef(
        run_id=run_id,
        model_name=_s(row, "model_name") or "unknown",
        model_version=_s(row, "model_version") or "unknown",
        algorithm=_s(row, "algorithm") or "unknown",
        feature_schema_version=_i(row, "feature_schema_version") or 0,
        published_at=row.get("published_at"),  # type: ignore[arg-type]
        code_sha=_s(row, "code_sha"),
    )


# ---------------------------------------------------------------------------
# Projection parts
# ---------------------------------------------------------------------------


def point_distribution(row: Row) -> PointDistribution:
    """Map a ``projection_points`` row onto its domain object.

    The two derived labels — confidence and shape — are attached here rather
    than computed by every caller, which is what keeps the thresholds in
    :mod:`nflfp.services.grading` genuinely single-sourced.
    """
    extrapolated = bool(row.get("extrapolated") or False)
    confidence = _f(row, "confidence")
    median = _f(row, "median_points")
    p25 = _f(row, "p25_points")
    p75 = _f(row, "p75_points")
    return PointDistribution(
        scoring_profile=str(row.get("scoring_profile") or ""),
        expected=_f(row, "expected_points"),
        predicted=_f(row, "predicted_points") or 0.0,
        floor=_f(row, "floor_points"),
        p25=p25,
        median=median,
        p75=p75,
        ceiling=_f(row, "ceiling_points"),
        standard_deviation=_f(row, "standard_deviation"),
        confidence=confidence,
        confidence_label=grading.confidence_label(confidence, extrapolated=extrapolated),
        boom_probability=_f(row, "boom_probability"),
        bust_probability=_f(row, "bust_probability"),
        boom_threshold=_f(row, "boom_threshold"),
        bust_threshold=_f(row, "bust_threshold"),
        shape=grading.outcome_shape(p25=p25, median=median, p75=p75),
        extrapolated=extrapolated,
        samples=_i(row, "distribution_samples"),
        calibration_method=_s(row, "calibration_method"),
    )


def projected_components(row: Row) -> ProjectedComponents:
    """Map the ``proj_*`` columns onto their domain object."""
    return ProjectedComponents(
        targets=_f(row, "proj_targets"),
        receptions=_f(row, "proj_receptions"),
        carries=_f(row, "proj_carries"),
        pass_attempts=_f(row, "proj_pass_attempts"),
        passing_yards=_f(row, "proj_passing_yards"),
        passing_tds=_f(row, "proj_passing_tds"),
        interceptions=_f(row, "proj_interceptions"),
        rushing_yards=_f(row, "proj_rushing_yards"),
        rushing_tds=_f(row, "proj_rushing_tds"),
        receiving_yards=_f(row, "proj_receiving_yards"),
        receiving_tds=_f(row, "proj_receiving_tds"),
    )


def usage_outlook(row: Row) -> UsageOutlook:
    """Map the lagged usage columns of ``feat_training_dataset``."""
    return UsageOutlook(
        snap_pct_l4=_f(row, "snap_pct_l4"),
        target_share_l4=_f(row, "target_share_l4"),
        targets_l4=_f(row, "targets_l4"),
        carries_l4=_f(row, "carries_l4"),
        receptions_l4=_f(row, "receptions_l4"),
        opportunities_l4=_f(row, "opportunities_l4"),
        air_yards_share_l4=_f(row, "air_yards_share_l4"),
        wopr_l4=_f(row, "wopr_l4"),
        snap_pct_trend=_f(row, "snap_pct_trend"),
        target_share_trend=_f(row, "target_share_trend"),
        snap_pct_season=_f(row, "snap_pct_season"),
        games_played_season=_i(row, "games_played_season"),
        games_in_window=_i(row, "games_in_window_l4"),
        fp_l4=_f(row, "fp_half_ppr_l4"),
        fp_season=_f(row, "fp_half_ppr_season"),
        fp_volatility_l4=_f(row, "fp_volatility_l4"),
    )


def matchup_context(row: Row) -> MatchupContext:
    """Grade the opponent matchup from the joined defensive rolling views."""
    grade = grading.grade_matchup(
        defense_rank=_i(row, "opp_defense_rank_vs_position"),
        sample_games=_i(row, "opp_defense_games_in_window"),
        stored_score=_f(row, "matchup_score"),
    )
    return MatchupContext(
        opponent=_s(row, "opponent"),
        is_home=_b(row, "is_home"),
        grade=grade,
        fp_allowed_vs_position_l4=_f(row, "opp_fp_allowed_vs_position_l4"),
        targets_allowed_l4=_f(row, "opp_targets_allowed_l4"),
        carries_allowed_l4=_f(row, "opp_carries_allowed_l4"),
        defense_rank_overall=_i(row, "opp_defense_rank_overall"),
        opponent_pace_l4=_f(row, "opp_pace_l4"),
    )


def game_context(row: Row) -> GameContext:
    """Map schedule and market context. Never applied to the projection."""
    return GameContext(
        game_id=_s(row, "game_id"),
        season=int(row["season"]),  # type: ignore[arg-type]
        week=int(row["week"]),  # type: ignore[arg-type]
        team=_s(row, "team"),
        opponent=_s(row, "opponent"),
        is_home=_b(row, "is_home"),
        kickoff=row.get("kickoff"),  # type: ignore[arg-type]
        gameday=row.get("gameday"),  # type: ignore[arg-type]
        team_spread=_f(row, "team_spread"),
        total_line=_f(row, "total_line"),
        implied_team_total=_f(row, "implied_team_total"),
        implied_opponent_total=_f(row, "implied_opp_total"),
        spread_movement=_f(row, "spread_movement"),
        spread_source=_s(row, "spread_source"),
        odds_book=_s(row, "odds_book"),
        odds_captured_at=row.get("odds_captured_at"),  # type: ignore[arg-type]
        rest_days=_i(row, "rest_days"),
        rest_advantage=_i(row, "rest_advantage"),
        divisional=_b(row, "div_game"),
        unapplied_reason=MARKET_UNAPPLIED_REASON,
    )


#: Why an observed condition is reported but not applied. Sourced from the
#: frozen foundation's own record so the API's explanation and the model's
#: documentation cannot drift apart.
WEATHER_UNAPPLIED_REASON = (
    "The frozen model excludes weather. History carries observed conditions "
    "while upcoming games carry forecasts, so training and serving would see "
    "different objects; measured against the baseline's residual, weather "
    "added nothing. Reported here as context for your own judgement."
)
INJURY_UNAPPLIED_REASON = (
    "The frozen model applies no injury adjustment. The designation is an "
    "official pre-kickoff fact and is reported verbatim; a projection for a "
    "player listed Out describes a player who will not take the field."
)
MARKET_UNAPPLIED_REASON = (
    "The frozen model excludes market features. Correlation with the lagged "
    "baseline's residual measured -0.039 to +0.021 across positions over "
    "2019-2025 — the raw relationship is confounded by good players playing "
    "on good offences."
)


def weather_context(row: Row) -> WeatherContext:
    """Map forecast conditions and whether the engine used them.

    ``weather_multiplier`` is ``NULL`` under the frozen foundation, so this
    reports context with an explicit reason. The read is unconditional, which
    is the whole extension point: an engine that starts writing the column
    flips ``applied_to_projection`` here with no further change.
    """
    multiplier = _f(row, "weather_multiplier")
    return WeatherContext(
        is_indoor=_b(row, "is_indoor"),
        temperature_f=_f(row, "temperature_f"),
        wind_mph=_f(row, "wind_mph"),
        wind_gust_mph=_f(row, "wind_gust_mph"),
        precipitation_probability=_f(row, "precipitation_probability"),
        snowfall_in=_f(row, "snowfall_in"),
        roof_uncertain=bool(row.get("roof_uncertain") or False),
        source=_s(row, "weather_source"),
        captured_at=row.get("weather_captured_at"),  # type: ignore[arg-type]
        multiplier=multiplier,
        applied_to_projection=multiplier is not None,
        unapplied_reason=None if multiplier is not None else WEATHER_UNAPPLIED_REASON,
    )


def injury_context(row: Row) -> InjuryContext:
    """Map the official injury report and whether the engine used it."""
    multiplier = _f(row, "injury_multiplier")
    return InjuryContext(
        report_status=_s(row, "injury_report_status"),
        practice_status=_s(row, "injury_practice_status"),
        detail=_s(row, "injury_detail"),
        multiplier=multiplier,
        applied_to_projection=multiplier is not None,
        unapplied_reason=None if multiplier is not None else INJURY_UNAPPLIED_REASON,
    )


def player_projection(row: Row) -> PlayerProjection:
    """Assemble one fully-populated projection from a joined result row.

    A single row carries the projection, its points, its lineage and whatever
    context the feature layer had. Context sub-objects are omitted rather than
    filled with nulls when the join produced nothing, so "we have no market for
    this game" and "the spread is zero" stay distinguishable.
    """
    season = int(row["season"])  # type: ignore[arg-type]
    week = int(row["week"])  # type: ignore[arg-type]

    has_matchup = row.get("opp_defense_rank_vs_position") is not None or (
        row.get("matchup_score") is not None
    )
    has_game = row.get("game_id") is not None
    # A block is present when there is either something observed *or* an
    # adjustment the engine applied. The multiplier has to count on its own:
    # a healthy player carries no injury designation, and if only the
    # designation made the block appear, an applied adjustment would vanish
    # from the response for exactly the players it was applied to.
    has_weather = (
        row.get("weather_source") not in (None, "none")
        or row.get("weather_multiplier") is not None
    )
    has_injury = (
        row.get("injury_report_status") is not None
        or row.get("injury_practice_status") is not None
        or row.get("injury_multiplier") is not None
    )

    return PlayerProjection(
        player=player_ref(row),
        season=season,
        week=week,
        team=_s(row, "team"),
        opponent=_s(row, "opponent"),
        is_home=_b(row, "is_home"),
        game_id=_s(row, "game_id"),
        points=point_distribution(row),
        components=projected_components(row),
        usage=usage_outlook(row),
        matchup=matchup_context(row) if has_matchup else None,
        game=game_context(row) if has_game else None,
        weather=weather_context(row) if has_weather else None,
        injury=injury_context(row) if has_injury else None,
        model=model_ref(row),
    )


# ---------------------------------------------------------------------------
# Ranking and tiering
# ---------------------------------------------------------------------------


def _sort_key(projection: PlayerProjection) -> tuple[float, float, str]:
    """Order a board.

    Primary key is the calibrated expectation. The tie-break is the ceiling,
    then the player id — the last one purely so the ordering is total and a
    board does not reshuffle between two identical requests.
    """
    headline = projection.points.headline
    ceiling = projection.points.ceiling
    return (
        -(headline if headline is not None else float("-inf")),
        -(ceiling if ceiling is not None else float("-inf")),
        projection.player.player_id,
    )


def assign_tiers(
    projections: Sequence[PlayerProjection],
    *,
    break_probability: float = TIER_BREAK_PROBABILITY,
) -> list[int]:
    """Group an ordered board into tiers using the projected distributions.

    A tier continues while the next player down still has at least
    ``break_probability`` chance of outscoring the player above them. That
    turns a tier boundary into a statement with a meaning — "these two are not
    interchangeable" — rather than a fixed points gap, which would produce
    enormous tiers at the top of a board and singleton tiers at the bottom
    purely because scoring is heteroscedastic.

    Players without a usable distribution fall back to a points-gap rule, so a
    board is never left untiered because one row is thin.

    Args:
        projections: Already sorted best-first.
        break_probability: Threshold below which a tier ends.

    Returns:
        One 1-based tier number per input projection, in the same order.
    """
    if not projections:
        return []

    curves = [p.points.curve() for p in projections]

    tiers = [1]
    tier = 1
    for index in range(1, len(projections)):
        above, below = curves[index - 1], curves[index]
        if above is not None and below is not None:
            keeps_pace = probability_beats(below, above) >= break_probability
        else:
            # No distribution for one of the pair. Fall back to a points gap
            # scaled by the board's own spread, which is crude but bounded and
            # never silently merges a 20-point player with a 2-point one.
            upper = projections[index - 1].points.headline or 0.0
            lower = projections[index].points.headline or 0.0
            keeps_pace = (upper - lower) < max(1.0, upper * 0.10)
        if not keeps_pace:
            tier += 1
        tiers.append(tier)
    return tiers


def rank_board(
    projections: Sequence[PlayerProjection],
    *,
    break_probability: float = TIER_BREAK_PROBABILITY,
) -> list[RankedProjection]:
    """Sort, rank, tier and positionally rank a set of projections.

    ``positional_rank`` is computed within the returned set, which is the
    behaviour a filtered request wants: asking for the RB board and getting
    ranks 1..N is correct, and asking for a mixed board gives each player their
    rank among their own position.
    """
    ordered = sorted(projections, key=_sort_key)
    tiers = assign_tiers(ordered, break_probability=break_probability)

    seen_by_position: dict[str, int] = {}
    ranked: list[RankedProjection] = []
    for index, projection in enumerate(ordered):
        position = projection.player.position or "UNK"
        seen_by_position[position] = seen_by_position.get(position, 0) + 1
        ranked.append(
            RankedProjection(
                rank=index + 1,
                positional_rank=seen_by_position[position],
                tier=tiers[index],
                projection=projection,
            )
        )
    return ranked


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def historical_week(row: Row, *, points_column: str) -> HistoricalWeek:
    """Map one completed player-week, with the projection made for it if any."""
    actual = _f(row, points_column)
    projected = _f(row, "projected_points")
    return HistoricalWeek(
        season=int(row["season"]),  # type: ignore[arg-type]
        week=int(row["week"]),  # type: ignore[arg-type]
        team=_s(row, "team"),
        opponent=_s(row, "opponent"),
        is_home=_b(row, "is_home"),
        actual_points=actual,
        projected_points=projected,
        error=None if actual is None or projected is None else projected - actual,
        snap_pct=_f(row, "offense_pct"),
        targets=_f(row, "targets"),
        carries=_f(row, "carries"),
        receptions=_f(row, "receptions"),
        receiving_yards=_f(row, "receiving_yards"),
        rushing_yards=_f(row, "rushing_yards"),
        passing_yards=_f(row, "passing_yards"),
        total_tds=sum(
            value
            for value in (
                _f(row, "receiving_tds"),
                _f(row, "rushing_tds"),
                _f(row, "passing_tds"),
            )
            if value is not None
        )
        or None,
        injury_report_status=_s(row, "injury_report_status"),
    )


#: A week under this many points is a bust; at or above the boom line it is a
#: week that won someone their matchup. Position-independent on purpose here —
#: these summarise a *player's* history, and the whole point of the exploration
#: finding TEs bust 48.5% of the time against RBs' 10.1% is that the difference
#: should be visible in the number, not normalised away by a position-specific
#: threshold.
BUST_LINE = 5.0
BOOM_LINE = 20.0


def summarise_history(weeks: Sequence[HistoricalWeek]) -> TrendSummary:
    """Aggregate a player's completed weeks into form and accuracy numbers.

    Accuracy (``mean_absolute_error``, ``bias``) is computed only over weeks
    that actually carried a stored projection, and ``graded_games`` reports how
    many those were. Averaging error over weeks with no projection would silently
    report a better model than exists.
    """
    scored = [w.actual_points for w in weeks if w.actual_points is not None]
    errors = [w.error for w in weeks if w.error is not None]

    return TrendSummary(
        games=len(scored),
        mean_points=statistics.fmean(scored) if scored else None,
        median_points=statistics.median(scored) if scored else None,
        standard_deviation=statistics.stdev(scored) if len(scored) > 1 else None,
        boom_rate=(
            sum(1 for p in scored if p >= BOOM_LINE) / len(scored) if scored else None
        ),
        bust_rate=(
            sum(1 for p in scored if p < BUST_LINE) / len(scored) if scored else None
        ),
        mean_absolute_error=(
            statistics.fmean([abs(e) for e in errors]) if errors else None
        ),
        bias=statistics.fmean(errors) if errors else None,
        graded_games=len(errors),
    )
