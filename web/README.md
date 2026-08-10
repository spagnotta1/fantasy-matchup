# web — the nflfp frontend

A React client for the projections API. It presents what the backend computes
and computes nothing itself: no projection, probability, matchup grade or
ranking is derived in browser code.

## Running it

The frontend needs the API. Start it first, from the repository root:

```powershell
$env:DATABASE_URL = "postgresql://nflfp:nflfp@localhost:55432/nflfp"
.\.venv\Scripts\python.exe -m nflfp.api --port 8010
```

Then:

```powershell
cd web
npm install
npm run dev          # http://localhost:5173
```

`npm run dev` proxies `/api` to `http://127.0.0.1:8010`. Point it elsewhere with
`VITE_DEV_API_PROXY` in a `.env.local`; see `.env.example`.

| command | what it does |
|---|---|
| `npm run dev` | dev server with HMR and the API proxy |
| `npm run build` | typecheck (`tsc -b`) then production build |
| `npm run preview` | serve the built output |
| `npm run lint` | oxlint |
| `npm run contract-check` | drive every endpoint against a running API |

## How this is served in production

There is no second origin. The API serves the built frontend itself, so the
client calls a relative `/api/v1`: no CORS exchange, no absolute base URL
compiled into the bundle, and no chance of a deploy where the page loads and
every request in it fails against a stale hostname.

The `Dockerfile` builds `web/` in a Node stage and copies only the output into
the Python image, which sets `WEB_DIST_DIR=/app/web/dist`. `nflfp.api.spa`
mounts the app when that variable points at a real build and does nothing when
it does not — which is what the ETL, projection and warmer containers want,
since they run the same image and have no business serving a frontend.

Nothing is discovered implicitly. There is deliberately no "look for `web/dist`
beside the source" fallback: it would make what the API serves depend on whether
a build artefact happened to be lying in the working tree, and a month-old
`dist` sitting next to a running dev server would be served at `/` in preference
to nothing at all. To exercise the deployed shape locally, ask for it:

```powershell
npm --prefix web run build
$env:WEB_DIST_DIR = "web/dist"
.\.venv\Scripts\python.exe -m nflfp.api --port 8010    # whole product on one port
```

## Checking the two halves still agree

`npm run contract-check` loads the real `src/api/*` modules — the same Zod
schemas and envelope validation the browser runs — and calls every endpoint the
product uses against a live API:

```powershell
npm run contract-check                        # defaults to http://127.0.0.1:8010
$env:API_BASE = "http://127.0.0.1:8011"; npm run contract-check
```

It is not a substitute for the backend's own tests. It catches the one class of
failure neither side's suite can see: the frontend compiling against a response
shape the backend does not produce. Two checks in it are worth knowing about —
it asserts `/rankings/K` and `/rankings/DST` are *refused*, because those
refusals are a documented part of the contract and a silent success would be the
real regression; and it builds its lineups with the application's own
`parseLineupFormats`, so the prose-parsing described below is exercised against
the live notice rather than a fixture.

It also runs the simulation workflow's own logic against the live API: that the
engine refuses a starter with no published projection, and that the builder's
pre-flight check reaches the same verdict from the board. Those two must agree —
if the API ever stopped refusing, blocking the run in the UI would become a bug
rather than a courtesy.

## Layout

```
src/
  api/          typed client, Zod contracts, one module per API resource
  app/          router, query client, the global season/week/scoring selection
  components/
    ui/         design-system primitives (Button, Card, Select, Skeleton, …)
    domain/     football-specific display (provenance, grades, ranges)
    feedback/   loading, error, empty and notice states
  hooks/        TanStack Query hooks over the api layer
  layouts/      the application shell — sidebar, header, mobile bar
  pages/        one file per route, lazily loaded
  styles/       design tokens and base styles
  utils/        formatting and class merging
```

Components never call `fetch`. They call a hook, which calls a typed function in
`src/api`, which is the only place that knows a URL exists.

## Three rules this codebase holds to

**Provenance is not decoration.** Every block of numbers the API returns is
labelled `model`, `derived`, `context` or `actual`, and those are not
interchangeable. A matchup grade is real analysis the model never saw; weather
is observed and not an input at all. The UI keeps them visibly apart, and
`applied_to_projection` is checked before anything implies a projection accounts
for the wind. See `components/domain/ProvenanceBadge.tsx`.

