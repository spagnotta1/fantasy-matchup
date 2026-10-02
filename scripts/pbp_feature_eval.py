"""Are play-level features worth building? Measured on the frozen harness.

README "Where this goes next" names success rate, explosive-play rate and
pressure rate as the features that need ``raw_pbp``. Before any of that is
built into the warehouse, the feature contract and the two slate views, this
asks the only question that decides whether it should be: does a model that
can see them project better than the same model that cannot?

    python -m nflfp.ingest --only pbp          # once; set NFLFP_DB to keep it apart
    python scripts/pbp_feature_eval.py

Design, fixed before the first backtest
---------------------------------------
* **The comparison is one variable wide.** ``lightgbm_components`` against the
  same class, same hyperparameters, same rows, same seasons, same harness —
  plus :data:`PBP_FEATURES`. Nothing else differs, so any difference is the
  features.
* **The feature list was written down before anything was evaluated** and is
  not pruned afterwards. Selecting features on 2019-2025 and then reporting
  2019-2025 would be selection on the test set.
* **Every play-level feature is lagged.** A player's window is their previous
  four games (carried across seasons, as ``feat_player_usage`` does); a team's
  or a defence's is its previous four games of the same season (reset each
  season, as the defensive views do). :func:`attach` asserts that no window
  reaches the week it describes.
* **Rates pool, counts average.** A success rate over a window is successes
  over plays across the window, not a mean of per-game rates, so a two-carry
  game does not weigh the same as a twenty-carry one. A window with no plays
  is missing, not zero; LightGBM routes missing values down a learned branch.

What "pressure rate" is here
----------------------------
nflverse play-by-play carries sacks and quarterback hits, not charted
pressures. ``*_sack_hit_rate`` is sacks-or-hits per dropback and is named for
what it is. Charted pressure lives in the PFR and FTN extras, which are a
different load and a different question.

What this does not do
---------------------
It does not register the model, publish anything, or add a column to the
feature contract. The experimental model is defined here and nowhere else, so
it cannot be selected by the projection job. If the features earn their place,
building them properly — feature views, ``AVAILABLE_FEATURES``, both slates —
is the follow-up, and the model that results is judged by
``scripts/challenger_eval.py`` like any other.

Writes artifacts/pbp_feature_eval_report.txt and _metrics.json and prints the
report. Seeded; two runs print the same numbers.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nflfp import duck  # noqa: E402
from nflfp.db import session_scope  # noqa: E402
from nflfp.predict.backtest import (  # noqa: E402
    BacktestResult,
    acceptance_inputs,
    run_backtest,
)
from nflfp.predict.dataset import load_rows  # noqa: E402
from nflfp.predict.features import AVAILABLE_FEATURES, assert_available  # noqa: E402
from nflfp.predict.foundation import VALIDATION_SEASONS, meets_acceptance  # noqa: E402
from nflfp.predict.models.gbm import LightGBMComponents  # noqa: E402
from nflfp.predict.registry import get_model_factory  # noqa: E402

WINDOW = 4
DRAWS = 5_000
SEED = 20261001

# ---------------------------------------------------------------------------
# The features. (name, numerator, denominator). A denominator of "games" makes
# it a per-game average; anything else makes it a pooled rate.
# ---------------------------------------------------------------------------

Spec = tuple[str, str, str]

PLAYER_SPECS: tuple[Spec, ...] = (
    # rushing — where the touchdowns are, and how the carries went
    ("pbp_rz_carries_l4", "rz_carries", "games"),
    ("pbp_gl_carries_l4", "gl_carries", "games"),
    ("pbp_rush_success_rate_l4", "rush_success", "carries"),
    ("pbp_explosive_rush_rate_l4", "explosive_rushes", "carries"),
    # receiving — the targets that are worth more than a target
    ("pbp_rz_targets_l4", "rz_targets", "games"),
    ("pbp_ez_targets_l4", "ez_targets", "games"),
    ("pbp_deep_targets_l4", "deep_targets", "games"),
    ("pbp_adot_l4", "target_air_yards", "targets"),
    ("pbp_target_success_rate_l4", "target_success", "targets"),
    ("pbp_explosive_rec_rate_l4", "explosive_receptions", "targets"),
    # passing
    ("pbp_dropbacks_l4", "dropbacks", "games"),
    ("pbp_rz_pass_attempts_l4", "rz_pass_attempts", "games"),
    ("pbp_ez_pass_attempts_l4", "ez_pass_attempts", "games"),
    ("pbp_scrambles_l4", "scrambles", "games"),
    ("pbp_deep_attempt_rate_l4", "deep_attempts", "pass_attempts"),
    ("pbp_cpoe_l4", "cpoe_sum", "cpoe_plays"),
    ("pbp_pass_success_rate_l4", "pass_success", "dropbacks"),
    ("pbp_sack_hit_rate_l4", "sacks_hits", "dropbacks"),
)

TEAM_SPECS: tuple[Spec, ...] = (
    ("pbp_team_plays_l4", "plays", "games"),
    ("pbp_team_rz_plays_l4", "rz_plays", "games"),
    ("pbp_team_pass_oe_l4", "pass_oe_sum", "pass_oe_plays"),
    ("pbp_team_success_rate_l4", "success", "plays"),
    ("pbp_team_epa_per_play_l4", "epa_sum", "plays"),
)

OPPONENT_SPECS: tuple[Spec, ...] = (
    ("pbp_opp_rz_plays_allowed_l4", "rz_plays", "games"),
    ("pbp_opp_pass_success_allowed_l4", "pass_success", "dropbacks"),
    ("pbp_opp_rush_success_allowed_l4", "rush_success", "rushes"),
    ("pbp_opp_explosive_rate_allowed_l4", "explosive", "plays"),
    ("pbp_opp_sack_hit_rate_l4", "sacks_hits", "dropbacks"),
    ("pbp_opp_epa_per_play_allowed_l4", "epa_sum", "plays"),
)

PBP_FEATURES: tuple[str, ...] = tuple(
    name for name, _, _ in (*PLAYER_SPECS, *TEAM_SPECS, *OPPONENT_SPECS)
)

# ---------------------------------------------------------------------------
# Play-by-play, aggregated to one row per player-game and per team-game.
# Scrimmage plays only: a real pass or run, no two-point tries, no kneels or
# spikes. nflverse stores its flags as 0/1 numerics.
# ---------------------------------------------------------------------------

_SCRIMMAGE = """
    play_type IN ('pass', 'run')
    AND COALESCE(two_point_attempt, 0) = 0
    AND COALESCE(qb_kneel, 0) = 0
    AND COALESCE(qb_spike, 0) = 0
    AND posteam IS NOT NULL
