"""Business-layer dataclasses to wire schemas.

The one place where a projection is split into its three provenance blocks.
Doing it here rather than in the service layer keeps the football free of
presentation concerns, and doing it in one function rather than per-router
means no endpoint can accidentally emit a projection whose weather panel has
lost its ``applied_to_projection`` flag.
"""

from __future__ import annotations

from ..services import dto, simulation
from . import schemas
from .provenance import Provenance


def player(ref: dto.PlayerRef) -> schemas.PlayerOut:
    return schemas.PlayerOut.model_validate(ref)


def team(ref: dto.TeamRef) -> schemas.TeamOut:
    return schemas.TeamOut.model_validate(ref)


def season(availability: dto.SeasonAvailability) -> schemas.SeasonOut:
    return schemas.SeasonOut(
        season=availability.season,
        published_weeks=list(availability.published_weeks),
        latest_published_week=availability.latest_published_week,
    )


def model_ref(ref: dto.ModelRef | None) -> schemas.ModelRefOut | None:
    return None if ref is None else schemas.ModelRefOut.model_validate(ref)


def points(distribution: dto.PointDistribution) -> schemas.PointsOut:
    return schemas.PointsOut(
        expected=distribution.expected,
        predicted=distribution.predicted,
        floor=distribution.floor,
        p25=distribution.p25,
        median=distribution.median,
        p75=distribution.p75,
        ceiling=distribution.ceiling,
        standard_deviation=distribution.standard_deviation,
        confidence=distribution.confidence,
        confidence_label=distribution.confidence_label,
        boom_probability=distribution.boom_probability,
        bust_probability=distribution.bust_probability,
        boom_threshold=distribution.boom_threshold,
        bust_threshold=distribution.bust_threshold,
        shape=distribution.shape,
        extrapolated=distribution.extrapolated,
        samples=distribution.samples,
        calibration_method=distribution.calibration_method,
    )


def game_context(context: dto.GameContext) -> schemas.GameContextOut:
    return schemas.GameContextOut(
        applied_to_projection=context.applied_to_projection,
        unapplied_reason=context.unapplied_reason,
        game_id=context.game_id,
        season=context.season,
        week=context.week,
        team=context.team,
        opponent=context.opponent,
        is_home=context.is_home,
        gameday=context.gameday,
        team_spread=context.team_spread,
        total_line=context.total_line,
        implied_team_total=context.implied_team_total,
        implied_opponent_total=context.implied_opponent_total,
        spread_movement=context.spread_movement,
        spread_source=context.spread_source,
        odds_book=context.odds_book,
        odds_captured_at=context.odds_captured_at,
        rest_days=context.rest_days,
        rest_advantage=context.rest_advantage,
        divisional=context.divisional,
    )


def weather(context: dto.WeatherContext) -> schemas.WeatherOut:
    return schemas.WeatherOut(
        applied_to_projection=context.applied_to_projection,
        unapplied_reason=context.unapplied_reason,
        multiplier=context.multiplier,
        is_indoor=context.is_indoor,
        temperature_f=context.temperature_f,
        wind_mph=context.wind_mph,
        wind_gust_mph=context.wind_gust_mph,
        precipitation_probability=context.precipitation_probability,
        snowfall_in=context.snowfall_in,
        roof_uncertain=context.roof_uncertain,
        source=context.source,
        captured_at=context.captured_at,
        is_adverse=context.is_adverse,
    )


def injury(context: dto.InjuryContext) -> schemas.InjuryOut:
    return schemas.InjuryOut(
        applied_to_projection=context.applied_to_projection,
        unapplied_reason=context.unapplied_reason,
        multiplier=context.multiplier,
        report_status=context.report_status,
        practice_status=context.practice_status,
        detail=context.detail,
        will_not_play=context.will_not_play,
        is_questionable_or_worse=context.is_questionable_or_worse,
    )


def matchup(context: dto.MatchupContext) -> schemas.MatchupOut:
    return schemas.MatchupOut(
        applied_to_projection=False,
        opponent=context.opponent,
        is_home=context.is_home,
        grade=schemas.matchup_grade_out(context.grade),
        fp_allowed_vs_position_l4=context.fp_allowed_vs_position_l4,
        targets_allowed_l4=context.targets_allowed_l4,
        carries_allowed_l4=context.carries_allowed_l4,
        defense_rank_overall=context.defense_rank_overall,
        opponent_pace_l4=context.opponent_pace_l4,
    )


