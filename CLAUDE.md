# nflfp — working agreement

NFL fantasy projection system. Python data layer (nflverse → DuckDB → Postgres)
under a FastAPI read API, with a React/Vite frontend in `web/`.

`README.md` is the reference and it is authoritative — 1,600 lines covering every
layer, with a `Verification` table listing what has actually been measured. Read
the relevant layer section before changing that layer. This file is only the
short list of rules that are easy to violate without noticing.

## The one rule that matters most

**Never upgrade a derived estimate into a certified verdict.**

Every number on the wire carries a `provenance` field, and the four values mean
different things:

| `provenance` | what it is |
|---|---|
| `model` | output of the frozen model run, carrying its measured guarantees |
| `derived` | computed *above* the model, from data the model never saw |
| `context` | observed, and explicitly **not** an input to the projection |
| `actual` | a recorded outcome, not a prediction |

A win probability of 0.973 is an estimate produced by resampling published
player distributions. It is not "Team A will win — 97% confidence". Prefer
"Estimated win probability: 63%" over "You will win". Never relabel a
probability as "confidence", and never imply context (injury, weather, market)
fed the model — it did not.

Corollaries, all of which already hold in the code:

- `matchup`, `usage` are `derived` and travel with `applied_to_projection: false`.
- `injury_multiplier` / `weather_multiplier` exist and are `NULL`. The read path
  already renders them. Do not hardcode a multiplier to make a number move.
- A designation of "Out" is a hard caveat *above* the statistical verdict. Never
  silently zero a projection — that destroys the distinction between "projected
  zero" and "not playing".
- Where a limitation applies to a number on screen, show it beside that number,
  not in a footnote.

Known limitations that must stay visible, stated as measured:

- **Player independence is an approximation, but not the one you might assume.**
  At the shipped tail factors (`LOWER_TAIL_FACTOR = 1.0` / `UPPER_TAIL_FACTOR =
  2.0`), Phase 6D measured the independent sampler's lineup intervals essentially
  *at* nominal on 2,878 held-out lineups: 80% coverage 0.7943 against nominal
  0.800, 90% coverage 0.8919. Enabling correlation moves both **past** nominal
  (0.8065 / 0.8961) and no proper score moves significantly. Do not write copy
  saying independence makes intervals "too narrow" or pushes win probabilities
  away from 50% — that was the pre-6C expectation and the measurement disproved
  it. The residual dependence that does exist is concentrated in QB-plus-own-
  receiver stacks.
- K and DST are not projected.
- Rookies have no trailing window, no projection, and no draft-pool entry.

If copy looks vague, it is usually load-bearing. Do not "tighten" it.

**The rule runs in both directions.** A caveat must match what was actually
measured, not what was once expected. An overstated limitation is the same
failure as an overstated verdict: it teaches a user to discount a number that
the evidence supports. When you change a caveat, cite the measurement in
`docs/simulation-readiness.md` that justifies it.

## Phase 3b is frozen

`shrinkage_eb` is the validated foundation. `src/nflfp/predict/foundation.py`
is the machine-readable record of what it measured and the bar a successor
must clear.

A challenger is promoted **only** by clearing `ACCEPTANCE` on the same
walk-forward harness over the same seasons. A model evaluated any other way has
not been compared to this one — it has been compared to nothing.

The failure mode being guarded against is an accidental trade: a successor that
sharpens the point estimate while quietly widening its intervals or
decalibrating its boom probabilities is not an improvement. Judge on the whole
distribution, not the centre. `tests/test_foundation.py` enforces this.

## Evaluation discipline

- **Walk-forward, never random split.** Leakage checks are asserted above the
  query and raise on violation. Do not relax them to make a test pass.
- Backtests are reproducible — run twice, get identical metrics. Preserve that.
- Absent data is reported in `meta.notices`, never patched with an invented
  number. An unpublished week returns an empty slate, not a 404.
- A matchup grade is a rank percentile: an "A" means "top few this week", not
  "good in absolute terms". Below three games of defensive history the grade is
  withheld with a reason rather than softened. Week 1 is ungraded by design.

## Architecture boundaries

- Nothing below `nflfp.api` imports FastAPI. The API is a thin serialisation of
  `nflfp.services`; ETL and worker images do not need it at runtime.
- The pipeline is two-phase with transactional publish. Rollback and recovery
  after a failed publish are both tested — keep them working.
- Historical rows are immutable. Publishing a new model version supersedes; it
  does not delete.
- The cache warmer drives the real ASGI app through httpx, deliberately. Never
  warm through a reimplementation of the render path.
- Scoring lives in `src/nflfp/scoring.py` as data. `fp_nflverse_parity` is not a
  league format — it is the proof the scoring maths is correct (0.0 diff).

## Commands

```powershell
# Backend
pytest                                        # unit; integration needs DATABASE_URL
pytest -m "not integration"                   # skip DB-backed tests
python -m nflfp.pipeline refresh              # weekly job, current season
python -m nflfp.explore --probe               # list canned probes
python scripts/verify_parity.py               # DuckDB vs Postgres, 13 checks
python scripts/phase8e_evaluate.py --seasons 2020 2021 2022 2023 2024 2025

# Frontend (web/)
npm run build                                 # tsc -b && vite build
npm run lint                                  # oxlint
npm run contract-check                        # API contract
npm run test:e2e                              # playwright
npm run test:contrast                         # token contrast
```

## Platform gotchas

- Windows: psycopg's async driver refuses `ProactorEventLoop`. Use
  `python -m nflfp.api`; tests set the selector policy in `conftest.py`.
- Postgres has no `round(double, int)` — cast to `::numeric`. Probe SQL is
  written portably so it runs on both engines.
- VS Code's database viewer holds a write lock on `data/nfl.duckdb`.
- Snap counts key on `pfr_player_id`, not gsis.
- `offense_pct` / `st_pct` are 0–1 fractions.
- `position` exists on three tables — always qualify it.

The full list is under `## Gotchas found while building this` in the README.
Check there before debugging anything that smells environmental.

## Scope

Deliberately not built: persistence, auth, saved leagues, draft history, live
drafting. A result is reproducible from `{settings, published run, historical
panel, seed}`, all of which travel in the response. Do not add storage to buy
what recomputation already gives.