"""

_PLAYER_SQL = f"""
    WITH plays AS (SELECT * FROM raw_pbp WHERE {_SCRIMMAGE}),
    rushing AS (
        SELECT rusher_player_id AS player_id, season, week,
               COUNT(*)                                              AS carries,
               SUM(CASE WHEN yardline_100 <= 20 THEN 1 ELSE 0 END)   AS rz_carries,
               SUM(CASE WHEN yardline_100 <= 5 THEN 1 ELSE 0 END)    AS gl_carries,
               SUM(COALESCE(success, 0))                             AS rush_success,
               SUM(CASE WHEN yards_gained >= 10 THEN 1 ELSE 0 END)   AS explosive_rushes,
               SUM(COALESCE(qb_scramble, 0))                         AS scrambles
        FROM plays
        WHERE rush_attempt = 1 AND rusher_player_id IS NOT NULL
        GROUP BY 1, 2, 3
    ),
    receiving AS (
        SELECT receiver_player_id AS player_id, season, week,
               COUNT(*)                                              AS targets,
               SUM(CASE WHEN yardline_100 <= 20 THEN 1 ELSE 0 END)   AS rz_targets,
               SUM(CASE WHEN air_yards >= yardline_100 THEN 1 ELSE 0 END) AS ez_targets,
               SUM(CASE WHEN air_yards >= 20 THEN 1 ELSE 0 END)      AS deep_targets,
               SUM(COALESCE(air_yards, 0))                           AS target_air_yards,
               SUM(COALESCE(success, 0))                             AS target_success,
               SUM(CASE WHEN complete_pass = 1 AND yards_gained >= 20 THEN 1 ELSE 0 END)
                                                                     AS explosive_receptions
        FROM plays
        WHERE pass_attempt = 1 AND COALESCE(sack, 0) = 0 AND receiver_player_id IS NOT NULL
        GROUP BY 1, 2, 3
    ),
    passing AS (
        SELECT passer_player_id AS player_id, season, week,
               COUNT(*)                                              AS dropbacks,
               SUM(CASE WHEN pass_attempt = 1 AND COALESCE(sack, 0) = 0 THEN 1 ELSE 0 END)
                                                                     AS pass_attempts,
               SUM(CASE WHEN pass_attempt = 1 AND COALESCE(sack, 0) = 0
                         AND yardline_100 <= 20 THEN 1 ELSE 0 END)   AS rz_pass_attempts,
               SUM(CASE WHEN pass_attempt = 1 AND COALESCE(sack, 0) = 0
                         AND air_yards >= yardline_100 THEN 1 ELSE 0 END) AS ez_pass_attempts,
               SUM(CASE WHEN pass_attempt = 1 AND COALESCE(sack, 0) = 0
                         AND air_yards >= 20 THEN 1 ELSE 0 END)      AS deep_attempts,
               SUM(COALESCE(cpoe, 0))                                AS cpoe_sum,
               COUNT(cpoe)                                           AS cpoe_plays,
               SUM(COALESCE(success, 0))                             AS pass_success,
               SUM(CASE WHEN COALESCE(sack, 0) = 1 OR COALESCE(qb_hit, 0) = 1
                        THEN 1 ELSE 0 END)                           AS sacks_hits
        FROM plays
        WHERE qb_dropback = 1 AND COALESCE(qb_scramble, 0) = 0 AND passer_player_id IS NOT NULL
        GROUP BY 1, 2, 3
    )
    SELECT COALESCE(r.player_id, c.player_id, p.player_id) AS player_id,
           COALESCE(r.season, c.season, p.season)          AS season,
           COALESCE(r.week, c.week, p.week)                AS week,
           r.* EXCLUDE (player_id, season, week),
           c.* EXCLUDE (player_id, season, week),
           p.* EXCLUDE (player_id, season, week)
    FROM rushing r
    FULL JOIN receiving c USING (player_id, season, week)
    FULL JOIN passing p
      ON p.player_id = COALESCE(r.player_id, c.player_id)
     AND p.season = COALESCE(r.season, c.season)
     AND p.week = COALESCE(r.week, c.week)
