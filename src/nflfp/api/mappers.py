"""Business-layer dataclasses to wire schemas.

The one place where a projection is split into its three provenance blocks.
Doing it here rather than in the service layer keeps the football free of
presentation concerns, and doing it in one function rather than per-router
means no endpoint can accidentally emit a projection whose weather panel has
lost its ``applied_to_projection`` flag.
"""

from __future__ import annotations

from ..services import dto, simulation
from ..services.draft import aggregate as draft_aggregate
from ..services.draft import engine as draft_engine
from ..services.draft import pool as draft_pool
from ..services.draft import service as draft_service
from ..services.draft import settings as draft_settings_module
from ..services.draft import valuation as draft_valuation
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


# ---------------------------------------------------------------------------
# Mock draft
# ---------------------------------------------------------------------------
#
# The historical evidence attached to a roster pick is looked up from the pool
# rather than carried on the pick. The engine's SimulatedPick holds only what a
# draft decision needed, and threading six seasons of a player's history through
# ten thousand simulations in order to display fifteen of them would be a great
# deal of copying for a presentation concern.


def draft_settings(settings: draft_settings_module.DraftSettings) -> schemas.DraftSettingsOut:
    return schemas.DraftSettingsOut(
        season=settings.season,
        teams=settings.teams,
        rounds=settings.rounds,
        scoring_profile=settings.scoring_profile,
        draft_format=settings.draft_format,
        roster=[
            schemas.RosterSlotIn(slot=r.slot, count=r.count) for r in settings.roster
        ],
        starters=settings.starters,
        bench=settings.bench,
        simulations=settings.simulations,
        seed=settings.seed,
    )


def historical_evidence(
    evidence: draft_pool.HistoricalEvidence | None,
) -> schemas.HistoricalEvidenceOut | None:
    if evidence is None:
        return None
    return schemas.HistoricalEvidenceOut(
        seasons=[
            schemas.HistoricalSeasonOut(
                season=s.season,
                games_played=s.games_played,
                team_games=s.team_games,
                total_points=s.total_points,
                points_per_game=s.points_per_game,
                weekly_stdev=s.weekly_stdev,
                position_rank=s.position_rank,
                position_percentile=s.position_percentile,
            )
            for s in evidence.seasons
        ],
        seasons_observed=evidence.seasons_observed,
        expected_games=evidence.expected_games,
        availability_rate=evidence.availability_rate,
        availability_basis=evidence.availability_basis,
        consistency_percentile=evidence.consistency_percentile,
        consistency_label=evidence.consistency_label,
        trend=evidence.trend,
        trend_detail=evidence.trend_detail,
    )


def pick_rationale(pick: draft_engine.SimulatedPick) -> schemas.PickRationaleOut | None:
    rationale = pick.rationale
    if rationale is None:
        return None
    return schemas.PickRationaleOut(
        explanation=draft_aggregate.explain_pick(pick.position, pick.name, rationale),
        slot=rationale.slot,
        marginal_value=rationale.marginal_value,
        value_over_next_available=rationale.value_over_next_available,
        expected_next_best_value=rationale.expected_next_best_value,
        next_best_player_id=rationale.next_best_player_id,
        next_best_player_name=rationale.next_best_player_name,
        next_pick_overall=rationale.next_pick_overall,
        survival_at_next_pick=rationale.survival_at_next_pick,
        scarcity=rationale.scarcity,
        tier_index=rationale.tier_index,
        tier_size=rationale.tier_size,
        tier_remaining=rationale.tier_remaining,
        runner_up_id=rationale.runner_up_id,
        runner_up_name=rationale.runner_up_name,
        runner_up_margin=rationale.runner_up_margin,
    )


def value_distribution(
    distribution: draft_aggregate.ValueDistribution,
) -> schemas.ValueDistributionOut:
    return schemas.ValueDistributionOut(
        mean=distribution.mean,
        median=distribution.median,
        stdev=distribution.stdev,
        p10=distribution.p10,
        p25=distribution.p25,
        p75=distribution.p75,
        p90=distribution.p90,
        minimum=distribution.minimum,
        maximum=distribution.maximum,
        observations=distribution.observations,
        standard_error=distribution.standard_error,
    )