def projection(source: dto.PlayerProjection) -> schemas.ProjectionOut:
    """Split one projection into model / derived / context.

    The three blocks are always present in the response even when their
    contents are empty, so a client's rendering code does not branch on
    whether a key exists — only on whether a value inside it is null.
    """
    return schemas.ProjectionOut(
        player=player(source.player),
        season=source.season,
        week=source.week,
        team=source.team,
        opponent=source.opponent,
        is_home=source.is_home,
        game_id=source.game_id,
        prediction=schemas.PredictionOut(
            provenance=Provenance.MODEL,
            scoring_profile=source.points.scoring_profile,
            points=points(source.points),
            components=schemas.ComponentsOut.model_validate(source.components),
            model=model_ref(source.model),
        ),
        usage=schemas.UsageOut.model_validate(source.usage),
        matchup=matchup(source.matchup) if source.matchup else None,
        context=schemas.ContextOut(
            game=game_context(source.game) if source.game else None,
            weather=weather(source.weather) if source.weather else None,
            injury=injury(source.injury) if source.injury else None,
        ),
    )


def ranked(entry: dto.RankedProjection) -> schemas.RankedProjectionOut:
    return schemas.RankedProjectionOut(
        rank=entry.rank,
        positional_rank=entry.positional_rank,
        tier=entry.tier,
        projection=projection(entry.projection),
    )


def historical_week(week: dto.HistoricalWeek) -> schemas.HistoricalWeekOut:
    return schemas.HistoricalWeekOut.model_validate(week)


def profile(source: dto.PlayerProfile) -> schemas.PlayerProfileOut:
    return schemas.PlayerProfileOut(
        player=player(source.player),
        scoring_profile=source.scoring_profile,
        current=projection(source.current) if source.current else None,
        history=[historical_week(week) for week in source.history],
        trend=schemas.TrendOut.model_validate(source.trend),
    )


def comparison_entry(entry: dto.ComparisonEntry) -> schemas.ComparisonEntryOut:
    return schemas.ComparisonEntryOut(
        projection=projection(entry.projection),
        expected=entry.expected,
        floor=entry.floor,
        ceiling=entry.ceiling,
        win_probability=entry.win_probability,
    )


def start_sit(advice: dto.StartSitAdvice) -> schemas.StartSitOut:
    return schemas.StartSitOut(
        a=comparison_entry(advice.a),
        b=comparison_entry(advice.b),
        win_probability=advice.win_probability,
        expected_margin=advice.expected_margin,
        verdict=advice.verdict,
        recommended=advice.recommended,
        rationale=list(advice.rationale),
        caveats=list(advice.caveats),
    )


def comparison(source: dto.Comparison) -> schemas.ComparisonOut:
    return schemas.ComparisonOut(
        season=source.season,
        week=source.week,
        scoring_profile=source.scoring_profile,
        entries=[comparison_entry(entry) for entry in source.entries],
        head_to_head=[start_sit(advice) for advice in source.head_to_head],
    )


def position_matchup(source: dto.PositionMatchup) -> schemas.PositionMatchupOut:
    return schemas.PositionMatchupOut(
        position=source.position,
        grade=schemas.matchup_grade_out(source.grade),
        fp_allowed_l4=source.fp_allowed_l4,
        targets_allowed_l4=source.targets_allowed_l4,
        carries_allowed_l4=source.carries_allowed_l4,
        yards_allowed_l4=source.yards_allowed_l4,
    )


def matchup_analysis(source: dto.MatchupAnalysis) -> schemas.MatchupAnalysisOut:
    return schemas.MatchupAnalysisOut(
        game_id=source.game_id,
        season=source.season,
        week=source.week,
        home=team(source.home),
        away=team(source.away),
        context=schemas.ContextOut(
            game=game_context(source.game) if source.game else None,
            weather=weather(source.weather) if source.weather else None,
        ),
        defense={
            abbr: [position_matchup(entry) for entry in entries]
            for abbr, entries in source.defense.items()
        },
        top_projections=[ranked(entry) for entry in source.top_projections],
    )