**Uncertainty is stated, not smoothed.** "Projected: 25.4", never "will score
25.4". A toss-up is rendered as a toss-up because the API declines to name a
starter below 58%. An ungraded matchup says "not graded", never a neutral C.

**Nulls are states, not errors.** An empty board with `meta.model === null`
means no run is published for that week — a Tuesday, not an outage. Every view
distinguishes it from a genuine failure.

## Two things worth knowing before reading the code

**The headline points number.** The API documents
`prediction.points.expected` as the number to display and `predicted` as
lineage only. On runs written before the distribution layer existed, `expected`
is null — including the run currently published. The backend already resolves
this (`PointDistribution.headline` is `expected ?? predicted`, and boards are
ordered by the same `COALESCE`), so `utils/format.ts#headlinePoints` mirrors that
rule rather than inventing one, and flags when the fallback was taken so the UI
can mark the number as uncalibrated.

**The stored ranges are bucketed.** Under the currently published run the
floor-to-ceiling width is not per-player: the 92 running backs fall into roughly
fifteen buckets, and the widest holds eight players with an identical 12.74
spread. So `ceiling - projection` is not an ordering — its top is an eight-way
tie broken by array order — and the product ships no "biggest upside" ranking
because of it. `hasBandedIntervals` in `utils/board.ts` detects the condition and
`CalibrationNotice` states it; both go quiet on a run with genuinely per-player
intervals. Same root cause as the missing `expected` above.

**The default week.** The API's own default is "the upcoming week", which is
correct during a season and unhelpful in August: it resolves to a week with
nothing published, and the whole product opens empty. `SlateProvider` instead
opens on the newest week that actually has a published board, which it reads
from `GET /seasons` — that endpoint returns the seasons a run has been published
for, each with its published weeks, so both selectors and the opening slate come
out of one response and the frontend infers nothing. A remembered season that is
no longer published is dropped rather than restored. An explicit `?season=&week=`
always wins, including for a season with no board; the week control explains
what is missing rather than the selection being overridden.

## Three decisions in the Phase 3 views

**Tier bands are drawn only where a tier means something.** `/rankings/{position}`
re-ranks and re-tiers inside one position, so a tier there says "these players
are interchangeable at this roster spot" and the rows are grouped by it. The
All tab reads `/projections`, whose tiers span positions and would group a
quarterback with a wide receiver — there the tier is a column, not a heading.
Grouping also disappears the moment the board is sorted by anything but rank,
because a tier is a statement about *adjacent* rows.

**A position the API does not project is not an error.** `/rankings/K` returns
422 with an explanation, and rendering that as a failed request would read as an
outage. `/meta/positions` already carries the same reason, so the tab is
disabled and the page shows what the model is blocked on. No request is made.

**The matchup grid is labelled by the defence, not the offence.** The API keys
`defense` by the *defending* team; the screen names each section for the defence
being attacked. Putting "DAL offence" over grades computed from what the New
York defence allows is the kind of quiet mislabel that inverts the conclusion.

## Three decisions in the Phase 4 simulation

**The two totals do not reconcile, and the screen says so.** The API keeps
`projection_sum` beside `expected_score` and documents the two agreeing as the
check that the sampler drew from the stored distributions. Under the current run
they differ by roughly 18% — same root cause as the missing `expected` above,
since `projection_sum` adds raw model output while the sampler draws from the
stored quantile curve, whose mean is higher. Showing both without explaining the
gap would be worse than showing either alone, so `SimulationResults` renders a
reconciliation notice and it disappears on a calibrated run.

**"Swing" is a published range, not a ±.** The spec shape for this panel is
`±9.2`. A symmetric tolerance is a statistic this API never published: the stored
distributions are asymmetric, so one number would misdescribe both ends. The
panel shows P10, P90 and the distance between them, and nothing re-runs the
simulation with a player removed — the ordering is by range width, which is the
honest reading of "who could swing this".

**History is local because the endpoint is stateless.** `POST /simulations`
stores nothing by design. What makes a local list worth keeping is that a run is
reproducible from its lineups, its seed and the model run it was made against,
so an entry stores the whole request and "Load" is a real re-run. Entries taken
against a superseded model run are marked.

## Four decisions in the Phase 7A simulation workflow

Phase 7A made the simulation the product's flagship workflow rather than one of
its screens. Nothing about the engine changed; what changed is everything around
the moment of running it.

