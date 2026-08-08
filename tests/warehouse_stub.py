"""A stub nflverse warehouse, built in a throwaway schema.

The business layer joins the application tables to seven warehouse and feature
relations. Verifying its SQL needs those relations to *exist with the right
column names*; it does not need 1.8 million real rows, and a test that requires
a full nflverse load is a test nobody runs.

So this module creates the relations as plain tables carrying the real column
names, and fills them with a two-team, four-player week. The shape is chosen to
exercise the cases that actually break:

* week 10 is scheduled but **not played**, which is the week a projection is
  for and the one ``feat_defense_position_rolling`` has no row for;
* weeks 1-9 are complete, so a trailing four-game window has more history than
  it should use;
* ``position`` is present on the projection, the player dimension *and* the
  usage table, so an unqualified reference resolves by join order;
* one player carries an injury designation and the two teams have opposite
  defensive profiles, so matchup grading has something to grade.
"""

from __future__ import annotations

from sqlalchemy import text

SEASON = 2025
UPCOMING_WEEK = 10

# ---------------------------------------------------------------------------
# Stub warehouse
# ---------------------------------------------------------------------------

_STUB_DDL = """
CREATE TABLE raw_players (
    gsis_id text PRIMARY KEY,
    display_name text,
    football_name text,
    position text,
    position_group text,
    latest_team text,
    jersey_number int,
    status text,
    headshot text,
    college_name text,
    years_of_experience int,
    rookie_season int,
    last_season int,
    height int,
    weight int,
    draft_year int,
    draft_round int,
    draft_pick int,
    draft_team text
);

CREATE TABLE raw_teams (
    team_abbr text PRIMARY KEY,
    team_name text,
    team_nick text,
    team_conf text,
    team_division text,
    team_color text,
    team_color2 text,
    team_logo_espn text,
    team_logo_wikipedia text
);

CREATE TABLE game_team (
    game_id text,
    season int,
    week int,
    game_type text,
    gameday date,
    weekday text,
    gametime text,
    div_game boolean,
    roof text,
    surface text,
    stadium text,
    team text,
    opponent text,
    is_home boolean,
    team_score int,
    opp_score int,
    total_line double precision,
    team_spread double precision,
    implied_team_total double precision,
    implied_opp_total double precision
);

CREATE VIEW upcoming_games AS
    SELECT * FROM game_team WHERE team_score IS NULL;

CREATE TABLE player_week (
    player_id text,
    player_name text,
    position text,
    season int,
    week int,
    team text,
    opponent text,
    is_home boolean,
    offense_pct double precision,
    targets double precision,
    carries double precision,
    receptions double precision,
    receiving_yards double precision,
    rushing_yards double precision,
    passing_yards double precision,
    receiving_tds double precision,
    rushing_tds double precision,
    passing_tds double precision,
    injury_report_status text,
    fp_standard double precision,
    fp_half_ppr double precision,
    fp_ppr double precision,
    fp_ppr_te_premium double precision
);

CREATE TABLE feat_player_usage (
    player_id text,
    player_name text,
    position text,
    season int,
    week int,
    team text,
    opponent text,
    game_id text,
    snap_pct_l4 double precision,
    target_share_l4 double precision,
    targets_l4 double precision,
    carries_l4 double precision,
    receptions_l4 double precision,
    opportunities_l4 double precision,
    air_yards_share_l4 double precision,
    wopr_l4 double precision,
    snap_pct_season double precision,
    games_played_season int,
    games_in_window_l4 int,
    fp_half_ppr_l4 double precision,
    fp_half_ppr_season double precision,
    fp_volatility_l4 double precision,
    snap_pct_prev double precision,
    target_share_prev double precision,
    injury_report_status text,
    injury_practice_status text
);

CREATE TABLE feat_defense_position (
    season int,
    week int,
    defteam text,
    position text,
    fp_allowed double precision,
    players_faced int,
    targets_allowed double precision,
    carries_allowed double precision,
    total_yards_allowed double precision
);

CREATE TABLE feat_defense_game (
    season int,
    week int,
    defteam text,
    fp_allowed double precision,
    plays_faced double precision
);

CREATE TABLE feat_game_context (
    game_id text,
    season int,
    week int,
    team text,
    opponent text,
    is_home boolean,
    div_game boolean,
    rest_days int,
    opp_rest_days int,
    rest_advantage int,
    roof text,
    surface text,
    team_spread double precision,
    total_line double precision,
    spread_source text,
    implied_team_total double precision,
    implied_opp_total double precision,
    moneyline int,
    spread_movement double precision,
    total_movement double precision,
    odds_captured_at timestamptz,
    odds_book text,
    temperature_f double precision,
    wind_mph double precision,
    wind_gust_mph double precision,
    precipitation_probability double precision,
    precipitation_in double precision,
    snowfall_in double precision,
    is_indoor boolean,
    roof_uncertain boolean,
    weather_source text,
    weather_captured_at timestamptz
);
"""

