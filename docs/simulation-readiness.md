# Matchup Simulation Engine

A user submits two lineups for a week and gets back a projected score
distribution for each side, a win probability, and an explicit statement of
everything the answer assumed.

**Phase 6A is built.** It is the stateless version: two lineup *payloads* in, a
result out, nothing stored. There is no roster table, no user, no authentication
and no simulation history, and that ordering is deliberate — see
[What is deliberately not built](#what-is-deliberately-not-built).

**Phase 6B is measured.** Player outcomes in the same game really are
correlated, a structure for it was fitted on held-out history, and it **did not
beat the independent baseline** — so the independent simulator remains
production and the correlated one ships behind an explicit experimental mode.
The evidence, including a Phase 6A claim the backtest disproved, is in
[Phase 6B](#phase-6b--correlated-simulation-the-measured-answer).

**Phase 6C is measured, approved and applied.** The outcome curve's two tail
factors were never validated on a *sum*, and at the lineup level the old pair
made the team total's 80% interval about two points too wide. `distributions.py`
now ships **`LOWER_TAIL_FACTOR = 1.0` / `UPPER_TAIL_FACTOR = 2.0`**, replacing
`1.5 / 2.5`. This is a **distribution/calibration improvement, not a
demonstrated winner-prediction improvement** — that distinction is load-bearing
and is preserved throughout. See
[Phase 6C](#phase-6c--lineup-level-tail-calibration).

**Phase 6D is measured. The verdict is C — correlation remains promising but
unproven, and independence stays the production default.** With the marginals
recalibrated, the independent simulator's team-total calibration is already
close to nominal, and correlation no longer has the error it was expected to
correct. It buys a slightly better 90% coverage and a slightly lower maximum
calibration error, costs a slightly worse PIT, and moves no proper score
significantly — at twice the CPU. See
[Phase 6D](#phase-6d--correlation-promotion-validation).

The governing constraint, unchanged from the brief: *the engine must consume
existing prediction outputs and must not create its own player projections.*
Everything below follows from it. The engine invokes no model, computes no
projection, fits no distribution and invents no uncertainty range. Every number
it samples was measured by Layer 3b and stored in `projection_points`.

---

## Architecture

```
POST /api/v1/simulations                       api/routers/simulations.py
        |
        v
services.lineup.validate_structure()           slots, counts, duplicates — no I/O
        |
        v
services.rosters.get_roster_projections()      one query for both lineups
        |
        v
services.lineup.validate_eligibility()         positions, now that they are known
        |
        v
dto.PointDistribution.curve()  ->  OutcomeCurve
        |
        v
services.simulation.simulate()                 Monte Carlo — pure, seeded
        |
        v
MatchupSimulation  ->  api/mappers  ->  Envelope[MatchupSimulationOut]
```

Four properties of that shape are load-bearing:

**The engine is pure.** `simulate()` takes two sequences of curves and returns
dataclasses. No session, no SQL, no clock, no global RNG. Retrieval happened in
`rosters`, and every statistical property in this document is unit-tested
against constructed distributions without a database.

**Validation is two-stage, cheap side first.** Slot names, slot counts,
duplicate ids and unsupported slots need no database and are checked before the
first round-trip. A lineup with two quarterbacks is rejectable without knowing
what week it is, and spending a query to resolve a window we are about to
discard is both slower and, when Postgres is down, a 500 where a 422 was
correct. Eligibility ("is this player actually a tight end?") needs the player
dimension and runs after.

**One query for both lineups.** Fourteen ids go to
`rosters.get_roster_projections()` together, which is also what gives the
matchup its cross-lineup correlation disclosure for free.

**Nothing is written.** The endpoint is a read plus arithmetic. Re-running the
same request reproduces the result exactly, which is what makes storing
simulations a later product decision rather than a prerequisite.

---

## Lineup slots

`services/lineup.py` is the single source of truth. Nothing else in the codebase
spells out "an RB, a WR or a TE".

| slot | accepts | simulable |
|---|---|---|
| `QB` | QB | yes |
| `RB` | RB | yes |
| `WR` | WR | yes |
| `TE` | TE | yes |
| `FLEX` | RB, WR, TE | yes |
| `K` | K | **no** — no kicker model |
| `DST` | DST | **no** — no team-defence model |

Served at `GET /api/v1/meta/lineup-slots`, so a client builds its lineup editor
from the registry rather than from a hard-coded eligibility map.

### Two levels, separated on purpose

`LineupSlot` is the **vocabulary** — what a slot is called, what fills it.
`LineupFormat` is a **league's shape** — how many of each slot a starting lineup
has. One format exists today:

```
standard_skill: 1xQB, 2xRB, 2xWR, 1xTE, 1xFLEX   (7 players)
```

Keeping the two apart is what makes superflex a new `LineupFormat` rather than a
change to what FLEX means, and what makes a new slot (`OP`, `WR/TE`) something
every existing format simply ignores. Counts are exact rather than ranges: a
simulation compares two totals, and a nine-player lineup beats an eight-player
lineup for reasons that have nothing to do with the players in it.

### K and DST are recognised, not omitted

Both are in the registry with eligibility pointing at positions the projection
layer declares `planned`. A request naming a `K` slot is refused with the reason
and the blockers read out of `services.positions.POSITION_SUPPORT` — the same
sentence `/meta/positions` gives, because it is literally the same string.

Leaving them out of the registry would produce `unknown slot 'K'`, which reads
like a typo when the truth is that no kicker model exists. That is the
distinction this design exists to preserve.

The extension path is mechanical and is exercised by the tests, which iterate
the registry rather than hard-coding five strings:

1. ship a kicker model and flip `K` to `projected` in `POSITION_SUPPORT`;
2. add `SlotRequirement("K", 1)` to `STANDARD_FORMAT`.

Nothing in `lineup.py`, `simulation.py`, the router or the schema changes.
`assumptions.kicker_projection_available` flips to `true` on its own, because it
reads the registry rather than a hard-coded `False`.

---

## Monte Carlo methodology

### Sampling: inverse transform, from the stored percentiles

For each iteration and each player: draw `u ~ U(0,1)`, take `curve.quantile(u)`.

`OutcomeCurve` is a monotone piecewise-linear quantile function through the
stored P10/P25/P50/P75/P90, with linearly extended tails. It passes through the
stored percentiles **exactly** and assumes no parametric family. That is the
whole reason to sample it rather than a fitted normal: Layer 3b chose empirical
residual quantiles over a Gaussian precisely because weekly fantasy scoring is
right-skewed with a hard floor near zero, and fitting a normal at the last step
would throw that away.

Each iteration then sums each side, records the winner, and stores both totals
and the margin. Percentiles are read off the sorted samples with linear
interpolation (NumPy's default, R type 7), so `p10 <= p25 <= p50 <= p75 <= p90`
holds **by construction** — there is no smoothing step that could reorder them.

### Why sampling and not an exact convolution

`distributions.probability_beats()` answers the *two-player* question exactly,
by quadrature, with no sampling — and deliberately so, because a start/sit call
that returns a different answer on every refresh is unusable.

The lineup question is a sum of seven right-skewed piecewise-linear variables
per side, then a comparison of two such sums. The exact convolution is tractable
but expensive, and it would have to be rewritten the moment correlation arrives.
Sampling costs a seed and yields the whole joint distribution — margin
percentiles, tie rate, and any threshold question a product decision asks for
next — from the same code.

### Iteration counts

| constant | value | why |
|---|---|---|
| `MIN_ITERATIONS` | 100 | below this a P10 is the fifth order statistic and moves by whole points between seeds |
| `DEFAULT_ITERATIONS` | 10,000 | Monte Carlo standard error on a win probability near 0.5 is 0.005 — an order of magnitude below the calibration error of the distributions being sampled |
| `MAX_ITERATIONS` | 50,000 | a **transport** bound: ~0.8 s of synchronous CPU, and the endpoint holds an event-loop worker for the whole run |

`MAX_ITERATIONS` is not a statistical limit. The engine runs past it happily
when called directly, and there is a test asserting exactly that. A
hundred-thousand-iteration run is a legitimate thing to want; it is a background
job, not a synchronous HTTP request.

### Deterministic seed behaviour

`inputs + published run + seed` reproduce a result exactly.

- The seed goes to a **private** `random.Random`, never `random.seed()`.
  Seeding the module-level RNG would make one simulation's draws depend on
  whatever else in the process had called `random`.
- Omitting `seed` does **not** randomise. `DEFAULT_SEED` is used and echoed back
  in `simulation.seed`, so a user refreshing the page does not watch their win
  probability wander. This matches the standing decision behind
  `probability_beats`.
- **Draw order is lineup order.** Which uniform a player receives is fixed by
  their position in the submitted lineup, so the seed contract is a statement
  about the request rather than about an internal sort that could change. A test
  pins this so a future "sort the lineup for tidiness" change fails loudly.
- `simulation.model` carries the published run. With the seed and the iteration
  count, that is what makes a result reproducible *after a model rollout* — the
  superseded run is still on disk.

### Ties

Team totals are rounded to two decimals — the precision a fantasy platform
scores to — before they are compared.

This is not a rounding convenience. The reconstructed curves are continuous, so
`P(a == b)` on raw floats is exactly zero, and an engine comparing raw floats
would report a tie probability of `0.0` for every matchup ever simulated. That
is a confident falsehood about an event fantasy managers genuinely experience.

The reported figure is a **lower bound** on the true tie rate rather than an
estimate of it: real scoring is discrete in ways the continuous reconstruction
does not model. Typical values are a few hundredths of a percent.

---

## What the result contains

### Per team

`expected_score`, `median_score`, `p10`, `p25`, `p75`, `p90`,
`win_probability`, `loss_probability`, `tie_probability`, plus the per-player
breakdown and `projection_sum`.

`projection_sum` is the sum of the stored calibrated means and is the one
**model**-provenance number in the block. It sits beside `expected_score` (the
mean of the sampled totals) because their agreement is the cheapest available
check that the sampler drew from the distributions it was handed.

They agree closely but not exactly, and the gap is expected rather than a
defect: `distributions.py` extends the upper tail 2.0x the P75–P90 segment
against 1.0x on the lower, because weekly scoring is right-skewed. The
reconstruction's mean therefore sits a percent or two above the stored mean.
Both numbers are reported so a caller can see that rather than discover it.

**The gap is not a tail-factor artifact and is not being closed.** Phase 6C
measured it under 36 tail configurations and found recalibration barely moves
it: the same gap is present at the *player* level, where it is a property of
reconstructing a right-skewed distribution from five percentiles. Forcing
`expected_score == projection_sum` would fix a cosmetic identity by making the
intervals measurably worse. It is recorded as an open foundation question —
[whether `expected_points` and the five stored percentiles imply the same
probability distribution](#the-open-foundation-question) — and not as a
simulation defect.

### Per matchup

`score_differential` (mean margin), `median_differential`, `iterations`, `seed`,
`sampling_method`, `lineup_format` and the `model` reference.

The two differentials disagree whenever one lineup is more volatile than the
other, which is exactly when a user should be told.

### Guaranteed invariants

- `p10 <= p25 <= median_score <= p75 <= p90`, by construction.
- `win + loss + tie == 1` on each side, to floating tolerance.
- `team_a.win_probability == team_b.loss_probability`.
- Every submitted slot appears in the response, in order. Nothing is dropped.

---

## Provenance

The result is **`derived`**. Every simulated number — team scores, percentiles,
win probability — carries `provenance: "derived"`, and this is the single most
important labelling decision in the feature.

A simulation consumes model predictions exclusively. It is still a calculation
performed *above* the model. Labelling its output `model` would extend the
frozen foundation's measured guarantees — interval coverage, calibration error,
conditional bias, all measured against held-out residuals — to a quantity nobody
ever measured that way.

| block | provenance | what it is |
|---|---|---|
| `team_*.players[].expected_points`, `floor`, `ceiling` | `model` | read from the published run |
| `team_*.projection_sum` | `model` | sum of stored calibrated means |
| `team_*` scores, percentiles, probabilities | `derived` | statistics of the sampled totals |
| `simulation` | `derived` | how the calculation was run |
| `simulation.correlation_mode`, `correlation_model_version` | `derived` | which sampler ran, and which fitted structure |
| `assumptions` | `derived` | what the calculation assumed |
| weather, injury, market | `context` | observed, not consumed — unchanged |
| matchup grade | `derived` | not consumed by this engine at all |

---

## Statistical assumptions and limitations

All four are exposed as **fields** on the response, not only as prose. A client
renders a banner from `assumptions.player_independence` without string-matching
a caveat, and the flags flip on their own when the underlying situation changes.

### 1. Player independence — measured twice, and still the default

Every player is drawn from their own independent uniform. That is wrong in three
places at once:

- **Teammates** divide one offence's finite plays. A QB and their WR1 are
  strongly positively correlated through team scoring and negatively correlated
  through target competition; two backs in a committee are strongly negative.
- **Opposing players in one game** share pace and script.
- **The two lineups** are correlated *with each other* whenever they hold
  players from the same game — common in a twelve-team league, and the case a
  pairwise start/sit call never has to think about.

All three are real, and Phase 6B measured how large each one is: see
[Phase 6B](#phase-6b--correlated-simulation-the-measured-answer). The
quarterback-to-own-receiver correlation is +0.24, and it is the pair a manager
deliberately assembles.

**What Phase 6A predicted about the consequence turned out to be wrong**, and
the correction is left visible here rather than quietly deleted. This document
used to say the intervals came out *too narrow* and the win probability sat
*further from 50% than the evidence supports*. Measured on 4,320 held-out
historical matchups, neither holds: the independent simulator's 80% team-total
interval covers **82.3%** of realised totals — too wide, not too narrow — and no
simulated win probability in the whole backtest landed outside [0.05, 0.95]. The
independence error is real but it is smaller than, and opposite in sign to, the
tail-extension error in `distributions.py` that sits on top of it.

**Correlation is available and is not the default.** `correlation_mode:
game_environment` applies a structure fitted on held-out history. It was scored
against this baseline twice — in
[Phase 6B](#phase-6b--correlated-simulation-the-measured-answer) under the old
tail factors, and again in
[Phase 6D](#phase-6d--correlation-promotion-validation) under the recalibrated
ones — and did not beat it either time. The second measurement is the one that
matters, because the first was entangled with a marginal error that has since
been fixed.

The short version of the second: with the marginals calibrated, the independent
sampler's team-total interval is already within half a point of nominal on
exactly the population correlation was supposed to fix, so correlation now
pushes it *past* nominal instead of onto it, and no proper score moves
significantly in either direction.

Under the default, the engine still names what it is ignoring:
`rosters.correlation_groups()` identifies every team group and game group inside
each lineup, `_shared_games()` identifies games spanning the two lineups, and
each becomes a caveat in `meta.notices` naming the specific players.

`assumptions.player_independence: true`.

### 2. Kickers and team defences are not projected

The gap that cannot be closed inside the simulation engine. A standard lineup
starts a K and a DST; neither has a projection, for the reasons and with the
blockers recorded in `services.positions.POSITION_SUPPORT`.

So `standard_skill` covers seven of a typical nine starters — roughly 80% of a
lineup's points. The missing 20% is **not** noise that cancels between two
teams: it is a systematically absent block with its own variance, and a win
probability computed as if both teams were complete is overconfident.

The decision is to **declare the gap, not fill it**. A league-average fallback
distribution for K and DST would make totals look complete while injecting two
uncalibrated numbers into a system whose entire premise is that every stored
distribution was measured against held-out residuals.

A `K` or `DST` slot is refused, and so is a kicker submitted in a FLEX — the
same gap wearing a different label, and the one that would silently cost a team
twenty points if tolerated.

`assumptions.kicker_projection_available: false`,
`assumptions.defense_projection_available: false`.

### 3. Injury is context, not adjustment

`injury_multiplier` is stored and unwritten — Layer 3b measured it and excluded
it on the evidence. A player designated Out has a projection describing a player
who will not take the field.

The engine **does not overrule the projection**. There is no invented injury
multiplier and no zeroing: a player listed Out contributes their full
distribution, because that is what the published run says, and silently zeroing
it here would destroy the distinction between "projected zero" and "not
playing". The designation becomes a caveat naming the player.

`assumptions.injury_adjustment_applied: false`.

### 4. Matchup grade is derived, and is not an input

`matchup_score` is NULL in the projection model. The matchup grade is computed
above the model from trailing defensive fantasy points allowed, and the model
has never seen it. This engine consumes no matchup grade at all — if one is
shown beside a simulation later it must come from `services.grading` and be
labelled `derived`.

`assumptions.matchup_adjustment_applied: false`.

### What a missing projection does

Any starter with no published projection **fails the whole request**, with a
message naming the player, the side and the reason. This is the one place the
simulation engine departs from the rest of the read layer, which reports gaps
and carries on.

The reason is that a team total is a *sum*. A missing starter does not make the
answer slightly less complete — it removes that player's entire contribution and
produces a win probability that is confidently wrong with nothing on the screen
to say so. `RosterProjections` already distinguishes the causes:

| reason | meaning | permanent? |
|---|---|---|
| `unprojected_position` | K, DST, or a non-fantasy position | yes |
| `unknown_player` | not in the player dimension | yes |
| `no_projection` | projectable, nothing published — bye, inactive, unpublished run | no |

A projection with fewer than three stored percentiles is refused for the same
reason: a simulation samples a distribution and cannot be run from a point
estimate. Substituting `expected ± some percentage` is exactly the fabrication
the distribution layer exists to prevent.

---

## Performance

Measured on one core of a developer machine (Windows, CPython 3.10), fourteen
players — two full `standard_skill` lineups:

| iterations | wall clock | per iteration |
|---|---|---|
| 1,000 | 14 ms | 13.8 µs |
| 10,000 (default) | 138 ms | 13.8 µs |
| 25,000 | 341 ms | 13.7 µs |
| 50,000 (max) | 701 ms | 14.0 µs |
| 100,000 | 1,445 ms | 14.5 µs |

Linear in iterations, as it must be for a bound set from one measurement to
describe another.

End to end through the ASGI app against real Postgres — request parsing,
validation, the projection query, 10,000 iterations, and JSON serialisation of
fourteen players — a default request measured **236 ms**. The projection fetch
is one query for both lineups, so the database contribution is roughly constant
in the iteration count.

`tests/test_simulation_performance.py` asserts the ceiling holds, with budgets
roughly an order of magnitude above the measurements — loose enough to survive a
slow CI runner, tight enough to catch an order-of-magnitude regression. If a
change makes an iteration three times more expensive, the fix is to lower
`MAX_ITERATIONS` or speed up the loop, not to raise the budget.

The endpoint is synchronous CPU work and holds an event-loop worker for the
whole run. That is what sets the ceiling, and it is why 100,000+ iterations is a
background-job concern rather than a larger bound.

---

## Phase 6B — correlated simulation, the measured answer

**Result: the correlated candidate did not beat the independent baseline on
held-out matchups, so the independent simulator remains the production
default.** It ships behind `correlation_mode: game_environment`, labelled
experimental, because the structure is real and worth keeping — but nothing in
the evidence justifies promoting it.

Everything below is reproducible with `python scripts/phase6b_backtest.py`, which
writes `artifacts/phase6b_report.txt`.

### Why independence was worth attacking

The Phase 6A engine assumes `P(A, B) = P(A) · P(B)` for every pair of players.
That is false for anyone sharing a game, and the pair it is most false for — a
quarterback and his own receiver — is the pair fantasy managers deliberately
build around. Whether it *mattered* was an open question, and the only way to
settle it was to fit a structure and score it.

### The historical evidence that exists

| what | where | coverage |
|---|---|---|
| player actual fantasy points | `player_week.fp_{profile}` | 2016–2025, 4 profiles |
| player / team / opponent / game id | `feat_training_dataset` | complete |
| season, week, home/away | `feat_training_dataset` | complete |
| positions | `feat_training_dataset` | QB/RB/WR/TE projected |
| betting total and spread | `game_team.total_line`, `team_spread` | complete from 2020; ~3% missing 2016–19 |
| implied team total | `game_team.implied_team_total` | derived from the two above |
| team and opponent score | `game_team` | complete |
| snap share | `player_week.offense_pct` | ~99.9% |
| projections and residuals | **generated**, not stored | see below |

The gap that shaped the design: **there is no stored history of projections.**
`projections` holds 348 rows for one published run, which is a current-week
artifact, not a history. And there is no history of fantasy *matchups* at all —
no rosters, no leagues, no users, deliberately, since Phase 6A was built without
them.

Both had to be constructed, and both are the places leakage would enter.

### Leakage control

Two boundaries, enforced separately.

**The projection boundary** is Layer 3b's and was not reimplemented.
`predict.backtest.run_backtest()` already walks forward week by week, refits the
base model on strictly-earlier rows, and fits the residual distribution on
residuals that are themselves out-of-fold. `correlation/panel.py` calls it
unchanged and joins on team, opponent and game id — three schedule facts known
months in advance — producing **38,061 player-weeks (2019–2025)**, each carrying
the projection and distribution a deployment would actually have had.

**The correlation boundary** is Phase 6B's. `estimate.walk_forward_models()`
fits the structure applied to week *N* on pairs from weeks strictly before *N*,
and asserts `estimation.through < (season, week)` before yielding. A week with
too little history yields `None` and is **skipped**, never back-filled with a
later fit. So a correlation is out-of-fold twice over: with respect to the model
that produced its residuals, and with respect to the week it is applied to.

`tests/test_correlation_estimate.py::TestLeakage` pins both.

### The marginals the correlation is measured through

Correlation is estimated on the **probability integral transform** — each
outcome mapped through its own published distribution, then through the inverse
normal CDF. That makes a quarterback and a tight end comparable despite scoring
in different units with different skew, and it is exactly the parameter a
Gaussian copula consumes.

It also means the estimate inherits any miscalibration in the marginals, so the
PIT is reported first. On the startable population it is flat:

```
[0.0,0.1) 0.100   [0.2,0.3) 0.101   [0.4,0.5) 0.096   [0.6,0.7) 0.098   [0.8,0.9) 0.091
[0.1,0.2) 0.092   [0.3,0.4) 0.103   [0.5,0.6) 0.113   [0.7,0.8) 0.107   [0.9,1.0) 0.101
```

Over the *whole* panel it is not — the bottom two bins hold 11.6% and 12.5%,
which is the zero atom on near-zero projections. That is one reason the
estimation is conditioned on startable players.

Zero is handled as a genuine atom via a **randomised PIT**: `OutcomeCurve` clamps
at zero, so every player scoring exactly zero would otherwise map to the same
value and two of them would look perfectly correlated, biasing every cell upward.

### What the history actually says

Measured correlations, half-PPR, projections ≥ 6.0 points, 2019–2025:

| pair | correlation | n | |
|---|---|---|---|
| QB – WR, **same team** | **+0.236** | 8,382 | the signal |
| QB – TE, **same team** | **+0.218** | 2,350 | |
| QB – QB, opposing | +0.143 | 2,279 | shootouts are real |
| QB – WR, opposing | +0.073 | 8,365 | |
| QB – RB, same team | +0.062 | 5,361 | |
| QB – TE, opposing | +0.061 | 2,332 | |
| WR – WR, opposing | +0.050 | 7,841 | |
| WR – TE, opposing | +0.046 | 4,437 | |
| QB – RB, opposing | +0.031 | 5,350 | |
| WR – WR, **same team** | **+0.004** | 5,497 | target competition cancels it |
| RB – WR, same team | −0.014 | 9,942 | |
| RB – RB, same team | −0.037 | 1,539 | committee |
| RB – RB, opposing | −0.039 | 3,214 | game script |
| QB – QB, same team | −0.357 | 519 | relief appearance — excluded |

Three findings, none of them assumed in advance:

1. **The dependence is concentrated on the quarterback.** QB↔own pass-catcher
   is +0.22 to +0.26 and stable in all seven seasons measured separately
   (0.218–0.259). Everything not involving a QB is within 0.05 of zero.
2. **Pass-catchers on the same team do not move together.** WR-WR same-team
   (+0.004) is *lower* than the same pair on opposite teams (+0.050). Shared
   offence and target competition cancel almost exactly.
3. **Correlation rises steeply with projection size** — QB-WR same-team runs
   +0.132 at no floor, +0.236 at 6 points, +0.312 at 10. A player projected for
   two points is mostly a question of whether he plays, which is idiosyncratic.
   The game-level effect barely moves, which is what an effect about the *game*
   rather than the players should do.

### The chosen structure, and what it cannot do

A two-factor latent model, positive semi-definite by construction and O(players)
per iteration:

```
z_i = alpha_p · G_game  +  beta_p · T_team  +  delta_p · e_i        (all N(0,1))

  same team:      alpha_p·alpha_q + beta_p·beta_q
  opposing:       alpha_p·alpha_q
  different game: exactly zero
```

Chosen over a 91-parameter player-by-player matrix (needs PSD repair, needs a
Cholesky per matchup, estimated from whatever pairs happen to be in one lineup)
and over an empirical copula (the same-team pairs number in the low thousands,
so it would be resampling past afternoons rather than describing a
distribution).

Fitted loadings, n-weighted least squares over 19 cells:

| position | game | team | own | shared variance |
|---|---|---|---|---|
| QB | 0.399 | 0.917 | 0.000 | 1.000 |
| WR | 0.176 | 0.162 | 0.971 | 0.057 |
| TE | 0.132 | 0.166 | 0.977 | 0.045 |
| RB | 0.028 | 0.044 | 0.999 | 0.003 |

Weighted RMSE **0.0241**.

**The quarterback's team loading is an identification, not a fit.** The team
loadings enter the objective only as products `beta_p·beta_q`, and the one cell
that would pin `beta_QB` alone is `QB-QB same` — excluded as a relief-appearance
artifact. So the objective falls monotonically as `beta_QB` rises and the
optimiser runs to the edge of the box. Rather than let a boundary artifact stand
in for a missing normalisation, `beta_QB = sqrt(1 − alpha_QB²)` is imposed, which
has a plain reading: **the shared part of an offence's week is the
quarterback's week.** It changes no correlation between two players a lineup can
hold.

**Three measured cells are unreachable and are reported, not hidden.** A factor
model gives same-position players identical loadings, so their correlation is
`alpha² + beta²` and cannot be negative:

| cell | observed | fitted | gap |
|---|---|---|---|
| WR-WR same | +0.004 | +0.057 | −0.053 |
| TE-TE opp | −0.032 | +0.017 | −0.049 |
| WR-TE same | +0.008 | +0.050 | −0.042 |
| RB-RB same | −0.037 | +0.003 | −0.040 |
| RB-RB opp | −0.039 | +0.001 | −0.039 |

All five are small, and all five err toward **over**-correlating — which widens
intervals rather than narrowing them, the conservative direction for a phase
whose stated risk is overconfidence.

### Marginal preservation

The safety property: a correlation model may change the joint distribution and
may not touch a marginal, or it has silently become a second unvalidated
projection model.

The sampler produces a **uniform per player**; the engine still calls
`curve.quantile(u)`. Since `z` is standard normal by construction, `Phi(z)` is
exactly uniform, so the marginal is preserved by construction rather than by
care. `tests/test_correlation_marginals.py` measures it anyway at roughly double
the fitted loadings — mean, median, P10 and P90 per player, plus a per-player
uniformity histogram — and the backtest reports the team-total drift against the
projection sum: **1.625 points independent, 1.633 correlated** on ~110-point
totals. Unchanged, so correlation neither inflates nor deflates a total.

### Baseline versus candidate

72 held-out weeks (2022–2025), 4,320 synthesised matchups per arm, identical
lineups and identical seeds in both arms, 2,000 iterations each.

| metric | independent | correlated | verdict |
|---|---|---|---|
| Brier | 0.22969 | **0.22921** | candidate, t = −2.06 (marginal) |
| log loss | 0.65081 | **0.64969** | candidate, −0.2% |
| ECE | **0.0094** | 0.0128 | baseline |
| **max calibration error** | **0.0478** | 0.0648 | baseline |
| coverage @ 80% (nominal 0.80) | **0.8228** | 0.8287 | baseline, t = +4.10 |
| coverage @ 50% (nominal 0.50) | **0.5332** | 0.5416 | baseline |
| mean P10–P90 width | 52.2 | 53.1 | +0.89 pts, t = +44 |
| CRPS | **10.7732** | 10.7771 | tie, t = +0.88 |
| total drift vs projection sum | 1.625 | 1.633 | tie — no bias introduced |
| win probs outside [0.05, 0.95] | 0.0% | 0.0% | neither is overconfident |

On stacked lineups — the population the candidate should help most — the pattern
is the same: Brier 0.22768 → 0.22730, max calibration error 0.0471 → 0.0443, and
coverage moving *further* from nominal, 0.8134 → 0.8280.

### The paired differences

Both arms see identical lineups, identical realised outcomes and identical
seeds, so the per-matchup difference isolates the sampler. Pairing matters here:
unpaired, the standard error on a Brier score across 4,320 matchups is ~0.004,
eight times the difference being looked for.

```
brier       delta=-0.000478  se=0.000233  t= -2.06   significant
crps        delta=+0.003974  se=0.004506  t= +0.88   indistinguishable from zero
cov80_gap   delta=+0.005903  se=0.001438  t= +4.10   significant
width       delta=+0.894882  se=0.020257  t=+44.18   significant
```

Read together: the Brier improvement is **real but marginal** — barely two
standard errors, and 0.2% of the metric's level. The coverage deterioration is
**four standard errors**, and the interval widening is not in doubt at all.

### Why it fails acceptance

**The one metric that improves does so marginally; the metric that degrades does
so decisively.** Brier moves in the candidate's favour by 0.0005 at t = −2.06.
Coverage moves *away* from nominal at t = +4.10. Log loss follows Brier, ECE,
maximum calibration error and CRPS follow coverage. A candidate that buys 0.2%
of a win-probability score by making a well-calibrated interval measurably worse
has not earned promotion.

**The mechanism is now clear, and it is a finding in its own right.** The
independent simulator's intervals are already **too wide** (82.3% coverage on a
nominal 80%), because the tail extension `distributions.py` shipped at the time
(2.5× on the upper segment) over-disperses a seven-player sum. Correlation only
ever *adds* variance under this structure. So it is pushing a distribution that
is already too wide further in the wrong direction, and the small Brier gain is
not evidence of a better model.

**Phase 6C fixed that error and Phase 6D re-ran this comparison against the
corrected marginals.** The re-test is the one that decides the question; the
paragraphs above are kept because they are the reasoning the re-test had to
answer, not because they are the current verdict. See
[Phase 6D](#phase-6d--correlation-promotion-validation).

**Independence was not causing the overconfidence it was accused of.** Zero
matchups in 4,320 produced a win probability outside [0.05, 0.95], and the
calibration table is close to the diagonal in both arms.

**No promotion.** The candidate is retained behind an explicit mode because the
structure is empirically real and the harness now exists to re-test it the
moment the marginals change. It is not the default and should not be until it
demonstrates an improvement.

### Performance

Fourteen players, one core, CPython 3.10:

| iterations | independent | correlated | ratio |
|---|---|---|---|
| 1,000 | 15 ms | 31 ms | 2.01× |
| 10,000 (default) | 156 ms | 311 ms | 2.00× |
| 25,000 | 394 ms | 787 ms | 1.99× |
| 50,000 (max) | 782 ms | 1,596 ms | 2.04× |

Linear in iterations in both modes, and a flat **2.0×** for correlation — it
draws a normal per player plus one per game and per team, and an error function
per player, against one uniform per player. A default request goes from ~236 ms
to roughly ~390 ms end to end, which stays inside a synchronous request budget.
No background job is introduced. `tests/test_simulation_performance.py` asserts
both the absolute budgets and the ratio.

### API

`POST /api/v1/simulations` is unchanged for every existing caller.
`correlation_mode` defaults to `"independent"`, and omitting it reproduces Phase
6A **bit for bit** — the independent sampler draws the same uniforms in the same
order, and `tests/test_api_simulations.py` pins that the response is byte-identical.

Two new provenance fields, read from the sampler that ran rather than echoed
from the request, so a response can never describe a correlated simulation that
was not one:

```json
"simulation": {
  "provenance": "derived",
  "sampling_method": "inverse_transform_from_stored_percentiles",
  "correlation_mode": "game_environment",
  "correlation_model_version": "1.0.0"
}
```

Two refusals rather than fallbacks. An unknown mode is a 422. A profile with no
fitted structure is a 422 — correlations are measured *through* each player's
own distribution, and those differ by scoring profile, so serving the half-PPR
structure for a PPR request would be an unmeasured claim wearing a measured
one's version number. Only `half_ppr` has a fitted structure.

### Limitations

1. **A Gaussian copula has no tail dependence.** A quarterback and his top
   receiver have their spectacular weeks on the same afternoon more often than
   this model allows. A t-copula would fix it; its degrees-of-freedom parameter
   is not identifiable from four figures' worth of same-team pairs.
2. **Negative correlations cannot be represented** — committee backs, opposing
   backs under game script, receivers competing for targets. All are small.
3. **One loading per position, regardless of projection size**, despite the
   measured effect nearly doubling between a 6-point and a 12-point projection.
   The estimation floor of 6.0 sits below a typical starter, so the fitted
   values understate a real lineup's dependence.
4. **Matchups are synthesised, not historical.** There is no roster history to
   evaluate against. Lineups are drawn from projections and eligibility only,
   with 35% built around a QB stack to over-sample the case where the arms
   disagree; but a real league's lineups are not this draw.
5. **Half-PPR and `shrinkage_eb` only.**
6. **K and DST are still absent**, so the RB-versus-opposing-defence
   relationship in the brief is not measurable at all.

### The finding that belongs to the foundation, not to this phase

The backtest measured something the correlation model cannot fix: **the team
total's 80% interval covers 82–83% of realised totals**, in both arms, and the
team-total PIT is mildly hump-shaped (0.093 / 0.099 in the bottom two bins
against 0.091 / 0.084 in the top two). The reconstructed distributions are
slightly over-dispersed and slightly right-shifted at the lineup level, which is
consistent with `LOWER_TAIL_FACTOR = 1.5` / `UPPER_TAIL_FACTOR = 2.5` in
`distributions.py` — the only free parameters in the reconstruction, and never
validated at the *sum* level because Phase 6A had no way to.

**This is a recommendation, not a change.** Per the phase's own rule, the frozen
Layer 3b foundation has not been touched, and neither have the tail factors. It
is recorded here as the next modelling question, and it is a better-evidenced one
than correlation was.

**Phase 6C took it up and confirmed it**, on the same panel and with the factors
as a parameter. See [Phase 6C](#phase-6c--lineup-level-tail-calibration).

---

## Phase 6C — lineup-level tail calibration

**Result: `LOWER_TAIL_FACTOR = 1.0` / `UPPER_TAIL_FACTOR = 2.0`, approved and
shipped.** They replace `1.5 / 2.5`, which had been the production constants
since Phase 6A. The recommendation was the region rather than the argmin, for
reasons given under
[the recommendation](#the-recommendation-and-what-it-is-not).

**What the change is, and what it is not.** It is a distribution/calibration
improvement: the team total's 80% interval was about two points too wide and now
sits on nominal, the team-total PIT is flatter, and maximum calibration error is
lower. It is **not** a demonstrated winner-prediction improvement. CRPS, Brier
and score-differential CRPS all moved in its favour and **none of them
significantly** (|t| between 0.8 and 1.5). Nothing below should be read as a
claim that the new factors make the simulator better at picking a matchup.

The tables in this section compare `1.5 / 2.5` against the *tuning argmin*
`0.5 / 2.0`, because that is what the selection rule chose and what the report
was written around. The approved pair `1.0 / 2.0` is the neighbouring cell, and
its held-out figures are given under
[the recommendation](#the-recommendation-and-what-it-is-not). Phase 6D then
measured `1.0 / 2.0` directly and at length; where the two disagree, Phase 6D is
the configuration that ships.

Everything here is reproducible with `python scripts/phase6c_tails.py`, which
writes `artifacts/phase6c_report.txt`.

### The question, and why the player level could not answer it

The two factors govern what happens **outside** the five stored percentiles:
below P10 the curve is extended by `LOWER_TAIL_FACTOR × (P25 − P10)`, above P90
by `UPPER_TAIL_FACTOR × (P90 − P75)`. They were chosen from the shape of a
single player's week, and at that level they are almost unfalsifiable — 80% of
the mass sits between the stored knots, which the factors cannot move at all.

Nothing the product sells is one player's week. A team total is a **sum of seven
curves**, and summing is exactly the operation that promotes a tail assumption
from a rounding error to the dominant term: the interior contributions average
out across seven players while the tail contributions, all pointing the same
direction, do not.

Phase 6B saw the symptom and could not act on it. Phase 6C makes the factors a
parameter and measures the sum.

### What is measured

Three levels, because they disagree, and the disagreement is the finding.

| level | metrics |
|---|---|
| player | coverage at each stored knot, CRPS, curve mean vs stored expected |
| lineup | knot calibration of the realised total, 80% and 90% interval coverage, PIT of the realised total, CRPS |
| matchup | win-probability Brier, log loss, ECE, **maximum** calibration error, score-differential CRPS and coverage |

Maximum calibration error is reported throughout and is not replaced by ECE, for
the reason given in `nflfp.predict.calibration`: ECE is sample-weighted and rates
a model excellent when its rare confident predictions are catastrophically
wrong.

### Leakage control

Three boundaries, and the first two are inherited rather than re-argued.

**The projection boundary** is Layer 3b's, enforced inside
`predict.backtest.run_backtest` and reused unchanged through the Phase 6B panel:
38,061 player-weeks, each carrying the distribution a deployment would have
published before that week kicked off.

**The correlation boundary** is Phase 6B's: any structure applied to week *N* is
fitted only on weeks strictly before *N*.

**The tuning boundary is this phase's.** Candidates are chosen on **2022–2023**
and reported on **2024–2025**, and the two never overlap. The held-out surface is
printed in full — but the recommendation is the tuning selection whatever the
held-out argmin says, which is the only way that word means anything.

The realised score enters in exactly one place: the metric. Lineups are
synthesised from projections and eligibility only, by the Phase 6B sampler.

### The search, and why it is a surface and not an argmin

36 cells: lower ∈ {0.0 … 2.5}, upper ∈ {0.5 … 3.0}, step 0.5, centred on the
incumbent and reaching zero on the lower factor because "do not extend at all"
is a real hypothesis once the summed distribution is suspected of being too
wide.

Every cell is scored on the **same lineups and the same draws**. That pairing is
the whole design — a difference between two cells is the tail configuration and
nothing else — and it is what makes differences this small legible at all.

Two properties of the surface matter more than its minimum. **It is smooth and
it has a basin**, in the same place on both periods:

```
lineup PIT divergence, tuning (lower is flatter)     [* = incumbent]
  lower\upper   0.50    1.00    1.50    2.00    2.50    3.00
       0.00   0.1535  0.1188  0.0750  0.0493  0.0764  0.0979
       0.50   0.1486  0.1132  0.0736  0.0368  0.0653  0.1000
       1.00   0.1542  0.1153  0.0819  0.0507  0.0687  0.1049
       1.50   0.1653  0.1188  0.0903  0.0715 0.0792*  0.1139
       2.00   0.1778  0.1299  0.1049  0.0882  0.0937  0.1236
       2.50   0.1882  0.1417  0.1215  0.1000  0.1076  0.1389

lineup PIT divergence, held-out                      [* = incumbent]
  lower\upper   0.50    1.00    1.50    2.00    2.50    3.00
       0.00   0.1712  0.1252  0.0803  0.0650  0.0893  0.1122
       0.50   0.1643  0.1179  0.0907  0.0705  0.0855  0.1008
       1.00   0.1584  0.1135  0.0754  0.0605  0.0793  0.1015
       1.50   0.1668  0.1225  0.0932  0.0712 0.0894*  0.0987
       2.00   0.1716  0.1288  0.0946  0.0851  0.1001  0.1147
       2.50   0.1751  0.1302  0.1043  0.0816  0.1053  0.1245
```

**The upper factor is doing nearly all the work.** Moving along a row changes the
metric by 3–4×; moving down a column barely moves it. That is not a quirk of the
metric — it is the hard floor. `HARD_FLOOR = -6.0` and a typical startable P10 is
1–4 points, so the lower extension is clamped or nearly flat for most players
whatever the factor says, while the upper extension is unbounded and multiplies
a P75–P90 gap that is 5–8 points wide. A phase that had tuned the two factors
independently would have reported the lower one as "well calibrated" when the
truth is that it is barely identified.

The tuning argmin is (0.5, 2.0); the held-out argmin is (1.0, 2.0). Both sit in a
basin whose floor is flat to within the noise, and **the upper factor is 2.0 in
both**.

### The selection rule, declared before the surface was read

1. **primary** — lineup-total PIT divergence, the total absolute deviation of a
   10-bin PIT histogram from uniform. The full shape of the team total's
   calibration, not two thresholds of it: a distribution can hit 80% coverage
   exactly while being wrong everywhere in between.
2. **tie-break** — lineup CRPS, a proper score, because PIT divergence is blind
   to sharpness and would happily accept a needlessly wide distribution that
   happens to be uniform.

### Baseline versus candidate, held-out

36 held-out weeks (2024–2025), 1,438 matchups, 2,876 lineups, identical lineups
and draws in both arms, 2,000 draws each.

| metric | incumbent 1.5/2.5 | candidate 0.5/2.0 | change |
|---|---:|---:|---:|
| lineup P10 coverage (0.100) | 0.0949 | 0.1092 | +0.0143 |
| lineup P25 coverage (0.250) | 0.2399 | 0.2580 | +0.0181 |
| lineup P50 coverage (0.500) | 0.5195 | 0.5202 | +0.0007 |
| lineup P75 coverage (0.750) | 0.7629 | **0.7469** | −0.0160 |
| lineup P90 coverage (0.900) | 0.9169 | **0.8995** | −0.0174 |
| 80% interval coverage (0.800) | 0.8220 | **0.7903** | −0.0316 |
| 90% interval coverage (0.900) | 0.9145 | **0.8884** | −0.0261 |
| mean 80% width | 52.03 | 48.63 | −3.40 |
| lineup PIT divergence | 0.0894 | **0.0705** | −0.0189 |
| lineup CRPS | 10.9130 | **10.9057** | −0.0073 |
| player CRPS | 3.9381 | **3.9359** | −0.0022 |
| player knot error | 0.0050 | 0.0050 | 0.0000 |
| win probability Brier | 0.22486 | **0.22450** | −0.00035 |
| win probability log loss | 0.64043 | **0.63953** | −0.00090 |
| ECE | 0.0213 | **0.0195** | −0.0018 |
| **max calibration error** | 0.0708 | **0.0561** | −0.0147 |
| score differential CRPS | 15.5353 | **15.5263** | −0.0090 |
| expected score − projection sum | +1.686 | +1.597 | −0.089 |

Read the coverage rows as distances from nominal, not as raw movement: 80%
coverage goes from 0.022 **too wide** to 0.010 too narrow, and 90% coverage from
0.0145 too wide to 0.0116 too narrow. Both end closer to nominal, and both
**overshoot** rather than land on it.

### Is it statistically justified?

Every cell sees the same lineups and the same draws, so the differences are
paired. Candidate minus incumbent, on held-out data:

```
lineup CRPS               delta=-0.007333  se=0.005472  t=  -1.34   indistinguishable
lineup 80% coverage       delta=-0.031641  se=0.003265  t=  -9.69   significant
lineup 90% coverage       delta=-0.026078  se=0.002972  t=  -8.77   significant
lineup PIT centrality     delta=+0.010763  se=0.000108  t= +99.64   significant
lineup 80% width          delta=-3.402112  se=0.007528  t=-451.91   significant
win probability Brier     delta=-0.000354  se=0.000236  t=  -1.50   indistinguishable
score differential CRPS   delta=-0.009011  se=0.011374  t=  -0.79   indistinguishable
```

**The dispersion claim is overwhelming; the accuracy claim is not.** The mean
distance of a realised total from the middle of its own forecast — `|PIT − 0.5|`,
which a calibrated forecast puts at 0.250 — moves from **0.2431 to 0.2538**, at
t = +99.6. The incumbent is measurably too wide and the candidate is measurably
slightly too narrow, and there is no doubt about either.

The scoring rules move the right way and **none of them significantly**. CRPS,
Brier and differential CRPS all favour the candidate at t between −0.8 and −1.5.
That is the honest summary: this recalibration fixes a *calibration* defect, and
it does not make the simulator meaningfully better at picking winners. It should
be argued for on the first ground and not the second.

### The shape of the error, which one global pair of factors cannot hold

The strongest argument against the candidate is in the conditional breakdown.

| held-out stratum | n | incumbent cov80 | candidate cov80 |
|---|---:|---:|---:|
| projection < 66 | 513 | 0.8363 | **0.7992** |
| projection 66–79 | 1,786 | 0.8270 | **0.7968** |
| projection > 79 | 577 | **0.7938** | 0.7626 |
| unstacked | 1,856 | 0.8346 | **0.8017** |
| stacked | 1,020 | **0.7990** | 0.7696 |

**The error is conditional, and the two conditions point opposite ways.**
Low-projection and unstacked lineups are too wide under the incumbent and the
candidate fixes them. High-projection and stacked lineups are *already* at
nominal under the incumbent, and the candidate makes them too narrow.

Both have mechanisms, and neither is a tail problem:

* a **high-projection** lineup is made of players whose distributions are wide in
  absolute terms, so its total is dominated by genuine spread rather than by the
  tail assumption;
* a **stacked** lineup contains players who are genuinely positively correlated,
  which the independent sampler does not model — so its simulated total is too
  narrow to begin with, and the over-wide tails were silently compensating.

The second of these is the same offsetting-errors story Phase 6B suspected, now
measured directly. It is the reason the correlation re-test below matters, and
the reason a single global pair of factors is a compromise rather than a fix.

Lineup size behaves as the summation argument predicts and does not disturb the
conclusion: the incumbent is too wide at 5, 7 and 9 players (cov80 0.8357 /
0.8208 / 0.8199) and the candidate lands near nominal at all three (0.8043 /
0.7972 / 0.7914).

### The expected-score gap, which is not a tail problem

Phase 6A observed `expected_score ≈ 4%` above `projection_sum` and attributed it
to the asymmetric tail extension. Measured on held-out data, the gap is
**+2.32%** (+1.686 points on a 72.7-point lineup) and the candidate moves it to
**+2.20%** (+1.597). Recalibration **barely touches it**, and no cell of the grid
that is defensible on calibration grounds removes it.

The reason is visible at the player level: the curve's own mean sits **+2.26%**
above the stored calibrated mean under the incumbent and **+2.20%** under the
candidate. The gap is a property of reconstructing a right-skewed distribution
from five percentiles, not of how far the tails are extended — a piecewise-linear
interpolation through P10…P90 already places mass differently than the
distribution the calibration measured, and the tails only modulate it.

Removing it would require forcing `E[curve] = expected`, which the grid says
costs calibration: the cells whose drift is near zero (upper ≈ 1.5) have PIT
divergence 0.075–0.093 against 0.0705 for the candidate, and 80% coverage of
0.77–0.79. **The distribution should keep its positive skew.** Weekly fantasy
scoring has a hard floor near zero and a genuinely long ceiling; a lineup's mean
sitting above the sum of its medians is what right-skew *means*, and forcing the
two to agree would fix a cosmetic identity by making the intervals worse.

This is now a foundation question — whether `expected_points` and the stored
percentiles imply the same distribution — and not a Phase 6C one.

### Correlation, re-tested under both configurations

Phase 6B's conclusion was reached with the incumbent tails, so it was entitled to
be revisited. Each arm's structure is **refitted from the PIT of the marginals it
is simulated with**: a correlation is a property of the PIT, and the PIT moves
when the tails do, so reusing the Phase 6B fit would have compared two things at
once.

All matchups (35% stacked, held-out, nominal cov80 = 0.800):

| arm | cov80 | cov90 | lineup CRPS | Brier | maxCE |
|---|---:|---:|---:|---:|---:|
| incumbent + independent | 0.8284 | 0.9229 | 10.6110 | 0.22885 | 0.0618 |
| incumbent + correlated | 0.8311 | 0.9281 | 10.6242 | 0.22941 | 0.0640 |
| candidate + independent | **0.7981** | 0.8972 | **10.5919** | **0.22878** | 0.0751 |
| candidate + correlated | 0.8051 | **0.9058** | 10.5986 | 0.22929 | 0.0566 |

**Stacked lineups only** — the population where the two samplers actually
disagree, and where the offsetting-errors story predicts something:

| arm | cov80 | cov90 | Brier | maxCE |
|---|---:|---:|---:|---:|
| incumbent + independent | 0.8215 | 0.9132 | 0.22763 | 0.0458 |
| incumbent + correlated | 0.8365 | 0.9257 | 0.22761 | 0.0531 |
| candidate + independent | 0.7833 | 0.8896 | 0.22737 | **0.0414** |
| candidate + correlated | **0.8017** | **0.9007** | **0.22733** | 0.0455 |

**The Phase 6B conclusion changes in one specific way and holds in another.**

*It changes on interval calibration.* Under the incumbent tails, correlation made
a too-wide interval wider — 0.8215 → 0.8365 — which is why it was rejected. Under
the candidate tails it moves a too-narrow interval onto nominal: **0.7833 →
0.8017 at 80% and 0.8896 → 0.9007 at 90%**, both landing within 0.002 and 0.001
of nominal. Correlation was never the wrong model for a stacked lineup; it was
being measured through marginals whose error pointed the other way and cancelled
it. That is a real finding and it belongs to this phase.

*It holds on win probability.* Brier moves from 0.22737 to 0.22733 on stacked
lineups — four in the fifth decimal place, and the sign flips between strata.
Correlation still does not help pick winners, and on the full population it now
pushes coverage slightly *past* nominal (0.7981 → 0.8051) rather than toward it.

So: **correlation should be re-evaluated for promotion after, and only after, the
tails are recalibrated, and on the strength of stacked-lineup interval
calibration rather than Brier.**

**That re-evaluation is [Phase 6D](#phase-6d--correlation-promotion-validation),
and it did not go the way this section expected.** The table above is scored at
the tuning argmin `0.5 / 2.0`; the pair that was approved is `1.0 / 2.0`, which
is half a step wider. At the approved factors the independent sampler's stacked
coverage is already 0.7951 / 0.8976 — the gap correlation was going to close is
mostly closed without it — and correlation moves both past nominal. The
prediction is left standing here rather than edited away, because the phase that
tested it is more useful read against what it was testing.

### The recommendation, and what it is not

```
LOWER_TAIL_FACTOR = 1.0     (was 1.5)     — approved, shipped
UPPER_TAIL_FACTOR = 2.0     (was 2.5)     — approved, shipped
```

**Not the tuning argmin.** The rule selected (0.5, 2.0) on the tuning seasons and
the held-out argmin was (1.0, 2.0). The recommended pair is the cell that is
inside the basin on **both** periods, and it is chosen deliberately over the
argmin: the lower factor is barely identified (the surface is nearly flat along
it, because the hard floor binds), the basin is flat to within the noise, and
picking a value in the middle of an underdetermined direction is more honest than
picking its minimum. On held-out data (1.0, 2.0) scores PIT divergence 0.0605
against 0.0705 for the tuning argmin and 0.0894 for the incumbent, and 80%
coverage 0.7976 against nominal 0.800.

What the change buys, and what it does not:

* **buys** — a lineup interval that is calibrated instead of 2 points too wide,
  a flatter team-total PIT, a lower maximum calibration error, and the
  precondition for correlation to be worth promoting;
* **does not buy** — a significantly better CRPS or Brier, a fix for the +2.3%
  expected-score gap, or a fix for the conditional error against projection size;
* **costs** — nothing measurable in CPU (below), and a small over-correction on
  high-projection and stacked lineups.

**Regression protection.** `tests/test_tail_calibration.py` asserts the shipped
constants by value. It asserted `1.5 / 2.5` while this recommendation was
pending and asserts `1.0 / 2.0` now; the assertion moved in the same commit as
the constants, which is the intended friction. The test's job is not "these
numbers are frozen" but "these numbers do not change by accident".

**What did not change.** The recalibration touches two knot *values* and no code
path. Verified directly against the panel's 38,061 distributions: every stored
percentile still reconstructs exactly, and the curve is identical to the old one
at every point between P10 and P90 (max drift 1.8e-15, one ULP). Only the q=0
and q=1 knots move — the lower one on 33,983 of 38,061 rows, the rest being
clamped by `HARD_FLOOR`, and the upper one on all of them. Projections, model
runs, stored percentiles, the API contract, provenance labelling and the
deterministic seed contract are all untouched, and the full suite passes at
967/967 with a database attached.

### Performance

Recalibration changes two knot *values* and no code path, so it cannot cost
anything, and the measurement confirms that it does not. Fourteen players, one
core, independent sampler:

| iterations | incumbent | candidate | ratio |
|---|---:|---:|---:|
| 1,000 | 14.8 ms | 14.7 ms | 0.99 |
| 10,000 (default) | 155.6 ms | 151.1 ms | 0.97 |
| 25,000 | 373.2 ms | 373.8 ms | 1.00 |
| 50,000 (max) | 754.2 ms | 760.2 ms | 1.01 |

The evaluation harness itself exploits the same structure: the factors enter only
the two outer segments of a piecewise-linear curve, so `LineupDraws` re-scores a
lineup under any configuration without re-sampling it, which is what makes a
36-cell paired sweep over 72 weeks a five-minute job. It is an optimisation of
the thing a production constant is chosen on, so it is proved equal to
`simulate()` draw-for-draw in the tests rather than trusted.

### Limitations

1. **One global pair of factors is a compromise**, and the report says where it
   fails: high-projection and stacked lineups do not want the same correction as
   low-projection and unstacked ones. A factor conditioned on projection size
   would fit better and is not proposed here, because it is a second parameter
   fitted on the same 2,876 held-out lineups.
2. **The lower factor is barely identified.** The hard floor clamps it for most
   startable players, so its surface is nearly flat and any value in 0.0–1.5 is
   defensible on this evidence.
3. **Matchups are synthesised, not historical** — inherited from Phase 6B, and
   the same caveat applies: a real league's lineups are not this draw.
4. **Half-PPR and `shrinkage_eb` only.** The residual distributions differ by
   profile, so the factors are not automatically transferable.
5. **The evaluation optimises the *sum*.** A user reading one player's P90 is
   reading a number this phase deliberately did not tune for, and the player-level
   metrics are reported as a guard rather than as an objective. They moved
   negligibly (CRPS −0.0022, knot error unchanged), so the guard held.
6. **2,876 held-out lineups is not a large sample** for a 36-cell surface. The
   basin's *location* is stable across two disjoint periods; its floor is not
   resolvable, which is exactly why a region and not an argmin is recommended.

---

## Phase 6D — correlation promotion validation

**Result: C — correlation remains promising but unproven. The independent
sampler stays the production default and the correlated one stays behind
`correlation_mode: game_environment`.**

Phase 6C's four-way comparison predicted that correlation would become worth
promoting once the tails were recalibrated: on stacked lineups it moved 80%
coverage from 0.783 onto 0.802 where under the old tails it had pushed 0.822 up
to 0.837. That prediction was made against the tuning argmin `0.5 / 2.0`. The
pair that was actually approved is `1.0 / 2.0`, which is wider — and at `1.0 /
2.0` the independent simulator is **already at nominal on stacked lineups**, so
the error correlation was expected to correct is largely gone before correlation
is applied.

Everything below is reproducible with `python scripts/phase6d_correlation.py`,
which writes `artifacts/phase6d_report.txt`.

### What was compared

`1.0 / 2.0 + independent` against `1.0 / 2.0 + correlated`, and nothing else.
The superseded tail factors do not appear: they cannot ship, and re-scoring them
would spend the sample on a configuration no decision depends on.

36 held-out weeks (2024–2025), 40 synthesised matchups per week, 2,000 draws per
lineup. Both arms see identical lineups, identical realised outcomes and
identical per-matchup seeds, so every difference is the sampler. The pairing is
asserted rather than assumed — the harness refuses to report a standard error if
the two arms scored different numbers of lineups.

The structure is **re-fitted, not reused**. A correlation is a property of the
PIT and the PIT moved when the tails did, so each held-out week's structure is
estimated from the recalibrated marginals on weeks strictly before it. All 36
held-out weeks have a prior-fitted structure. The loadings barely moved:

| position | game | team | own | shared variance |
|---|---|---|---|---|
| QB | 0.385 | 0.923 | 0.001 | 1.000 |
| WR | 0.168 | 0.157 | 0.973 | 0.053 |
| TE | 0.144 | 0.157 | 0.977 | 0.045 |
| RB | 0.031 | 0.040 | 0.999 | 0.003 |

### All held-out matchups

2,878 lineups, 1,439 matchups. Read coverage as **distance from nominal**, not
as raw movement.

| metric | independent | correlated | delta | paired t |
|---|---:|---:|---:|---:|
| **80% interval coverage** (0.800) | **0.7943** | 0.8065 | +0.0122 | +4.83 |
| **90% interval coverage** (0.900) | 0.8919 | **0.8961** | +0.0042 | +2.27 |
| **lineup CRPS** | 10.9306 | **10.9264** | −0.0041 | −0.53 |
| **differential CRPS** | 15.2663 | **15.2506** | −0.0157 | −1.06 |
| **lineup PIT divergence** | **0.0314** | 0.0354 | +0.0040 | — |
| **max calibration error** | 0.0517 | **0.0481** | −0.0036 | — |
| Brier | 0.23337 | **0.23297** | −0.00040 | −1.00 |
| log loss | 0.65870 | **0.65797** | −0.00074 | — |
| ECE | 0.0306 | **0.0299** | −0.0008 | — |
| mean 80% width | 49.16 | 49.93 | +0.77 | +25.40 |
| differential 80% coverage (0.800) | 0.8131 | 0.8075 | −0.0056 | −1.63 |
| win probs outside [0.05, 0.95] | 0.0% | 0.0% | — | — |
| expected score − projection sum | +1.130 | +1.121 | −0.009 | — |

80% coverage is 0.0057 from nominal independent and 0.0065 correlated — a tie,
if anything favouring independence. 90% coverage is 0.0081 from nominal
independent and 0.0039 correlated — correlated, and significantly. The two
primary coverage metrics disagree.

**No proper score moves significantly.** Lineup CRPS, differential CRPS and
Brier all favour correlation, at |t| of 0.53, 1.06 and 1.00. That is the whole
accuracy case, and it is indistinguishable from zero three times over.

The team-total PIT is flat in both arms — the widest bin is 0.1056 against a
nominal 0.100 independent, 0.1067 correlated — which is the recalibration's
doing, not correlation's.

### By population

The structure predicts three different things, so they are reported separately.
A same-team pair gets `alpha·alpha + beta·beta`, an opposing pair gets
`alpha·alpha` alone, and two players in different games get exactly zero. Every
lineup is classified by **what it holds**, read off the drawn rows — not by what
the generator was asked to build, because a week whose slate has no eligible
pair yields an ordinary lineup under a flag that says otherwise.

#### Same-team stacks — the population the promotion case rested on

Every lineup a QB stack; 2,880 lineups, 1,440 matchups.

| metric | independent | correlated | delta | paired t |
|---|---:|---:|---:|---:|
| 80% coverage (0.800) | **0.7951** | 0.8118 | +0.0167 | +5.85 |
| 90% coverage (0.900) | **0.8976** | 0.9090 | +0.0115 | +4.94 |
| lineup CRPS | 10.9366 | **10.9334** | −0.0032 | −0.40 |
| differential CRPS | **15.4180** | 15.4232 | +0.0052 | +0.35 |
| lineup PIT divergence | **0.0257** | 0.0347 | +0.0090 | — |
| max calibration error | 0.0873 | **0.0846** | −0.0026 | — |
| Brier | **0.22286** | 0.22303 | +0.00017 | +0.46 |
| mean 80% width | 49.21 | 50.89 | +1.68 | +60.58 |

**This is the finding that decides the phase.** Under the recalibrated
marginals the independent sampler's stacked-lineup coverage is 0.7951 and
0.8976 — within half a point of nominal at both thresholds. Correlation moves
both *past* nominal, to 0.8118 and 0.9090, and takes PIT divergence from 0.0257
to 0.0347. Distance from nominal roughly doubles at 80% and quadruples at 90%.

That is Phase 6B's failure mode with the sign flipped. There, correlation made
an already-too-wide interval wider. Here it makes a correctly-sized interval too
wide. In both cases the mechanism is the same: this structure only ever *adds*
variance, and it is being asked to fix an error that is no longer present.

Phase 6C was not wrong — at `0.5 / 2.0` the independent stacked coverage really
was 0.7833 and correlation really did move it onto 0.8017. The approved pair is
half a step wider, and it closed the same gap without a second model.

#### Opposing-player combinations

QB against a WR, TE or RB on the other sideline of his own game; 2,880 lineups.

| metric | independent | correlated | delta | paired t |
|---|---:|---:|---:|---:|
| 80% coverage (0.800) | 0.7906 | **0.7969** | +0.0062 | +2.85 |
| 90% coverage (0.900) | 0.8938 | **0.8955** | +0.0017 | +0.87 |
| lineup CRPS | **10.9612** | 10.9697 | +0.0084 | +1.15 |
| differential CRPS | **15.3961** | 15.4061 | +0.0100 | +0.71 |
| lineup PIT divergence | 0.0486 | **0.0437** | −0.0049 | — |
| max calibration error | 0.0262 | **0.0190** | −0.0073 | — |
| Brier | **0.22833** | 0.22902 | +0.00069 | +1.83 |
| ECE | 0.0134 | **0.0080** | −0.0054 | — |

**This is the one population where correlation still has a case, and it is
mixed.** Every calibration metric improves — coverage at both thresholds, PIT
divergence, ECE, maximum calibration error. Every proper score gets slightly
worse, and Brier does so at t = +1.83, the largest single movement against the
candidate anywhere in the report.

Broken down by pair, at the lineup level: QB–WR 0.7632 → 0.7939, QB–TE 0.7978 →
0.8090, QB–RB 0.7703 → 0.7838. All three move toward nominal, and only QB–TE
crosses it.

#### Quarterback duels — the cross-lineup channel

The two lineups' quarterbacks facing each other; 2,810 lineups, 1,405 matchups.
This is the dependence that moves the *margin* rather than either side's own
interval, and it is the case a pairwise start/sit call never has to think about.

| metric | independent | correlated | delta | paired t |
|---|---:|---:|---:|---:|
| 80% coverage (0.800) | 0.8096 | 0.8103 | +0.0007 | +0.26 |
| 90% coverage (0.900) | 0.9068 | 0.9085 | +0.0018 | +0.78 |
| differential CRPS | **14.3539** | 14.3602 | +0.0063 | +0.44 |
| differential 80% coverage | 0.8313 | 0.8327 | +0.0014 | +0.63 |
| max calibration error | **0.0400** | 0.0481 | +0.0081 | — |
| Brier | **0.22842** | 0.22861 | +0.00019 | +0.49 |

Nothing here is distinguishable from zero. The channel correlation was expected
to own outright — two managers watching one afternoon — produces no measurable
difference in the margin distribution or the win probability.

#### Unrelated lineups — the control

No two players in a lineup share a game; 448 lineups, 224 matchups. Under this
structure their correlation is **exactly zero**, so the two arms must agree, and
they do:

| metric | independent | correlated | delta | paired t |
|---|---:|---:|---:|---:|
| 80% coverage | 0.7969 | 0.7991 | +0.0022 | +0.38 |
| 90% coverage | 0.9174 | 0.9174 | 0.0000 | +0.00 |
| lineup CRPS | 10.5152 | 10.5004 | −0.0148 | −0.81 |
| PIT centrality | — | — | −0.00005 | −0.07 |
| mean 80% width | 49.16 | 49.20 | +0.05 | +0.75 |

Every paired difference is inside noise, and the 80% width moves by 0.05 points
against +0.77 on the full population. **This is what makes the rest of the
report readable**: the harness produces a null where a null is predicted, so the
nulls elsewhere are the model's and not the instrument's.

#### Projection size

| stratum | n | independent cov80 | correlated cov80 |
|---|---:|---:|---:|
| projection < 66 | 561 | **0.8111** | 0.8307 |
| projection 66–79 | 1,762 | 0.7872 | **0.8008** |
| projection > 79 | 555 | **0.8000** | **0.8000** |

Correlation helps the middle band, overshoots the low band, and does nothing at
the top. The conditional error against projection size that Phase 6C reported is
still there and correlation does not address it.

### Marginal preservation

The safety property: a correlation model may change the joint distribution and
may not touch a marginal, or it has silently become a second unvalidated
projection model.

Measured on 12 held-out matchups drawn to be maximally stacked *and* maximally
opposing — 168 players, 20,000 draws each — comparing every player's own
simulated P10/P25/P50/P75/P90 and mean. The comparison is reported against a
**Monte Carlo control**: the same independent sampler run twice at different
seeds. Without the control there is no way to say whether a 0.5-point difference
is a violation or the price of estimating a percentile from a finite sample.

| comparison | max knot drift | as share of P10–P90 width | mean knot drift | max mean drift |
|---|---:|---:|---:|---:|
| correlated vs independent | 0.545 pts | 3.29% | 0.086 | 0.239 |
| **independent vs itself (control)** | **0.541 pts** | **2.95%** | **0.120** | **0.187** |

The correlated-versus-independent figure is indistinguishable from what the
*same* sampler costs at a different seed, and its mean drift is actually lower.
The marginal is preserved. This is a check on the implementation rather than on
the theory — `Phi(z)` for a standard normal `z` is exactly uniform, so the
property holds by construction — and `tests/test_correlation_marginals.py`
pins it at roughly double the fitted loadings.

### Team-level expected score

A correlation model may move a total's spread and must not move its centre.

| population | independent | correlated | delta |
|---|---:|---:|---:|
| all lineups | +1.1305 | +1.1210 | −0.0095 |
| same-team stacks | +1.1646 | +1.1481 | −0.0165 |
| opposing pairs | +1.1313 | +1.1420 | +0.0108 |
| quarterback duels | +1.1376 | +1.1485 | +0.0109 |
| unstacked | +1.1368 | +1.1808 | +0.0439 |

Every delta is under 0.05 points on a ~73-point total — under 0.06% — and the
sign is not consistent, which is what sampling noise looks like. Correlation
does not move the centre.

The gap itself is `+1.130` points (**+1.56%**) independent and `+1.121`
(**+1.55%**) correlated, against a projection sum of 72.49. It is not being
closed; see [the open foundation question](#the-open-foundation-question).

### Performance

Fourteen players, one core, CPython 3.10:

| iterations | independent | correlated | ratio |
|---|---:|---:|---:|
| 1,000 | 15.4 ms | 32.6 ms | 2.12× |
| 10,000 (default) | 148.3 ms | 348.7 ms | 2.35× |
| 25,000 | 395.8 ms | 821.5 ms | 2.08× |
| 50,000 (max) | 742.7 ms | 1,629.8 ms | 2.19× |

End to end through the ASGI app against Postgres, 10,000 iterations:

| mode | latency |
|---|---:|
| `independent` | 180.3 ms |
| `game_environment` | 326.8 ms |

Correlation costs a flat ~2.2× of CPU and ~1.8× of end-to-end latency. Both stay
inside a synchronous request budget, so **performance is not the reason for the
verdict** — it is priced in as a cost that a real improvement would have been
worth paying and an unproven one is not.

### The decision

**C — correlation remains promising but unproven. It stays experimental.**

The acceptance rule was that the correlated model must demonstrate incremental
improvement over `1.0 / 2.0 + independent` on held-out data. It does not:

1. **No proper score improves significantly, anywhere.** Lineup CRPS,
   differential CRPS and Brier are the three metrics that would settle this, and
   across every population reported their |t| never exceeds 1.83 — and the 1.83
   is *against* the candidate. The sign flips between populations: CRPS favours
   correlation overall and on stacks, and favours independence on opposing pairs
   and duels.
2. **On the population the case rested on, it now makes calibration worse.**
   Stacked-lineup coverage was the promotion argument. The recalibrated
   independent sampler already lands at 0.7951 / 0.8976; correlation pushes both
   past nominal and takes PIT divergence from 0.0257 to 0.0347. Whatever else is
   true, the specific claim Phase 6C put forward has been tested and did not
   hold at the factors that shipped.
3. **The one population it helps, it helps ambiguously.** Opposing pairs improve
   on every calibration metric and get slightly worse on every proper score.
   That is a real signal and it is not a promotion case.
4. **The cross-lineup channel produces nothing measurable at all.**

And it is not a *rejection*, which is why this is C rather than B:

* the structure is empirically real — QB to own pass-catcher is +0.22 to +0.26
  and stable across seven seasons measured separately;
* it creates **no unacceptable regressions**. The unrelated-lineup control is
  clean at every metric, marginals are preserved to within Monte Carlo noise,
  the team total's centre does not move, no win probability lands outside
  [0.05, 0.95] in either arm, and 90% coverage and maximum calibration error
  genuinely improve on the full population;
* the cost is bounded and known.

**What would change the verdict.** Not a re-run — the sample is the same 2,876
held-out lineups Phase 6C already used, and running it again buys nothing. The
things that would:

* a structure with **tail dependence** (a t-copula), since the Gaussian copula's
  missing top corner is exactly the case a QB stack is bought for, and the
  metrics that would move are the ones that are currently flat;
* **loadings conditioned on projection size**, since the measured QB–WR effect
  nearly doubles between a 6-point and a 12-point projection and one loading per
  position understates a real starter's lineup;
* **real roster history**, so the stacked share reflects what managers actually
  build rather than a 35% over-sample;
* an error that correlation is uniquely placed to fix, which the tail
  recalibration removed.

### Limitations

1. **The evaluated marginals are now well calibrated, which shrinks the room a
   correlation model has to improve anything.** That is a real result and also a
   caveat: this comparison is less able to detect a small improvement than the
   Phase 6B one was, because the baseline it is measured against is better.
2. **Matchups are synthesised, not historical** — inherited from Phase 6B. There
   is no roster history, so the stacked, opposing and duelling populations are
   constructed rather than observed, and a real league's lineups are not this
   draw.
3. **Half-PPR and `shrinkage_eb` only.** Only that profile has a fitted
   structure, and the endpoint refuses the others rather than substituting.
4. **The Gaussian copula still has no tail dependence, and negative correlations
   still cannot be represented.** Both unchanged from Phase 6B, both small, both
   erring toward over-correlation.
5. **The tail factors were calibrated on five-percentile rows.** A stored
   three-point summary (P10/P50/P90) extends its tails from much wider segments,
   so the same constants produce a materially wider curve there. Nothing in
   either phase measured that case.
6. **K and DST are still absent**, so the RB-versus-opposing-defence
   relationship in the brief remains unmeasurable.

### API behaviour

Unchanged, and already explicit — no work was needed here and none was done.

```json
"simulation": {
  "provenance": "derived",
  "sampling_method": "inverse_transform_from_stored_percentiles",
  "correlation_mode": "game_environment",
  "correlation_model_version": "1.0.0"
}
```

Verified live against the running app:

| request | `correlation_mode` | `correlation_model_version` | `player_independence` |
|---|---|---|---|
| `"independent"` | `independent` | `null` | `true` |
| `"game_environment"` | `game_environment` | `"1.0.0"` | `false` |
| field omitted | `independent` | `null` | `true` |
| `"bogus"` | **422**, not a fallback | — | — |

Both fields are read from the **sampler that ran**, not echoed from the request,
so a response cannot describe a correlated simulation that was not one. There is
no silent switching: the default is `independent`, an unknown mode is a 422, and
a profile with no fitted structure is a 422. Correlation output remains
`derived`, like every other simulated number.

---

## The open foundation question

**Do `expected_points` and the five stored percentiles imply the same
probability distribution?**

They do not, quite. A lineup's simulated mean sits **+1.56%** above the sum of
its players' stored calibrated means (+1.13 points on a 72.5-point lineup), and
the same gap is visible one level down: a player's reconstructed curve has a
mean a couple of percent above the `expected_points` the calibration measured.

Three things are known about it, and all three say it does not belong to the
simulation engine:

* **It is not a tail-factor artifact.** Phase 6C measured it across 36 tail
  configurations. Recalibration moved it from +2.32% to +2.20% at the tuning
  argmin, and Phase 6D measures +1.56% at the shipped factors — smaller, but
  present, and no cell of the grid that is defensible on calibration grounds
  removes it.
* **It is not a sampler artifact.** Phase 6D's two arms report +1.130 and +1.121;
  correlation does not touch it.
* **Forcing it to zero would cost calibration.** The grid cells whose drift is
  near zero (upper ≈ 1.5) have PIT divergence 0.075–0.093 and 80% coverage
  0.77–0.79, against 0.0314 and 0.7943 at the shipped configuration.

**It is deliberately not being fixed.** `expected_score == projection_sum` is a
cosmetic identity, and a right-skewed distribution is *supposed* to put its mean
above the sum of its medians — weekly fantasy scoring has a hard floor near zero
and a genuinely long ceiling. Altering the distribution to make the two agree
would trade a real, measured calibration property for a number that looks tidier
in a response body.

What the question actually is: a piecewise-linear interpolation through
P10…P90 places mass differently than whatever distribution the residual
calibration measured its mean from, and the two were never required to agree.
Settling it means going back to Layer 3b and asking what distribution
`expected_points` is the mean *of* — which is a question about the frozen
foundation, not about the engine that reads it. Both numbers are reported side
by side in every response so a caller can see the gap rather than discover it.

---

## What is deliberately not built

None of the brief's future tables exist: `fantasy_rosters`, `roster_players`,
`matchup_simulations`, `simulation_results`.

**Authentication precedes persisted rosters.** Three of those four need a
`user_id`, and `dependencies.current_principal` still returns an anonymous
principal. Creating a `user_id` column with nothing behind it produces a foreign
key to a table that does not exist and a permission model that is a comment.

A stateless engine taking two lineup payloads needs none of them, which is why
it is the version built first.

**Persistence, when it arrives, should store the request and the aggregates.**
Storing 10,000 iterations per simulation is a write path measured in millions of
rows per week for numbers that are computable at simulation time — and the
result is reproducible from `(request, run, seed)` anyway. Per-iteration rows
should wait for a product question that needs them.

The response cache does not apply: `POST` never reaches it, a simulation's
inputs are two whole lineups so the hit rate would be near zero, and the run is
cheap and deterministic — recomputing is the right answer.

---

## Future improvements

Roughly in the order they buy the most honesty per unit of work:

1. ~~Apply the recalibrated tail factors.~~ **Done** — `1.0 / 2.0` shipped, see
   [Phase 6C](#phase-6c--lineup-level-tail-calibration).
2. ~~Correlated player outcomes — re-test for promotion once (1) lands.~~
   **Done, and the answer was no** — see
   [Phase 6D](#phase-6d--correlation-promotion-validation). What is left of the
   idea is narrower and better specified than "try correlation": a **t-copula**,
   so the structure has tail dependence in the corner a QB stack is actually
   bought for, and **loadings conditioned on projection size**, since the
   measured effect nearly doubles between a 6-point and a 12-point projection.
   Neither is identifiable from the panel as it stands, so both are gated on
   more data rather than on more modelling.
3. **Whether `expected_points` and the stored percentiles imply the same
   distribution.** The remaining known gap in the foundation, isolated by two
   phases and belonging to neither. See
   [the open foundation question](#the-open-foundation-question).
4. **K and DST models.** Closes the coverage gap. Both need their own component
   vocabulary and a discrete outcome model — residual quantiles fitted on
   continuous production do not transfer to distance-bucketed field goals or to
   scoring dominated by rare, high-value events.
5. **Injury-aware distributions.** A fitted availability model, so an Out
   designation changes the distribution rather than a caveat.
6. **Game-level simulation.** Simulate the game, derive the players. Subsumes
   what is left of (2) and much of (4), and is the largest change here.
7. **Persistent simulations, user rosters, authentication, history.** Product
   surface rather than statistics, and gated on auth as above.
8. **Configurable lineup formats over the wire.** `LineupFormat` already exists
   as a service-level parameter; superflex is a data change plus a request
   field.

---

## Verifying it

```bash
pytest tests/test_services_lineup.py -q          # slots, formats, validation
pytest tests/test_services_simulation.py -q      # the Monte Carlo, no database
pytest tests/test_simulation_performance.py -q   # the latency bound
pytest tests/test_services_rosters.py -q         # gaps, correlation, the curve bridge
pytest tests/test_services_distributions.py -q   # the curve itself
pytest tests/test_api_simulations.py -q          # live HTTP, needs DATABASE_URL
```

Phase 6B:

```bash
pytest tests/test_correlation_marginals.py -q    # correlation cannot move a marginal
pytest tests/test_correlation_stress.py -q       # stacks, opponents, degenerate cases
pytest tests/test_correlation_estimate.py -q     # PIT, parameter recovery, leakage
pytest tests/test_simulation_performance.py -q   # both samplers, and the 2x ratio

python scripts/phase6b_backtest.py               # the whole evidence base, ~15 min
```

The script needs `DATABASE_URL` (or the default local warehouse) only for the
first run; it caches the panel in `artifacts/` and reuses it. Every number in
[Phase 6B](#phase-6b--correlated-simulation-the-measured-answer) comes out of
`artifacts/phase6b_report.txt`.

Phase 6C:

```bash
pytest tests/test_tail_calibration.py -q         # the factors as a parameter,
                                                 # and the harness's equality
                                                 # with the production sampler
python scripts/phase6c_tails.py                  # the whole evidence base, ~20 min
```

Reuses the same cached panel. Every number in
[Phase 6C](#phase-6c--lineup-level-tail-calibration) comes out of
`artifacts/phase6c_report.txt`. `--skip-correlation` drops the four-way
comparison, which is most of the runtime.

Phase 6D:

```bash
pytest tests/test_correlation_promotion.py -q   # the classifier, the filters,
                                                # the marginal control, and the
                                                # frozen 6B/6C draw stream
python scripts/phase6d_correlation.py           # the whole evidence base, ~12 min
```

Also reuses the cached panel. Every number in
[Phase 6D](#phase-6d--correlation-promotion-validation) comes out of
`artifacts/phase6d_report.txt`. `--skip-http` drops the end-to-end latency
measurement, which is the only step needing a seeded warehouse.

**The earlier reports stay reproducible.** Phase 6D added two parameters to the
matchup generator (`opponent_share`, `duel_share`) and both are short-circuited
before they touch its random stream, so a Phase 6B or 6C call draws the exact
sequence of lineups it always did — verified as an identical digest over all
1,440 held-out matchups, and pinned in
`tests/test_correlation_promotion.py::TestTheOlderPhasesStillDrawWhatTheyDrew`.
`artifacts/phase6b_report.txt` and `artifacts/phase6c_report.txt` are kept as
the baseline the tail change and the correlation decision are argued against;
neither has been rewritten to make the current configuration look like the
incumbent it never was.

---

## Example

```http
POST /api/v1/simulations
```

```json
{
  "season": 2025,
  "week": 10,
  "scoring_profile": "ppr",
  "simulation_count": 10000,
  "seed": 42,
  "team_a": [
    {"player_id": "00-0001001", "slot": "QB"},
    {"player_id": "00-0001002", "slot": "RB"},
    {"player_id": "00-0001003", "slot": "RB"},
    {"player_id": "00-0001004", "slot": "WR"},
    {"player_id": "00-0001005", "slot": "WR"},
    {"player_id": "00-0001006", "slot": "TE"},
    {"player_id": "00-0001007", "slot": "FLEX"}
  ],
  "team_b": [
    {"player_id": "00-0002001", "slot": "QB"},
    {"player_id": "00-0002002", "slot": "RB"},
    {"player_id": "00-0002003", "slot": "RB"},
    {"player_id": "00-0002004", "slot": "WR"},
    {"player_id": "00-0002005", "slot": "WR"},
    {"player_id": "00-0002006", "slot": "TE"},
    {"player_id": "00-0002007", "slot": "FLEX"}
  ]
}
```

```json
{
  "data": {
    "season": 2025,
    "week": 10,
    "scoring_profile": "ppr",
    "simulation": {
      "provenance": "derived",
      "iterations": 10000,
      "seed": 42,
      "sampling_method": "inverse_transform_from_stored_percentiles",
      "lineup_format": "standard_skill",
      "model": {
        "run_id": 1,
        "model_name": "shrinkage_eb",
        "model_version": "1.0.0",
        "algorithm": "baseline",
        "feature_schema_version": 1,
        "published_at": "2026-08-08T19:00:56.155188Z",
        "code_sha": null
      }
    },
    "team_a": {
      "provenance": "derived",
      "expected_score": 118.40417384669382,
      "median_score": 116.27470777927458,
      "p10": 84.2404613349928,
      "p25": 98.84773776867374,
      "p75": 136.4544207239769,
      "p90": 155.0433401050202,
      "win_probability": 0.973,
      "loss_probability": 0.027,
      "tie_probability": 0.0,
      "projection_sum": 114.0,
      "players": [
        {
          "provenance": "model",
          "player_id": "00-0001001",
          "name": "Alpha QB",
          "slot": "QB",
          "position": "QB",
          "team": "KC",
          "game_id": "2025_10_KC_OPP",
          "expected_points": 22.0,
          "floor": 7.7,
          "ceiling": 39.6,
          "simulated_mean": 22.830353009238372
        }
      ]
    },
    "team_b": { "...": "same shape; projection_sum 59.0, win_probability 0.027" },
    "score_differential": 56.814388742673394,
    "median_differential": 55.919313140904734,
    "assumptions": {
      "provenance": "derived",
      "player_independence": true,
      "kicker_projection_available": false,
      "defense_projection_available": false,
      "injury_adjustment_applied": false,
      "matchup_adjustment_applied": false,
      "weather_adjustment_applied": false,
      "notes": ["..."]
    }
  },
  "meta": {
    "window": {"season": 2025, "week": 10, "resolution": "explicit", "is_upcoming": true},
    "scoring_profile": "ppr",
    "model": {"run_id": 1, "model_name": "shrinkage_eb"},
    "notices": [
      "Player outcomes were drawn independently. ...",
      "No projections exist for kickers or team defences, ...",
      "team_a: Alpha RB1, Alpha QB share an offence (KC). ..."
    ]
  }
}
```

A refusal uses the same error shape as every other endpoint:

```json
{
  "code": "invalid_request",
  "message": "team_a names the Kicker (K) slot, which this engine cannot simulate. Kicker (K) is recognised but not projected. Kicker scoring is distance-bucketed field goals and extra points. ... Blocked on: a kicking component vocabulary (attempts and makes by distance band); ... Simulate the projectable slots (QB, RB, WR, TE, FLEX) and add the missing positions by hand, or drop them from both lineups so the comparison stays symmetric.",
  "field": "team_a.slot",
  "remedy": null
}
```
