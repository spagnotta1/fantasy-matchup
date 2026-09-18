"""The slate for a week that has not been played yet.

Why this view exists
--------------------
:mod:`nflfp.features.usage` builds ``feat_player_usage`` ``FROM player_week``,
which is *recorded production*. Every window in it is correctly lagged, so
every row is usable on the Thursday before its game — but the **row itself**
only comes into existence once that game has been played and ingested. That is
right for training and wrong for the one thing the weekly job does.

``generate_projections`` resolves its target from ``upcoming_games`` — the
earliest scheduled week with no result — and then loaded that week's slate from
``feat_training_dataset``. The two disagree by construction: the job asks for a
week nobody has played and builds its board from games that have been. In
2026 week 2 that produced a **22-player board** out of a ~580-player slate,
because exactly one of sixteen games had been played when the job ran.

It went unnoticed for so long because the two paths that do work hide it. Week
1 of a season falls back to :mod:`nflfp.features.preseason`, but only when the
season has *no* rows at all — true in August, false the moment week 1 kicks
off. And ``backfill_projections`` walks historical weeks, where every row
exists. Weeks 2-18 of a live season had never been generated in production.

What this view is
-----------------
Exactly what ``feat_preseason_slate`` is for week 1, generalised to any
unplayed week: one row per rostered skill-position player for their team's next
scheduled game, carrying the usage window that ends with their last completed
game. The schedule supplies the slate; ``player_week`` supplies the history.

Why the model can read it without a new model
----------------------------------------------
The columns and the windows are the same ones ``feat_training_dataset``
carries, computed over the same games. The in-season view's four-game window is
``ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING`` partitioned by player and ordered
by ``(season, week)``; the ``recency <= 4`` filter here selects that identical
set of games. A row built here for week 6 is the row the in-season view will
build for week 6 once week 6 has been played — the same player, the same
window, the same opponent strength — with the target columns null because the
game has not happened.

Where it differs from the preseason slate, and why
---------------------------------------------------
``feat_preseason_slate`` nulls the season-to-date and opponent-strength columns
because in week 1 of a season there genuinely is no such thing. Mid-season
there is, so this view computes them:

* **Season-to-date** (``snap_pct_season``, ``games_played_season``,
  ``fp_half_ppr_season``) is averaged over completed games *of the target
  season only*, which is what ``_SEASON`` does in the in-season view.
* **Opponent strength** joins the rolling defensive views on the target week.
  Those reset each season and are withheld below three games of history, so
  weeks 1-3 come back null on their own — the same behaviour a real row gets,
  arrived at the same way rather than hardcoded.
* **Volatility, ceiling and floor** are computed over the four-game window. The
  preseason slate leaves them null on the grounds that a spread crossing an
  offseason is not the fitted quantity; that argument does not carry here,
  because the in-season window is partitioned by player and *not* by season, so
  a real week-2 row's volatility crosses the offseason too. Computing them
  matches what the model was fitted on. Leaving them null would not.

The leakage rule, restated where it is executed
------------------------------------------------
The join to ``player_week`` is ``strictly before`` the target week —
``pw.season < target OR (pw.season = target AND pw.week < target_week)``. That
is this view's version of ``ROWS BETWEEN n PRECEDING AND 1 PRECEDING``, and it
is the only place a future game could enter. ``tests/test_features.py`` asserts
it holds for every row.

Two properties this view inherits deliberately
-----------------------------------------------
* **Every target column is null**, so ``load_rows(completed_only=True)``
  filters on ``fp_half_ppr_actual IS NOT NULL`` and cannot see one of these
  rows however they are joined. A slate row can never reach a training set.
* **Rookies are absent.** No completed games means no window, means no row.
  The same hole the preseason slate has, for the same reason, and it closes
  itself as the season progresses and they accumulate games.

A partially-played week resolves correctly. Week 2 with the Thursday game in
the books yields 22 rows in ``feat_training_dataset`` and the other fifteen
games here; the two sets are disjoint, because a team is in exactly one of
them.
"""

from __future__ import annotations

from .base import REGISTRY, FeatureView

#: Positions with a projection model. A row for a kicker or a defence would be
#: a row nothing can score.
SLATE_POSITIONS = ("QB", "RB", "WR", "TE")

#: Window lengths, in completed games. The same two
#: :mod:`nflfp.features.usage` uses — a row reaching further back than a real
#: row would be a different row wearing the same name.
WINDOW_L4 = 4
WINDOW_L8 = 8

