"""The week 1 board for a season that has not started.

Why this view exists
--------------------
Every other feature row in this system describes a game that has a player-week
behind it: ``player_week`` is built from ``raw_player_week``, which is *recorded
production*, so a game nobody has played contributes no row and gets no
projection. That is correct for the weekly job, and it is the exact reason a
draft cannot be simulated for an upcoming season. A manager drafts in August.
Nobody has played anything. There is no row.

What is knowable in August is nonetheless considerable, and all of it is already
in the warehouse: the schedule for the coming season (``raw_schedules``), who is
on which roster (``raw_rosters``), and every snap, target and carry of the
season just finished (``player_week``). This view is that join, and nothing
more — one row per rostered skill-position player for their team's week 1 game,
carrying the usage window that ends with their last completed game.

Why the model can read it without a new model
----------------------------------------------
The frozen model's usage windows are partitioned by **player**, ordered by
``(season, week)`` — see the note at the top of :mod:`nflfp.features.usage`. A
week-1 row's trailing four games are therefore the last four of the previous
season, deliberately, and every week 1 from every season in the training set has
that shape. A preseason row built here is the same row: the same columns, the
same window, the same absent season-to-date columns, the same absent opponent
history. It is in-distribution because week 1 always was.

What is different, stated rather than smoothed over
----------------------------------------------------
Three things, and none of them are patched with an invented number:

* **A player who changes team in free agency carries their old team's usage.**
  The window is what they did; the roster is where they are. That is the honest
  pair, and it is also what any human draft board does in August.
* **Rookies are absent entirely.** No completed games means no window, means no
  row, means no projection and no pool entry. In a real draft the rookie class
  goes in the first five rounds, so this is a hole in the board rather than a
  rounding — :mod:`nflfp.services.draft.pool` raises it as a notice, loudly,
  because a board that silently omits them reads as complete.
* **Opponent-strength features are null**, exactly as they are for a real week 1:
  the defensive views reset each season, so nobody has a trailing defensive
  average in week 1 of anything.

This view is additive. Nothing that existed before reads it, ``completed_only``
training loads cannot see it, and building it changes no number anywhere else.
"""

from __future__ import annotations

from .base import REGISTRY, FeatureView

#: Positions the draft pool can hold, which is the only consumer this view has.
#: Kickers and defences have no projection model, so a row for one would be a
#: row nothing can score.
SLATE_POSITIONS = ("QB", "RB", "WR", "TE")

#: How far back the trailing windows reach, in completed games. The same two
#: lengths :mod:`nflfp.features.usage` uses, because a row that reached further
#: back than a real week-1 row would be a different row wearing the same name.
WINDOW_L4 = 4
WINDOW_L8 = 8

_POSITION_LIST = ", ".join(f"'{position}'" for position in SLATE_POSITIONS)


def _l4(expression: str, alias: str) -> str:
    """Average an expression over the last four completed games."""
    return f"AVG({expression}) FILTER (WHERE t.recency <= {WINDOW_L4}) AS {alias}"


def _l8(expression: str, alias: str) -> str:
    """Average an expression over the last eight completed games."""
    return f"AVG({expression}) FILTER (WHERE t.recency <= {WINDOW_L8}) AS {alias}"


_USAGE_L4 = ",\n        ".join(
    _l4(source, alias)
    for source, alias in (
        ("t.offense_pct", "snap_pct_l4"),
        ("t.target_share", "target_share_l4"),
        ("t.targets", "targets_l4"),
        ("t.carries", "carries_l4"),
        ("t.receptions", "receptions_l4"),
        ("t.attempts", "pass_attempts_l4"),
        ("t.air_yards_share", "air_yards_share_l4"),
        ("t.wopr", "wopr_l4"),
        ("COALESCE(t.carries, 0) + COALESCE(t.targets, 0)", "opportunities_l4"),
        ("t.fp_half_ppr", "fp_half_ppr_l4"),
        ("t.receiving_yards", "receiving_yards_l4"),
        ("t.rushing_yards", "rushing_yards_l4"),
        ("t.passing_yards", "passing_yards_l4"),
        ("t.receiving_tds", "receiving_tds_l4"),
        ("t.rushing_tds", "rushing_tds_l4"),
        ("t.passing_tds", "passing_tds_l4"),
        ("t.passing_interceptions", "passing_interceptions_l4"),
        ("t.fumbles_lost_total", "fumbles_lost_l4"),
        ("t.special_teams_tds", "special_teams_tds_l4"),
    )
)

_USAGE_L8 = ",\n        ".join(
    _l8(source, alias)
    for source, alias in (
        ("t.receiving_yards", "receiving_yards_l8"),
        ("t.rushing_yards", "rushing_yards_l8"),
        ("t.passing_yards", "passing_yards_l8"),
        ("t.receiving_epa", "receiving_epa_l8"),
        ("t.rushing_epa", "rushing_epa_l8"),
        ("t.passing_epa", "passing_epa_l8"),
    )
)