def team_outlook(source: dto.TeamOutlook) -> schemas.TeamOutlookOut:
    return schemas.TeamOutlookOut(
        team=team(source.team),
        season=source.season,
        week=source.week,
        scoring_profile=source.scoring_profile,
        context=schemas.ContextOut(
            game=game_context(source.game) if source.game else None,
            weather=weather(source.weather) if source.weather else None,
        ),
        players=[ranked(entry) for entry in source.players],
        projected_points=source.projected_points,
    )


def simulated_player(source: simulation.SimulatedPlayer) -> schemas.SimulatedPlayerOut:
    return schemas.SimulatedPlayerOut(
        player_id=source.player_id,
        name=source.name,
        slot=source.slot,
        position=source.position,
        team=source.team,
        game_id=source.game_id,
        expected_points=source.expected_points,
        floor=source.floor,
        ceiling=source.ceiling,
        simulated_mean=source.simulated_mean,
    )


def team_simulation(source: simulation.TeamSimulation) -> schemas.TeamSimulationOut:
    return schemas.TeamSimulationOut(
        expected_score=source.expected_score,
        median_score=source.median_score,
        p10=source.p10,
        p25=source.p25,
        p75=source.p75,
        p90=source.p90,
        win_probability=source.win_probability,
        loss_probability=source.loss_probability,
        tie_probability=source.tie_probability,
        projection_sum=source.projection_sum,
        players=[simulated_player(entry) for entry in source.players],
    )


def matchup_simulation(
    source: simulation.MatchupSimulation,
) -> schemas.MatchupSimulationOut:
    """Split a simulation into its run metadata, two derived team blocks, and
    its assumptions.

    The team blocks are ``derived``, not ``model``, even though every number in
    them descends from model output. A simulation is a calculation performed
    above the model, and labelling its output ``model`` would extend the
    foundation's measured guarantees — interval coverage, calibration,
    conditional bias — to a quantity that was never measured against a held-out
    residual.
    """
    return schemas.MatchupSimulationOut(
        season=source.season,
        week=source.week,
        scoring_profile=source.scoring_profile,
        simulation=schemas.SimulationRunOut(
            iterations=source.iterations,
            seed=source.seed,
            sampling_method=source.assumptions.sampling_method,
            correlation_mode=source.assumptions.correlation_mode,
            correlation_model_version=source.assumptions.correlation_model_version,
            lineup_format=source.lineup_format,
            model=model_ref(source.model),
        ),
        team_a=team_simulation(source.team_a),
        team_b=team_simulation(source.team_b),
        score_differential=source.score_differential,
        median_differential=source.median_differential,
        assumptions=schemas.SimulationAssumptionsOut(
            player_independence=source.assumptions.player_independence,
            kicker_projection_available=source.assumptions.kicker_projection_available,
            defense_projection_available=source.assumptions.defense_projection_available,
            injury_adjustment_applied=source.assumptions.injury_adjustment_applied,
            matchup_adjustment_applied=source.assumptions.matchup_adjustment_applied,
            weather_adjustment_applied=source.assumptions.weather_adjustment_applied,
            correlation_mode=source.assumptions.correlation_mode,
            correlation_model_version=source.assumptions.correlation_model_version,
            notes=list(source.assumptions.notes()),
        ),
    )


def week(summary: dict) -> schemas.WeekOut:
    """Map the week summary. A plain dict from the service, like `game`."""
    return schemas.WeekOut(
        season=int(summary["season"]),
        week=int(summary["week"]),
        games=[game(row) for row in summary["games"]],
        game_count=int(summary["game_count"]),
        completed_games=int(summary["completed_games"]),
        upcoming_games=int(summary["upcoming_games"]),
        projections_published=bool(summary["projections_published"]),
        projection_count=int(summary["projection_count"]),
        model=model_ref(summary["model"]),
    )


def game(row: dict) -> schemas.GameOut:
    """Map a raw schedule row. Games have no derived content, so no DTO."""
    return schemas.GameOut(
        game_id=str(row["game_id"]),
        season=int(row["season"]),
        week=int(row["week"]),
        gameday=row.get("gameday"),
        home_team=str(row["home_team"]),
        away_team=str(row["away_team"]),
        home_score=row.get("home_score"),
        away_score=row.get("away_score"),
        home_spread=row.get("home_spread"),
        total_line=row.get("total_line"),
        is_upcoming=bool(row.get("is_upcoming")),
    )