#: Two teams of skill players, ordered so the expected board is unambiguous.
PLAYERS = [
    # (id, name, position, team, expected points)
    ("00-0000001", "Alpha Receiver", "WR", "KC", 18.4),
    ("00-0000002", "Bravo Back", "RB", "KC", 13.1),
    ("00-0000003", "Charlie End", "TE", "BUF", 9.6),
    ("00-0000004", "Delta Passer", "QB", "BUF", 17.2),
]
GAME_ID = f"{SEASON}_{UPCOMING_WEEK}_BUF_KC"


async def build_warehouse(session) -> int:
    """Create the stub warehouse and one published run. Returns the run id."""
    await session.execute(text(_STUB_DDL))

    for abbr, name, nick, conf, div in (
        ("KC", "Kansas City Chiefs", "Chiefs", "AFC", "AFC West"),
        ("BUF", "Buffalo Bills", "Bills", "AFC", "AFC East"),
    ):
        await session.execute(
            text(
                "INSERT INTO raw_teams (team_abbr, team_name, team_nick, team_conf,"
                " team_division) VALUES (:a, :n, :k, :c, :d)"
            ),
            {"a": abbr, "n": name, "k": nick, "c": conf, "d": div},
        )

    for player_id, name, position, team, _ in PLAYERS:
        await session.execute(
            text(
                "INSERT INTO raw_players (gsis_id, display_name, football_name,"
                " position, latest_team, status, last_season, years_of_experience)"
                " VALUES (:i, :n, :n, :p, :t, 'ACT', :s, 4)"
            ),
            {"i": player_id, "n": name, "p": position, "t": team, "s": SEASON},
        )

    # Weeks 1-9 are played; week 10 is not. That gap is the whole point: the
    # defensive window has to produce a row for week 10 anyway.
    for week in range(1, UPCOMING_WEEK + 1):
        played = week < UPCOMING_WEEK
        for team, opponent, is_home in (("KC", "BUF", False), ("BUF", "KC", True)):
            await session.execute(
                text(
                    "INSERT INTO game_team (game_id, season, week, game_type, gameday,"
                    " team, opponent, is_home, team_score, opp_score, total_line,"
                    " team_spread, implied_team_total, implied_opp_total, div_game)"
                    " VALUES (:g, :s, :w, 'REG', :day, :t, :o, :h, :ts, :os, 47.5,"
                    " 2.5, 25.0, 22.5, false)"
                ),
                {
                    "g": f"{SEASON}_{week}_BUF_KC",
                    "s": SEASON,
                    "w": week,
                    "day": f"{SEASON}-09-{week:02d}",
                    "t": team,
                    "o": opponent,
                    "h": is_home,
                    "ts": 24 if played else None,
                    "os": 21 if played else None,
                },
            )

    # Defensive history: BUF soft against WR, tough against RB; KC the reverse.
    allowed = {("BUF", "WR"): 26.0, ("BUF", "RB"): 6.0, ("KC", "TE"): 15.0, ("KC", "QB"): 19.0}
    for week in range(1, UPCOMING_WEEK):
        for (defteam, position), fp in allowed.items():
            await session.execute(
                text(
                    "INSERT INTO feat_defense_position (season, week, defteam, position,"
                    " fp_allowed, players_faced, targets_allowed, carries_allowed,"
                    " total_yards_allowed) VALUES (:s, :w, :d, :p, :f, 3, 8, 12, 190)"
                ),
                {"s": SEASON, "w": week, "d": defteam, "p": position, "f": fp},
            )
        for defteam, fp in (("KC", 88.0), ("BUF", 102.0)):
            await session.execute(
                text(
                    "INSERT INTO feat_defense_game (season, week, defteam, fp_allowed,"
                    " plays_faced) VALUES (:s, :w, :d, :f, 62)"
                ),
                {"s": SEASON, "w": week, "d": defteam, "f": fp},
            )

    for player_id, name, position, team, _ in PLAYERS:
        await session.execute(
            text(
                "INSERT INTO feat_player_usage (player_id, player_name, position, season,"
                " week, team, opponent, game_id, snap_pct_l4, target_share_l4, targets_l4,"
                " carries_l4, receptions_l4, opportunities_l4, games_in_window_l4,"
                " fp_half_ppr_l4, snap_pct_prev, target_share_prev, injury_report_status)"
                " VALUES (:i, :n, :p, :s, :w, :t, :o, :g, 0.82, 0.24, 8.1, 2.0, 5.4, 10.1,"
                " 4, 13.2, 0.75, 0.21, :inj)"
            ),
            {
                "i": player_id,
                "n": name,
                "p": position,
                "s": SEASON,
                "w": UPCOMING_WEEK,
                "t": team,
                "o": "BUF" if team == "KC" else "KC",
                "g": GAME_ID,
                "inj": "Questionable" if player_id == "00-0000002" else None,
            },
        )
        # A little completed history for the profile queries.
        for week in range(1, UPCOMING_WEEK):
            await session.execute(
                text(
                    "INSERT INTO player_week (player_id, player_name, position, season,"
                    " week, team, opponent, is_home, offense_pct, targets, carries,"
                    " receptions, receiving_yards, rushing_yards, passing_yards,"
                    " receiving_tds, rushing_tds, passing_tds, fp_standard, fp_half_ppr,"
                    " fp_ppr, fp_ppr_te_premium)"
                    " VALUES (:i, :n, :p, :s, :w, :t, :o, false, 0.8, 7, 2, 5, 68, 9, 0,"
                    " 0.5, 0, 0, :std, :half, :ppr, :prem)"
                ),
                {
                    "i": player_id,
                    "n": name,
                    "p": position,
                    "s": SEASON,
                    "w": week,
                    "t": team,
                    "o": "BUF" if team == "KC" else "KC",
                    "std": 10.0 + week,
                    "half": 12.5 + week,
                    "ppr": 15.0 + week,
                    "prem": 15.0 + week,
                },
            )

    for team, opponent, is_home in (("KC", "BUF", False), ("BUF", "KC", True)):
        await session.execute(
            text(
                "INSERT INTO feat_game_context (game_id, season, week, team, opponent,"
                " is_home, div_game, rest_days, rest_advantage, team_spread, total_line,"
                " spread_source, implied_team_total, implied_opp_total, temperature_f,"
                " wind_mph, is_indoor, roof_uncertain, weather_source)"
                " VALUES (:g, :s, :w, :t, :o, :h, false, 7, 0, 2.5, 47.5, 'market',"
                " 25.0, 22.5, 41.0, 14.0, false, false, 'forecast')"
            ),
            {
                "g": GAME_ID,
                "s": SEASON,
                "w": UPCOMING_WEEK,
                "t": team,
                "o": opponent,
                "h": is_home,
            },
        )

    run_id = (
        await session.execute(
            text(
                "INSERT INTO model_runs (model_name, model_version, algorithm, season,"
                " week, status, feature_schema_version, published_at, created_at,"
                " updated_at) VALUES ('shrinkage_eb', '1.0.0', 'baseline', :s, :w,"
                " 'published', 1, now(), now(), now()) RETURNING id"
            ),
            {"s": SEASON, "w": UPCOMING_WEEK},
        )
    ).scalar_one()

    for player_id, _, position, team, expected in PLAYERS:
        projection_id = (
            await session.execute(
                text(
                    "INSERT INTO projections (model_run_id, player_id, season, week,"
                    " game_id, team, opponent, position, is_home, proj_targets,"
                    " proj_receptions, proj_receiving_yards, created_at, updated_at)"
                    " VALUES (:r, :i, :s, :w, :g, :t, :o, :p, false, 8.1, 5.4, 61.0,"
                    " now(), now()) RETURNING id"
                ),
                {
                    "r": run_id,
                    "i": player_id,
                    "s": SEASON,
                    "w": UPCOMING_WEEK,
                    "g": GAME_ID,
                    "t": team,
                    "o": "BUF" if team == "KC" else "KC",
                    "p": position,
                },
            )
        ).scalar_one()
        for profile in ("half_ppr", "ppr"):
            bump = 1.5 if profile == "ppr" else 0.0
            await session.execute(
                text(
                    "INSERT INTO projection_points (projection_id, scoring_profile,"
                    " predicted_points, expected_points, floor_points, p25_points,"
                    " median_points, p75_points, ceiling_points, standard_deviation,"
                    " confidence, boom_probability, bust_probability, boom_threshold,"
                    " bust_threshold, calibration_method, distribution_samples,"
                    " extrapolated) VALUES (:p, :prof, :pred, :exp, :f, :q1, :med, :q3,"
                    " :c, 6.4, 0.71, 0.22, 0.14, 20.0, 5.0,"
                    " 'heldout_residual_quantiles_v1', 1200, false)"
                ),
                {
                    "p": projection_id,
                    "prof": profile,
                    "pred": expected + bump + 0.4,
                    "exp": expected + bump,
                    "f": max(0.0, expected + bump - 7.0),
                    "q1": max(0.0, expected + bump - 3.5),
                    "med": expected + bump - 0.6,
                    "q3": expected + bump + 3.8,
                    "c": expected + bump + 9.2,
                },
            )

    await session.commit()
    return int(run_id)