_POSITION_LIST = ", ".join(f"'{position}'" for position in SLATE_POSITIONS)


def _l4(expression: str, alias: str) -> str:
    """Average over the last four completed games before the target week."""
    return f"AVG({expression}) FILTER (WHERE t.recency <= {WINDOW_L4}) AS {alias}"


def _l8(expression: str, alias: str) -> str:
    """Average over the last eight completed games before the target week."""
    return f"AVG({expression}) FILTER (WHERE t.recency <= {WINDOW_L8}) AS {alias}"


# Column-for-column the in-season four-game window, including the two-point
# conversions the preseason slate leaves null. The model reads these; a null
# where training saw a number is a silent shift in the input distribution.
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
        ("t.passing_2pt_conversions", "passing_2pt_conversions_l4"),
        ("t.rushing_2pt_conversions", "rushing_2pt_conversions_l4"),
        ("t.receiving_2pt_conversions", "receiving_2pt_conversions_l4"),
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


UPCOMING_SLATE = REGISTRY.register(
    FeatureView(
        name="feat_upcoming_slate",
        requires=(
            "player_week",
            "upcoming_games",
            "raw_rosters",
            "feat_game_context",
            "feat_defense_position_rolling",
            "feat_defense_rolling",
        ),
        unique_index=("player_id", "season", "week"),
        indexes=(("slate", ("season", "week", "position")),),
        description=(
            "Every rostered skill player joined to their team's next unplayed "
            "regular-season game, carrying the usage window that ends with "
            "their last completed game. What the weekly job projects from. "
            "Target columns are null by construction, so these rows cannot "
            "reach a training set."
        ),
        sql=f"""
    WITH target AS (
        -- The schedule, not production. `upcoming_games` is `game_team` with
        -- no score, so this is one row per team per scheduled, unplayed game.
        -- A team on a bye contributes nothing, which is correct.
        SELECT g.season, g.week, g.team, g.opponent, g.game_id
        FROM upcoming_games AS g
        WHERE g.game_type = 'REG'
    ),
    roster AS (
        -- Who is on which team now. `raw_rosters` is reloaded by the weekly
        -- pipeline, so mid-season this reflects trades and signings; it is
        -- unique on (season, gsis_id), so nobody appears twice.
        SELECT
            r.season,
            r.gsis_id   AS player_id,
            -- raw_rosters spells this full_name; every feature view calls it
            -- player_name. Renamed here rather than leaking a source-table
            -- spelling into the model's input.
            r.full_name AS player_name,
            r.position,
            r.team
        FROM raw_rosters AS r
        WHERE r.position IN ({_POSITION_LIST})
          AND r.gsis_id IS NOT NULL
          AND r.team IS NOT NULL
    ),
    slate AS (
        SELECT
            t.season, t.week, t.team, t.opponent, t.game_id,
            r.player_id, r.player_name, r.position
        FROM target AS t
        JOIN roster AS r
              ON r.team = t.team
             AND r.season = t.season
    ),
    tail AS (
        -- Every completed game a slate player has *before* the week being
        -- projected, ranked most recent first. The season/week inequality is
        -- this view's leakage boundary: it is the only join through which a
        -- future game could reach a row, and it is strict on both sides.
        SELECT
            s.season AS target_season,
            s.week   AS target_week,
            s.player_id,
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
            pw.passing_2pt_conversions,
            pw.rushing_2pt_conversions,
            pw.receiving_2pt_conversions,
            pw.receiving_epa,
            pw.rushing_epa,
            pw.passing_epa,
            pw.season AS source_season,
            ROW_NUMBER() OVER (
                PARTITION BY s.season, s.week, s.player_id
                ORDER BY pw.season DESC, pw.week DESC
            ) AS recency
        FROM slate AS s
        JOIN player_week AS pw
              ON pw.player_id = s.player_id
             AND pw.season_type = 'REG'
             AND (
                    pw.season < s.season
                 OR (pw.season = s.season AND pw.week < s.week)
             )
    ),
    windows AS (
        SELECT
            t.target_season,
            t.target_week,
            t.player_id,
            {_USAGE_L4},
            {_USAGE_L8},
            -- Evidence weight for the shrinkage: how many games the four-game
            -- window actually covers. A player returning from injury arrives
            -- with a 1 here and the model is entitled to distrust the average.
            COUNT(*) FILTER (WHERE t.recency <= {WINDOW_L4}) AS games_in_window_l4,

            -- Season-to-date, over completed games of the target season only.
            -- This is what `_SEASON` computes in the in-season view: partition
            -- by (player, season), everything strictly before this week.
            AVG(t.fp_half_ppr) FILTER (WHERE t.source_season = t.target_season)
                AS fp_half_ppr_season,
            AVG(t.offense_pct) FILTER (WHERE t.source_season = t.target_season)
                AS snap_pct_season,
            COUNT(*) FILTER (WHERE t.source_season = t.target_season)
                AS games_played_season,

            -- Window statistics over the same four games. Computed, not
            -- nulled: the in-season window is partitioned by player and not by
            -- season, so a real week-2 row's spread crosses the offseason in
            -- exactly this way.
            STDDEV_SAMP(t.fp_half_ppr) FILTER (WHERE t.recency <= {WINDOW_L4})
                AS fp_volatility_l4,
            MAX(t.fp_half_ppr) FILTER (WHERE t.recency <= {WINDOW_L4})
                AS fp_ceiling_l4,
            MIN(t.fp_half_ppr) FILTER (WHERE t.recency <= {WINDOW_L4})
                AS fp_floor_l4,

            -- How stale the window is, in seasons. 0 is the ordinary
            -- mid-season case. 1 or more means this player has not played
            -- since a previous season and `games_in_window_l4` cannot say so,
            -- because it counts games played rather than weeks elapsed.
            -- Reported, never applied: the discount a stale window deserves
            -- has not been measured on the walk-forward harness.
            CAST(
                t.target_season - MAX(t.source_season) FILTER (WHERE t.recency = 1)
                AS INTEGER
            ) AS seasons_since_last_game,

            -- The single most recent game, which is what the in-season view's
            -- LAG produces and what the trend columns measure against.
            MAX(t.offense_pct)  FILTER (WHERE t.recency = 1) AS snap_pct_prev,
            MAX(t.target_share) FILTER (WHERE t.recency = 1) AS target_share_prev
        FROM tail AS t
        GROUP BY t.target_season, t.target_week, t.player_id
    )
    SELECT
        s.player_id,
        s.player_name,
        s.position,
        s.season,
        s.week,
        s.team,
        s.opponent,
        s.game_id,

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
        w.snap_pct_season,
        w.games_played_season,
        w.games_in_window_l4,
        w.seasons_since_last_game,
        w.snap_pct_l4 - w.snap_pct_prev         AS snap_pct_trend,
        w.target_share_l4 - w.target_share_prev AS target_share_trend,

        -- production and volatility
        w.fp_half_ppr_l4,
        w.fp_half_ppr_season,
        w.fp_volatility_l4,
        w.fp_ceiling_l4,
        w.fp_floor_l4,

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
        w.passing_2pt_conversions_l4,
        w.rushing_2pt_conversions_l4,
        w.receiving_2pt_conversions_l4,

        -- efficiency
        w.receiving_yards_l8,
        w.rushing_yards_l8,
        w.passing_yards_l8,
        w.receiving_epa_l8,
        w.rushing_epa_l8,
        w.passing_epa_l8,

        -- game context, from the published schedule and the live providers
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

        -- opponent strength, from the same lagged rolling views a played row
        -- reads. Null in weeks 1-3 because those views withhold a grade below
        -- three games of history — the real behaviour, not a hardcoded null.
        d.fp_allowed_l4      AS opp_fp_allowed_vs_position_l4,
        d.fp_allowed_rank    AS opp_defense_rank_vs_position,
        d.targets_allowed_l4 AS opp_targets_allowed_l4,
        d.carries_allowed_l4 AS opp_carries_allowed_l4,
        dr.fp_allowed_rank   AS opp_defense_rank_overall,
        dr.plays_faced_l4    AS opp_pace_l4,

        -- availability: the current designation for a game not yet played
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
    FROM slate AS s
    JOIN windows AS w
          ON w.player_id = s.player_id
         AND w.target_season = s.season
         AND w.target_week = s.week
    LEFT JOIN feat_game_context AS c
          ON c.game_id = s.game_id AND c.team = s.team
    LEFT JOIN feat_defense_position_rolling AS d
          ON d.season = s.season AND d.week = s.week
         AND d.defteam = s.opponent AND d.position = s.position
    LEFT JOIN feat_defense_rolling AS dr
          ON dr.season = s.season AND dr.week = s.week
         AND dr.defteam = s.opponent
        """,
    )
)