"""


def _unit_sql(side: str) -> str:
    """Per-game totals for an offence (``posteam``) or a defence (``defteam``)."""
    return f"""
        SELECT {side} AS team, season, week,
               COUNT(*)                                              AS plays,
               SUM(CASE WHEN yardline_100 <= 20 THEN 1 ELSE 0 END)   AS rz_plays,
               SUM(COALESCE(success, 0))                             AS success,
               SUM(COALESCE(epa, 0))                                 AS epa_sum,
               SUM(COALESCE(pass_oe, 0))                             AS pass_oe_sum,
               COUNT(pass_oe)                                        AS pass_oe_plays,
               SUM(COALESCE(qb_dropback, 0))                         AS dropbacks,
               SUM(CASE WHEN qb_dropback = 1 THEN COALESCE(success, 0) ELSE 0 END)
                                                                     AS pass_success,
               SUM(CASE WHEN COALESCE(qb_dropback, 0) = 0 THEN 1 ELSE 0 END) AS rushes,
               SUM(CASE WHEN COALESCE(qb_dropback, 0) = 0 THEN COALESCE(success, 0) ELSE 0 END)
                                                                     AS rush_success,
               SUM(CASE WHEN (qb_dropback = 1 AND yards_gained >= 20)
                          OR (COALESCE(qb_dropback, 0) = 0 AND yards_gained >= 10)
                        THEN 1 ELSE 0 END)                           AS explosive,
               SUM(CASE WHEN COALESCE(sack, 0) = 1 OR COALESCE(qb_hit, 0) = 1
                        THEN 1 ELSE 0 END)                           AS sacks_hits
        FROM raw_pbp
        WHERE {_SCRIMMAGE} AND {side} IS NOT NULL
        GROUP BY 1, 2, 3
    """


Key = tuple[int, int]


def _fetch(con, sql: str, key: str) -> dict[str, dict[Key, dict[str, float]]]:
    """Rows as ``{entity: {(season, week): {stat: value}}}``, nulls as zero.

    A null here is a category of play the player had none of in that game —
    a running back with no targets — which is a true zero, not missing data.
    """
    cursor = con.execute(sql)
    columns = [column[0] for column in cursor.description]
    out: dict[str, dict[Key, dict[str, float]]] = defaultdict(dict)
    for record in cursor.fetchall():
        row = dict(zip(columns, record))
        entity = str(row.pop(key))
        season, week = int(row.pop("season")), int(row.pop("week"))
        out[entity][(season, week)] = {k: float(v or 0.0) for k, v in row.items()}
    return out


def _window_value(games: list[dict[str, float]], numerator: str, denominator: str) -> float:
    """One feature over a window of per-game stat dicts. NaN when undefined."""
    if not games:
        return math.nan
    top = sum(game.get(numerator, 0.0) for game in games)
    bottom = float(len(games)) if denominator == "games" else sum(
        game.get(denominator, 0.0) for game in games
    )
    return top / bottom if bottom > 0 else math.nan


def attach(rows: list[dict], pbp_path: Path) -> dict[str, float]:
    """Add every :data:`PBP_FEATURES` column to ``rows`` in place.

    Returns the share of rows with a non-missing value per feature, so the
    report can show how much of the board each feature actually reaches.

    Raises:
        ValueError: if any window includes the week it is attached to.
    """
    con = duck.connect(pbp_path, read_only=True)
    try:
        players = _fetch(con, _PLAYER_SQL, "player_id")
        offence = _fetch(con, _unit_sql("posteam"), "team")
        defence = _fetch(con, _unit_sql("defteam"), "team")
    finally:
        con.close()

    # A player's window is their previous games *in the training table* — the
    # same games feat_player_usage's lagged window counts — so a game with no
    # qualifying play still occupies a slot, as a zero.
    appearances: dict[str, list[Key]] = defaultdict(list)
    for row in rows:
        appearances[str(row["player_id"])].append((int(row["season"]), int(row["week"])))
    for games in appearances.values():
        games.sort()
    position_in_history = {
        (player, key): index
        for player, games in appearances.items()
        for index, key in enumerate(games)
    }

    def unit_window(table: dict[Key, dict[str, float]], season: int, week: int):
        keys = sorted(k for k in table if k[0] == season and k[1] < week)[-WINDOW:]
        return keys, [table[k] for k in keys]

    filled: dict[str, int] = defaultdict(int)
    for row in rows:
        player = str(row["player_id"])
        here = (int(row["season"]), int(row["week"]))

        index = position_in_history[(player, here)]
        player_keys = appearances[player][max(0, index - WINDOW):index]
        player_games = [players.get(player, {}).get(key, {}) for key in player_keys]

        team_keys, team_games = unit_window(offence.get(str(row["team"]), {}), *here)
        opp_keys, opp_games = unit_window(defence.get(str(row["opponent"]), {}), *here)

        for keys in (player_keys, team_keys, opp_keys):
            if keys and max(keys) >= here:
                raise ValueError(f"window for {player} at {here} reaches {max(keys)}: leakage")

        for specs, games in (
            (PLAYER_SPECS, player_games),
            (TEAM_SPECS, team_games),
            (OPPONENT_SPECS, opp_games),
        ):
            for name, numerator, denominator in specs:
                value = _window_value(games, numerator, denominator)
                row[name] = None if math.isnan(value) else value
                filled[name] += not math.isnan(value)

    return {name: filled[name] / len(rows) for name in PBP_FEATURES}


# ---------------------------------------------------------------------------
# The experimental model: the challenger, plus the play-level columns.
# ---------------------------------------------------------------------------


@dataclass
class LightGBMPlayLevel(LightGBMComponents):
    """``lightgbm_components`` with :data:`PBP_FEATURES` added. Unregistered."""

    name: str = "lightgbm_components+pbp"
    version: str = "0.0.0-experiment"
    required_features: tuple[str, ...] = AVAILABLE_FEATURES + PBP_FEATURES

    def __post_init__(self) -> None:
        # The contract still governs every column that is in it. The play-level
        # columns are not in the feature table at all yet — that is the thing
        # under test — so they cannot be in the contract, and this model is
        # kept out of the registry for exactly that reason.
        assert_available(
            tuple(name for name in self.required_features if name not in PBP_FEATURES)
        )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def paired_difference(
    reference: BacktestResult, candidate: BacktestResult, value
) -> tuple[float, float, int]:
    """Mean of ``value(candidate) - value(reference)`` with a week-bootstrap SE.

    Paired on (player, season, week): both models scored the same rows, so the
    difference removes everything about a player-week that neither model could
    have known, which is most of the variance.
    """
    def keyed(result):
        return {
            (p.player_id, p.season, p.week): value(p)
            for p in result.predictions
            if value(p) is not None
        }

    a, b = keyed(reference), keyed(candidate)
    by_week: dict[Key, list[float]] = defaultdict(list)
    for key in a.keys() & b.keys():
        by_week[(key[1], key[2])].append(b[key] - a[key])

    weeks = [(sum(v), len(v)) for _, v in sorted(by_week.items())]
    total_n = sum(n for _, n in weeks)
    mean = sum(s for s, _ in weeks) / total_n

    rng = random.Random(SEED)
    draws = []
    for _ in range(DRAWS):
        s = n = 0.0
        for _ in range(len(weeks)):
            ws, wn = weeks[rng.randrange(len(weeks))]
            s += ws
            n += wn
        draws.append(s / n)
    centre = sum(draws) / len(draws)
    se = (sum((d - centre) ** 2 for d in draws) / (len(draws) - 1)) ** 0.5
    return mean, se, total_n


def headline(result: BacktestResult, baseline: BacktestResult) -> dict:
    inputs = acceptance_inputs(result, baseline)
    passed, reasons = meets_acceptance(**inputs)
    return {
        "crps": round(inputs["crps"], 4),
        "coverage_p10_p90": round(inputs["coverage_p10_p90"], 4),
        "width_p10_p90": next(
            (round(c.mean_width, 3) for c in result.coverage if c.nominal == 0.80), None
        ),
        "max_calibration_error": round(inputs["max_calibration_error"], 4),
        "max_conditional_bias": round(inputs["max_conditional_bias"], 4),
        "mae_by_position": {k: round(v, 4) for k, v in sorted(inputs["mae_by_position"].items())},
        "passed": passed,
        "failures": list(reasons),
    }


def gain_shares(rows: list[dict]) -> list[tuple[str, float]]:
    """Each feature's share of total split gain, averaged over components.

    One fit on every completed row. Descriptive only — it says what the trees
    leaned on, not what a feature is worth; the backtest answers that.
    """
    model = LightGBMPlayLevel()
    model.fit(rows)
    shares: dict[str, float] = defaultdict(float)
    for booster in model._models.values():
        gains = booster.feature_importance(importance_type="gain")
        total = float(sum(gains)) or 1.0
        for name, gain in zip(booster.feature_name(), gains):
            shares[name] += float(gain) / total / len(model._models)
    return sorted(shares.items(), key=lambda item: -item[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seasons", type=int, nargs="+", default=list(VALIDATION_SEASONS))
    parser.add_argument("--profile", default="half_ppr")
    parser.add_argument("--pbp-db", type=Path, default=None,
                        help="DuckDB file holding raw_pbp (default: NFLFP_DB / data/nfl.duckdb)")
    parser.add_argument("--out-dir", default="artifacts")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    started = time.monotonic()

    with session_scope() as session:
        rows = load_rows(session, completed_only=True)
    reach = attach(rows, args.pbp_db or duck.db_path())

    baseline = run_backtest(
        get_model_factory("baseline_l4"), rows, test_seasons=args.seasons,
        profile=args.profile, fit_distribution=False,
    )
    reference = run_backtest(
        get_model_factory("lightgbm_components"), rows,
        test_seasons=args.seasons, profile=args.profile,
    )
    candidate = run_backtest(
        LightGBMPlayLevel, rows, test_seasons=args.seasons, profile=args.profile
    )

    ref, cand = headline(reference, baseline), headline(candidate, baseline)

    lines = [
        "PLAY-LEVEL FEATURES — do they earn a place in the feature table?",
        "=" * 88,
        f"seasons {args.seasons[0]}-{args.seasons[-1]}, {args.profile}; "
        f"{len(PBP_FEATURES)} lagged play-by-play features added to lightgbm_components,",
        "nothing else changed. Feature list fixed before evaluation; none removed after.",
        "",
        f"  {'':<24}{'lightgbm_components':>22}{'+ play-level':>18}",
    ]
    for key in ("crps", "coverage_p10_p90", "width_p10_p90",
                "max_calibration_error", "max_conditional_bias"):
        lines.append(f"  {key:<24}{ref[key]!s:>22}{cand[key]!s:>18}")
    for position in sorted(ref["mae_by_position"]):
        lines.append(
            f"  {'MAE ' + position:<24}{ref['mae_by_position'][position]!s:>22}"
            f"{cand['mae_by_position'][position]!s:>18}"
        )
    for label, verdict in (("lightgbm_components", ref), ("+ play-level", cand)):
        lines.append(f"  ACCEPTANCE {label}: {'PASS' if verdict['passed'] else 'FAIL'}")
        lines.extend(f"    - {reason}" for reason in verdict["failures"])

    lines += ["", "PAIRED DIFFERENCE (+ play-level minus reference; negative is better)",
              f"  standard errors from {DRAWS:,} resamples of whole weeks, seed {SEED}"]
    paired: dict[str, dict] = {}
    comparisons = [("CRPS, all", lambda p: p.crps, None)] + [
        (f"CRPS, {position}", lambda p: p.crps, position) for position in ("QB", "RB", "TE", "WR")
    ] + [("abs error, all", lambda p: abs(p.error), None)]
    for label, value, position in comparisons:
        def scoped(p, value=value, position=position):
            return value(p) if position is None or p.position == position else None

        mean, se, n = paired_difference(reference, candidate, scoped)
        paired[label] = {"mean": round(mean, 5), "se": round(se, 5), "n": n}
        lines.append(
            f"  {label:<16} {mean:+.4f}  se {se:.4f}  "
            f"95% [{mean - 1.96 * se:+.4f}, {mean + 1.96 * se:+.4f}]  n={n:,}"
        )

    lines += ["", "REACH — share of rows where the feature is not missing"]
    lines.extend(f"  {name:<36}{share:6.1%}" for name, share in reach.items())

    shares = gain_shares(rows)
    pbp_total = sum(share for name, share in shares if name in PBP_FEATURES)
    lines += ["", "SPLIT GAIN — one fit on all completed rows; descriptive, not a verdict",
              f"  play-level features together: {pbp_total:.1%} of gain"]
    lines.extend(
        f"  {rank:>2}. {name:<36}{share:6.1%}{'  <- play-level' if name in PBP_FEATURES else ''}"
        for rank, (name, share) in enumerate(shares[:20], start=1)
    )
    lines.append(f"\n  total {time.monotonic() - started:.0f}s")

    report = "\n".join(lines)
    print(report)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pbp_feature_eval_report.txt").write_text(report, encoding="utf-8")
    (out / "pbp_feature_eval_metrics.json").write_text(
        json.dumps(
            {
                "seasons": args.seasons,
                "profile": args.profile,
                "features": list(PBP_FEATURES),
                "reference": ref,
                "candidate": cand,
                "paired": paired,
                "reach": {name: round(share, 4) for name, share in reach.items()},
                "gain_share_play_level": round(pbp_total, 4),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
