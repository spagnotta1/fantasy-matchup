---
name: challenger-eval
description: Evaluate a challenger projection model, a new feature set, or a change to a caveat against the frozen foundation in nfl-fantasy. Covers the local database, the three evaluation scripts, how long they take, and the rules that keep the comparison honest. Use when asked to improve the model, add or test features, "boost confidence", explain why a challenger failed acceptance, or promote one.
---

# Evaluating a challenger

`shrinkage_eb` is frozen (see `CLAUDE.md` and `src/nflfp/predict/foundation.py`).
Anything that claims to be better is judged on the same walk-forward harness,
over the same seasons, against `ACCEPTANCE`. This skill is how to do that
without fooling yourself.

## Before you start

- **Database.** Backtests read `feat_training_dataset` from Postgres. A local
  mirror of production usually runs on this machine:
  `DATABASE_URL=postgresql://nflfp:nflfp@localhost:5432/nflfp` (documented dev
  credentials; note port 5432, not the README's Docker port 55432). Check with a
  one-line `psycopg.connect`. It is replaced wholesale by the daily pull, so
  treat it as read-only and never publish a run to it.
- **Interpreter.** `.venv/Scripts/python.exe`. The system Python lacks the
  dependencies.
- **Long runs go in the background.** A LightGBM backtest is ~14 minutes alone
  and longer with a second one running. Start it with `run_in_background` and
  work on something else; do not poll.

## The scripts

| script | answers | runtime |
|---|---|---|
| `scripts/challenger_eval.py <model>` | Does it clear `ACCEPTANCE`? Runs incumbent and challenger from one load of the same rows. **This is the verdict.** | ~16 min for a booster |
| `scripts/acceptance_power.py <model>` | How much of the conditional-bias line is noise? Per-band bias with a week-bootstrap standard error, and how often each model would clear the limit. | ~16 min |
| `scripts/pbp_feature_eval.py --pbp-db data/pbp.duckdb` | Do the play-level features help? One-variable comparison against `lightgbm_components`, with paired differences. Needs `NFLFP_DB=data/pbp.duckdb python -m nflfp.ingest --only pbp` first. | ~40 min |

All three write a report under `artifacts/` and are seeded: two runs print the
same numbers.

## Rules

1. **Decide the design before the first backtest, and write it down.** Feature
   list, hyperparameters, calibration variant. Choosing any of them after
   seeing 2019-2025 results and then reporting 2019-2025 is selection on the
   test set, even though every fold is walk-forward.
2. **One pre-declared variant, run once, reported whichever way it lands.** A
   replay of the distribution stage takes 40 seconds, which makes it easy to
   try ten calibrations and keep the one that passes. Don't.
3. **Never move the bar to let a model through.** `ACCEPTANCE` is the user's
   to change, not yours. If a criterion looks statistically unsound, measure
   that (`acceptance_power.py`), report it, and ask.
4. **Judge the whole distribution.** CRPS, coverage, worst calibration bin and
   conditional bias together. A sharper centre with wider or decalibrated
   intervals is a trade, not an improvement.
5. **Read a difference against its error.** Bootstrap by *week*, not by
   player-week: outcomes inside a week share a slate. A band of a few hundred
   projections has a bias standard error near half a point.
6. **A caveat shown to a user quotes a measurement.** If you change one, record
   the measurement in `docs/simulation-readiness.md` and pin the constant to
   `foundation.py` with a test (see "Range evidence" there for the pattern).
   Check the measurement holds across scoring profiles before trusting a
   single cell: a bucket that fails under half-PPR and passes under PPR is
   noise.

## Things that have bitten

- `python -m nflfp.api --reload` can stall after a file change on Windows and
  keep serving old code. Restart it without `--reload` when verifying.
- The player page defaults to half-PPR; add `?scoring=ppr` to compare with a
  PPR screenshot.
- `ppr_te_premium` has no `fp_*_actual` column, so it cannot be backtested.
- Frontend changes are verified in a headed Chrome for Testing window against
  a local API (`python -m nflfp.api --port 8010`, then `npm run dev` in `web/`),
  at 1440x900 and Pixel 7.

## Reporting

Lead with what was found, then the number and its error bar. State plainly
when something did not clear the bar, and when the reason is noise rather than
a defect say that too, with the evidence. Update the README's Frozen foundation
section and Verification table when a measurement is added.
