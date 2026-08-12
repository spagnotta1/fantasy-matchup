# nflfp — NFL fantasy projection data layer

Ingests [nflverse](https://nflverse.nflverse.com/) NFL data into **Postgres** as
the system of record, with a local **DuckDB** copy for fast exploration. A
weekly pipeline keeps the warehouse current.

All seven layers are complete: the warehouse and application schema, two
forward-looking external providers, a leakage-free feature layer, a scheduled
job system, a **frozen** projection engine, the business layer that turns its
output into rankings, matchups and start/sit calls, a REST API over the top, a
cache whose only invalidation event is a publish, and the deployment shape that
runs all of it from one image.

The API's distinguishing feature is that it never lets three kinds of number
blur together: what the model predicted, what was derived above the model, and
what is merely observed context the model does not use. See
[provenance](#three-kinds-of-number-kept-apart-on-the-wire).

See [`docs/lineage.md`](docs/lineage.md) for how every prediction input travels
from its source to the API.

## Architecture

```
nflverse parquet (GitHub releases)
        │  DuckDB reads over httpfs — no download step, no pandas, no API key
        ├──────────────► data/nfl.duckdb        local, for exploration
        └──────────────► Postgres (Railway)     system of record, feeds the app
                              ▲
                              └── weekly cron: python -m nflfp.pipeline refresh
```

Both targets are built from the same source and the same view definitions.
`scripts/verify_parity.py` proves they agree — see [Verification](#verification).

### Two-phase pipeline

The pipeline deliberately separates a slow, fallible phase from a fast, atomic one:

1. **Load** — DuckDB reads nflverse parquet over HTTP and writes it into
   Postgres *staging* tables via `ATTACH`. Network-bound and safe to fail:
   nothing user-visible has changed yet.
2. **Publish** — one Postgres transaction swaps staging into the live tables,
   recreates indexes and rebuilds the views. Readers never see a half-updated
   warehouse, and a failure mid-publish rolls back completely.

### Refresh strategy

Each dataset declares how it updates (`refresh` in `sources.py`):

| strategy | datasets | what happens weekly |
|---|---|---|
| `by_season` | player_week, snap_counts, injuries, rosters, pbp, pfr_* | reload only the current season's file, `DELETE` those rows, reinsert |
| `full` | schedules, players, teams, depth_charts, ngs_* | reload whole (single-file sources, or no usable season column) |

`by_season` **never** falls back to a table swap. In refresh mode staging holds
only the current season, so a swap would silently delete every prior year. If
nflverse adds columns, the live table is widened and the insert uses the shared
column list instead.

## Quick start

### Local Postgres

```powershell
docker run -d --name nflfp-pg -e POSTGRES_PASSWORD=nflfp -e POSTGRES_USER=nflfp `
  -e POSTGRES_DB=nflfp -p 55432:5432 postgres:16

$env:DATABASE_URL = "postgresql://nflfp:nflfp@localhost:55432/nflfp"

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

.\.venv\Scripts\python.exe -m nflfp.pipeline full     # first build, ~21s
.\.venv\Scripts\python.exe -m nflfp.pipeline status
```

### Local DuckDB (exploration)

```powershell
.\.venv\Scripts\python.exe -m nflfp.ingest            # ~13s, 47 MB
.\.venv\Scripts\python.exe -m nflfp.explore --tables
```

### Commands

```powershell
python -m nflfp.pipeline full                 # rebuild everything, 2016-2026
python -m nflfp.pipeline refresh              # weekly job: current season only
python -m nflfp.pipeline refresh --seasons 2025 2026
python -m nflfp.pipeline refresh --only player_week snap_counts
python -m nflfp.pipeline status               # run history from pipeline_runs

python -m nflfp.ingest --list                 # dataset manifest
python -m nflfp.ingest --all                  # + play-by-play, NGS, PFR, FTN

python -m nflfp.explore --probe               # list canned probes
python -m nflfp.explore --probe usage         # against DuckDB
python -m nflfp.explore --probe usage --pg    # against Postgres
python -m nflfp.explore --schema player_week
python -m nflfp.explore --sql "SELECT ..." --pg

python scripts/verify_parity.py               # DuckDB vs Postgres
```

## Schema

```
raw_*                 materialised nflverse tables (the only real state)
game_team             one row per (game, team) — schedule flipped to team perspective
player_week           the modelling fact table: box score + game context + snaps + injury
upcoming_games        games with no result yet — what you actually project
pipeline_runs         one row per pipeline execution: mode, status, rows, duration
pipeline_run_datasets per-dataset detail for each run
```

Everything except `raw_*` and the run log is a **view**, so reshaping the model
layer costs nothing and can't drift out of sync with a load.

### Two owners, one database

The schema is split into zones with different lifecycles, and the split is
enforced in code rather than by convention:

| zone | owner | lifecycle |
|---|---|---|
| `raw_*`, `stg_*` | `nflfp.pipeline` | `DROP`/`RENAME`-swapped from parquet each run; columns follow nflverse |
| `player_week`, `game_team`, `upcoming_games` | `nflfp.transform` | dropped and recreated on every publish |
| `model_runs`, `projections`, `projection_points`, `pipeline_runs` | **Alembic** | versioned migrations |

`nflfp/db/alembic_guard.py` is what keeps those apart. Without it,
`alembic revision --autogenerate` compares the live database against the ORM
metadata, finds eight tables it has never heard of, and writes
`op.drop_table("raw_player_week")` — verified: it proposes **54 operations
including 8 table drops**. With the guard it proposes nothing. That is a safety
interlock, not a tidiness measure, which is why it lives in the package with its
own tests.

The same boundary forbids foreign keys pointing *into* the warehouse: a
`REFERENCES raw_players(gsis_id)` would either block the weekly swap or be
destroyed by the `CASCADE` that performs it. Projections carry `player_id` and
`game_id` as plain natural keys.

### Application schema

```
model_runs         lineage — which model, version, params, metrics, status
projections        one row per (run, player, week), scoring-agnostic:
                   projected usage + production + matchup/injury/weather scalars
projection_points  one row per (projection, scoring_profile):
                   predicted / floor / median / ceiling, confidence, boom, bust
```

Points are split from components deliberately. A projection's *components* are
facts about football; its *points* exist once per league format. Flattening them
would store ~30 component columns four times per player-week and make "add TE
premium" a data migration. Split, a new format is a few narrow rows.

`matchup_score` is stored as a number, not a letter grade — the grade is derived
above the database so the thresholds live in one place.

Publishing is a flag, not a table swap: a partial unique index allows only one
`published` run per `(model_name, season, week)`, so promoting or rolling back a
model is a one-row `UPDATE` inside a transaction, with the previous run still on
disk.

```powershell
alembic upgrade head            # apply migrations
alembic upgrade head --sql      # print the DDL a deploy would run, for review
alembic downgrade base          # verified round trip
```

Migrations inline their enum values rather than importing `nflfp.db.enums`: a
migration is a historical record and must keep producing the schema it produced
the day it was written.

Current core build: **1,854,291 rows**, 182,252 player-weeks across 2016–2025,
plus the full 2026 schedule (272 games, of which **52** carry a closing
spread/total — which is why Layer 2 adds a live market feed).

## Layer 2 — providers, features, jobs

nflverse covers everything that is knowable *after* a game. Two things are only
knowable *before* one, and those are what `nflfp.providers` adds:

| | nflverse gives you | why that is not enough | provider |
|---|---|---|---|
| weather | `temp`/`wind`, observed | **0 of 272** games on the 2026 schedule have either | Open-Meteo (no API key) |
| market | `spread_line`/`total_line`, closing | only **52 of 272** posted, and stale by kickoff | ESPN scoreboard (no API key) |

Nothing downstream imports a concrete provider. Code depends on the protocols in
`providers/base.py` and resolves implementations through `providers/registry.py`,
so swapping Open-Meteo for a paid forecast service is one registry entry.
Setting `WEATHER_PROVIDER=null` disables a feed without removing its job — it
still runs, still logs, still reports zero.

Snapshots are **append-only and change-detected**. Line movement is itself a
feature, so nothing is overwritten; but an unchanged poll is not stored either,
which is what stops hourly polling writing thousands of identical offseason rows
and keeps the table a genuine line-movement history.

### Feature layer

Seven materialized views, built in dependency order (~6s over ten seasons):

```
feat_defense_game ─┐
feat_defense_position ─┤
                       ├─► feat_defense_rolling ──────┐
                       └─► feat_defense_position_rolling ─┤
feat_game_context ────────────────────────────────────────┤
feat_player_usage ────────────────────────────────────────┴─► feat_training_dataset
```

They are **ETL-owned, not Alembic-owned**, for the same reason the plain views
are: they read `raw_*`, and a `full` publish drops those `CASCADE`, taking any
dependent matview with them. Each declares a unique index so refresh can run
`CONCURRENTLY` — the non-concurrent form takes an `ACCESS EXCLUSIVE` lock, which
on a Sunday morning is an outage.

**The rule everything else follows from: a feature may only use information
available before kickoff.** Every rolling window ends at the *previous* week
(`ROWS BETWEEN n PRECEDING AND 1 PRECEDING`). A same-week aggregate would
backtest beautifully and be worthless in production, because on Thursday the
current week has not happened. `lagged_window()` exists so no definition
re-derives this, and the tests reject any frame ending at `CURRENT ROW`.

Two window choices are deliberately opposite, and both are tested:

- **player usage crosses the season boundary** — last December is genuinely
  known in September, and it is what gives Week 1 any features at all (298 of
  338 Week 1 2024 rows get a history this way). Defensible because usage is
  precisely what persists year over year (r = 0.63–0.73).
- **defensive windows reset each season** — a defence turns over in the
  offseason in a way a player's role does not.

Play-level metrics (success rate, explosive plays, pressure rate) need
`raw_pbp`, which is opt-in and not loaded. Those features declare it as a
dependency and are skipped until it exists. EPA allowed *is* available without
it, because nflverse pre-aggregates EPA onto the weekly stats.

### Jobs

Schedules are declared in `jobs/registry.py`, never inside a provider — cadence
is an operational decision that changes with the season, and it must not be a
code change to the thing that talks to the network.

```powershell
python -m nflfp.jobs list                        # jobs and cadences
python -m nflfp.jobs run refresh_odds            # manual execution
python -m nflfp.jobs run refresh_weather --horizon-days 3
python -m nflfp.jobs run-all
python -m nflfp.jobs status                      # run history
python -m nflfp.jobs schedule                    # Railway cron config
```

| job | cadence | why |
|---|---|---|
| `refresh_odds` | hourly | fastest-moving input; one request per week of games |
| `refresh_weather` | 6-hourly | forecast models publish ~4x/day; polling faster returns the same numbers |
| `refresh_injuries` | daily | practice reports land Wed/Thu/Fri and a designation flips on Saturday |
| `build_features` | weekly, after the nflverse load | full rebuild is ~6s, so no need for incrementality yet |
| `refresh_features` | hourly | concurrent refresh propagates new snapshots without blocking readers |
| `generate_projections` | weekly, after the feature build | see [Layer 6](#layer-6--background-jobs-and-caching) |
| `warm_cache` | hourly | the first request after a publish should not be the one that pays |
| `evaluate_model` | weekly, the day after a projection run | a model whose accuracy drifts does not announce itself |
| `backfill_projections` | **manual only** | a catch-up run, not a cadence — once the history is published the weekly job keeps it current |
| `invalidate_cache` | **manual only** | publishing already invalidates; a cron would discard the cache on a timer |

Failure is survivable: a non-critical job that fails is recorded and the batch
continues, so an odds outage cannot stop the feature build running on data
already in the warehouse. The run log is written on its own transaction, so a
failing job cannot roll back the record of its own failure.

## Layer 3a — the prediction bar and the harness

The prediction engine reads `feat_training_dataset` and nothing below it, runs
offline, and writes through Layer 1's schema. Phase 3a builds the *measurement*
before any modelling: the bar, the harness, and the calibration report.

### What the model predicts

**Components, not points.** The engine projects targets, carries, yards and
touchdowns; `nflfp.scoring.points_for` converts those to points per league
format. One model serves all four scoring profiles, `projections` stays
scoring-agnostic as Layer 1 assumes, and the output is explainable — "8.4
targets" rather than "14.2 points".

`ScoringRules` is now rendered twice: to SQL for scoring history, to Python for
scoring projections. Two renderers can drift, so a test evaluates both over
20,000 real player-weeks across all five profiles and requires exact agreement.

### The bar

```powershell
python -m nflfp.predict models
python -m nflfp.predict backtest baseline_l4 --seasons 2023 2024 2025
python -m nflfp.predict calibration baseline_l4
python -m nflfp.predict compare
```

`baseline_l4` — "last four games", what a human does by eye — walk-forward over
2023-25, 54 weeks, 17,666 predictions:

| position | n | MAE | RMSE | bias | r | Spearman |
|---|---|---|---|---|---|---|
| QB | 1,991 | 6.63 | 8.44 | +0.29 | 0.465 | 0.454 |
| RB | 4,584 | 4.26 | 6.10 | +0.04 | 0.606 | 0.671 |
| TE | 3,694 | 3.18 | 4.52 | +0.02 | 0.493 | 0.532 |
| WR | 7,397 | 4.05 | 5.74 | +0.08 | 0.539 | 0.602 |

Nothing ships without beating this. Shipping a model that does not would be
worse than shipping nothing — it carries the authority of a model without the
accuracy.

### Walk-forward, never random

Layer 3's version of Layer 2's lag rule: train on weeks < N, predict week N.
A random split on time-series data lets a model learn from week 12 to predict
week 5 — it does not error, and it produces validation numbers that are
fiction. `assert_no_leakage()` re-checks each fold against the rows themselves
rather than trusting the loop that built them.

### Distributions and calibration

Floor/median/ceiling come from **empirical residual quantiles** bucketed by
position and projected volume — not a Gaussian, because weekly scoring is
right-skewed with a hard floor near zero.

The acceptance test is calibration: a stated 20% bust probability must be wrong
20% of the time. Two metrics are reported, and the second exists because of what
it caught:

```
calibration ECE: boom=0.006, bust=0.015
calibration max: boom=0.212, bust=0.064   <- worst well-sampled bin
```

ECE is sample-weighted, so it rated boom probabilities near-perfect while the
0.9-1.0 bin stated 94% and delivered 17%. High-confidence projections are
exactly the ones a user acts on, so `max_calibration_error` is reported beside
it. **Boom probabilities are not yet fit to ship** — see the gaps below.

## Layer 3b — honest distributions

3a exposed that a 32-point L4 projection actually returns **18** points. That
mis-centred point estimate, not the interval around it, is why boom
probabilities stated 94% and delivered 17%. 3b fixes the centre, then builds the
distribution on genuinely held-out residuals.

### Shrinkage (`shrinkage_eb`)

Empirical Bayes, `shrunk = (n·player + k·prior) / (n + k)` with
`k = σ²_within / σ²_between` computed per position and component from the
training fold. `k` reads as *the number of games of evidence the prior is
worth*; nothing is hand-tuned. Sample size enters only as `n`, because measured,
its effect on residual spread is negligible once projection level is controlled
for (4.32 vs 4.21 within a band) — not a signal worth a parameter.

### Held-out residuals

```
weeks < N ──► fit model ──► predict week N
     │                            │
     └── residuals from earlier ──┴──► fit distribution ──► evaluate on week N
```

Each residual is out-of-fold twice: with respect to the model that produced it,
and in the past relative to the week it describes. 3a fitted residuals on the
same predictions it scored, which understates width.

Residual bins are **equal-count** (300 obs), so resolution follows data density
instead of pooling a 35-point projection with an 18-point one. Projections
beyond the fitted range are flagged `extrapolated` rather than given a
confident interval.

### `expected_points` vs `predicted_points`

Both are stored. `predicted_points` is the model's raw output, kept for lineage;
it is conditionally biased because shrinkage trades bias for variance.
`expected_points` is the mean of the held-out distribution — the calibrated
number, and what a simulator should use.

### Results — walk-forward 2019-2025, 38,061 held-out distributions

```
INTERVAL COVERAGE      P10-P90  0.803 (nominal 0.80)  width 13.2
                       P25-P75  0.507 (nominal 0.50)  width  6.7
                       CRPS 2.927   pinball 1.440

CALIBRATION            boom  ECE=0.001  max=0.130
                       bust  ECE=0.006  max=0.014

BY PROJECTION RANGE    0-5    n=17,702  bias +0.09  cov80 0.808
                       5-10   n=10,866  bias -0.08  cov80 0.798
                       10-15  n= 7,017  bias -0.06  cov80 0.806
                       15-20  n= 2,217  bias +0.06  cov80 0.783
                       20-25  n=   254  bias +0.09  cov80 0.795
                       25-30  n=     5  (!! too few to judge)
```

Conditional bias is within ±0.1 points in every band with a usable sample,
against −14.1 for the raw 4-game average at the top.

### `spread_source` resolution: measure, then drop

Market features are **excluded from the model**. nflverse's `spread_line` is a
settled closing line for played games but a live market capture for upcoming
ones (verified: identical to our ESPN capture, corr 1.0000), so training and
serving see different objects.

Rather than manage the shift, it was measured. Correlation with the *residual*
of the lagged baseline, 2019-2025:

| | QB | RB | TE | WR |
|---|---|---|---|---|
| corr(implied total, points) | 0.235 | 0.089 | 0.117 | 0.099 |
| corr(implied total, l4 residual) | **−0.039** | **0.011** | **0.021** | **−0.001** |

The raw correlation is confounded — good players on good offences have both. The
market adds nothing measurable, so dropping it removes the whole class of
problem instead of papering over it. Weather is excluded for the same reason
(history has observations, upcoming games have forecasts).

`predict/features.py` makes this enforceable: models declare
`required_features` and `assert_available()` refuses anything unavailable at
prediction time. A test runs it over every registered model.

### Reproducing

```powershell
python -m nflfp.predict compare
python -m nflfp.predict backtest shrinkage_eb --seasons 2022 2023 2024 2025
python -m nflfp.predict calibration shrinkage_eb
python -m nflfp.predict project shrinkage_eb --season 2025 --week 18 --publish
```

## Layer 4 — the business layer

Everything the application can answer is answered in `nflfp.services`, and the
web layer above it is meant to contain no football at all: validate a request,
call one function, serialise the result. That is enforced by shape rather than
by convention — nothing in the package imports a web framework, nothing raises
an HTTP exception, and nothing returns a Pydantic model.

```
catalog     when and what format   ─┐
projections slate, rankings, a week │
players     search, profile, history├─► assemble (pure) ─► grading, distributions
matchups    a game from both sides  │         ▲
advice      start/sit, compare      │         │
rosters     a named set + its gaps ─┘   repository (the only SQL)
```

`rosters` is the newest and the odd one out: it answers a question about a
*set* of players rather than about a board or a pair. Its contract is that
nothing is dropped silently — every requested id comes back either as a
projection or as a typed reason it has none — because the consumer it exists
for sums those players into a team score, where a missing row is not a smaller
answer but a wrong one. See `docs/simulation-readiness.md`.

The split exists so the interesting parts don't need a database. Tier
boundaries, grade thresholds, toss-up cutoffs and the head-to-head integral are
unit-tested against constructed inputs; only the queries need Postgres. A wrong
grade boundary renders perfectly and changes what people start, which is
exactly the kind of bug an integration test is bad at catching.

### Distributions are the product

`projection_points` stores five percentiles. `services/distributions.py`
reconstructs a monotone piecewise-linear quantile function through them, which
**passes through the stored percentiles exactly** and assumes nothing about the
shape — Layer 3b chose empirical residual quantiles over a Gaussian precisely
because weekly scoring is right-skewed with a hard floor, and fitting a normal
at the last step would throw that away.

Three things fall out of having a real curve:

- **Start/sit is a probability, not a points comparison.** "Start A, 12.4 vs
  11.8" states an edge smaller than the model's own mean absolute error.
  `P(A > B)` is integrated over the two curves — one deterministic pass, no
  sampling, because a recommendation that changes on refresh is not a
  recommendation — and a half-point gap correctly returns 52% and an explicit
  toss-up. **Below 58% no player is named.**
- **Tiers mean something.** Two adjacent players stay in one tier while the
  lower still has ≥45% chance of outscoring the one above. A fixed points gap
  would produce enormous tiers at the top of a board and singletons at the
  bottom, purely because scoring is heteroscedastic.
- **Mean and odds can disagree**, and it is reported rather than resolved. A
  player with the higher projection but a fatter left tail is *less* likely to
  win the week. That case is the whole reason distributions are stored, and a
  points-only comparison gets it backwards.

### Defensive form is computed at read time, not read

`feat_defense_position_rolling` looks like the obvious source for a matchup
grade and is the wrong one. It derives from `feat_defense_position`, which is
restricted to completed games — so **there is no row for the week you are
projecting**, the only week anyone cares about. Its latest row is week N-1,
whose window covers N-5 to N-2, a game staler than necessary.

So the repository aggregates `feat_defense_position` directly with a
`week < :week` cutoff. That produces the genuinely correct "last four games
before this one" for completed and upcoming weeks alike, keeps the lag rule the
whole feature layer obeys, and costs an aggregation over ~2,300 rows per
season. No new materialized view was needed to answer the headline question.

### What the grade actually claims

A matchup grade is a **rank percentile**, so by construction about 2.5 defences
hold each letter every week. An "A" means "top few matchups this week", not
"unusually good in absolute terms" — different claims, and only the first is
supported by a rank. The magnitude claim travels beside it as
`fp_allowed_vs_position_l4`, in points, because either number alone misleads.

Below three games of defensive history the grade is **withheld with a reason**
rather than softened. Week 1 has no defensive history at all, so every Week 1
matchup is ungraded — correct, and much better than a confident letter derived
from last season's defence.

### Context that is reported, never applied

The brief asks for injury impact and weather impact. The honest answer is that
the model uses neither: Layer 3b measured market and weather against the
baseline's residual, found −0.039 to +0.021 across positions, and excluded
them. So `GameContext`, `WeatherContext` and `InjuryContext` each carry
`applied_to_projection = False`, and a designation of "Out" is surfaced as a
hard caveat *above* the statistical verdict rather than silently zeroing a
projection — which would destroy the distinction between "projected zero" and
"not playing".

A fabricated "weather impact: −8%" would be worse than useless. Observed
conditions, clearly labelled as context the model did not use, are both true
and still what a user wants.

### Operational shape

- An **unpublished week returns an empty slate, not an error.** The projection
  job not having run is a state a UI renders as "projections coming Thursday";
  a 404 makes it indistinguishable from a bad URL. `Slate.model is None` is the
  flag to branch on.
- **"This week" resolves forward.** The default is the earliest week with a game
  that has no result — the week a lineup is being decided — falling back to the
  latest completed week once the season ends. Every response reports which.
- A **dropped materialized view names itself and the command that fixes it.**
  A `pipeline full` publish drops `raw_*` with `CASCADE`, taking dependent
  matviews with it; that must not surface as `relation "feat_player_usage" does
  not exist` from 400 lines of SQL.
- One query per slate. Fetching projections, then usage, then defence, then
  market is four round-trips and an N+1 the first time somebody loops.

### Reproducing

```powershell
pytest tests/test_services_grading.py tests/test_services_distributions.py `
       tests/test_services_assemble.py tests/test_services_advice.py    # no database

$env:DATABASE_URL = "postgresql://..."
pytest tests/test_services_repository.py tests/test_services.py        # real SQL
```

The integration tests build the warehouse and feature relations as **stub
tables with the real column names** (`tests/warehouse_stub.py`) rather than
running the pipeline: week 10 scheduled but unplayed, weeks 1-9 complete, and
`position` deliberately present on three of the joined relations. A test that
needs a 1.8-million-row nflverse load to check a join is a test nobody runs.

## Layer 5 — the REST API

```powershell
python -m nflfp.api --reload             # http://localhost:8000/docs
```

Use the module entry point rather than `uvicorn nflfp.api.main:app` directly.
On Windows uvicorn selects `ProactorEventLoop` whenever it is *not* running
under a reloader, and psycopg's async driver refuses to run on it — so the
plain uvicorn command starts cleanly, serves `/health` as `degraded`, and fails
every database request with an `InterfaceError` that mentions neither uvicorn
nor Postgres. Worse, `--reload` happens to work, so the development command
succeeds and the production-shaped one silently does not. `python -m nflfp.api`
installs the selector policy and hands uvicorn `loop="none"`. Railway runs
Linux, where none of this applies.

A thin serialisation of `nflfp.services`. There is no football in
`nflfp/api/`: a route unpacks query parameters, calls exactly one service
function, maps the result onto a schema and attaches metadata. Anything more
than that is a missing function in the business layer.

The one thing this layer *adds* is **provenance**.

### Three kinds of number, kept apart on the wire

A projection screen mixes numbers that look identical and mean entirely
different things. Blurring them at the last step would waste every honesty
property the layers below worked for, so the split is in the schema — a field a
client reads every time, not a caveat in a guide it reads once.

| `provenance` | what it is | example |
|---|---|---|
| `model` | output of the frozen model run, carrying its measured guarantees | `prediction.points.expected` |
| `derived` | computed **above** the model from data it never saw | `matchup.grade`, `usage.snap_pct_l4` |
| `context` | observed, and **not** an input to the projection | `context.weather`, `context.game`, `context.injury` |
| `actual` | a recorded outcome, not a prediction at all | `history[].actual_points` |

```jsonc
{
  "prediction": { "provenance": "model",   "points": { "expected": 14.8, ... } },
  "matchup":    { "provenance": "derived", "applied_to_projection": false,
                  "source": "feat_defense_position", "grade": { ... } },
  "usage":      { "provenance": "derived", "snap_pct_l4": 0.82, ... },
  "context": {
    "provenance": "context",
    "weather": { "applied_to_projection": false, "multiplier": null,
                 "unapplied_reason": "The frozen model excludes weather...",
                 "wind_mph": 14.0, "is_adverse": false }
  }
}
```

The matchup grade is the interesting case. It is **real analysis** — a trailing
four-game aggregate of defensive fantasy points allowed, ranked within position
— and the model has never seen it. Calling it `model` would imply it was
validated as a prediction; calling it `context` would understate it. It is
`derived`, with `applied_to_projection: false` beside it.

### The extension point is wired, not promised

`projections` already carries `injury_multiplier` and `weather_multiplier`, and
the read path already reads them. Today they are `NULL`, so every context block
reports `applied_to_projection: false` with a reason. The moment a future engine
writes one, the same field a client is already rendering starts saying
something different — no schema version, no client change, no edit to the API.

That is asserted rather than asserted-in-prose: `tests/test_api.py` writes a
multiplier into the database mid-test and checks the flag flips over HTTP.

### Endpoints

```
GET /api/v1/projections                  ranked board, filterable
GET /api/v1/projections/{player_id}      one player's week
GET /api/v1/rankings/{position}          single-position board
GET /api/v1/players                      browse the index, paged and filterable
GET /api/v1/players/{id}/profile         projection + history + accuracy
GET /api/v1/players/{id}/history         completed weeks vs what was stored
GET /api/v1/search?q=                    name search
GET /api/v1/games                        the schedule
GET /api/v1/weeks/{week}                 a week: schedule + is there a board yet
GET /api/v1/matchups/{game_id}           one game, both sides, per position
GET /api/v1/defense-rankings             which defences to attack
GET /api/v1/teams/{team}/outlook         a team's week
GET /api/v1/start-sit?player_a=&player_b= head-to-head call
GET /api/v1/compare?player_ids=          up to six players
GET /api/v1/meta/model                   the frozen foundation, audited
GET /api/v1/meta/positions               what is projected, and why not
GET /api/v1/meta/provenance              the label legend
GET /api/v1/meta/cache                   which endpoints are cached, and why
GET /api/v1/health                       liveness + database + cache
GET /api/v1/health/live                  process only — the platform's check
GET /api/v1/health/ready                 dependencies — the load balancer's

POST /api/v1/mock-draft/analyze          one draft position, simulated
POST /api/v1/mock-draft/compare          every draft position, ranked
GET  /api/v1/mock-draft/config           bounds, and which seasons can be drafted
```

Every response is `{"data": ..., "meta": ...}`. `meta` carries the resolved
window (and *how* it resolved), the published run behind the numbers,
pagination, and `notices` — non-fatal things a client should surface, such as
an ungraded matchup or an unpublished week.

Errors have one shape everywhere: `{code, message, field, remedy}`. `404` not
found, `422` semantically impossible, `503` **with a `Retry-After`** for a
recoverable server state.

`remedy` names the command, and **which** command depends on which relation is
missing — a matview needs `jobs run build_features`, a warehouse view needs
`pipeline full`, an application table needs `alembic upgrade head`. That
matters most on a fresh deployment: the default week resolves against
`upcoming_games`, so before the pipeline has ever run *every* endpoint fails at
once, and "run the pipeline" is the only useful thing to say.

### Deliberate response behaviours

- **An unpublished week is an empty board**, `200` with `meta.model: null` and a
  notice. A `404` would be indistinguishable from a bad URL.
- **`predicted` is never the headline.** `expected` is the calibrated mean;
  `predicted` is the raw output, conditionally biased by construction, kept for
  lineage and documented as not-for-display.
- **A toss-up names nobody.** Below a 58% win probability `recommended` is
  `null`.
- **Requesting kickers returns 422 with a roadmap**, not an empty list — the
  reason and the specific blockers, straight from the registry.
- **Versioned from the first commit.** `/api/v1` costs nothing today and is the
  difference between shipping a breaking change and being unable to.
- **`/weeks/{week}` disambiguates an empty board.** A bye-heavy week, an
  unbuilt warehouse and a projection job that has not run all produce the same
  `200` with the same empty array. `projections_published` and
  `projection_count` say which, so a client stops guessing — and a published
  run holding zero projections, which is a real state, becomes visible instead
  of looking like an outage.
- **`/players` is ordered by name, not by anything derived.** It is the one
  listing whose job is to be predictable; a board that reorders itself between
  page 1 and page 2 makes paging skip players. Every ranked listing already
  exists elsewhere. It accepts K and DST, unlike `/rankings/{position}` —
  listing a kicker is reasonable, inventing a projection for one is not.

## Layer 6 — background jobs and caching

Two things belong outside a request: work that takes minutes, and work that has
already been done.

### The projection run is a job, not an endpoint

Fitting the model over ten seasons and writing a slate is minutes of work. Done
inside a request it would hold a pooled connection for the duration, and a pool
starved of connections turns one slow endpoint into a total outage — the same
reason `statement_timeout` exists two layers down.

So `generate_projections` joins the existing feed jobs, and the logic moved out
of the CLI into `predict/generate.py`. That relocation is the point: the weekly
production run previously existed only as an argparse handler, which survives
exactly until something else needs to invoke it, and then the choice is to shell
out to a CLI from inside a worker or to copy the logic. **A manual rerun after a
failed Tuesday must produce what the job would have produced**, and that is only
guaranteed by there being one implementation.

```powershell
python -m nflfp.jobs run generate_projections --publish
python -m nflfp.jobs run generate_projections --week 12 --no-publish
python -m nflfp.jobs run generate_projections --model challenger --no-publish
```

The job resolves the upcoming week the same way `services/catalog` resolves it
for a reader. They have to agree: a job that projects week 11 while every
endpoint defaults to week 12 produces an empty board and no error anywhere.

Two rules from lower layers are re-enforced on this path rather than assumed.
`_assert_trained_before()` re-checks the training rows against the target week
— the production equivalent of `assert_no_leakage()` — and a player for whom no
scoring profile yields a distribution is **dropped and counted**, not stored as
a bare point estimate. Layer 3b's claim is that the interval is the product; a
number with no honest spread is indistinguishable in the API from one that has
been measured.

The Tuesday chain runs in dependency order with an hour of slack between links:

```
12:00  pipeline refresh        nflverse warehouse
13:00  build_features          feature views read raw_*
14:00  generate_projections    reads feat_training_dataset, publishes
14:20  warm_cache              first request is not the one that pays
Wed 16:00  evaluate_model      re-measure what was just published
```

### One week a firing is not one week of product

`generate_projections` publishes the upcoming slate, and availability is
measured in *published runs* — `/seasons` reports what has been projected, not
what the warehouse holds, because offering a season no run covers produces an
empty screen a user cannot explain. Both halves are right, and together they
have a failure mode: an install whose weekly job has fired once has ten seasons
in the warehouse and exactly **one** week in its selectors. Nothing is broken,
no error is raised, and the product looks like it has one week of data because
in the only sense the API measures, it does.

`backfill_projections` walks the same generator over every week the feature
layer supports:

```powershell
python -m nflfp.jobs run backfill_projections --publish
python -m nflfp.jobs run backfill_projections --seasons 2024 2025
python -m nflfp.jobs run backfill_projections --skip-existing   # after a new season
```

It is `MANUAL`, for the reason `invalidate_cache` is: this is a catch-up run,
not a cadence. Once the history is published the weekly job keeps it current,
and a cron would spend an hour a week rewriting boards for seasons that ended
years ago.

Every week goes through **`generate_week` unchanged**. That is the whole design
constraint — a historical importer running beside the live path is two
implementations that drift, and the symptom is a 2019 board that cannot be
reconciled with a 2025 one. What the backfill adds is a `FitCache` that
memoises the inputs which provably do not vary within a season: the completed
history, a season's feature rows, and the residual model's scored output. That
is sound only because a model's `predict` is row-wise, so scoring a range once
and slicing it per week is identical to scoring each week separately —
`generate_week(cache=None)` remains the definition, and a test asserts the two
agree exactly.

It is worth 5x: 141 weeks in ~3 minutes rather than ~15.

**Weeks are refused, never approximated.** The held-out distribution refits on
everything before the *previous* season, so the first two seasons in a
warehouse have a full training set and no residual history at all. Projecting
them anyway would store point estimates whose intervals came from a model
fitted on nothing — precisely what Layer 3b exists to prevent. On a 2016-2025
warehouse that refuses 34 weeks (2016 and 2017) with the reason recorded in the
job log, and publishes 141.

`GET /api/v1/seasons` is then the honest answer to "what does this deployment
have", and the frontend's Settings page renders it as a coverage table rather
than leaving it to be inferred from a dropdown.

### Retraining is continuous; *checking* it is the job

`generate_projections` refits from scratch every week, so there is no separate
retrain step to schedule. What there was no step for is verifying the retrained
model still behaves — and a model whose accuracy drifts does not announce
itself. Projections keep appearing, intervals keep being stated, and the first
signal is a user noticing the numbers are wrong.

`evaluate_model` runs the same walk-forward harness the foundation was frozen
on, over the **last three seasons rather than the full validation window** —
the frozen record is a fixed historical measurement, and this asks a different
question ("is it still behaving *now*?") that a seven-season average would
dilute below the tolerance meant to catch it.

It changes nothing. No publish, no rollback. A drifting model is an operator
decision, and an automated rollback would hide the drift behind a model that
has the same problem a week earlier. Failing the criteria is a **successful
run** with `passed: false` in the job log — queryable, rather than buried in an
exception that would read as "the evaluation broke" instead of "the model
moved".

### Injuries move faster than the warehouse

Everything else rides the Tuesday nflverse load, and for injuries that is the
wrong cadence. A practice report lands Wednesday, Thursday and Friday and a
designation flips on Saturday — by which point the weekly load is four days
stale, and the API is either stating a hard caveat that has since been lifted
or missing one that has since been added. Since Layer 4 surfaces "Out" as a
caveat *above* the statistical verdict, that staleness is user-visible in the
one place accuracy matters most.

`refresh_injuries` reloads that one dataset daily. It is `by_season`, so the
cost is a single parquet file and a partitioned delete/insert — which is why a
daily job is affordable and a daily full refresh is not.

### Caching is a configuration decision, not an invalidation problem

Every cached response is a pure read keyed by `(season, week, scoring_profile,
filters)` against a published run, and **a published run never changes** —
Layer 3 writes a new run and Layer 1's partial unique index swaps a flag. So
there is exactly one event that can make a cached body wrong, and it is a
publish.

That collapses the hard part. No dependency tracking, no per-key invalidation,
no `SCAN` storm. The namespace carries a monotonic **epoch**; publishing
increments it; every key minted afterwards lives in a new namespace and every
key from the old one becomes unreachable. Orphans expire on their own TTL,
which is what stops it being a leak.

```
nflfp:v1:<epoch>:http:<digest>
      │    │          └── path + normalised query, hashed
      │    └── bumped by publish_run(); the only invalidation event
      └── response schema version — a deploy must not serve the previous shape
```

The epoch is read from Redis at most once every ten seconds per instance, not
once per request; fetching it per lookup would double the round-trips the cache
exists to save. That bounds how long an instance can serve the retired
namespace, and ten seconds behind a Tuesday-morning publish is not a
correctness problem.

**The cache sits above the routers, not inside the services.** It stores the
serialised body, so a hit skips query, assembly, mapping *and* Pydantic
serialisation — and `nflfp.services` stays a pure read layer that imports no web
framework and no cache. Caching an endpoint is a line in `cache/policy.py`,
which is also where you look to find out whether an endpoint is cached; a
decorator per handler puts that answer in thirteen places.

Caching is **opt-in**. A path with no rule is not cached, so forgetting to add
one costs latency rather than correctness.

| | TTL | why |
|---|---|---|
| `/meta/*`, `/teams` | 3600s | frozen constants and a registry; changes on deploy |
| `/games`, `/seasons` | 600–900s | the schedule moves for a flexed kickoff; availability moves on a publish |
| slates, rankings, matchups, start/sit | 300s | see below |
| `/search` | 60s | cheap query, unbounded term cardinality |
| `/health*` | never | a cached liveness check is not a liveness check |

Those five minutes are not about publishing. **The default week resolves
forward**, and that answer rolls over when the first game of a slate kicks off
— an event no publish accompanies. The TTL bounds the one thing the epoch
cannot cover.

Every response says what happened, because a support question about a stale
number should be answered by a header rather than a log dig:

```
X-Cache: HIT | MISS | BYPASS
Age: 42
Cache-Control: public, max-age=258        # what's LEFT, not the full TTL
```

`Cache-Control: no-cache` on a request bypasses it — how an operator checks
whether a wrong number is stale or genuinely wrong, without turning the cache
off for everyone. `GET /api/v1/meta/cache` serves the policy table itself.

### A broken cache changes nothing

Every backend error is a miss. Redis restarting, timing out, or never having
been configured all produce the behaviour the application had before Layer 6,
because the read path behind the cache is the Postgres query that was fast
enough to ship without one. Socket timeouts default to 250ms for the same
reason — a cache lookup that hangs is the one door the fail-open design leaves
open.

`REDIS_URL` unset selects `NullCache` and is a **supported configuration**, not
a degraded one, the same way `WEATHER_PROVIDER=null` disables a feed without
removing its job. `/health/ready` reports the cache and never fails on it:
taking a working API out of rotation to protect an optimisation is backwards.

`MemoryCache` exists and is never chosen as a fallback. An in-process cache
silently ignores the epoch bumps other instances perform, so a replica holding
one would serve superseded projections indefinitely with nothing to indicate
it.

### The warmer drives the real application

`warm_cache` requests the top paths through the actual ASGI app in-process
rather than re-implementing the render path. A warmer that builds its own body
is a second serialiser, and the first time a schema changes it starts filling
the cache with something the API would never produce — undetectable from
outside, because the responses look fine.

```powershell
python -m nflfp.jobs run warm_cache
python -m nflfp.jobs run invalidate_cache    # after a manual data correction
```

`invalidate_cache` is registered with schedule `manual` and is excluded from
`run-all`. It wants the same run log, failure recording and CLI as every other
job, but a cron that periodically threw the cache away would be a slow leak of
the benefit it exists to provide.

## Layer 7 — infrastructure

### One image, several services

The API, the ETL cron, the projection job, the cache warmer and the provider
feeds all run from the same image with different start commands. Separate
images drift the first time one is rebuilt and the other is not, and the
symptom is a response shape that no single commit explains. The default command
is the API, because that is the service that must come up by itself after a
platform restart.

Service configs live in [`deploy/`](deploy/), and all but one are **generated**:

```powershell
python -m nflfp.jobs schedule --emit deploy/
```

Cadence is declared once, in the job registry. A generator rather than hand-
written files is what makes "the deployed cron" and "the documented cron"
provably the same numbers — and `tests/test_jobs.py` asserts it.

### Liveness and readiness are different questions

```
GET /api/v1/health/live     checks nothing external
GET /api/v1/health/ready    checks Postgres; reports Redis
GET /api/v1/health          the human-readable union of the two
```

The split is load-bearing. A **liveness** probe that consults Postgres restarts
every healthy container in the fleet the moment the database fails over,
turning a recoverable incident into an outage. A **readiness** probe should
take an instance that cannot reach Postgres out of rotation rather than
restart it. Railway's health check points at `/health/live`; it is also the
only endpoint guaranteed to answer in microseconds, which is what makes a
two-second probe timeout safe.

Neither the engine nor the cache is eagerly connected at startup. A deploy that
cannot reach Postgres should still boot and report `degraded`, because a
container that refuses to start cannot tell anyone why.

### One log format, and a field that ties it together

`nflfp/logging.py` configures the API, the workers, the jobs and the ETL
identically — JSON when deployed, aligned text locally. `request_id` is a
context variable set by middleware and read by the formatter, so one field
connects a slow response to the query underneath it **without threading an id
through every signature**, including the ones in `nflfp.services`, which must
not know that HTTP exists. An inbound `X-Request-ID` is honoured rather than
replaced, or the platform's id and ours could never be joined.

`extra={...}` on any log call becomes a queryable field. uvicorn's own handlers
are removed and made to propagate: left alone they emit plain text into the
middle of a JSON stream, which breaks the parser for every line, not just
theirs.

```
X-Request-ID: 8f3c...        on every response
X-Response-Time-ms: 12.4     including cache hits, which is what you want to see
```

Health-check paths are excluded from the access log. A platform probe runs
every few seconds forever, and logging it is most of the log volume of an idle
service.

### Prepared for horizontal scaling

Nothing in the API holds request-scoped state, so replicas are independent —
with two exceptions that Layer 6 had to get right for that to be true. The
cache is shared and epoch-versioned, so no replica can serve a namespace
another has retired; and `MemoryCache` is never selected implicitly, because a
per-replica cache is exactly the thing that breaks the property.

The real constraint is connections. `DB_POOL_SIZE` × (replicas + concurrently
running jobs) must stay under the Postgres limit, and the failure arrives as
`FATAL: too many connections` on the API — the service that was working — while
the job that exhausted the budget succeeds. The cron services are the ones to
watch: invisible between runs, then all starting within an hour of each other
on a Tuesday.

## Layer 8 — the Mock Draft

```powershell
POST /api/v1/mock-draft/analyze     one seat, simulated many times
POST /api/v1/mock-draft/compare     every seat, ranked
GET  /api/v1/mock-draft/config      bounds, and which seasons can be drafted
```

*Given a league and a draft slot, what roster is that seat likely to build, and
which slot builds the strongest one?* It is a **consumer** of the frozen
foundation in exactly the sense the simulation engine is: no model is invoked,
no projection is computed, and every point estimate it uses came out of a
published `projection_points` row.

### There is no season-long projection, and none is invented

This is the constraint the whole design follows from, so it is stated first.
`shrinkage_eb` projects **one week** from a trailing four-game usage window.
Weeks 2-18 of a season are not projectable before weeks 1-17 have happened —
`feat_player_usage` has no row for a game nobody has played — so a season-long
number would mean a second, unvalidated model, which the frozen-foundation rule
forbids.

What is used instead keeps the halves apart and labels both:

```
season_value  =  expected_points_per_game   provenance: model    (published week 1 board)
              x  expected_games_played      provenance: derived  (historical availability)
```

The model supplies the rate and nothing else. History supplies availability,
volatility and trend — quantities the model does not estimate and never has. The
two are **multiplied, never averaged**, so no historical number is ever blended
into a projected one. A player who scored 300 points last season and is projected
for 11 points a game is projected for 11 points a game here too.

The obvious cost is that this is a *draft-day rate*, not a forecast of how a
season unfolds: no in-season injury, trade or role change is in it. That sentence
is in `meta.notices` on every response, where a client cannot render the board
without it.

### Which seasons can be drafted, and why that is a short list

A draft for season S reads the published **week 1** board for S. That run is
fitted only on data strictly before week 1 of S — `predict/generate.py` asserts
it row by row — so it is exactly what a manager had on draft day.

But week 1 of S is only projectable once S has begun, so the *current* season
cannot be mock-drafted before it starts. `GET /mock-draft/config` serves
`draftable_seasons` for precisely this reason, and the season picker is built
from it rather than from the schedule.

That constraint turns out to be a gift: every draftable season has since been
played, so the strategy can be **backtested against what actually happened**.

### Draft value, which is not projected points

Four quantities, each built on the last:

| | what it is |
|---|---|
| **replacement level** | what the worst starter at a position is worth once every team has filled its lineup. Flex slots are **allocated by auction** — each in turn to whichever eligible position offers the most valuable next player — so a receiver-heavy pool moves the levels on its own |
| **value over replacement** | season value minus that. The number that makes positions comparable, and why the highest-scoring quarterback is not the first pick |
| **marginal roster value** | adjusted for what the roster holds. A third back on a roster starting two earns their surplus only in the weeks the two ahead miss, so the bench weight is *derived from those two players' own availability estimates* rather than from a constant |
| **value over next available** | marginal value now, minus the expected marginal value of what the position still offers at your next pick |

The last is the strategy. A candidate is worth taking now to the extent that the
position will be worse later, which is why the engine will pass on the highest
value on the board. The expectation is an exact order statistic over the survival
probabilities, not a sample:

```
E[best left] = sum_i  value_i * P(i survives) * prod_{j<i} (1 - P(j survives))
```

### Opposing managers are simulated, and that model is an assumption

**There is no ADP data in this repository**, and inventing a number and calling
it ADP would be the most misleading thing this feature could do — ADP is the one
input a user would assume was observed. So the other eleven seats draft from a
stated behavioural model: a standardised blend of value over replacement and last
completed season's actual points, plus a positional-need bonus, sampled by
Gumbel-max (which makes the selection exactly a softmax draw, with a stated
distribution a test can check rather than "pick randomly from the top five").

Its two parameters are **assumptions, not measurements** — nothing here can fit
them — so they are request fields, and every response reports which values
produced it. Blending a projection with a historical actual is exactly what the
*value* side of this package refuses to do, and is right here, because this is
not a value estimate: it is a model of what other people will do, and other
people demonstrably over-weight last season.

### Availability is calibrated, then read

Two stages. A **calibration** batch runs complete drafts in which every seat uses
the opponent model, recording where each player went; that produces a survival
curve per player. The **analysis** batch then runs drafts in which the user's
seat uses the real strategy and reads those curves.

Calibrating without the user's strategy in it is deliberate — one seat in twelve
barely moves the board, and a curve that already assumed the strategy would have
the strategy optimising against its own shadow. The residual bias is real and is
*measured*, not asserted: `evaluate.availability_calibration` bins the predicted
probabilities against what was observed in drafts the strategy took part in.

```
Availability calibration, 2020-2025    ECE 0.002   worst band 0.025
```

### It beats its baselines, measured against seasons that happened

`scripts/phase8e_evaluate.py` drafts seasons that have since been played and
scores each resulting roster on **actual** points. Four strategies see an
identical sequence of opponent behaviour — the seed keys on the seat and the
index, not on the strategy — so any difference is the decision-making.

```
Mean actual points scored by the drafted starting lineup, 2020-2025
  value_over_next_available       1352.9      +0.0
  highest_season_value            1171.1    -181.8
  highest_points_per_game         1148.3    -204.6
  random                          1161.6    -191.3
```

It wins in **every one of the six seasons**, by 30 to 354 points against a
standard error near 10. Note what that does *not* say: it beats these baselines
against *these* opponents. Against real drafters the margin would differ, and
nothing on disk can say by how much.

### Leakage

A draft for season S may see S-1 and earlier, and nothing else. The bound is a
`<` in the query **and** re-asserted above the database by
`history.assert_no_future_seasons`, which raises rather than filters — this is
the failure that produces a spectacular, meaningless backtest, and it must fail
loudly rather than degrade into a slightly optimistic one.

### Architecture

```
POST /api/v1/mock-draft/analyze          api/routers/draft.py    (thin)
        |
        v
services.draft.settings.validate_settings()   pure, pre-I/O
        |
        v
services.draft.pool.build_pool()              3 queries; the only I/O
        |
        v
services.draft.valuation                      replacement, scarcity, VOR — pure
        |
        v
services.draft.engine.simulate_draft()        pure, seeded, no session
        |
        v
services.draft.aggregate                      counts and sums only
        |
        v
DraftAnalysis -> api/mappers -> Envelope[DraftAnalysisOut]
```

Only `pool.py` and `service.py` know what a database is; everything that decides
anything is pure and seeded, which is why 135 of the feature's 162 tests need no
Postgres. `service.py` hands the whole synchronous batch to `asyncio.to_thread`
in one hop — three awaited calls would release and reacquire the loop three
times, and each gap is a chance for another request to interleave CPU-bound work
onto it.

**Aggregates, never a transcript.** Ten thousand drafts is 150,000 selections per
seat; the loop keeps counts and sums. The one complete draft that survives is the
simulation whose roster value is **closest to the median**, replayed with its
reasoning captured — never the best, because the best of ten thousand drafts
happened because the board fell kindly and presenting it as "your roster" would
promise an outcome most drafts do not produce.

### Every recommendation is derived from the calculation

`rationale` carries the marginal value, the expected value of waiting, the
survival probability at the next pick, the tier state and the runner-up margin —
the actual numbers the engine compared — and the sentence is assembled from them
mechanically. It reads a little plainly, which is the correct trade against a
fluent sentence that is not derived from anything:

> **Davante Adams:** Fills a starting WR slot, worth 101 points above a
> replacement-level WR; and survives to your next pick (#28) in only 20% of
> simulations; waiting on WR would most likely leave DeVonta Smith at roughly 242
> season points, a 15-point difference; tier 2 at WR has 2 player(s) left; chosen
> over Drake London by 1 points of draft value.

### Performance

Measured before optimising, on one core of a developer machine, 12-team/15-round
over a 354-player board:

| | |
|---|---|
| pool retrieval (3 queries) | 458 ms |
| availability calibration (200 drafts) | 1,341 ms |
| analysis, per simulated draft | **8.27 ms**, flat from 100 to 10,000 |
| 100 / 1,000 / 5,000 / 10,000 simulations | 0.83 s / 8.3 s / 41.3 s / 82.7 s |
| comparison, 12 seats x 250 | 24.9 s |

An index-array rewrite of the two inner loops took this from 33 ms to 8.3 ms per
draft with **identical output** — the same seeds produce the same rosters, which
is asserted by a test rather than eyeballed. `MAX_TOTAL_DRAFTS` bounds one
request at 15,000 drafts, which is about two minutes of worker time; anything
past a few thousand belongs in a background job, exactly as the projection run
does.

### What is deliberately not built

No persistence, no authentication, no saved leagues, no draft history, and no
live drafting where you make a pick and the board responds. A result is
reproducible from `{settings, published run, historical panel, seed}` — all four
of which travel in the response — so a stored copy would buy nothing that
recomputing does not.

**Rookies are absent from the pool entirely.** The model's features are a
trailing four-game window; a player who has never played has no window, no
projection and no pool entry. Real drafts spend early picks on them, so a
simulated board is shallower at the top than a real one. That is a material gap
rather than a rounding error, and it is stated in `meta.notices` rather than
patched with an invented number.

### Reproducing

```powershell
pytest tests/test_services_draft.py                       # no database
$env:DATABASE_URL = "postgresql://..."
pytest tests/test_api_draft.py                            # real SQL, real board
python scripts/phase8e_evaluate.py --seasons 2020 2021 2022 2023 2024 2025
python scripts/phase8_benchmark.py
```

## Frozen foundation

**Phase 3b is frozen.** `shrinkage_eb` is the validated model everything above
it is built on, and `nflfp/predict/foundation.py` is the machine-readable
record: what it measured, the naive bar it beat, and the criteria a successor
must clear.

```powershell
python -c "import json,nflfp.predict as p; print(json.dumps(p.foundation_summary(),indent=2))"
```

Freezing does not stop anyone registering a new model. It means a challenger is
promoted only by clearing `ACCEPTANCE` **on the same walk-forward harness over
the same seasons** — a model evaluated any other way has not been compared to
this one, it has been compared to nothing.

| criterion | limit | 3b achieved |
|---|---|---|
| P10-P90 coverage error | ≤ 0.02 | **0.003** |
| worst calibration bin | ≤ 0.15 | **0.130** (boom) |
| conditional bias, any band | ≤ 0.25 pts | **0.10** |
| CRPS | ≤ 2.927 | **2.927** |
| beats `baseline_l4` per position | required | yes |
| walk-forward evaluation | required | yes |

The criteria are tolerances against the record rather than absolute numbers,
because the failure mode worth guarding against is a trade made by accident: a
successor that sharpens the point estimate while quietly widening its intervals
or decalibrating its boom probabilities is not an improvement.

`tests/test_foundation.py` asserts the incumbent passes its own criteria — if it
could not, the bar would be wrong — and that a model with a better centre but a
worse distribution is rejected on CRPS.

## Scoring

`src/nflfp/scoring.py` defines league rules as data. `player_week` exposes one
column per profile — `fp_standard`, `fp_half_ppr`, `fp_ppr`, `fp_ppr_te_premium`
— so you can compare formats without rebuilding. Edit `PROFILES` to match your
actual league; that is the one config you should change before modelling.

`fp_nflverse_parity` is not a league format. It reproduces nflverse's own
`fantasy_points` exactly so `--probe scoring_check` proves the scoring maths is
correct rather than merely plausible. It verifies at **0.0** max difference
across all ten seasons.

One deliberate divergence: `count_return_fumbles=True` counts fumbles lost on
punt/kick returns, because ESPN/Sleeper/Yahoo do. It affects ~0.2% of
player-weeks, essentially all return men and DBs.

## Verification

Nothing here is asserted without a check that fails loudly:

| what | how | result |
|---|---|---|
| Scoring maths | `explore --probe scoring_check` | 0.0 diff vs nflverse, all seasons |
| DuckDB ≡ Postgres | `scripts/verify_parity.py` | 13/13 checks match |
| Refresh idempotency | run `refresh` repeatedly | row counts stable at 182,252 |
| Publish rollback | fault injected mid-transaction | tables + views intact, exit 1 |
| Recovery after failure | rerun after a failed publish | orphan staging cleaned, counts correct |
| Container parity | `docker run` against local PG | identical output to host run |
| Weather provider | live Open-Meteo fetch | real forecast, indoor neutral row, unknown venue + beyond-horizon skipped |
| Odds provider | live ESPN fetch | 17 games, spread/total/moneyline, signs consistent |
| Forward-looking coverage | `feat_game_context`, 2026 wk 1 | **32/32** team rows on a live market line (nflverse: 52/272 games) |
| No feature leakage | recompute every window by hand | **0 disagreements** across 56,518 player-weeks |
| Spread sign survives features | `corr(team_spread, margin)` | +0.449, matching `game_team` |
| Implied totals | `home + away == total` | 0 violations |
| Snapshot change detection | run `refresh_odds` twice | 17 written, then 0 |
| Python ≡ SQL scoring | both renderers, 5 profiles | exact over 20,000 player-weeks |
| Components ≡ points | score lagged components vs `fp_half_ppr_l4` | **0 mismatches** / 56,518 |
| Walk-forward has no leakage | re-check every fold's rows | enforced per fold, unit-tested |
| Backtest reproducibility | run twice | identical metrics |
| Held-out interval coverage | P10-P90 over 38,061 predictions | **0.803** vs nominal 0.80 |
| Held-out P25-P75 coverage | same | **0.507** vs nominal 0.50 |
| Conditional bias by range | every band to 25 pts | within **±0.1 points** |
| Boom calibration | max error, well-sampled bins | 0.212 → **0.130** |
| Bust calibration | max error | **0.014** |
| Percentile ordering | 1,392 stored rows | 0 violations |
| Train/serve feature parity | every registered model | enforced by `assert_available()` |
| Draft strategy beats its baselines | actual points, 2020-2025 | **+182 vs best-available**, wins all 6 seasons |
| Draft availability calibration | predicted vs observed survival | ECE **0.002**, worst band 0.025 |
| No draft-time leakage | every historical row, every season | asserted above the query, raises on violation |
| Draft engine determinism | same seed, before and after the index rewrite | identical rosters and values |
| Draft optimisation is behaviour-preserving | 33 ms -> 8.3 ms per draft | identical output, asserted |
| Historical immutability | publish a new model version | old rows unchanged, superseded not deleted |
| Curve passes through stored percentiles | reconstruct, re-read P10-P90 | exact to 1e-9 |
| Head-to-head is deterministic | same pair, repeated | identical; grid 64 vs 4096 differs < 0.01 |
| Head-to-head is complementary | P(a>b) + P(b>a) | 1.000 |
| A half-point edge is a toss-up | 12.4 vs 11.8 | 52%, no player named |
| Matchup grade is a percentile | all 32 ranks | monotone, ≤ 4 teams per letter |
| Rank 1 is the toughest matchup | KC allows 4.0, BUF 26.0 | KC ranks 1, BUF 2 |
| Defensive form exists for an unplayed week | week 10, no result | rows returned, window = 4 |
| Read-time window never reaches the week | insert a week-10 defence row | window unchanged |
| Only published runs are read | supersede, republish v2 | v1 invisible, v2 served |
| `position` resolves to the projection | 3 relations carry the column | filter returns WR only |
| Missing matview is actionable | drop `feat_player_usage` | names relation + `build_features` |
| Unpublished week is empty not 404 | week with no run | 0 entries, `model is None` |
| Provenance is on every block | slate response | model/derived/context/actual all labelled |
| Model output is only in `prediction` | slate response | no points on matchup or context |
| Context declares it is unapplied | every context block | `false` + a reason, always |
| Injury multiplier flips the flag | write 0.75, re-request | `applied_to_projection: true` |
| Weather multiplier flips the flag | write 0.92, re-request | `applied_to_projection: true` |
| Kicker request explains itself | `GET /rankings/K` | 422 + reason + blockers |
| Dropped matview is recoverable | drop, request | 503 + `Retry-After` + remedy |
| Remedy matches the missing relation | matview / view / table | `build_features` / `pipeline` / `alembic` |
| Unbuilt warehouse is actionable | drop `upcoming_games` | 503 naming the pipeline, not a 500 |
| Async engine can actually connect | real `get_async_engine()` | `SELECT 1` succeeds |
| Statement timeout reaches the server | `SHOW statement_timeout` | `4321ms`, both engines |
| Unreachable database fails fast | health check vs dead host | **2s**, was 130s |
| Publish is the only invalidation event | bump the epoch, re-request | HIT becomes MISS |
| Parameter order does not split an entry | `?a=1&b=2` vs `?b=2&a=1` | one entry, HIT |
| Repeated parameters are distinct | `positions=WR` vs `+TE` | two entries |
| A cache key is bounded | 200 repeated parameters | < 100 chars |
| Errors are never cached | request a 503 twice | handler runs twice |
| An authenticated request bypasses | `Authorization:` header | BYPASS, no entry written |
| `no-cache` bypasses one request | operator header | BYPASS, others still HIT |
| A broken cache changes no answer | backend that always fails | every request computed, 200 |
| A malformed entry is discarded | write garbage under a live key | recomputed, not corrupt |
| A stale epoch survives an outage | backend down mid-read | last known epoch kept |
| Warmed paths are actually cached | every `warmable_path` | TTL > 0 |
| Production path rejects leakage | train rows at/after target week | `ValueError`, per-row count |
| No distribution means not stored | position with no residuals | dropped and counted |
| Emitted cron ≡ registry | `schedule --emit` vs `REGISTRY` | schedules and commands match |
| A manual job gets no cron service | `invalidate_cache`, `backfill_projections` | no file emitted, absent from `run-all` |
| Backfill ≡ the weekly job | `FitCache` vs `cache=None` | identical residual samples |
| A backfilled week sees no future | cached range sliced per week | strictly increasing, prefix only |
| Too little history is refused | 2016-17, no residual fold | 34 weeks skipped with a reason, 141 published |
| One number across every view | board / rankings / profile / compare / single | 0 mismatches over 6 slates |
| Logging installs one handler | configure twice | 1 handler, no doubled lines |
| Player index does not skip on paging | two pages of 2 | 4 distinct ids |
| Player index is stably ordered | full listing | alphabetical |
| Unprojected positions are listable | `/players?positions=K` | 200, not 422 |
| An unpublished week says so | week with no run | `projections_published: false` + notice |
| A published week names its run | week 10 | count matches, `model.run_id` set |
| Injuries refresh daily, not weekly | `refresh_injuries` cron | `* * *` in the date fields |
| Evaluation runs after a projection | both crons | later weekday |
| Evaluation never fails the batch | `critical` flag | False |
| Frozen model passes its own bar | `ACCEPTANCE` vs `VALIDATION` | passes |
| Better centre, worse spread rejected | CRPS +0.5 | rejected on CRPS |
| Foundation is still registered | `predict.available()` | `shrinkage_eb` present |
| Alembic can't touch the warehouse | `pytest tests/test_migrations.py` | guard excludes all 8 `raw_*` + 3 views |
| Migration ≡ ORM models | autogenerate after `upgrade head` | 0 diffs against the live database |
| Migration round trip | `upgrade head` then `downgrade base` | app tables gone, ETL run log preserved |
| ETL unaffected by app schema | `pipeline refresh` after migrating | swap + view rebuild ok, 0 drift after |

`verify_parity.py` uses exact comparison for counts, sums and join coverage, and
a `1e-3` tolerance for `corr()` — the two engines sum in different orders and
disagree around the 4th decimal. That's arithmetic, not a porting bug.

## Gotchas found while building this (don't relearn these)

- The current release tag is `stats_player` (`stats_player_week_{year}.parquet`).
  The older `player_stats` tag still exists and is stale — don't use it.
- `spread_line` in `raw_schedules` is signed from the **home** team's
  perspective. `game_team.team_spread` normalises it to "points this team is
  favoured by", verified against actual margins (r = +0.44).
- Snap counts key on `pfr_player_id`, **not** gsis. `player_week` bridges via
  `raw_players.pfr_id`. Row count is unchanged by the join (182,252), so it
  doesn't fan out.
- `offense_pct` / `st_pct` are 0–1 fractions, not 0–100.
- `position` exists on the stats, players *and* snap-count tables — always
  qualify it. This is why `points_expression()` takes an `alias`.
- nflverse dropped the season column from `depth_charts` 2025+, which is why
  that dataset is `refresh="full"` rather than `by_season`.
- Postgres `round(double, int)` doesn't exist — cast to `::numeric`. Probe SQL
  is written portably so it runs on both engines.
- Postgres only allows `CREATE OR REPLACE VIEW` when the column list is
  unchanged; adding a scoring profile changes it. Views are dropped and
  recreated every run.
- VS Code's database viewer holds a write lock on `data/nfl.duckdb`. If
  `nflfp.ingest` reports "file is already open", close it in the editor.
- A SQLAlchemy `connect` event listener that opens a cursor **cannot** be shared
  between the sync and async engines. On the async engine the raw connection is
  an async adapter whose `cursor()` is not a synchronous context manager, so the
  listener raises `AttributeError: __enter__` and every API request fails while
  the ETL works perfectly. Session settings belong in libpq `connect_args`
  (`options="-c statement_timeout=..."`), which both engines share.
- libpq waits effectively forever for an unreachable host. Without an explicit
  `connect_timeout`, `check_database()` took **130 seconds** to return `False` —
  a health endpoint that hangs is worse than one that reports failure, because a
  platform health check cannot tell a hang from a slow start.
- psycopg's async driver refuses `ProactorEventLoop`, which is what uvicorn
  picks on Windows outside a reloader. `python -m nflfp.api` handles it; the
  test suite sets the selector policy in `conftest.py`.

## What the data says so far

From `--probe usage` and `--probe stability`, 2016–2025 regular season:

| | RB | WR | TE | QB |
|---|---|---|---|---|
| snap % ↔ points (same week) | **0.71** | 0.56 | 0.49 | **0.62** |
| target share ↔ points | 0.58 | **0.73** | **0.71** | — |
| snap % year-over-year | 0.73 | 0.73 | 0.63 | — |
| efficiency (yds/opp) year-over-year | 0.23 | 0.19 | 0.16 | — |

Game context is a much weaker lever: implied team total correlates just
0.10–0.23 with weekly points, and home-field is worth ~0.1–0.8 points.

Two things follow. **Usage is the signal** — and it persists year to year while
efficiency essentially doesn't (0.16–0.23), so a model that projects opportunity
and applies a regressed efficiency prior will beat one that extrapolates last
year's yards per touch. **Vegas context is a modifier, not a foundation** — real,
but second-order next to snaps and targets.

Caveat: those correlations are same-week, so they measure description, not
prediction. The honest version uses lagged usage to predict the next week —
that's the first thing to build, and it's the baseline every fancier model has
to beat.

Position shapes differ enough to matter (`--probe boom`, 2024–25, ≥50% snaps):
TEs bust (<5 pts) 48.5% of the time and WRs 37.2%, versus 10.1% for RBs. Weekly
*distributions*, not point estimates, are what lineup decisions actually need.

## Deploying to Railway

Full service table, variables and first-deploy sequence:
**[`deploy/README.md`](deploy/README.md)**. The short version:

```powershell
railway link
railway add --database postgres
railway add --database redis
railway up
```

`railway.json` at the root is the **API** service — always on, health-checked at
`/api/v1/health/live`. Every other service is a cron that runs and exits, so it
costs nothing between runs, and each points at a config file in `deploy/`.

> **Upgrading an existing deployment:** the root `railway.json` used to be the
> pipeline cron and is now the API. If you already have a cron service deployed
> from the repository root, point its config path at
> `deploy/railway.pipeline.json` before the next deploy — otherwise it will come
> back as a web service.

Then, once, by hand — the crons only ever do incremental work:

```powershell
railway run python -m nflfp.pipeline full
railway run alembic upgrade head
railway run python -m nflfp.jobs run build_features
railway run python -m nflfp.jobs run generate_projections --publish
railway run python -m nflfp.jobs run backfill_projections --publish
```

The backfill is what makes the season and week selectors describe the
warehouse rather than the last cron firing. Skipping it leaves a deployment
that works correctly and offers exactly one week.

Until that completes, every endpoint returns `503` naming the command it is
waiting on rather than a 500.

Notes:

- `pg.dsn()` adds `sslmode=require` automatically for non-local hosts, and
  accepts Railway's `postgres://` scheme as well as `postgresql://`.
- Prefer the private `DATABASE_URL` over `DATABASE_PUBLIC_URL` — same-project
  traffic stays on the private network and isn't billed as egress. `pg.dsn()`
  already prefers it.
- In-season you may want this daily rather than weekly: injury reports and depth
  charts move all week, and `refresh` is idempotent, so `0 12 * * *` is safe.
- The DuckDB file is *not* deployed. It's a local exploration convenience;
  Railway reads Postgres.

## Where this goes next

All eight layers are done. What remains is modelling and scale, not structure.

1. **A better model** — `shrinkage_eb` clears the L4 baseline and is honest
   about its intervals, but it is still a shrunk average. The feature layer
   already carries opponent strength, pace and trend; a gradient booster on the
   same walk-forward harness is the obvious next comparison, judged by
   `ACCEPTANCE` in `nflfp/predict/foundation.py`.
4. **Play-level features** — success rate, explosive-play rate and pressure
   rate need `raw_pbp`, which is opt-in and not loaded. Those feature
   definitions already declare the dependency and skip themselves until it
   exists.
5. **The Matchup Simulation Engine** — **built**, stateless, at
   `POST /api/v1/simulations`, and documented in
   `docs/simulation-readiness.md`. Lineup payloads in, two score distributions
   and a win probability out; nothing stored. Phase 6B then fitted and scored a
   correlation structure over it and kept the independent sampler as the
   default on the evidence.
   Three of the four things that used to block an honest version still do — no
   K/DST projections, no user or roster tables (which want authentication
   first), and unquantified injury impact — and all three are refused or
   disclosed rather than papered over. The fourth, player independence, is now
   measured rather than assumed.
6. **The Mock Draft** — **built**, stateless, at `POST /api/v1/mock-draft/*`
   and `/mock-draft` in the app. It is the first feature to need a *season*
   number from a week-by-week model, and it gets one by multiplying the
   published week 1 rate by an availability estimate rather than by fitting a
   second model. Backtested against 2020-2025 actuals, where it beats every
   baseline in every season. Two things would move it furthest: **real ADP
   data**, which would turn the opponent model from an assumption into a fitted
   one, and **rookies**, who have no projection and are therefore absent from a
   board real drafters spend early picks on.

## Documented gaps

These are known and deliberate. Each is stated here, surfaced through the API,
and has a defined path forward — none is a surprise waiting for a user to find.

### There is no ADP data, so the draft's opponent model is unvalidated

The Mock Draft simulates eleven opposing managers, and nothing in this
repository can say whether it simulates them *well*. There is no
average-draft-position feed, no draft results, no league histories. The
consensus board is therefore a **stated behavioural assumption** with two
parameters exposed as request fields, and every response says so. Its measured
result — that the strategy beats its baselines — is a statement about these
opponents and not about real ones.

Acquiring an ADP feed would turn the assumption into a fitted model and make
`evaluate.py`'s availability calibration a claim about reality rather than about
internal consistency. Until then, no number in that area is presented as
validated.

### Rookies have no projection and are absent from the draft pool

The model's features are a trailing four-game usage window. A player who has
never taken a snap has no window, so no projection, so no entry on a draft
board. Real drafts spend early picks on rookies, which makes a simulated board
shallower at the top than a real one — a material gap, and one this engine
refuses to close by inventing a number for a player it has never seen.

The path forward is a draft-capital and college-production prior, which is a
model, and therefore a challenger to be judged by `ACCEPTANCE` rather than a
patch to be dropped in.

### A season projection is a rate times an availability estimate

Not a season model. `season_value` reads the published week 1 projection as a
points-per-game rate and multiplies by estimated games played, which assumes a
player's role is roughly the shape it is in week 1 and models no in-season
injury, trade or breakout. Measured against 2020-2025 actuals it correlates
**0.34 to 0.72** with actual season points within position — the spread across
seasons is as large as the spread across positions, which is itself the finding
— and is biased low, most at quarterback (+15.4 points of actual over projected,
pooled, against +1.0 at receiver).

That positional bias is a property of the **frozen model**, not of the draft
engine, and it is reported here rather than corrected there — a per-position
scaling factor applied above the foundation would be an unvalidated second model
wearing the first one's guarantees.

### Kickers and team defences are not projected

`GET /api/v1/meta/positions` returns this, so a client renders the reason rather
than an empty list, and a request for them is a `422` carrying the blockers.

| | why not | blocked on |
|---|---|---|
| **K** | scoring is distance-bucketed field goals; the component model projects targets, carries, yards and touchdowns, none of which describe a kicker | a kicking component vocabulary; FG-opportunity features (needs `raw_pbp`); a discrete outcome model — kicker results are low-count and the continuous quantile approach does not transfer |
| **DST** | a defence is not a player-week row; its scoring comes from sacks, takeaways and points allowed, which are properties of a game | a team-week fact table (`feat_defense_game` is the natural base); opponent line and turnover-propensity features; a model for rare high-value events |

Adding either is an entry in `nflfp/services/positions.py` plus a model. No
router, schema or validator changes — the tests iterate the registry rather than
hard-coding four strings.

### Injury and weather are not quantified

The frozen model applies neither. Layer 3b measured both against the baseline's
residual and excluded them on the evidence, so the API reports observed
conditions with `applied_to_projection: false` and an `unapplied_reason`.

The path forward is already wired: `projections.injury_multiplier` and
`weather_multiplier` exist, the read path reads them, and writing a value flips
the flag through to the response with no other change. What is missing is the
*evidence* — a fitted adjustment that demonstrably improves the backtest, which
is a model change judged by the frozen acceptance criteria.

A designation of Out is surfaced as a hard caveat above the statistical verdict
rather than zeroing the projection, because that would destroy the distinction
between "projected zero" and "not playing".

### `matchup_score` is stored NULL

The engine writes no matchup number, for the same reason. The business layer
derives a grade from the defensive views instead and labels it `derived`. If a
future model does consume a matchup feature, `grade_matchup()` already prefers a
stored score over the derived one.

### Smaller items

- **Player search does a sequential scan.** `ILIKE '%term%'` cannot use a btree
  index. At ~20,000 dimension rows that is single-digit milliseconds; a trigram
  index is the fix when it stops being, and it is a migration, not a redesign.
- **Matchup grades are percentiles, not magnitudes.** About 2.5 defences hold
  each letter every week. The magnitude claim travels beside the grade in
  points; a client showing only the letter is showing half the picture.
- **Head-to-head assumes independence.** Wrong for teammates and for players
  facing each other, and both are detected and disclosed in `caveats` rather
  than corrected. Phase 6B measured how wrong: a quarterback and his own
  receiver correlate **+0.24**, opposing quarterbacks +0.14, and everything not
  involving a quarterback is within 0.05 of zero. A fitted correlation structure
  now exists (`POST /simulations` with `correlation_mode: game_environment`) and
  is **not** the default, because on 4,320 held-out matchups it did not beat the
  independent baseline. The same backtest disproved the reason this section used
  to give for wanting it: the lineup-level interval is not too narrow, it is
  slightly too **wide** — 82.3% coverage on a nominal 80% — because the outcome
  curve's tail extension over-disperses a seven-player sum by more than
  independence under-disperses it. Phase 6C measured those tail factors at the
  lineup level and **recommends `LOWER_TAIL_FACTOR = 1.0` / `UPPER_TAIL_FACTOR =
  2.0`, awaiting approval — the shipped values are still 1.5 / 2.5.** It also
  found that the two errors were cancelling: on stacked lineups under the
  recalibrated tails, correlation moves 80% coverage from 0.783 onto 0.802,
  where under the current tails it made an already-wide interval wider. So
  correlation is worth re-testing for promotion once the tails land, on interval
  calibration rather than on Brier. `rosters.correlation_groups()` still reports
  the structure under the default mode. See `docs/simulation-readiness.md`.
- **No authentication.** `dependencies.current_principal` returns an anonymous
  principal, so adding auth is one function plus a router dependency rather than
  a signature change across every endpoint. The cache is already excluded for
  any request carrying `Authorization` or `Cookie`, so turning auth on cannot
  make a shared cache serve one principal's response to another.
- **No single-flight on a cold key.** If a popular board expires while a
  hundred requests are in flight, all hundred assemble the slate and all
  hundred write the same entry. It is correct, just wasteful, and it is
  bounded: `warm_cache` refills the expensive paths on a cadence, so a natural
  expiry is normally refilled by a job rather than by a user. The fix is a
  per-key lock with a short lease, which is worth adding when a slate
  assembly is measurably hot rather than in advance.
- **The cache stores whole bodies.** A full slate is one entry, so a client
  requesting the same board with `limit=25` and `limit=50` occupies two. That
  is the right trade at this size — the alternative is caching service results
  and re-serialising, which puts a second copy of the response shape in the
  cache and gives up the serialisation saving that makes a hit cheap.
- **Rate limiting is not implemented.** The cache absorbs repeated identical
  requests, which is most of what a naive client does, but it is not a defence
  against an abusive one. That belongs beside authentication, keyed on the
  principal that does not exist yet.
