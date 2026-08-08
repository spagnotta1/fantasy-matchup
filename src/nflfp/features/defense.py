"""Defensive strength features, derived entirely from data already in Postgres.

No new external source, per the brief. Everything here is an aggregation of
``player_week`` viewed from the other side: for a defence D in a given week, the
rows where ``opponent = D`` are exactly what offences did against it.

Three layers, each earning its place:

``feat_defense_game``
    One row per (season, week, defence). Raw allowed totals — the fact table.
``feat_defense_rolling``
    Trailing 4-game averages **excluding the current week**, plus a 1-32 rank
    within the season. This is what a projection actually consumes.
``feat_defense_position``
    Fantasy points allowed split by position, because "good defence" is not one
    number: a front seven that erases running backs may be a smash spot for
    tight ends, and that distinction is most of the value of a matchup feature.

Leakage
-------
``feat_defense_game`` is a same-week aggregate and is **not** safe to feed a
model directly — it describes the game being predicted. Only the rolling view,
whose window ends one week back, is model-ready. The naming makes that visible;
the tests enforce it.

Metrics not available
---------------------
Success rate, explosive-play rate and pressure rate need play-level data.
``raw_pbp`` is an opt-in dataset (``pipeline --all``) and is not loaded by
default, so those features are declared with ``raw_pbp`` in ``requires`` and are
simply skipped until it is. EPA allowed *is* available without it, because
nflverse pre-aggregates per-player EPA onto the weekly stats.
"""

from __future__ import annotations

from .base import REGISTRY, FeatureView, lagged_window

# Half-PPR is the reference format for defensive strength. Using one profile
# keeps the table narrow; the *ranking* a defence gets barely moves between
# formats, and a start/sit decision needs the ordering, not the absolute value.
_FP = "fp_half_ppr"


DEFENSE_GAME = REGISTRY.register(
    FeatureView(
        name="feat_defense_game",
        requires=("player_week",),
        unique_index=("season", "week", "defteam"),
        indexes=(("defteam", ("defteam", "season")),),
        description=(
            "Per-game totals allowed by each defence. Same-week facts: an input "
            "to the rolling view, never a model feature on its own."
        ),
        sql=f"""
    SELECT
        pw.season,
        pw.week,
        pw.opponent                                       AS defteam,
        MAX(pw.game_id)                                   AS game_id,
        MAX(pw.team)                                      AS offteam,

        -- production allowed
        SUM(COALESCE(pw.passing_yards, 0))                AS pass_yards_allowed,
        SUM(COALESCE(pw.rushing_yards, 0))                AS rush_yards_allowed,
        SUM(COALESCE(pw.receiving_yards, 0))              AS rec_yards_allowed,
        SUM(COALESCE(pw.passing_tds, 0))                  AS pass_tds_allowed,
        SUM(COALESCE(pw.rushing_tds, 0))                  AS rush_tds_allowed,
        SUM(COALESCE(pw.receiving_tds, 0))                AS rec_tds_allowed,
        SUM(COALESCE(pw.passing_interceptions, 0))        AS interceptions_forced,
        SUM(COALESCE(pw.receptions, 0))                   AS receptions_allowed,
        SUM(COALESCE(pw.targets, 0))                      AS targets_allowed,
        SUM(COALESCE(pw.carries, 0))                      AS carries_allowed,

        -- EPA allowed. nflverse aggregates EPA per player-week, so this is
        -- available without play-by-play.
        SUM(COALESCE(pw.passing_epa, 0))                  AS pass_epa_allowed,
        SUM(COALESCE(pw.rushing_epa, 0))                  AS rush_epa_allowed,

        -- efficiency: yards per opportunity, the pace-independent version
        CASE WHEN SUM(COALESCE(pw.attempts, 0)) > 0
             THEN SUM(COALESCE(pw.passing_yards, 0)) / SUM(pw.attempts)::numeric
        END                                               AS yards_per_pass_attempt,
        CASE WHEN SUM(COALESCE(pw.carries, 0)) > 0
             THEN SUM(COALESCE(pw.rushing_yards, 0)) / SUM(pw.carries)::numeric
        END                                               AS yards_per_carry,

        SUM(COALESCE(pw.{_FP}, 0))                        AS fp_allowed,
        SUM(COALESCE(pw.attempts, 0)) + SUM(COALESCE(pw.carries, 0)) AS plays_faced
    FROM player_week AS pw
    WHERE pw.season_type = 'REG'
      AND pw.opponent IS NOT NULL
      AND pw.team_score IS NOT NULL   -- completed games only
    GROUP BY pw.season, pw.week, pw.opponent
        """,
    )
)