def seat_analysis(
    analysis: draft_aggregate.SeatAnalysis,
    history: dict[str, draft_pool.HistoricalEvidence],
) -> schemas.SeatAnalysisOut:
    starters = set(analysis.representative.starters)
    return schemas.SeatAnalysisOut(
        draft_position=analysis.draft_position,
        simulations=analysis.simulations,
        roster_value=value_distribution(analysis.roster_value),
        starter_points=value_distribution(analysis.starter_points),
        picks=list(analysis.picks),
        waits=list(analysis.waits),
        representative_index=analysis.representative_index,
        roster=[
            schemas.SimulatedPickOut(
                overall=pick.overall,
                round_number=pick.round_number,
                player_id=pick.player_id,
                name=pick.name,
                position=pick.position,
                team=pick.team,
                season_value=pick.season_value,
                projected_points_per_game=pick.projected_points_per_game,
                expected_games=pick.expected_games,
                value_over_replacement=pick.value_over_replacement,
                is_starter=pick.player_id in starters,
                rationale=pick_rationale(pick),
                historical=historical_evidence(history.get(pick.player_id)),
            )
            for pick in analysis.representative.picks
        ],
        round_positions=[
            schemas.RoundPositionShareOut(
                round_number=s.round_number, position=s.position, share=s.share
            )
            for s in analysis.round_positions
        ],
        position_strength=[
            schemas.PositionStrengthOut(
                position=s.position,
                mean_starter_points=s.mean_starter_points,
                mean_value_over_replacement=s.mean_value_over_replacement,
                mean_starters=s.mean_starters,
            )
            for s in analysis.position_strength
        ],
        insights=[
            schemas.StrategyInsightOut(
                kind=i.kind,
                headline=i.headline,
                detail=i.detail,
                evidence=dict(i.evidence),
            )
            for i in analysis.insights
        ],
        availability=[
            schemas.PlayerAvailabilityOut(
                player_id=a.player_id,
                name=a.name,
                position=a.position,
                season_value=a.season_value,
                reference_pick=a.reference_pick,
                next_reference_pick=a.next_reference_pick,
                first_pick_probability=a.first_pick_probability,
                next_pick_probability=a.next_pick_probability,
                drafted_before_next_pick=a.drafted_before_next_pick,
                mean_selection_pick=a.mean_selection_pick,
                selected_rate=a.selected_rate,
            )
            for a in analysis.availability
        ],
    )


def draft_pool_summary(summary: draft_service.PoolSummary) -> schemas.DraftPoolOut:
    return schemas.DraftPoolOut(
        players=summary.players,
        positions=list(summary.positions),
        season=summary.season,
        board_week=summary.board_week,
        season_games=summary.season_games,
        history_seasons=list(summary.history_seasons),
        players_without_history=summary.players_without_history,
        rookies_absent=summary.rookies_absent,
        replacement=[
            schemas.ReplacementLevelOut(
                position=level.position,
                starters=level.starters,
                value=level.value,
                player_id=level.player_id,
                flex_share=level.flex_share,
            )
            for level in summary.replacement
        ],
    )


def _methodology(
    *,
    calibration_drafts: int,
    opponents: draft_service.OpponentModel,
    elapsed_seconds: float,
    settings: draft_settings_module.DraftSettings,
) -> schemas.DraftMethodologyOut:
    return schemas.DraftMethodologyOut(
        calibration_drafts=calibration_drafts,
        opponent_skill=opponents.skill.name,
        opponent_skill_label=opponents.skill.label,
        opponent_overrides=list(opponents.overridden),
        board_scatter_ratio=round(opponents.scatter_ratio, 2),
        history_weight=opponents.history_weight,
        noise=opponents.noise,
        elapsed_seconds=elapsed_seconds,
        seed=settings.seed,
        simulations=settings.simulations,
    )


def opponent_skill(
    level: draft_valuation.OpponentSkill, *, is_default: bool
) -> schemas.OpponentSkillOut:
    return schemas.OpponentSkillOut(
        name=level.name,
        label=level.label,
        summary=level.summary,
        history_weight=level.history_weight,
        noise=level.noise,
        scatter=level.scatter,
        strategy_edge=level.strategy_edge,
        is_default=is_default,
    )


def draft_analysis(
    analysis: draft_service.DraftAnalysis,
    history: dict[str, draft_pool.HistoricalEvidence],
) -> schemas.DraftAnalysisOut:
    return schemas.DraftAnalysisOut(
        settings=draft_settings(analysis.settings),
        seat=seat_analysis(analysis.seat, history),
        pool=draft_pool_summary(analysis.pool),
        methodology=_methodology(
            calibration_drafts=analysis.calibration_drafts,
            opponents=analysis.opponents,
            elapsed_seconds=analysis.elapsed_seconds,
            settings=analysis.settings,
        ),
    )


def draft_comparison(
    comparison: draft_service.DraftPositionComparison,
    history: dict[str, draft_pool.HistoricalEvidence],
) -> schemas.DraftComparisonOut:
    return schemas.DraftComparisonOut(
        settings=draft_settings(comparison.settings),
        seats=[
            schemas.SeatSummaryOut(
                draft_position=seat.draft_position,
                roster_value=value_distribution(seat.roster_value),
                starter_points=value_distribution(seat.starter_points),
                percentile=seat.percentile,
                is_best=seat.is_best,
            )
            for seat in comparison.comparison.seats
        ],
        best_position=comparison.comparison.best_position,
        spread=comparison.comparison.spread,
        spread_is_resolvable=comparison.comparison.spread_is_resolvable,
        detail=[seat_analysis(analysis, history) for analysis in comparison.seats],
        pool=draft_pool_summary(comparison.pool),
        methodology=_methodology(
            calibration_drafts=comparison.calibration_drafts,
            opponents=comparison.opponents,
            elapsed_seconds=comparison.elapsed_seconds,
            settings=comparison.settings,
        ),
    )
