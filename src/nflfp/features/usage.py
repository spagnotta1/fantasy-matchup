"""Player usage features and the assembled model-ready dataset.

Usage is the signal
-------------------
The exploratory work in the README is what shapes this module. Over 2016-2025,
snap share correlates 0.62-0.71 with weekly points for RBs and QBs and target
share 0.71-0.73 for WRs and TEs — and, crucially, usage *persists* year over
year (0.63-0.73) while efficiency essentially does not (0.16-0.23).

That asymmetry has a direct consequence for feature design: project
**opportunity** and regress **efficiency** toward a prior. So the rolling
windows here are deliberately asymmetric — 4 games for usage, which is stable
enough to trust recent form, and a longer 8-game window for efficiency, which is
mostly noise and needs the extra sample to mean anything.

Everything is lagged
--------------------
Every window ends at the previous week. The correlations quoted above are
*same-week* and therefore measure description, not prediction; a model fed
same-week usage would look extraordinary in validation and be unusable on a
Thursday, because Sunday's snap count does not exist yet.
"""

from __future__ import annotations

from .base import REGISTRY, FeatureView, lagged_window

# Partitioned by player only, *not* by (player, season) — so a Week 1 window
# carries the tail of the previous season. That is deliberate: last December is
# information genuinely available in September, and it is the difference
# between a Week 1 slate with features and one without (verified: 298 of 338
# Week 1 2024 rows get a usage history this way). It is defensible precisely
# because usage is the thing that persists year over year (r = 0.63-0.73).
#
# The defensive views take the opposite decision and reset each season, because
# a defence is a unit that turns over in the offseason in a way a player's role
# does not. Both choices are asserted in tests so neither drifts by accident.
_U = lagged_window("player_id", "season, week", preceding=4)
_E = lagged_window("player_id", "season, week", preceding=8)
_SEASON = (
    "OVER (PARTITION BY player_id, season ORDER BY season, week "
    "ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)"
)


