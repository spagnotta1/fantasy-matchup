"""Game-context features: market, weather, rest, venue.

This is where the two new providers meet the warehouse. The joins resolve
"latest known" from the append-only snapshot tables with ``DISTINCT ON``, which
is the whole reason those tables keep history: a projection generated on
Thursday should use Thursday's line, and a backtest of that projection should be
able to reconstruct exactly what was known then.

Provenance is explicit. ``spread_source`` records whether a number came from the
live market or from nflverse's closing line, because a model trained on closing
lines and served forward-looking ones is being fed two different distributions,
and that difference must be visible rather than silently averaged away.

Sign convention
---------------
``team_spread`` is "points this team is favoured by", matching
:mod:`nflfp.transform`. The market's ``spread_home`` is the opposite sign
(negative means the home team lays points), so it is negated on the way in.
Getting this backwards produces a model that is confidently wrong in a way no
aggregate metric reveals, so it is asserted in the tests.
"""

from __future__ import annotations

from .base import REGISTRY, FeatureView

# One row per game: the most recent capture from each provider feed.
_LATEST_ODDS = """
    SELECT DISTINCT ON (game_id)
        game_id, spread_home, total, moneyline_home, moneyline_away,
        spread_home_open, total_open, captured_at, book
    FROM odds_snapshots
    ORDER BY game_id, captured_at DESC
"""

_LATEST_WEATHER = """
    SELECT DISTINCT ON (game_id)
        game_id, temperature_f, wind_mph, wind_gust_mph,
        precipitation_probability, precipitation_in, snowfall_in,
        is_indoor, roof_uncertain, captured_at
    FROM weather_forecasts
    ORDER BY game_id, captured_at DESC
"""


GAME_CONTEXT = REGISTRY.register(
    FeatureView(
        name="feat_game_context",
        requires=("game_team", "odds_snapshots", "weather_forecasts"),
        unique_index=("game_id", "team"),
        indexes=(
            ("slate", ("season", "week")),
            ("team", ("team", "season", "week")),
        ),
        description=(
            "One row per (game, team): market, weather and schedule context, "
            "preferring live provider data and falling back to nflverse, with "
            "the source recorded."
        ),
        sql=f"""
    WITH latest_odds AS ({_LATEST_ODDS}),
         latest_weather AS ({_LATEST_WEATHER})
    SELECT
        g.game_id,
        g.season,
        g.week,
        g.team,
        g.opponent,
        g.is_home,
        g.div_game,
        g.rest_days,
        g.opp_rest_days,
        g.rest_days - g.opp_rest_days                     AS rest_advantage,
        g.roof,
        g.surface,

        -- ---- market -------------------------------------------------------
        -- Live line first, nflverse closing line as the fallback. Negated for
        -- the away team, and negated again out of market convention, so this
        -- is always "points THIS team is favoured by".
        COALESCE(
            CASE WHEN g.is_home THEN -o.spread_home ELSE o.spread_home END,
            g.team_spread
        )                                                 AS team_spread,
        COALESCE(o.total, g.total_line)                   AS total_line,
        CASE
            WHEN o.spread_home IS NOT NULL THEN 'market'
            WHEN g.team_spread IS NOT NULL THEN 'nflverse_close'
            ELSE 'none'
        END                                               AS spread_source,

        -- Implied team total, recomputed from whichever pair won above so it
        -- can never disagree with them.
        (COALESCE(o.total, g.total_line) / 2.0)
          + (COALESCE(
                CASE WHEN g.is_home THEN -o.spread_home ELSE o.spread_home END,
                g.team_spread
            ) / 2.0)                                      AS implied_team_total,
        (COALESCE(o.total, g.total_line) / 2.0)
          - (COALESCE(
                CASE WHEN g.is_home THEN -o.spread_home ELSE o.spread_home END,
                g.team_spread
            ) / 2.0)                                      AS implied_opp_total,

        CASE WHEN g.is_home THEN o.moneyline_home ELSE o.moneyline_away END
                                                          AS moneyline,
        -- Line movement: positive means this team's number improved since open.
        CASE
            WHEN o.spread_home IS NULL OR o.spread_home_open IS NULL THEN NULL
            WHEN g.is_home THEN o.spread_home_open - o.spread_home
            ELSE o.spread_home - o.spread_home_open
        END                                               AS spread_movement,
        o.total - o.total_open                            AS total_movement,
        o.captured_at                                     AS odds_captured_at,
        o.book                                            AS odds_book,

        -- ---- weather ------------------------------------------------------
        -- Forecast first; nflverse temp/wind are observed post-game and exist
        -- only for history, which is exactly why the forecast provider exists.
        COALESCE(w.temperature_f, g.temp)                 AS temperature_f,
        COALESCE(w.wind_mph, g.wind)                      AS wind_mph,
        w.wind_gust_mph,
        w.precipitation_probability,
        w.precipitation_in,
        w.snowfall_in,
        COALESCE(w.is_indoor, g.roof IN ('dome', 'closed')) AS is_indoor,
        COALESCE(w.roof_uncertain, FALSE)                 AS roof_uncertain,
        CASE
            WHEN w.game_id IS NOT NULL THEN 'forecast'
            WHEN g.temp IS NOT NULL THEN 'nflverse_observed'
            ELSE 'none'
        END                                               AS weather_source,
        w.captured_at                                     AS weather_captured_at
    FROM game_team AS g
    LEFT JOIN latest_odds    AS o ON o.game_id = g.game_id
    LEFT JOIN latest_weather AS w ON w.game_id = g.game_id
        """,
    )
)
