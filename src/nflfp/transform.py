"""Derived views over the raw nflverse tables.

The view bodies here are plain SQL that both DuckDB and Postgres accept, so the
local exploration database and the deployed warehouse share one definition of
`player_week`. Only the DDL wrapper differs per engine (DuckDB takes
CREATE OR REPLACE VIEW; Postgres only allows that when the column list is
unchanged, so it gets DROP + CREATE).

Everything is a VIEW, not a table: the raw_* tables are the only materialised
state, so re-shaping the model layer costs nothing and can't drift out of sync
with an ingest. Promote a view to a table only once a definition has settled
and the query cost actually hurts.
"""

from __future__ import annotations

from .scoring import PROFILES, points_expression


def _game_team_select() -> str:
    """One row per (game, team) — the team-perspective view of the schedule.

    `spread_line` in nflverse is signed from the home team's perspective
    (verified: positive correlates +0.44 with home margin). We normalise it to
    `team_spread`, always "points THIS team is favoured by", so downstream code
    never has to remember the convention.
    """
    shared = """
        game_id, season, week, game_type, gameday, weekday, gametime,
        div_game, roof, surface, temp, wind, stadium, stadium_id, referee,
        total_line, overtime
    """
    return f"""
    SELECT
        {shared},
        home_team          AS team,
        away_team          AS opponent,
        TRUE               AS is_home,
        home_rest          AS rest_days,
        away_rest          AS opp_rest_days,
        home_score         AS team_score,
        away_score         AS opp_score,
        home_qb_id         AS team_qb_id,
        away_qb_id         AS opp_qb_id,
        home_coach         AS team_coach,
        away_coach         AS opp_coach,
        spread_line        AS team_spread,
        total_line / 2.0 + spread_line / 2.0 AS implied_team_total,
        total_line / 2.0 - spread_line / 2.0 AS implied_opp_total
    FROM raw_schedules
    UNION ALL
    SELECT
        {shared},
        away_team          AS team,
        home_team          AS opponent,
        FALSE              AS is_home,
        away_rest          AS rest_days,
        home_rest          AS opp_rest_days,
        away_score         AS team_score,
        home_score         AS opp_score,
        away_qb_id         AS team_qb_id,
        home_qb_id         AS opp_qb_id,
        away_coach         AS team_coach,
        home_coach         AS opp_coach,
        -spread_line       AS team_spread,
        total_line / 2.0 - spread_line / 2.0 AS implied_team_total,
        total_line / 2.0 + spread_line / 2.0 AS implied_opp_total
    FROM raw_schedules
    """


def _upcoming_select() -> str:
    """Games with no result yet — what you actually need to project."""
    return """
    SELECT * FROM game_team WHERE team_score IS NULL
    """


def _player_week_select(has_snaps: bool, has_injuries: bool) -> str:
    """Player-week fact joined to game context, snaps and injury designation."""
    fp_cols = ",\n        ".join(
        f"{points_expression(rules, alias='s')} AS fp_{name}"
        for name, rules in PROFILES.items()
    )

    # Snap counts key on pfr_player_id, not gsis — bridge through raw_players.
    snap_join = (
        """
    LEFT JOIN raw_players AS pl
           ON pl.gsis_id = s.player_id
    LEFT JOIN raw_snap_counts AS sn
           ON sn.game_id = s.game_id
          AND sn.pfr_player_id = pl.pfr_id
        """
        if has_snaps
        else ""
    )
    snap_cols = (
        """
        sn.offense_snaps,
        sn.offense_pct,
        sn.st_snaps,
        sn.st_pct,
        """
        if has_snaps
        else """
        CAST(NULL AS INTEGER)          AS offense_snaps,
        CAST(NULL AS DOUBLE PRECISION) AS offense_pct,
        CAST(NULL AS INTEGER)          AS st_snaps,
        CAST(NULL AS DOUBLE PRECISION) AS st_pct,
        """
    )

    inj_join = (
        """
    LEFT JOIN raw_injuries AS inj
           ON inj.gsis_id = s.player_id
          AND inj.season  = s.season
          AND inj.week    = s.week
          AND inj.team    = s.team
        """
        if has_injuries
        else ""
    )
    inj_cols = (
        """
        inj.report_status          AS injury_report_status,
        inj.practice_status        AS injury_practice_status,
        inj.report_primary_injury  AS injury_detail,
        """
        if has_injuries
        else """
        CAST(NULL AS VARCHAR) AS injury_report_status,
        CAST(NULL AS VARCHAR) AS injury_practice_status,
        CAST(NULL AS VARCHAR) AS injury_detail,
        """
    )

    return f"""
    SELECT
        s.player_id,
        s.player_display_name AS player_name,
        s.position,
        s.position_group,
        s.season,
        s.week,
        s.season_type,
        s.game_id,
        s.team,
        s.opponent_team AS opponent,

        -- game context
        g.is_home,
        g.team_spread,
        g.total_line,
        g.implied_team_total,
        g.implied_opp_total,
        g.rest_days,
        g.opp_rest_days,
        g.div_game,
        g.roof,
        g.surface,
        g.temp,
        g.wind,
        g.gameday,
        g.weekday,
        g.gametime,
        g.team_score,
        g.opp_score,
        {snap_cols.strip()}
        {inj_cols.strip()}

        -- usage
        s.attempts,
        s.completions,
        s.carries,
        s.targets,
        s.receptions,
        s.target_share,
        s.air_yards_share,
        s.wopr,

        -- production
        s.passing_yards,
        s.passing_tds,
        s.passing_interceptions,
        s.passing_epa,
        s.rushing_yards,
        s.rushing_tds,
        s.rushing_epa,
        s.receiving_yards,
        s.receiving_tds,
        s.receiving_air_yards,
        s.receiving_epa,
        s.fumbles_lost_total,
        s.special_teams_tds,

        -- Two-point conversions. Rare, but they are the entire difference
        -- between a player's points and the sum of their other components:
        -- verified, all 946 rows where the identity failed had one.
        s.passing_2pt_conversions,
        s.rushing_2pt_conversions,
        s.receiving_2pt_conversions,

        -- nflverse's own scoring, kept for cross-checking ours
        s.fantasy_points     AS nflverse_fp_standard,
        s.fantasy_points_ppr AS nflverse_fp_ppr,

        {fp_cols}
    FROM raw_player_week AS s
    LEFT JOIN game_team AS g
           ON g.game_id = s.game_id
          AND g.team    = s.team
    {snap_join}
    {inj_join}
    """