PRESEASON_SLATE = REGISTRY.register(
    FeatureView(
        name="feat_preseason_slate",
        requires=("player_week", "game_team", "raw_rosters", "feat_game_context"),
        unique_index=("player_id", "season", "week"),
        indexes=(("slate", ("season", "week", "position")),),
        description=(
            "Week 1 of a season with no completed games: every rostered skill "
            "player joined to their team's opener, carrying the usage window "
            "that ends with their last game of the previous season. The only "
            "way to draft a season before it starts. Rookies are absent by "
            "construction — no completed games, no window, no row."
        ),
        sql=f"""
    WITH roster AS (
        -- Who is on which team for the season being drafted. One row per
        -- player per season: `raw_rosters` is unique on (season, gsis_id), so
        -- a player traded mid-previous-season still appears once here.
        SELECT
            r.season,
            r.gsis_id AS player_id,
            -- raw_rosters names this column full_name; every other feature
            -- view calls it player_name, so it is renamed here rather than
            -- leaking a source-table spelling into the model's input.
            r.full_name AS player_name,
            r.position,
            r.team
        FROM raw_rosters AS r
        WHERE r.position IN ({_POSITION_LIST})
          AND r.gsis_id IS NOT NULL
          AND r.team IS NOT NULL
    ),
    opener AS (
        -- Each team's week 1 game in that season. Restricted to the regular
        -- season because a preseason game is not what anybody drafts for.
        SELECT g.season, g.week, g.team, g.opponent, g.game_id
        FROM game_team AS g
        WHERE g.week = 1
          AND g.game_type = 'REG'
    ),
    tail AS (
        -- Every completed game a rostered player has, ranked most recent
        -- first *relative to the season being drafted*. Ranking inside the
        -- join rather than globally is what lets one player contribute a
        -- different window to a 2026 board than to a 2025 one.
        SELECT
            r.season AS target_season,
            r.player_id,
            pw.offense_pct,
            pw.target_share,
            pw.targets,
            pw.carries,
            pw.receptions,
            pw.attempts,
            pw.air_yards_share,
            pw.wopr,
            pw.fp_half_ppr,
            pw.receiving_yards,
            pw.rushing_yards,
            pw.passing_yards,
            pw.receiving_tds,
            pw.rushing_tds,
            pw.passing_tds,
            pw.passing_interceptions,
            pw.fumbles_lost_total,
            pw.special_teams_tds,
            pw.receiving_epa,
            pw.rushing_epa,
            pw.passing_epa,
            ROW_NUMBER() OVER (
                PARTITION BY r.season, r.player_id
                ORDER BY pw.season DESC, pw.week DESC
            ) AS recency
        FROM roster AS r
        JOIN player_week AS pw
              ON pw.player_id = r.player_id
             AND pw.season < r.season
             AND pw.season_type = 'REG'
    ),
    windows AS (
        SELECT
            t.target_season,
            t.player_id,
            {_USAGE_L4},
            {_USAGE_L8},
            -- Evidence weight for the shrinkage, exactly as in-season: how many
            -- games the four-game window actually covers. A player who missed
            -- most of last season arrives with a 1 here, and the model is
            -- entitled to distrust the average accordingly.
            COUNT(*) FILTER (WHERE t.recency <= {WINDOW_L4}) AS games_in_window_l4,
            -- The single most recent game, which is what the in-season view's
            -- LAG produces and what the trend columns are measured against.
            MAX(t.offense_pct) FILTER (WHERE t.recency = 1) AS snap_pct_prev,
            MAX(t.target_share) FILTER (WHERE t.recency = 1) AS target_share_prev
        FROM tail AS t
        GROUP BY t.target_season, t.player_id
    )
    SELECT
        r.player_id,
        r.player_name,
        r.position,
        o.season,
        o.week,
        r.team,
        o.opponent,
        o.game_id,

        -- usage
        w.snap_pct_l4,
        w.target_share_l4,
        w.targets_l4,
        w.carries_l4,
        w.receptions_l4,
        w.pass_attempts_l4,
        w.air_yards_share_l4,
        w.wopr_l4,
        w.opportunities_l4,
        -- Season-to-date is null in week 1 of every season, here and in the
        -- in-season view alike. Nothing has happened yet.
        CAST(NULL AS DOUBLE PRECISION) AS snap_pct_season,
        CAST(NULL AS BIGINT)           AS games_played_season,
        w.games_in_window_l4,
        w.snap_pct_l4 - w.snap_pct_prev         AS snap_pct_trend,
        w.target_share_l4 - w.target_share_prev AS target_share_trend,

        -- production and volatility
        w.fp_half_ppr_l4,
        CAST(NULL AS DOUBLE PRECISION) AS fp_half_ppr_season,
        -- Volatility, ceiling and floor are window statistics the in-season
        -- view takes over the same four games. They are left null rather than
        -- approximated: a spread computed over a window that crosses an
        -- offseason is not the quantity the model was fitted on.
        CAST(NULL AS DOUBLE PRECISION) AS fp_volatility_l4,
        CAST(NULL AS DOUBLE PRECISION) AS fp_ceiling_l4,
        CAST(NULL AS DOUBLE PRECISION) AS fp_floor_l4,

        -- lagged production components
        w.receiving_yards_l4,
        w.rushing_yards_l4,
        w.passing_yards_l4,
        w.receiving_tds_l4,
        w.rushing_tds_l4,
        w.passing_tds_l4,
        w.passing_interceptions_l4,
        w.fumbles_lost_l4,
        w.special_teams_tds_l4,
        CAST(NULL AS DOUBLE PRECISION) AS passing_2pt_conversions_l4,
        CAST(NULL AS DOUBLE PRECISION) AS rushing_2pt_conversions_l4,
        CAST(NULL AS DOUBLE PRECISION) AS receiving_2pt_conversions_l4,

        -- efficiency
        w.receiving_yards_l8,
        w.rushing_yards_l8,
        w.passing_yards_l8,
        w.receiving_epa_l8,
        w.rushing_epa_l8,
        w.passing_epa_l8,

        -- game context, from the published schedule for the coming season
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

        -- Opponent strength is null in week 1 of every season: the defensive
        -- views reset each year, so nobody has a trailing average yet.
        CAST(NULL AS DOUBLE PRECISION) AS opp_fp_allowed_vs_position_l4,
        CAST(NULL AS BIGINT)           AS opp_defense_rank_vs_position,
        CAST(NULL AS DOUBLE PRECISION) AS opp_targets_allowed_l4,
        CAST(NULL AS DOUBLE PRECISION) AS opp_carries_allowed_l4,
        CAST(NULL AS BIGINT)           AS opp_defense_rank_overall,
        CAST(NULL AS DOUBLE PRECISION) AS opp_pace_l4,

        -- availability: no injury report exists for a game months away
        CAST(NULL AS VARCHAR) AS injury_report_status,
        CAST(NULL AS VARCHAR) AS injury_practice_status,

        -- Targets. All null, and that is the load-bearing property of this
        -- view: `dataset.load_rows(completed_only=True)` filters on
        -- `fp_half_ppr_actual IS NOT NULL`, so not one of these rows can reach
        -- a training set however this view is joined.
        CAST(NULL AS DOUBLE PRECISION) AS targets_actual,
        CAST(NULL AS DOUBLE PRECISION) AS carries_actual,
        CAST(NULL AS DOUBLE PRECISION) AS receptions_actual,
        CAST(NULL AS DOUBLE PRECISION) AS pass_attempts_actual,
        CAST(NULL AS DOUBLE PRECISION) AS receiving_yards_actual,
        CAST(NULL AS DOUBLE PRECISION) AS rushing_yards_actual,
        CAST(NULL AS DOUBLE PRECISION) AS passing_yards_actual,
        CAST(NULL AS DOUBLE PRECISION) AS receiving_tds_actual,
        CAST(NULL AS DOUBLE PRECISION) AS rushing_tds_actual,
        CAST(NULL AS DOUBLE PRECISION) AS passing_tds_actual,
        CAST(NULL AS DOUBLE PRECISION) AS passing_interceptions_actual,
        CAST(NULL AS DOUBLE PRECISION) AS fumbles_lost_actual,
        CAST(NULL AS DOUBLE PRECISION) AS special_teams_tds_actual,
        CAST(NULL AS DOUBLE PRECISION) AS passing_2pt_conversions_actual,
        CAST(NULL AS DOUBLE PRECISION) AS rushing_2pt_conversions_actual,
        CAST(NULL AS DOUBLE PRECISION) AS receiving_2pt_conversions_actual,
        CAST(NULL AS DOUBLE PRECISION) AS fp_half_ppr_actual,
        CAST(NULL AS DOUBLE PRECISION) AS fp_ppr_actual,
        CAST(NULL AS DOUBLE PRECISION) AS fp_standard_actual
    FROM roster AS r
    JOIN opener AS o
          ON o.team = r.team AND o.season = r.season
    JOIN windows AS w
          ON w.player_id = r.player_id AND w.target_season = r.season
    LEFT JOIN feat_game_context AS c
          ON c.game_id = o.game_id AND c.team = r.team
        """,
    )
)