**A refusal is pre-empted, not just reported.** The engine refuses the whole
matchup if any one starter has no published projection — correctly, since a team
total is a sum and a missing starter removes their whole contribution. That
refusal used to arrive as a paragraph after fourteen slots had been filled.
`features/simulations/availability.ts` reaches the same verdict from the board
the builder already holds, so the row says so where the points would be and the
run is blocked with the slot named. Two guard rails matter here: the API remains
the authority (a lineup that passes this is still submitted and can still be
refused), and the check reports `unknown` and blocks nothing when the board is
truncated, because a false "no projection" on a projected player is worse than
the 422 it avoids. `contract-check` asserts the two verdicts agree.

**Search marks what it cannot simulate.** `/players/search` searches the player
*dimension*, which holds everyone who ever played, so "smith" offers receivers
who retired in the nineties beside this week's starters. Hiding them would
misrepresent the endpoint; the results are marked instead, before the click.

**The matchup lives in the URL.** Fourteen searches is too much work to lose to
a refresh, and a matchup is the most sendable thing in the product. Both lineups
are mirrored into the query string as they are built (`?a=QB:00-…,RB:…&b=…`) and
a link rebuilds them by resolving the ids against the current dimension. The URL
is read once, at mount — after that the page owns the state — which is what stops
an edit and a hydration from overwriting each other. Copying is copying the
address bar, so the shareable thing and the thing on screen cannot drift.

**Caveats are sorted into the lineup they are about.** A real matchup returns a
dozen notices, and the engine already labels the ones belonging to a side
(`team_a: Kyle Pitts is listed Questionable.`). Flat, the two that name your own
starters are indistinguishable from the boilerplate, so `notices.ts` reads that
prefix — and only that prefix — and anything unlabelled stays with the run.

The one place this client parses prose is `features/simulations/lineupFormat.ts`.
`/meta/lineup-slots` serves the slot vocabulary structurally but the *composition*
(`1xQB, 2xRB, …`) only as a `meta.notices` string. The parser falls back to one
row per simulable slot if that shape ever changes, and the API's own validation
is the authority either way — but a structured `lineup_formats` block is the one
API gap worth closing for this view.

## Configuration

Everything a `VITE_`-prefixed variable holds ends up in the client bundle. There
are no secrets here and there must never be: the API is anonymous, requires no
credentials, and nothing in this directory should ever hold one.

## Browser QA

`tests/e2e` is a Playwright suite covering what unit tests cannot: rendered
colour, focus order, tap targets, and whether a phone-width layout overflows.

```bash
npm run test:e2e                       # both viewports, against the deployment
E2E_BASE_URL=http://localhost:4173 npm run test:e2e   # against a local build
npm run test:contrast                  # design-token contrast audit, no server
```

The default target is the deployed origin, because most of what the suite asks
about — a published week with real projections in it, gzip, SPA deep links —
only exists there. To test a change before it ships, build it and point the
suite at a local preview:

```bash
npm run build
VITE_DEV_API_PROXY=https://<your-api-host> npm run preview -- --port 4173
E2E_BASE_URL=http://localhost:4173 npm run test:e2e
```

`preview` proxies `/api` exactly as `dev` does, so a production bundle can be
exercised against the real API without deploying it first.

Four specs, by what they protect:

| spec | what breaks without it |
|---|---|
| `a11y.spec.ts` | axe (WCAG 2.1 AA) on every route, one `h1` per page, no skipped heading levels, skip link, focus-on-navigation, visible focus rings, labelled controls, keyboard-only simulation |
| `walkthrough.spec.ts` | the dashboard→board→player→matchup path, slate state surviving a reload, share links, the error/empty states, a full simulation |
| `responsive.spec.ts` | horizontal overflow at phone width, the fixed nav not covering content, cards replacing the table, 44px tap targets |
| `data-states.spec.ts` | K/DST refusals, nothing published, an empty board, slow and failed requests, a missing projection, a 400-player board |

`token-contrast.mjs` is the one to run when touching the palette. It parses the
token blocks out of `styles/index.css` — not a copy of them — resolves every
`oklch()` through a real browser canvas, and checks every pairing the UI draws
in both themes. It prints the smallest lightness that would fix each failure and
exits non-zero, so it works as a pre-commit check. `axe` only sees the colours
on the page it is given; this sees the ones a future component will reach for.

Two workers, always. Every run goes through one API instance behind one cache,
and the default worker count measures contention rather than the app.