DEFENSE_POSITION = REGISTRY.register(
    FeatureView(
        name="feat_defense_position",
        requires=("player_week",),
        unique_index=("season", "week", "defteam", "position"),
        indexes=(("lookup", ("defteam", "season", "position")),),
        description=(
            "Fantasy points allowed by defence, split by position. 'Good "
            "defence' is not one number — the split is most of a matchup's value."
        ),
        sql=f"""
    SELECT
        pw.season,
        pw.week,
        pw.opponent                                    AS defteam,
        pw.position,
        SUM(COALESCE(pw.{_FP}, 0))                     AS fp_allowed,
        COUNT(*)                                       AS players_faced,
        SUM(COALESCE(pw.targets, 0))                   AS targets_allowed,
        SUM(COALESCE(pw.carries, 0))                   AS carries_allowed,
        SUM(COALESCE(pw.receiving_yards, 0)
            + COALESCE(pw.rushing_yards, 0)
            + COALESCE(pw.passing_yards, 0))           AS total_yards_allowed
    FROM player_week AS pw
    WHERE pw.season_type = 'REG'
      AND pw.opponent IS NOT NULL
      AND pw.position IN ('QB', 'RB', 'WR', 'TE')
      AND pw.team_score IS NOT NULL
    GROUP BY pw.season, pw.week, pw.opponent, pw.position
        """,
    )
)


# The trailing window. Four games is short enough to track a defence that has
# lost a corner and long enough not to be dominated by one blowout.
_W = lagged_window("defteam, season", "season, week", preceding=4)
_WP = lagged_window("defteam, position, season", "season, week", preceding=4)


DEFENSE_ROLLING = REGISTRY.register(
    FeatureView(
        name="feat_defense_rolling",
        requires=("feat_defense_game",),
        unique_index=("season", "week", "defteam"),
        indexes=(("rank", ("season", "week", "fp_allowed_rank")),),
        description=(
            "Model-ready defensive strength: trailing 4-game averages ending at "
            "the PREVIOUS week, plus a 1-32 season rank. The lag is what makes "
            "these usable on a Thursday."
        ),
        sql=f"""
    WITH rolling AS (
        SELECT
            season,
            week,
            defteam,
            AVG(fp_allowed)             {_W} AS fp_allowed_l4,
            AVG(pass_yards_allowed)     {_W} AS pass_yards_allowed_l4,
            AVG(rush_yards_allowed)     {_W} AS rush_yards_allowed_l4,
            AVG(pass_tds_allowed + rec_tds_allowed) {_W} AS pass_tds_allowed_l4,
            AVG(rush_tds_allowed)       {_W} AS rush_tds_allowed_l4,
            AVG(pass_epa_allowed)       {_W} AS pass_epa_allowed_l4,
            AVG(rush_epa_allowed)       {_W} AS rush_epa_allowed_l4,
            AVG(yards_per_pass_attempt) {_W} AS yards_per_pass_attempt_l4,
            AVG(yards_per_carry)        {_W} AS yards_per_carry_l4,
            AVG(plays_faced)            {_W} AS plays_faced_l4,
            COUNT(*)                    {_W} AS games_in_window
        FROM feat_defense_game
    )
    SELECT
        season,
        week,
        defteam,
        fp_allowed_l4,
        pass_yards_allowed_l4,
        rush_yards_allowed_l4,
        pass_tds_allowed_l4,
        rush_tds_allowed_l4,
        pass_epa_allowed_l4,
        rush_epa_allowed_l4,
        yards_per_pass_attempt_l4,
        yards_per_carry_l4,
        plays_faced_l4,
        games_in_window,
        -- Rank 1 = toughest defence (fewest points allowed), matching the
        -- convention in Projection.defense_rank_vs_position.
        RANK() OVER (PARTITION BY season, week ORDER BY fp_allowed_l4 NULLS LAST)
            AS fp_allowed_rank,
        RANK() OVER (PARTITION BY season, week ORDER BY pass_yards_allowed_l4 NULLS LAST)
            AS pass_defense_rank,
        RANK() OVER (PARTITION BY season, week ORDER BY rush_yards_allowed_l4 NULLS LAST)
            AS rush_defense_rank
    FROM rolling
        """,
    )
)


DEFENSE_POSITION_ROLLING = REGISTRY.register(
    FeatureView(
        name="feat_defense_position_rolling",
        requires=("feat_defense_position",),
        unique_index=("season", "week", "defteam", "position"),
        indexes=(("rank", ("season", "week", "position", "fp_allowed_rank")),),
        description=(
            "Trailing fantasy points allowed per position with a 1-32 rank. The "
            "direct input to a player's matchup grade."
        ),
        sql=f"""
    WITH rolling AS (
        SELECT
            season, week, defteam, position,
            AVG(fp_allowed)          {_WP} AS fp_allowed_l4,
            AVG(targets_allowed)     {_WP} AS targets_allowed_l4,
            AVG(carries_allowed)     {_WP} AS carries_allowed_l4,
            AVG(total_yards_allowed) {_WP} AS yards_allowed_l4,
            COUNT(*)                 {_WP} AS games_in_window
        FROM feat_defense_position
    )
    SELECT
        season, week, defteam, position,
        fp_allowed_l4,
        targets_allowed_l4,
        carries_allowed_l4,
        yards_allowed_l4,
        games_in_window,
        RANK() OVER (
            PARTITION BY season, week, position ORDER BY fp_allowed_l4 NULLS LAST
        ) AS fp_allowed_rank
    FROM rolling
        """,
    )
)