PLAYER_USAGE = REGISTRY.register(
    FeatureView(
        name="feat_player_usage",
        requires=("player_week",),
        unique_index=("player_id", "season", "week"),
        indexes=(
            ("slate", ("season", "week", "position")),
            ("team", ("team", "season", "week")),
        ),
        description=(
            "Lagged rolling usage, efficiency and production per player-week. "
            "Every window ends one week back, so every row is usable on the "
            "Thursday before the game it describes."
        ),
        sql=f"""
    SELECT
        pw.player_id,
        pw.player_name,
        pw.position,
        pw.season,
        pw.week,
        pw.team,
        pw.opponent,
        pw.game_id,

        -- ---- lagged usage (4 games) ---------------------------------------
        AVG(pw.offense_pct)   {_U} AS snap_pct_l4,
        AVG(pw.target_share)  {_U} AS target_share_l4,
        AVG(pw.targets)       {_U} AS targets_l4,
        AVG(pw.carries)       {_U} AS carries_l4,
        AVG(pw.receptions)    {_U} AS receptions_l4,
        AVG(pw.attempts)      {_U} AS pass_attempts_l4,
        AVG(pw.air_yards_share) {_U} AS air_yards_share_l4,
        AVG(pw.wopr)          {_U} AS wopr_l4,
        AVG(COALESCE(pw.carries, 0) + COALESCE(pw.targets, 0)) {_U} AS opportunities_l4,
        -- How many games the lagged window actually covers (0-4). The evidence
        -- weight for shrinkage: a 4-game average and a 1-game average are not
        -- equally trustworthy, and the model must be able to tell them apart.
        COUNT(*)              {_U} AS games_in_window_l4,

        -- ---- lagged production --------------------------------------------
        AVG(pw.fp_half_ppr)   {_U} AS fp_half_ppr_l4,
        AVG(pw.fp_ppr)        {_U} AS fp_ppr_l4,
        AVG(pw.fp_standard)   {_U} AS fp_standard_l4,
        STDDEV_SAMP(pw.fp_half_ppr) {_U} AS fp_volatility_l4,
        MAX(pw.fp_half_ppr)   {_U} AS fp_ceiling_l4,
        MIN(pw.fp_half_ppr)   {_U} AS fp_floor_l4,

        -- ---- lagged production components (4 games) -------------------------
        -- The predictors a component-space model needs. Touchdowns especially:
        -- they are 6 points each and the noisiest thing a player does, so a
        -- model that cannot see recent scoring cannot regress it sensibly.
        AVG(pw.receiving_yards) {_U} AS receiving_yards_l4,
        AVG(pw.rushing_yards)   {_U} AS rushing_yards_l4,
        AVG(pw.passing_yards)   {_U} AS passing_yards_l4,
        AVG(pw.receiving_tds)   {_U} AS receiving_tds_l4,
        AVG(pw.rushing_tds)     {_U} AS rushing_tds_l4,
        AVG(pw.passing_tds)     {_U} AS passing_tds_l4,
        AVG(pw.passing_interceptions) {_U} AS passing_interceptions_l4,
        AVG(pw.fumbles_lost_total)    {_U} AS fumbles_lost_l4,
        AVG(pw.special_teams_tds)     {_U} AS special_teams_tds_l4,
        AVG(pw.passing_2pt_conversions)   {_U} AS passing_2pt_conversions_l4,
        AVG(pw.rushing_2pt_conversions)   {_U} AS rushing_2pt_conversions_l4,
        AVG(pw.receiving_2pt_conversions) {_U} AS receiving_2pt_conversions_l4,

        -- ---- lagged efficiency (8 games) -----------------------------------
        -- Longer window on purpose: efficiency barely persists (r ~= 0.2), so
        -- a 4-game efficiency average is mostly noise.
        AVG(pw.receiving_yards) {_E} AS receiving_yards_l8,
        AVG(pw.rushing_yards)   {_E} AS rushing_yards_l8,
        AVG(pw.passing_yards)   {_E} AS passing_yards_l8,
        AVG(pw.receiving_epa)   {_E} AS receiving_epa_l8,
        AVG(pw.rushing_epa)     {_E} AS rushing_epa_l8,
        AVG(pw.passing_epa)     {_E} AS passing_epa_l8,

        -- ---- season-to-date -----------------------------------------------
        AVG(pw.fp_half_ppr)  {_SEASON} AS fp_half_ppr_season,
        AVG(pw.offense_pct)  {_SEASON} AS snap_pct_season,
        COUNT(*)             {_SEASON} AS games_played_season,

        -- ---- trend: is usage rising or falling? ----------------------------
        -- Most recent game minus the 4-game average. Positive means a player
        -- whose role is expanding, which a flat average hides.
        LAG(pw.offense_pct)  OVER (PARTITION BY pw.player_id ORDER BY pw.season, pw.week)
            AS snap_pct_prev,
        LAG(pw.target_share) OVER (PARTITION BY pw.player_id ORDER BY pw.season, pw.week)
            AS target_share_prev,

        -- ---- availability --------------------------------------------------
        pw.injury_report_status,
        pw.injury_practice_status,

        -- ---- the target variables (NULL for unplayed games) ----------------
        -- Present so the same view serves training and inference. A training
        -- query filters to rows where these are set; inference reads the rows
        -- where they are NULL.
        --
        -- Components as well as points, because the model predicts components
        -- and derives points from them. Names match nflfp.scoring's
        -- COMPONENT_FIELDS so a predicted row and an actual row can be scored
        -- by the same function.
        pw.targets                  AS targets_actual,
        pw.carries                  AS carries_actual,
        pw.receptions               AS receptions_actual,
        pw.attempts                 AS pass_attempts_actual,
        pw.receiving_yards          AS receiving_yards_actual,
        pw.rushing_yards            AS rushing_yards_actual,
        pw.passing_yards            AS passing_yards_actual,
        pw.receiving_tds            AS receiving_tds_actual,
        pw.rushing_tds              AS rushing_tds_actual,
        pw.passing_tds              AS passing_tds_actual,
        pw.passing_interceptions    AS passing_interceptions_actual,
        pw.fumbles_lost_total       AS fumbles_lost_actual,
        pw.special_teams_tds        AS special_teams_tds_actual,
        pw.passing_2pt_conversions  AS passing_2pt_conversions_actual,
        pw.rushing_2pt_conversions  AS rushing_2pt_conversions_actual,
        pw.receiving_2pt_conversions AS receiving_2pt_conversions_actual,

        pw.fp_half_ppr AS fp_half_ppr_actual,
        pw.fp_ppr      AS fp_ppr_actual,
        pw.fp_standard AS fp_standard_actual
    FROM player_week AS pw
    WHERE pw.season_type = 'REG'
      AND pw.position IN ('QB', 'RB', 'WR', 'TE')
        """,
    )
)


