"""The feature contract: what a model is allowed to use, and why.

The rule
--------
**A feature may only be used if the same information would have been available
at the moment the prediction was generated.**

Layer 2 enforces one half of that with lagged windows. This module enforces the
other half, which lagging cannot catch: a column can be perfectly lagged and
still be unavailable at prediction time, because the *value stored for history*
was measured under different conditions than the value available for an
upcoming game.

Two columns in ``feat_training_dataset`` are exactly that, and both are market
or weather provenance.

The spread_source finding
-------------------------
``feat_game_context.team_spread`` resolves to nflverse's ``spread_line`` for
historical games and to a live market capture for upcoming ones. Measured:

* For the 17 upcoming games where both sources exist, they agree **exactly**
  (corr 1.0000, mean absolute difference 0.000). nflverse populates
  ``spread_line`` for future games *from the live market*, so it is only a
  settled closing line for games already played.
* Therefore training rows carry a line that incorporates everything the market
  learned up to kickoff, while serving rows carry a line from days earlier. The
  model would learn a relationship with a better-informed number than it will
  ever be given.

The resolution is not a correction factor. It is a measurement of whether the
feature is worth the problem, taken over 2019-2025:

============  ======  =====================  ===========================
position      n       corr(implied, points)  corr(implied, l4 residual)
============  ======  =====================  ===========================
QB            4,379   0.235                  **-0.039**
RB            10,321  0.089                  **0.011**
TE            8,159   0.117                  **0.021**
WR            16,402  0.099                  **-0.001**
============  ======  =====================  ===========================

The raw correlation is entirely confounded: good players on good offences have
both high implied totals and high lagged production. Once lagged usage is
accounted for, the market contributes **nothing measurable** — residual
correlations sit between -0.04 and +0.02 across 39,000 player-weeks.

So market features are excluded. That is the simple, honest resolution: a
feature that adds no measurable skill is not worth a train/serve distribution
shift, and dropping it removes the entire class of problem rather than managing
it. They remain in the feature table — they are legitimate data, useful for
display and for the future simulation engine — they are just not model inputs.

Weather is excluded on the same reasoning: ``temperature_f`` falls back to
nflverse's *observed* post-game reading for history and to a forecast for
upcoming games. Forecast collection began in 2026, so no historical row has one.
Training on observations and serving forecasts is the same shift, and the same
test would be needed to justify it.

This is a decision to revisit, not a permanent one. Now that snapshots are being
captured, a season from now there will be genuine prediction-time lines and
forecasts for historical weeks, and the question can be re-measured properly.

Declared, or excluded with a reason. Never neither.
---------------------------------------------------
A column of ``feat_training_dataset`` that appears in neither list is in a third
state this contract should not have: :func:`assert_available` rejects it as "not
declared in the feature contract", which is the *same* message a typo produces.
So an unmade decision is indistinguishable from a mistake, and the one thing
this module exists to make legible -- whether a feature was considered and
refused, or simply never considered -- is exactly what is lost.

Four columns sat in that state and are now resolved. ``snap_pct_trend`` and
``target_share_trend`` are declared available: both are differences of lagged
quantities, so nothing about them is unknowable before kickoff. The two injury
designations are declared excluded, on availability rather than on measured
skill -- see ``_AVAILABILITY_REASON``. Neither resolution changes a model:
``shrinkage_eb`` requires two features and reads component ``*_l4`` columns, so
what the contract permits and what the frozen model uses remain different
questions.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Feature-set version. Bumped whenever the available set below changes, and
#: recorded on every model run so a stored projection stays interpretable.
FEATURE_VERSION = 3


@dataclass(frozen=True)
class FeatureSpec:
    """One column of ``feat_training_dataset`` and its availability."""

    name: str
    available_at_prediction: bool
    reason: str = ""


#: Lagged player history. Every window ends at the previous week, and the values
#: are box-score facts that do not change after the fact.
USAGE_FEATURES: tuple[str, ...] = (
    "snap_pct_l4",
    "target_share_l4",
    "targets_l4",
    "carries_l4",
    "receptions_l4",
    "pass_attempts_l4",
    "air_yards_share_l4",
    "wopr_l4",
    "opportunities_l4",
    "snap_pct_season",
    "games_played_season",
    "games_in_window_l4",
    "fp_half_ppr_l4",
    "fp_half_ppr_season",
    "fp_volatility_l4",
    "fp_ceiling_l4",
    "fp_floor_l4",
    "receiving_yards_l4",
    "rushing_yards_l4",
    "passing_yards_l4",
    "receiving_tds_l4",
    "rushing_tds_l4",
    "passing_tds_l4",
    "passing_interceptions_l4",
    "fumbles_lost_l4",
    "receiving_yards_l8",
    "rushing_yards_l8",
    "passing_yards_l8",
    "receiving_epa_l8",
    "rushing_epa_l8",
    "passing_epa_l8",
    # Lagged by construction and therefore available: `snap_pct_prev` and
    # `target_share_prev` are LAG() over the player's previous row, and the l4
    # window ends at the previous week, so the difference is knowable before
    # kickoff. Both feature views emit them -- the preseason slate computes the
    # same difference over the last four completed games -- so declaring them
    # does not create a column that exists in training and not at serving.
    "snap_pct_trend",
    "target_share_trend",
)

#: Schedule facts, fixed once the season is scheduled.
SCHEDULE_FEATURES: tuple[str, ...] = (
    "is_home",
    "div_game",
    "rest_days",
    "rest_advantage",
)

#: Opponent strength, from lagged defensive aggregates.
OPPONENT_FEATURES: tuple[str, ...] = (
    "opp_fp_allowed_vs_position_l4",
    "opp_defense_rank_vs_position",
    "opp_targets_allowed_l4",
    "opp_carries_allowed_l4",
    "opp_defense_rank_overall",
    "opp_pace_l4",
)

_MARKET_REASON = (
    "train/serve shift: historical rows carry a settled line, upcoming rows a "
    "live one. Measured to add nothing beyond lagged usage "
    "(residual corr -0.04..+0.02, n=39,261), so excluded rather than managed."
)
_AVAILABILITY_REASON = (
    "train/serve shift, and an absent column at the one moment it would matter "
    "most: `feat_training_dataset` carries the *current* week's designation "
    "unlagged, which for a played game is the settled final report and for an "
    "upcoming game is whatever the report says days out. `feat_preseason_slate` "
    "emits NULL for both by construction -- no injury report exists for a game "
    "months away -- so a model reading these could not produce a week 1 board "
    "at all. Excluded on availability, not on measured skill: the question of "
    "whether a designation predicts residual production has not been asked, "
    "and asking it needs prediction-time snapshots that collection only "
    "recently began. See README, 'Injury and weather are not quantified'."
)
_WEATHER_REASON = (
    "train/serve shift: historical rows carry nflverse's post-game *observation*, "
    "upcoming rows a forecast. No historical row has a forecast, so the "
    "relationship cannot be learned from prediction-time data."
)

#: Columns present in the feature table that models must NOT use.
EXCLUDED_FEATURES: tuple[FeatureSpec, ...] = tuple(
    FeatureSpec(name, False, _MARKET_REASON)
    for name in (
        "team_spread",
        "total_line",
        "implied_team_total",
        "implied_opp_total",
        "spread_movement",
        "spread_source",
    )
) + tuple(
    FeatureSpec(name, False, _WEATHER_REASON)
    for name in (
        "temperature_f",
        "wind_mph",
        "precipitation_probability",
        "weather_source",
    )
) + tuple(
    FeatureSpec(name, False, _AVAILABILITY_REASON)
    for name in (
        "injury_report_status",
        "injury_practice_status",
    )
)

#: Everything a model may read.
AVAILABLE_FEATURES: tuple[str, ...] = (
    USAGE_FEATURES + SCHEDULE_FEATURES + OPPONENT_FEATURES
)

_EXCLUDED_NAMES = frozenset(spec.name for spec in EXCLUDED_FEATURES)


def is_available(name: str) -> bool:
    """Whether `name` may be used as a model input."""
    return name in AVAILABLE_FEATURES


def excluded_reason(name: str) -> str | None:
    """Why `name` is excluded, or None if it is not."""
    for spec in EXCLUDED_FEATURES:
        if spec.name == name:
            return spec.reason
    return None


def assert_available(names: object) -> None:
    """Raise if any named feature is not available at prediction time.

    Called by every model's ``required_features`` check and by the tests. This
    is the regression guard against future information silently re-entering the
    model — a column added to the feature table for display can otherwise be
    picked up by a model that has no right to it.

    Raises:
        ValueError: naming each offending feature and why it is excluded.
    """
    offenders = []
    for name in names:
        if name in _EXCLUDED_NAMES:
            offenders.append(f"{name}: {excluded_reason(name)}")
        elif not is_available(name):
            offenders.append(f"{name}: not declared in the feature contract")
    if offenders:
        raise ValueError(
            "model requests features unavailable at prediction time:\n  "
            + "\n  ".join(offenders)
        )