def _norm_name(col: str) -> str:
    """A player name reduced to what two sources agree on.

    Lower-case letters and single spaces only, generational suffix dropped, so
    "D.J. Moore" / "DJ Moore" and "Kenneth Walker III" / "Kenneth Walker" meet.
    Portable: DuckDB and Postgres both take the 'g' flag.
    """
    x = f"lower({col})"
    x = f"regexp_replace({x}, '[^a-z ]', '', 'g')"
    x = f"regexp_replace({x}, ' +', ' ', 'g')"
    x = f"regexp_replace(trim({x}), ' (jr|sr|ii|iii|iv|v)$', '', 'g')"
    return x


def _player_adp_select(has_schedules: bool, has_players: bool) -> str:
    """One row per (season, ADP entry): the season's draft-day snapshot, with
    each entry matched to a `gsis_id` where the match is unambiguous.

    **Which snapshot.** The source serves a rolling window, and the pipeline
    appends each one it sees. A season's ADP is its last window that closed
    before that season's first regular-season game -- the market on draft day,
    not the thin in-season trickle after it. Until a pre-kickoff window has been
    captured (the season in which this dataset was first loaded, say), the
    latest window stands in, and `is_preseason` says so.

    **Matching.** ADP carries names, not ids. Three tiers, most trustworthy
    first, and the first tier to find anyone decides: (1) the season's roster,
    same position, by normalised full name or football name + last name; (2)
    the season's roster, same position and team, by surname -- nicknames; (3)
    the player dimension by name -- players on no roster that season. Within a
    tier a team match breaks a tie; if exactly one candidate is left it wins,
    otherwise the entry is `ambiguous` with no id rather than given a guess. A
    renamed player (Robby Anderson -> Robbie Chosen) stays `unmatched`. K and
    DST entries are `not_applicable`: K has no roster match worth making and
    DST is a team, not a player.
    """
    kickoff = (
        """
        LEFT JOIN (
            SELECT season, MIN(CAST(gameday AS DATE)) AS kickoff
            FROM raw_schedules
            WHERE game_type = 'REG'
            GROUP BY season
        ) AS k ON k.season = a.season
        """
        if has_schedules
        else "LEFT JOIN (SELECT NULL AS season, CAST(NULL AS DATE) AS kickoff) AS k ON FALSE"
    )
    # Tier 3: not on that season's roster at all -- a free agent in the
    # current season's ADP -- so fall back to the player dimension by name.
    players_tier = (
        f"""
        UNION
        SELECT a.season, a.ffc_player_id, p.gsis_id, 3 AS tier, 0 AS team_match
        FROM adp AS a
        JOIN raw_players AS p
          ON p.position = a.position
         AND p.gsis_id IS NOT NULL
         AND {_norm_name("p.display_name")} = a.norm_name
        WHERE a.position IN ('QB', 'RB', 'WR', 'TE')
        """
        if has_players
        else ""
    )
    return f"""
    WITH windows AS (
        SELECT
            w.*,
            ROW_NUMBER() OVER (
                PARTITION BY w.season
                ORDER BY w.is_preseason DESC, w.window_end DESC, w.window_start DESC
            ) AS pick
        FROM (
            SELECT DISTINCT
                a.season, a.window_start, a.window_end,
                COALESCE(a.window_end < k.kickoff, TRUE) AS is_preseason
            FROM raw_adp AS a
            {kickoff}
        ) AS w
    ),
    adp AS (
        SELECT a.*, w.is_preseason,
               {_norm_name("a.name")} AS norm_name,
               CASE a.team WHEN 'LAR' THEN 'LA' ELSE a.team END AS roster_team
        FROM raw_adp AS a
        JOIN windows AS w
          ON w.season = a.season
         AND w.window_start = a.window_start
         AND w.window_end = a.window_end
         AND w.pick = 1
    ),
    candidates AS (
        -- Tier 1: the season's roster, by full name or football name.
        SELECT
            a.season, a.ffc_player_id, r.gsis_id, 1 AS tier,
            CASE WHEN r.team = a.roster_team THEN 1 ELSE 0 END AS team_match
        FROM adp AS a
        JOIN raw_rosters AS r
          ON r.season = a.season
         AND r.position = a.position
         AND r.gsis_id IS NOT NULL
         AND (
              {_norm_name("r.full_name")} = a.norm_name
           OR {_norm_name("r.football_name || ' ' || r.last_name")} = a.norm_name
         )
        WHERE a.position IN ('QB', 'RB', 'WR', 'TE')

        UNION
        -- Tier 2: a nickname ("Hollywood" Brown, Gabe Davis). Same season,
        -- team, position and surname.
        SELECT a.season, a.ffc_player_id, r.gsis_id, 2 AS tier, 1 AS team_match
        FROM adp AS a
        JOIN raw_rosters AS r
          ON r.season = a.season
         AND r.position = a.position
         AND r.team = a.roster_team
         AND r.gsis_id IS NOT NULL
         AND {_norm_name("r.last_name")} = regexp_replace(a.norm_name, '^.* ', '')
        WHERE a.position IN ('QB', 'RB', 'WR', 'TE')
        {players_tier}
    ),
    best AS (
        -- The most trustworthy tier that found anyone, then the best team
        -- agreement within it.
        SELECT season, ffc_player_id, tier, MAX(team_match) AS team_match
        FROM candidates AS c
        WHERE tier = (
            SELECT MIN(c2.tier) FROM candidates AS c2
            WHERE c2.season = c.season AND c2.ffc_player_id = c.ffc_player_id
        )
        GROUP BY season, ffc_player_id, tier
    ),
    matched AS (
        -- Exactly one candidate at the best level wins; two is ambiguous and
        -- gets no id rather than a coin flip.
        SELECT c.season, c.ffc_player_id, MIN(c.gsis_id) AS gsis_id
        FROM candidates AS c
        JOIN best AS b
          ON b.season = c.season
         AND b.ffc_player_id = c.ffc_player_id
         AND b.tier = c.tier
         AND b.team_match = c.team_match
        GROUP BY c.season, c.ffc_player_id
        HAVING COUNT(DISTINCT c.gsis_id) = 1
    )
    SELECT
        a.season,
        m.gsis_id                                   AS player_id,
        a.ffc_player_id,
        a.name                                      AS adp_name,
        a.position,
        a.team,
        a.adp,
        CAST(CEIL(a.adp / a.teams) AS INTEGER)      AS adp_round,
        a.adp_formatted,
        a.times_drafted,
        a.high,
        a.low,
        a.stdev,
        a.teams,
        a.total_drafts,
        a.window_start,
        a.window_end,
        a.is_preseason,
        CASE
            WHEN a.position NOT IN ('QB', 'RB', 'WR', 'TE') THEN 'not_applicable'
            WHEN m.gsis_id IS NOT NULL THEN 'matched'
            WHEN EXISTS (
                SELECT 1 FROM candidates AS c
                WHERE c.season = a.season AND c.ffc_player_id = a.ffc_player_id
            ) THEN 'ambiguous'
            ELSE 'unmatched'
        END                                         AS match_status
    FROM adp AS a
    LEFT JOIN matched AS m
           ON m.season = a.season
          AND m.ffc_player_id = a.ffc_player_id
    """


def view_definitions(tables: set[str]) -> list[tuple[str, str]]:
    """(name, SELECT body) for every view buildable from `tables`, in dependency order."""
    defs: list[tuple[str, str]] = []

    if "raw_schedules" in tables:
        defs.append(("game_team", _game_team_select()))
        defs.append(("upcoming_games", _upcoming_select()))

    if "raw_player_week" in tables:
        defs.append((
            "player_week",
            _player_week_select(
                has_snaps="raw_snap_counts" in tables and "raw_players" in tables,
                has_injuries="raw_injuries" in tables,
            ),
        ))

    if "raw_adp" in tables and "raw_rosters" in tables:
        defs.append((
            "player_adp",
            _player_adp_select(
                has_schedules="raw_schedules" in tables,
                has_players="raw_players" in tables,
            ),
        ))

    return defs


# reverse dependency order
VIEW_NAMES = ("player_adp", "player_week", "upcoming_games", "game_team")


def build_views(con) -> list[str]:
    """(Re)create all derived views in a DuckDB connection. Returns names created."""
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    created = []
    for name, body in view_definitions(tables):
        con.execute(f"CREATE OR REPLACE VIEW {name} AS {body}")
        created.append(name)
    return created
