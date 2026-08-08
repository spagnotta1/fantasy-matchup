# Data lineage

Every prediction input, traced from its origin to the API response.

The purpose of this document is to make three questions answerable without
reading code:

1. **Where did this number come from?** When a projection looks wrong, the fault
   is usually four layers below where it surfaced.
2. **What breaks if this provider changes?** Swapping a data source should have a
   bounded, visible blast radius.
3. **Is this feature legitimate?** A feature computed from information that did
   not exist before kickoff will backtest beautifully and fail in production.

Layers 1 and 2 are complete and Layer 3 is partly built (phase 3a: the bar, the
walk-forward harness, distributions and calibration). Layers 4–7 are described
as the contract they must honour; those sections are marked **planned**.

---

## The pipeline, end to end

```
 EXTERNAL SOURCES          ETL                  FEATURES            PREDICTION      BUSINESS       API
─────────────────── ─────────────────── ──────────────────── ─────────────── ──────────── ─────────

 nflverse parquet ──► raw_player_week ──┬─► feat_player_usage ──┐
 (GitHub releases)    raw_schedules   ──┤   feat_defense_game   │
                      raw_snap_counts ──┤   feat_defense_*_rolling
                      raw_injuries    ──┤                       ├─► feat_training_dataset
                      raw_players     ──┘                       │          │
                                        ┌─► feat_game_context ──┘          │
 Open-Meteo ────────► weather_forecasts─┤                                  ▼
 (forecast)                             │                            model_runs
                                        │                            projections ──► services ──► GET /...
 ESPN scoreboard ───► odds_snapshots ───┘                            projection_points   (planned)   (planned)
 (live market)
                                             ▲                            ▲
                      nflfp.pipeline    nflfp.features            nflfp.predict (3a built)
                      nflfp.etl         (matviews)
                           ▲
                      nflfp.jobs (scheduling, run log)
```

The boundary that matters: **the prediction engine reads
`feat_training_dataset` and nothing below it.** It never touches `raw_*`, never
calls a provider, never joins a snapshot table. That is what allows a provider
to be replaced without the model noticing.

---

## Layer-by-layer trace

### 1. Sources

| source | transport | auth | what it uniquely provides |
|---|---|---|---|
| nflverse | parquet over HTTPS, read by DuckDB | none | all historical facts: box scores, snaps, injuries, schedules, rosters |
| Open-Meteo | JSON REST | none | **forecast** conditions — nflverse's `temp`/`wind` are observed after kickoff |
| ESPN scoreboard | JSON REST | none | **live** spread/total/moneyline — nflverse ships closing lines only |

Neither new provider needs a key, so the whole pipeline runs from a clean
checkout. Both are swappable through `nflfp/providers/registry.py`; the natural
paid upgrades are a commercial forecast API and The Odds API (multi-book).

### 2. ETL → raw tables

| target | writer | update mode | lifecycle |
|---|---|---|---|
| `raw_*` | `nflfp.pipeline` | two-phase load + atomic swap | schema follows nflverse; swapped weekly |
| `weather_forecasts` | `nflfp.etl.external` | append-only, change-detected | app-owned, Alembic-managed |
| `odds_snapshots` | `nflfp.etl.external` | append-only, change-detected | app-owned, Alembic-managed |

Snapshot tables keep history rather than current state, because line movement
and forecast revision are themselves predictive. "Latest known" is resolved at
read time with `DISTINCT ON (game_id) ... ORDER BY captured_at DESC`.

Change detection means an unchanged poll is not stored. Without it, hourly odds
polling would write ~24 rows per game per day whether or not the market moved.

### 3. Model layer (views)

`game_team` flips the schedule to one row per (game, team) and normalises
`spread_line` — which nflverse signs from the *home* team's perspective — into
`team_spread`, "points this team is favoured by". Verified at
`corr(team_spread, actual margin) = +0.449`.

`player_week` joins box score, game context, snaps and injury designation, and
computes fantasy points for four scoring profiles from components.

### 4. Feature engineering

Seven materialized views. Build order is dependency order:

| view | grain | source | model-ready? |
|---|---|---|---|
| `feat_defense_game` | season, week, defence | `player_week` | **no** — same-week facts |
| `feat_defense_position` | + position | `player_week` | **no** — same-week facts |
| `feat_defense_rolling` | season, week, defence | `feat_defense_game` | yes — lagged, ranked 1–32 |
| `feat_defense_position_rolling` | + position | `feat_defense_position` | yes — lagged, ranked 1–32 |
| `feat_game_context` | game, team | `game_team` + both snapshot tables | yes |
| `feat_player_usage` | player, season, week | `player_week` | yes — all windows lagged |
| `feat_training_dataset` | player, season, week | the four above | yes — **the model's only input** |