TRAINING_DATASET = REGISTRY.register(
    FeatureView(
        name="feat_training_dataset",
        requires=(
            "feat_player_usage",
            "feat_game_context",
            "feat_defense_position_rolling",
            "feat_defense_rolling",
        ),
        unique_index=("player_id", "season", "week"),
        indexes=(
            ("slate", ("season", "week", "position")),
            ("target", ("season", "week", "fp_half_ppr_actual")),
        ),
        description=(
            "The assembled model-ready table: one row per player-week with "
            "lagged usage, game context and opponent strength already joined. "
            "The prediction engine reads this and nothing below it."
        ),
        sql="""
    SELECT
        u.player_id,
        u.player_name,
        u.position,
        u.season,
        u.week,
        u.team,
        u.opponent,
        u.game_id,

        -- usage
        u.snap_pct_l4,
        u.target_share_l4,
        u.targets_l4,
        u.carries_l4,
        u.receptions_l4,
        u.pass_attempts_l4,
        u.air_yards_share_l4,
        u.wopr_l4,
        u.opportunities_l4,
        u.snap_pct_season,
        u.games_played_season,
        u.games_in_window_l4,
        u.snap_pct_l4 - u.snap_pct_prev      AS snap_pct_trend,
        u.target_share_l4 - u.target_share_prev AS target_share_trend,

        -- production and volatility
        u.fp_half_ppr_l4,
        u.fp_half_ppr_season,
        u.fp_volatility_l4,
        u.fp_ceiling_l4,
        u.fp_floor_l4,

        -- lagged production components (the component model's predictors)
        u.receiving_yards_l4,
        u.rushing_yards_l4,
        u.passing_yards_l4,
        u.receiving_tds_l4,
        u.rushing_tds_l4,
        u.passing_tds_l4,
        u.passing_interceptions_l4,
        u.fumbles_lost_l4,
        u.special_teams_tds_l4,
        u.passing_2pt_conversions_l4,
        u.rushing_2pt_conversions_l4,
        u.receiving_2pt_conversions_l4,

        -- efficiency
        u.receiving_yards_l8,
        u.rushing_yards_l8,
        u.passing_yards_l8,
        u.receiving_epa_l8,
        u.rushing_epa_l8,
        u.passing_epa_l8,

        -- game context
        c.is_home,
        c.div_game,
        c.rest_days,
        c.rest_advantage,
        c.team_spread,
        c.total_line,
        c.implied_team_total,
        c.implied_opp_total,
        c.spread_movement,
        c.spread_source,
        c.temperature_f,
        c.wind_mph,
        c.precipitation_probability,
        c.is_indoor,
        c.roof_uncertain,
        c.weather_source,

        -- opponent strength for this player's position
        d.fp_allowed_l4                      AS opp_fp_allowed_vs_position_l4,
        d.fp_allowed_rank                    AS opp_defense_rank_vs_position,
        d.targets_allowed_l4                 AS opp_targets_allowed_l4,
        d.carries_allowed_l4                 AS opp_carries_allowed_l4,
        dr.fp_allowed_rank                   AS opp_defense_rank_overall,
        dr.plays_faced_l4                    AS opp_pace_l4,

        -- availability
        u.injury_report_status,
        u.injury_practice_status,

        -- training targets: components and points
        u.targets_actual,
        u.carries_actual,
        u.receptions_actual,
        u.pass_attempts_actual,
        u.receiving_yards_actual,
        u.rushing_yards_actual,
        u.passing_yards_actual,
        u.receiving_tds_actual,
        u.rushing_tds_actual,
        u.passing_tds_actual,
        u.passing_interceptions_actual,
        u.fumbles_lost_actual,
        u.special_teams_tds_actual,
        u.passing_2pt_conversions_actual,
        u.rushing_2pt_conversions_actual,
        u.receiving_2pt_conversions_actual,
        u.fp_half_ppr_actual,
        u.fp_ppr_actual,
        u.fp_standard_actual
    FROM feat_player_usage AS u
    LEFT JOIN feat_game_context AS c
           ON c.game_id = u.game_id AND c.team = u.team
    LEFT JOIN feat_defense_position_rolling AS d
           ON d.season = u.season AND d.week = u.week
          AND d.defteam = u.opponent AND d.position = u.position
    LEFT JOIN feat_defense_rolling AS dr
           ON dr.season = u.season AND dr.week = u.week AND dr.defteam = u.opponent
        """,
    )
)