The two `_game`/`_position` views are deliberately *not* model-ready: they
aggregate the week they describe. Only their rolling descendants, whose windows
end one week back, may be fed to a model. The naming makes the distinction
visible and the tests enforce it.

### 5. Prediction engine — **phases 3a + 3b built**

Reads `feat_training_dataset`; writes `model_runs`, `projections`,
`projection_points`. Built: the dataset loader, leakage-proof walk-forward splits, the
`baseline_l4` bar, the `shrinkage_eb` model, held-out residual distributions,
full calibration analysis, and versioned persistence.

**The feature contract** (`predict/features.py`) is the second half of the
leakage rule. Lagging cannot catch a column whose *stored history* was measured
under different conditions than the value available for an upcoming game —
market lines and weather are both that. Models declare `required_features` and
`assert_available()` refuses anything excluded; a test runs it over every
registered model.

**Components, not points.** The engine predicts stat components; points are
derived by `nflfp.scoring.points_for` — the same `ScoringRules` that scored the
training targets, rendered to Python instead of SQL. Verified equal across
20,000 player-weeks and all five profiles.

`predict/scoring_bridge.py` owns the column-name seam between
`feat_training_dataset` (`fumbles_lost_actual`) and the scoring rules
(`fumbles_lost_total`). It is an explicit table, not a string rule: deriving it
by pattern silently mis-scored 1,018 player-weeks.

Contract:

- one `model_runs` row per execution, carrying algorithm, version, params,
  metrics and code SHA, so any projection can be traced to what produced it;
- projections are **scoring-agnostic** components; points are written once per
  scoring profile;
- a run becomes visible by moving to `published`, guarded by a partial unique
  index allowing one published run per `(model_name, season, week)`.

### 6. Business services — **planned**

Combines projections with warehouse dimensions into player profiles, matchup
analysis, rankings and start/sit calls. This is where `matchup_score` becomes a
letter grade — stored as a number precisely so the thresholds live in one place.

### 7. REST API — **planned**

Reads business services only. No SQL, no model invocation, no provider calls in
a request path.

---

## Field-level trace: a single projection

Following `predicted_points` for one player in one week, all the way down:

| # | stage | object | what happens |
|---|---|---|---|
| 1 | source | nflverse `stats_player_week_2026.parquet` | targets, receptions, yards, snaps |
| 2 | source | ESPN scoreboard | DraftKings spread −3.5, total 44.5 |
| 3 | source | Open-Meteo | 41.5 °F, 12.5 mph wind at the kickoff hour |
| 4 | ETL | `raw_player_week`, `odds_snapshots`, `weather_forecasts` | validated, stored |
| 5 | view | `player_week` | box score + context + snaps + injury, four scoring profiles |
| 6 | view | `game_team` | `spread_line` → `team_spread` (sign normalised) |
| 7 | feature | `feat_player_usage` | `snap_pct_l4` = mean of the **previous 4** games |
| 8 | feature | `feat_game_context` | `implied_team_total` = total/2 + team_spread/2, market preferred over nflverse |
| 9 | feature | `feat_defense_position_rolling` | opponent's fantasy points allowed to this position, lagged, ranked |
| 10 | feature | `feat_training_dataset` | the joined row the model sees |
| 11 | model | components projected and **shrunk** toward a positional prior; `explain` records source and shrink weight |
| 12 | model | `score_components()` → points per profile; held-out residual quantiles → P10/P25/P50/P75/P90, SD, boom, bust |
| 13 | persist | `projections` | components + `features` JSONB; `model_runs` carries version, feature version, params, code SHA, data snapshot |
| 14 | persist | `projection_points` | one row per scoring profile, with `calibration_method` and `distribution_samples` |
| 15 | simulate | `load_distribution()` | the interface the Monte Carlo engine calls — a full distribution, never `expected ± a percentage` |
| 13 | service *(planned)* | player profile | `matchup_score` → letter grade |
| 14 | API *(planned)* | `GET /projections` | JSON |

Step 11's `features` column is what makes this traceable in production:
`model_runs.feature_schema_version` says how to interpret it, so a projection
from three weeks ago can still be explained after the feature set has moved on.

---

## Provenance and fallbacks

Two feature columns record where their value came from, because a model trained
on one distribution and served another is a silent failure:

| column | values | meaning |
|---|---|---|
| `spread_source` | `market` / `nflverse_close` / `none` | live line, closing line, or unpriced |
| `weather_source` | `forecast` / `nflverse_observed` / `none` | forecast, post-game observation, or unknown |

For 2026 Week 1, all 32 team rows report `spread_source = 'market'` — nflverse
had a closing line for only 52 of the season's 272 games.

This matters for training: historical rows are `nflverse_close` (a settled
line), while inference rows are `market` (a moving one). Those are genuinely
different distributions, and the column is what lets a model account for it
rather than average over it.

---

## The leakage rule

It applies twice, once per layer.

**Layer 3: a model may only train on weeks that have already happened.**
`walk_forward()` yields folds where every training row strictly precedes the
test week, and `assert_no_leakage()` re-checks that against the rows themselves
rather than trusting the loop that produced them. A random train/test split
would let the model learn from week 12 to predict week 5 — no error, no visible
symptom, and validation numbers that are pure fiction.

**Layer 2: a feature may only use information available before kickoff.**

Mechanically: every rolling window ends at the previous week —
`ROWS BETWEEN n PRECEDING AND 1 PRECEDING`, never `CURRENT ROW`.

This is the single easiest thing to get wrong and the hardest to notice. A
leaked feature does not raise, does not look wrong in a row, and produces
excellent validation scores — until the model is asked to project a game that
has not been played.

Enforcement is in three places:

1. `lagged_window()` in `features/base.py` — no definition re-derives the frame;
2. a unit test rejecting any window ending at `CURRENT ROW` or
   `UNBOUNDED FOLLOWING`, applied to every registered view;
3. an integration test that recomputes `snap_pct_l4` from `player_week` for
   every row and asserts agreement — **0 disagreements across 56,518
   player-weeks**.

### Two deliberate asymmetries

| | window | crosses seasons? | why |
|---|---|---|---|
| player usage | 4 games | **yes** | last December is known in September, and usage is what persists year over year (r = 0.63–0.73). Gives Week 1 features at all: 298 of 338 Week 1 2024 rows. |
| player efficiency | 8 games | yes | efficiency barely persists (r ≈ 0.2), so a short window is mostly noise |
| defensive strength | 4 games | **no** | a defence turns over in the offseason in a way a player's role does not |

Both choices are asserted in tests, so neither drifts by accident.

---

## Change impact

| change | what moves | what does not |
|---|---|---|
| swap weather provider | one registry entry + one new file | ETL, features, model, API |
| swap odds provider | one registry entry + one new file | everything downstream |
| add a scoring profile | `scoring.PROFILES`, `ScoringProfile` enum | feature tables (points are per-profile rows) |
| add a feature | one `FeatureView` + a migration-free rebuild | model code (it reads the assembled table) |
| nflverse adds a column | pipeline widens the table automatically | features, unless the column is adopted |
| retrain a model | a new `model_runs` row; publish flips a flag | features, API contract |

---

## Known gaps

| gap | cause | resolution |
|---|---|---|
| success rate, explosive plays, pressure rate | need `raw_pbp`, an opt-in dataset not currently loaded | features already declare the dependency and are skipped; run `pipeline --all` to activate |
| travel distance | needs stadium-to-stadium distance | stadium coordinates already exist in `providers/stadiums.py` |
| forecasts beyond 16 days | Open-Meteo's horizon | games outside it are skipped with a reason, not failed |
| retractable roof state | genuinely unknown before kickoff | `roof_uncertain` flag rather than a guess in either direction |
| one sportsbook | ESPN exposes DraftKings only | The Odds API gives multiple books, at the cost of a key |
| **no projection exceeds ~25 points** | shrinkage compresses the top; only 5 observations landed in 25-30 and none above | the system cannot answer "is a 30+ projection calibrated?" because it does not make one. Elite-ceiling discrimination needs a richer model, not more shrinkage. |
| QB intervals slightly narrow | coverage 0.774 vs nominal 0.80 | QB scoring has a fatter tail than one pooled residual set captures; per-position residual shapes would help |
| thin-evidence intervals slightly narrow | 1 game of history: coverage 0.768 | residuals are dominated by 4-game-window players; conditioning on evidence needs more data than exists |
| boom max error 0.130 | one well-sampled bin (0.6-0.7, n=47) states 0.640 and delivers 0.511 | small absolute count; revisit as more seasons accumulate |
| ~~train/serve line shift~~ | **resolved** | market and weather features excluded and enforced — measured to add nothing beyond lagged usage |
