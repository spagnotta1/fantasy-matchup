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
| `npm test` | unit tests (Vitest) for the pure logic under `src/` |
| `npm run contract-check` | drive every endpoint against a running API |
| `npm run test:e2e` | Playwright against a local build and the local API |
| `npm run test:visual` | compare sixteen screens against committed screenshots |

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

## The design system

Small on purpose: tokens, two primitives everything else is built from, and one
page that shows all of it. Open `/specimens` (routed, but not in the navigation
or the palette) to see every part in every state with the real tokens.

### Tokens

All in `src/styles/index.css`. Colour is defined once per theme on
`[data-theme]`; everything else is in `@theme` and is the same in both.

| | utilities | values |
|---|---|---|
| type | `text-hero` `text-title` `text-section` `text-body` `text-detail` `text-caption` `text-chip` | 56, 24, 17, 14, 13, 12.5, 11.5px |
| radius | `rounded-card` `rounded-control` `rounded-chip`, and `rounded-full` | 10, 6, 4px; the pill is for status and provenance labels only |
| control height | `h-control` `h-control-sm` `h-control-xs` `h-touch` | 40, 32, 28px; 44px under a finger |
| row height | `h-row-compact` `h-row` `h-row-comfortable` | 32, 40, 48px |
| elevation | `shadow-raised` `shadow-overlay` | the one lifted panel; overlays. A card is a hairline and no shadow. |

A type token carries its own line height, and the two headings their weight,
so a role is one class. `text-hero` is not tabular: tabular figures are for
columns. A size off this scale needs its reason written beside it; today that
is the initials inside `TeamLogo`'s fixed discs and the player page's
decorative jersey numeral.

New token names must be registered with tailwind-merge in `utils/cn.ts`.
Unregistered, `text-caption` is read as a colour and silently dropped beside
`text-ink`. `cn.test.ts` pins the cases.

**Themes.** `data-theme` is always set to `light` or `dark` — "follow my
device" is resolved by the inline script in `index.html` before first paint and
kept in step by `useTheme` — so each palette is written once. Because the
palettes are scoped to the attribute and not to the root, any element can carry
one: `<div data-theme="dark">` is a dark island, which is how a second dark
palette can be judged beside the first.

### Buttons

`components/ui/Button.tsx`. Four components over one class builder
(`buttonStyles.ts`), so a link drawn as a button cannot drift from the button
beside it:

| component | element | notes |
|---|---|---|
| `Button` | `<button>` | `loading` shows a spinner in the icon's place, keeps the width and keeps focus |
| `ButtonLink` | router `<Link>` | no `disabled`: a link that cannot be followed should not be drawn |
| `IconButton` | square `<button>` | `label` is required; it is the accessible name and the hover title |
| `IconButtonLink` | square `<Link>` | the same, navigating |

`variant`: `primary`, `secondary` (default), `ghost`, `danger`, `link`.
`size`: `md` 40px for a page's primary action, `sm` 32px in toolbars, `xs`
28px inside table rows. On a touch device `md` and `sm` grow to 44px; `xs`
keeps its size, so it cannot make its row taller, and is given a 40px-tall hit
area instead. Pass a glyph as `icon` rather than as a child when the button can
load.

### Tables

`components/ui/DataTable.tsx`. A real `<table>` with a caption and scoped
headers, sentence-case headers in one size, numbers right-aligned in tabular
figures, a sticky header and three densities (`compact` 32, `default` 40,
`comfortable` 48).

```tsx
<DataTable
  caption="2026 season value against ADP"
  columns={COLUMNS}            // id, header, cell, numeric?, rowHeader?, sortValue?, tip?
  rows={entries}
  rowKey={(entry) => entry.player.player_id}
  sort={sort}                  // the caller owns it, so it can live in the URL
  onSortChange={(next) => setState({ sort: next.key, dir: next.direction })}
  minWidth="42rem"             // below this the table scrolls sideways...
  freezeFirstColumn            // ...with its first column kept in view
/>
```

- **Sorting** is a button in the header, `aria-sort` on the sorted column and
  the sort spoken in the caption. Missing values sort last in both directions.
  The helpers are in `utils/tableSort.ts`.
- **A column that needs explaining** takes a `tip`. The header's own label is
  the trigger, marked with a dotted underline: no icon and no extra width. On a
  sortable column the tip is the sort button's description, so the pair is one
  tab stop.
- **`layout="fixed"`** sizes columns from the header alone, so the table
  cannot outgrow its frame and the one column without a width takes the rest.
  **`stickyTop`** moves the header's stopping point for a page with a sticky
  toolbar of its own.
- **A row that goes somewhere** holds one `RowLink` in the cell that names it.
  That link is the keyboard and screen-reader path; for a pointer the whole row
  follows it, except on a control of its own.
- **Narrow screens.** Nothing is hidden to make a table fit. Given `minWidth`,
  a table with less room than that becomes its own scroller, no taller than
  the screen, so the header stays at its top and the first column at its left.
  With enough room nothing scrolls but the page, and the header sticks under
  the application bar. Under 480px of room a table of players is not a table
  at all: see "Row list" below.
- **A card around a sticky table** clips with `overflow-clip`, not
  `overflow-hidden`, which would make the card the thing the header sticks to.
- For a body that is not a flat list — tier groups, memoised rows — compose the
  parts the wrapper is built from: `Table`, `TableHead`, `ColumnHeader`,
  `TableBody`, `GroupHeaderRow`, `TableRow`, `RowHeaderCell`, `TableCell`.

- **A group of rows** gets its own `TableBody` opened by a `GroupHeaderRow`: a
  tier, a designation, a position. Its words are held at the left edge, so they
  stay readable while a narrow table scrolls sideways.
- **`highlighted`** on a `TableRow` tints a row that belongs to a set the
  reader marked (a player on their own roster). The row says so in words too.
  It is not `selected`, which is the one row in question.
- **`stickyHeader={false}`** for a short table in the middle of a long page.
  A sticky header is also what caps a scrolling table at the screen's height,
  and twenty rows do not need a second scrollbar.

`PlayerCell` (`components/domain`) is the first cell of every table of
players: a 24px headshot, the name as the row's link, the grey line that
places the player this week, then any designation. One line where there is
room and wrapping where there is not.

Seven screens are on it:

| screen | built with | too narrow for its columns | under 480px of room |
|---|---|---|---|
| Rankings | parts, tier groups | the list replaces it, from 912px down (see "The board") | the list |
| Draft board | `DataTable`, sortable | scrolls in its frame, player held | the same: it sorts from its headers, and a list has none |
| Live | parts, memoised rows | scrolls in its frame; live points and the projection come first after the player | a list |
| Usage | `DataTable` | scrolls in its frame; the change comes first | a list |
| Injuries | parts, one group per designation | scrolls in its frame | a list |
| Teams | parts, one group per position | scrolls in its frame | a list |
| My team | parts, two tables | never scrolls: under 42rem each player folds onto two lines | the same |

Only Rankings and the draft board sort from their headers. The other five each
have one order that is the point of the page (highest live points, largest
change, designation then projection, position then rank, lineup slot), and the
caption says which.

My team is the exception in two more ways, both because its rows hold Bench,
Start and Remove. The name is an ordinary link and the row is not one, so a
press that just misses a button does not leave the page. And the range strip
has a column only from 60rem of table width; below that the actions keep the
room.

Still hand-built: the matchup boards and the schedule grid (including the one
row of it on a team page), the mock draft's tables, compare and the track
record. The player page's game log is on `DataTable` (see "The player page"):
a table at every width, with the week held while a phone scrolls the rest.

### Row list

`components/ui/RowList.tsx`. What a table of players becomes on a phone. It is
the board's phone list (`ProjectionList`) with its frame, sections and rows
taken out as parts, so Live, Usage, Injuries and Teams fold the same way and
the board is built from the same parts as they are.

```tsx
const [frameRef, asList] = useRowList<HTMLDivElement>()   // hooks/useRowList

<div ref={frameRef}>
  {asList ? (
    <RowList value="Projection">                 {/* what the right-hand number is */}
      <RowListGroup id="report-out" heading="Ruled out" note="18 players">
        <RowListRows>
          <RowListItem to={`/players/${id}`}>    {/* the whole row is this one link */}
            <PlayerAvatar player={player} size="xs" />
            <RowListTitle name={player.name} meta="QB · CHI vs PHI" />
            <ProjectionValue points={points} className="justify-self-end" />
            <RowListLine>...</RowListLine>         {/* a further line under the name */}
          </RowListItem>
        </RowListRows>
      </RowListGroup>
    </RowList>
  ) : (
    <Table ...>
  )}
</div>
```

**Why a list there.** A table scrolling sideways on a phone holds the name and
shows one other column beside it. So the two things each page sets side by
side were never on screen together: live points and the projection, a
designation and the number it qualifies, a change in share and the bar that
explains it. On Live and Usage the table was also a second scroller, capped at
the height of the screen. The list is the page scrolling, with every column of
the row in it.

| screen | line one | under it |
|---|---|---|
| Live | name, team, where the game stands, "My team", "Past the 20"; live points | the field strip and the projection; the stat line and, once final, the difference |
| Usage | place, name, team, designation; the change | the average-to-last bar, full width; the projection |
| Injuries | name, both teams; the projection | the designation, the injury and "will not play" under the number; the practice line |
| Teams | name, designation; the projection | the board's own second line: grade, range strip, chance of 20+ |

- **`useRowList`** measures the room the table has (`ROW_LIST_BELOW`, 480px: a
  frozen player column and two columns of numbers) and not the window, like
  everything else here that chooses what to draw. Put the ref on an element
  that is mounted for as long as the component is.
- **A list has no header row**, so `RowList` prints once what the right-hand
  number is (`value`), and a `note` where a table's header had a tip. A number
  that is not the headline is named where it is printed ("Proj. 14.2").
- **One link per row.** The row is the link to the player and holds no second
  one, so a team abbreviation that is a link in the Injuries table is text in
  the list. Groups are sections named by an `h3` (`h2` on the board, where the
  page's `h1` is the only heading above).
- **The draft board stays a table**: its order is chosen from its column
  headers. **My team** keeps its own two-line table, because its rows hold
  Bench, Start and Remove.

### Filter toolbar

`components/ui/FilterToolbar.tsx`. The controls that decide which rows a table
holds, laid out one way. It is layout and behaviour only and owns no state:
each page keeps its filters in the URL through `useUrlState`, as before.

```tsx
<FilterToolbar label="Filter players" summary="12 of 214 players">
  <FilterSearch label="Search players" value={search} onChange={setSearch} />
  <FilterChoice label="Position" value={position} onChange={setPosition} options={POSITIONS} />
  <Select label="Team" hideLabel size="sm" ... />
  <FilterChip removeLabel="Show every game" onRemove={clearGame}>DET @ CAR</FilterChip>
</FilterToolbar>
```

- **One height.** 32px, and 44px under a finger, for every control in it. A
  search box and a select are given the touch height by the toolbar; the
  segmented control and buttons already had it.
- **It wraps between controls, never inside one.** A `FilterChoice` is a
  segmented control where its options fit the toolbar's own measured width and
  a native select where they do not, with each option prefixed by the filter's
  name ("Designation: All"), since a closed select shows only one.
- **`summary`** is the count at the trailing edge, announced when it changes.
- **`FilterChip`** is a filter set somewhere else on the page (a game picked
  from the Live ticker) with a named button to drop it. Squared, not a pill.

Rankings, Live, Usage, Injuries and the draft board use it. Rankings keeps its
position tabs as links, because the position is part of its path. On the draft
board the season is a `Select` whose options name it ("2026 season"), since
its label is not drawn, and the link to the mock draft sits at the row's
trailing edge. Its lens ("Everyone, We rank higher, Drafters rank higher")
used to stay a segmented control on a phone and wrap its labels onto two
lines; as a `FilterChoice` it is a select there.

On a phone the board's search, team and sort are 44px like its position tabs
above them and like every other toolbar. They were 32px before the toolbar,
which was the one place a control under a finger was smaller than the rule in
"Tokens" says. It costs 24px of height over the two lines.

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

## The board

`/rankings` is the one board, and it is drawn three ways from the same rows.

| room the board has | drawing | a row |
|---|---|---|
| 948px or more | a table (`ProjectionTable`, on the shared table parts) | one line, 40px; 48px with "Roomy" |
| less | a list (`ProjectionList`) | two lines, about 65px |
| any, by choice | cards (`ProjectionCards`, `?view=cards`) | one player at a time |

**The range strip is on every row at every width.** It used to be a column only
from 1,280px; a tablet saw none. In the table its width is what the table has
to spare after the fixed columns and a 21rem player cell, never under 13rem and
never over 38% — sized in container units, so it is right whether the sidebar
is open or not. Floor and ceiling are printed either side of the strip in every
drawing, which is why the separate Floor and Ceiling columns are gone; both
still sort, from the toolbar. In the list the strips share a left edge and a
width, so the yard lines of one row line up with the next.

**On a week with an ungraded matchup the list folds once more below 412px.**
The grade's slot is then as wide as the words "Not graded", and the second
line needs 322px: a 412px phone has exactly that, and at 390px and 360px the
ceiling was printed under the chance of 20+. There the strip takes the whole
line and the grade and the chance go under it (`ProjectionLine`). With every
matchup graded the two lines fit down to 360px and are as they were.

**"Room" is measured, not guessed from the window.** The sidebar takes 240px,
so a 1,100px laptop window has less room than an 820px tablet. The page
measures its own content width and draws the table only where a name and a
game fit on one line beside six other columns (`TABLE_MIN_WIDTH`).

**One bar stays in view.** Position tabs, search, team and sort sit in a bar
that sticks under the application header, and the table's column header sticks
under that. The bar wraps on a narrow screen, so its height is measured and
handed to the table as `stickyTop`. On a phone only the tabs stick; three more
controls would cost a fifth of the screen for the whole scroll.

**A designation is on the board in every drawing.** "Out" or "Questionable"
sits beside the name it qualifies, in the table, the list and the cards
(`RowFlags`). It used to be on the cards only, so the desktop table printed a
ruled-out player's projection with nothing beside it.

**Row height is a preference, not a filter.** "Compact" and "Roomy" are kept in
this browser's storage with the theme, not in the URL with the sort: a shared
link should not set the row height of whoever opens it.

**A table row opens with a tick box**, for choosing players to compare; see
"Compare" below. Its 36px column is why the table is drawn from 948px of room
and not 912px: the player column keeps the 270px a name and a game need.

## Compare

`/compare?players=…` answers "which of these do I start", and it is reached
from a list, not from a search box.

**Every range is on one ruler** (`features/comparison/RangeRuler`). The
players are rows and their strips share a left edge, a width and a scale, so a
floor is further right or it is not. They used to be columns, each strip on
its own axis. The scale runs from zero to the yard line above the highest
ceiling among the players being compared (`fieldScaleMax`), and the heading
says so: "Range, 0 to 35 points". It is the board's row on purpose, the mark a
reader already learned on Rankings.

| room the ruler has | drawing |
|---|---|
| 640px or more | a table: player (with the matchup grade), range, chance of 20+, projection |
| less | the board's two-line row (`ProjectionLine`), strips still lined up |

**The numbers are side by side at every width** (`ComparisonGrid`, on the
shared table parts). On a phone it used to become one list per player, so two
floors were compared by scrolling between them. Two players now fit a 412px
phone as they are. With more, or on a narrower phone, the table scrolls
sideways in its own frame with the metric column held at the left.

**A row's best number is marked once, by weight and a small dot.** It was a
tinted cell and the word BEST, which ran seven times down one column when one
player led most rows and read as a verdict on the player. A tie marks nobody,
and neither does a row with no winner (matchup, opponent, what the range is
based on). The line under the table still says what the mark is not: a
recommendation.

**Players are ticked on a list** (`useCompareSelection`, `CompareTick`,
`CompareBar`). Every row of the board's table and of My team's two tables
opens with a tick box, and a bar at the foot of the screen names who is
ticked and goes to their comparison. One ticked player is not a comparison,
so the button is disabled and says to tick one more; at six, the most the
endpoint takes, the empty boxes are disabled where they stand.

- The ticks are in the list's own URL, `?compare=id,id`, written like a
  filter (in place, without scrolling the page). They survive a reload and
  Back from the comparison, and the board's position tabs carry them, so a
  running back and a wide receiver can be ticked on two boards for one flex
  decision. Search, team and sort are still dropped by a tab.
- The box shows its tick at once and the URL catches up. The router applies a
  change of address as a transition, and a box bound straight to it stayed
  empty until the board had re-rendered.
- A press on the box's cell ticks the box; it does not follow the row's link.
- The bar sits above the phone's navigation bar, and outside the part of My
  team that goes inert while a week loads.
- The board's phone list and its cards have no box. A row there is one link,
  and a link cannot hold a second control. The bar is still drawn for them, so
  a selection that arrived in a link can be used or cleared.

## The shell

The sidebar, the header and the phone's bottom bar (`layouts/`), and one list
they are all built from (`layouts/navigation.ts`).

**Nine entries and a foot.** The sidebar was thirteen lines. It is now two
groups and a foot:

| | entries |
|---|---|
| This week | Dashboard, Rankings, Matchups, Live, Reports |
| Tools | My team, Simulation, Compare, Trade analyzer |
| foot | Track record, Settings, and the control that folds the sidebar |

Four of the thirteen were this week's slate from another angle, and each had
grown a line of its own:

| was | is now | old address |
|---|---|---|
| Teams (`/teams`) | the Teams view of Matchups, `/matchups?view=teams` | forwards there |
| a team's page (`/teams/BAL`) | where it was; Matchups is what is marked while it is open | unchanged |
| Injuries (`/injuries`) | a view of Reports, `/reports/injuries` | forwards, filters and all |
| Usage trends (`/usage`) | a view of Reports, `/reports/usage` | forwards, filters and all |

`MovedPage` is the redirect: it carries the query string across, so
`/usage?metric=target&position=WR` arrives showing the same rows. Each report
keeps its own heading and its own question; the switch between them sits where
Matchups has its own. Switching carries the week and the scoring format and
leaves the other report's filters behind.

**The command palette still lists every page by its own name**, including the
three that are views now (`PALETTE_ONLY`). Typing "usage" lands on the usage
view, not on Reports.

**The rail.** The sidebar folds to 56px of icons (`useSidebarRail`, kept in
this browser's storage with the theme, not in the URL). Each icon keeps its
name as its accessible name and its hover title. The 184px goes to the page,
and since every table here chooses its drawing by the room it has, that is a
column: in a 1,100px window the board is a table with the rail (996px of
room) and a two-line list without it (804px, under the table's 912px).

**What a path belongs to** is decided in one place (`isAt`): a whole-segment
match on the entry's own address plus any it lists in `alsoAt`. It replaced
`NavLink`'s own matching so that a team's page could mark Matchups.

**The header** holds the slate, search and the theme. Compare and Settings are
no longer in it (each has a place in the sidebar, and on a phone in the menu),
and the "not signed in" badge is gone: there are no accounts.

**The slate is one button**, at every width: "2026 · Wk 4 · Half PPR". It says
what every number on the page is for, and pressing it shows the three
selectors (`SlateSwitch` in `TopBar.tsx`): a row under the header on a phone,
a panel under the button from 768px. It used to be three dropdowns across a
desktop header and an unlabelled icon on a phone. The three change at very
different rates (the week weekly, the season almost never, scoring once per
league), and what a reader needs all the time is to read the slate, not to
change it. The panel is a disclosure: it stays open while more than one is
changed, and closes on Escape (focus returns to the button), on a press
elsewhere, and on leaving the page. On the player page the week stepper is the
quick way to change the week, and this button is where it is read.

**The phone bar** is unchanged: Dashboard, Rankings, Matchups, Simulation,
My team.

**A filter keeps the page where it is.** Filters, the slate, the roster and
the other things kept in the query string are written with
`preventScrollReset`. The router treats any change of address as a new page
and scrolls to its top, which is right for a link and wrong for a filter: the
position switch on a team's remaining schedule is three screens down, and
every press of it threw the reader back to the top. `useUrlState` does this
for every page that uses it; a new direct `setSearchParams` has to as well.

## The player page

`/players/:id` is where one player's week is read, and where the week before
it is one press away.

**A bar stays in view** (`PlayerBar`), under the application bar, for the
whole scroll. It holds three things:

| | where | why |
|---|---|---|
| the week stepper | always, at the trailing edge | one press moves the page a week from wherever the reader is |
| who and how much: name and projection, and with room (960px of bar) the chance of 20+, the header's two actions and, from 1,280px, the range strip | once the header has scrolled away | until then the header says it, and the bar does not say it twice |
| links to This week, Game log, Usage, Matchup, Context | from 720px of bar | on a phone the bar is one line and the links sit under the header instead |

The summary repeats the header for the eye and is hidden from assistive
technology. A link scrolls its section to just under the bar (the bar's height
is measured and published as `--player-bar`, since it is two lines where it
wraps) and moves focus there, so the next Tab carries on from the section.

**Stepping a week keeps the page.** The stepper writes the same `?week=` every
screen reads, through `SlateProvider`, and walks only the published weeks. Two
things make it usable half-way down a page. The profile query keeps the same
player's previous week on screen until the new one arrives, so the page dims
instead of collapsing to a skeleton. And a change of week no longer scrolls
the page to its top: the slate's setters navigate with `preventScrollReset`,
on every screen. At the first or last published week the button stays, says
why it does nothing, and keeps the keyboard's focus; a disabled button would
drop it.

**The header is beside its scoreboard** from 64rem of its own width, which is
what puts the projection card and the top of the game log on a laptop's first
screen (the page went from 3,153px to about 2,700px at 1440). The outline
jersey number is not drawn in that layout; it is still in the meta line.

**The game log** draws each game's stored projection as an ink tick across its
column, with a legend, and the table has a Difference column (points minus
projection). The table is on the shared `DataTable` and scrolls with the page,
not in a box. A select chooses the last 17 games or one season, and the usage
trend under it draws the same games. Earlier seasons are loaded on request
(`weeks=120` on the profile endpoint): the page opens with 24 games, and a
season cut off by that limit is not offered until the rest of it is loaded.
The accuracy figures under the chart are over every loaded game and say how
many that is.

**The lists are narrower.** Injury, weather and the betting line sit side by
side from 56rem of card; usage and matchup rows go to two columns where their
card is wide enough. Label and value used to be up to 1,100px apart.

The order of the sections is unchanged and deliberate: nearest the model
first. See the note at the top of `pages/PlayerDetailPage.tsx`.

## The simulation result

`/simulation` is two pages in one address. Before a run it is the two lineup
builders, the run controls and what a run will produce. Once a run is asked
for, it is read from the top down as an answer:

| | what | where it is drawn |
|---|---|---|
| 1 | the result: estimated win probability, the two score ranges, the position gaps | `SimulationSummary`, one card, first on the page |
| 2 | each lineup, folded to a line | `LineupBuilder` with `disclosure` |
| 3 | the run controls | as before |
| 4 | the rest: what the engine flagged about each lineup, the margin and the added-up projections, the swing players, the assumptions | `SimulationDetails` |

A finished run used to be read in the order it was built, with the answer
under both builders and the controls. On a 1440px screen all of 1 to 3 is now
in the first screenful; on a 412px phone the estimate and both ranges are,
with the gaps starting at its foot.

**The summary is one surface, not a row of cards.** The estimate and the
ranges sit side by side from 44rem of the card's own width (a query container,
so a laptop with the sidebar open is judged by the room it has), and the gaps
run under both, two positions to a line. Narrower, the three are stacked in
that order. The figure is 36px; it was 60px.

**Nothing the old result showed is gone, and each notice is still shown
once.** Two of the four tiles are: each lineup's simulated average and median
are in the summary now, beside its range ("116.4 pts on average", "Middle
115.3"), and printing them again was the same numbers twice. The limits that
qualify the estimate (no kickers or defences, players simulated on their own,
no injury adjustment) are still directly under it, in the same part of the
card.

**The numbers beside a position's bar are outside it.** They were printed
inside, where the bar ran over them: the larger a lead, the less legible the
number that made it. Each column of rows is headed with whose number is on
which side.

**A lineup folds to a line and is not removed.** The line says whose it is,
how many slots are filled, who is in it, and names any starter carrying an
injury designation with the designation, which is never the part that is cut
short. "Edit lineup" is a disclosure button: one button, in the same place open
or shut so it keeps the focus through a press, with `aria-expanded` and
`aria-controls`. The body stays mounted and hidden, so an opened lineup is
exactly as it was left.

**The lineups fold when the run starts, not when it comes back.** The waiting
card is where the result will be and holds some of its height, so the page the
answer lands in is already there and grows under it instead of collapsing. A
refused run opens the lineups again, under the refusal: it is a thing to fix
in a lineup. Loading an earlier run from the history goes back to building.

**Three pieces of copy moved by a word.** "The overlap is why the result above
is a chance" lost "above", because on a wide screen the estimate is beside the
chart. The position rows gained "Gap" and each side's name as column heads.
Each range line gained "pts on average". No statistical claim was reworded.

Not done here: the ranges are still the simulation's own bars and not the
field strip. That is P2.7, the chart kit.

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
gap would be worse than showing either alone, so `SimulationDetails` renders a
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

## Tests

Three kinds, by what each can see.

### Unit tests

`npm test` runs Vitest over `src/**/*.test.ts(x)`: the pure logic a redesign is
most likely to disturb without anyone noticing. Board sorting and tier
grouping, search ranking, tie handling, lineup parsing, share links, trade
arithmetic, the formatters. No DOM and no server; the whole suite takes about a
second. Fixtures in `src/test/factories.ts` are built through the real Zod
contracts, so a fixture cannot describe a response the API could not send.

A component is unit-tested only by rendering it to a string, for what it
*says* (`CalibrationNotice.test.tsx`). How it looks is a screenshot's job and
how it behaves is Playwright's.

### Browser QA

`tests/e2e` is a Playwright suite covering what unit tests cannot: rendered
colour, focus order, tap targets, and whether a phone-width layout overflows.

```bash
npm run test:e2e                       # both viewports, against a local build and the local API
npm run test:contrast                  # design-token contrast audit, no server
```

**Local first.** With `E2E_BASE_URL` unset the suite builds nothing itself: it
starts `vite preview` on port 4173 over the bundle in `dist/`, which proxies
`/api` to the local API (`python -m nflfp.api --port 8010`, or whatever
`VITE_DEV_API_PROXY` names). So the usual run is:

```bash
npm run build
npm run test:e2e
```

The suite used to default to the deployed origin. That made a failing test
ambiguous — a change in this checkout, or a change in this week's data — and
it meant a fix could not be tested before it shipped. The deployment is still
one variable away, for the things that only exist there (gzip, SPA deep links,
a cold start):

```bash
E2E_BASE_URL=https://<the-deployed-origin> npm run test:e2e
```

Fourteen specs, by what they protect:

| spec | what breaks without it |
|---|---|
| `a11y.spec.ts` | axe (WCAG 2.1 AA) on every route, one `h1` per page, no skipped heading levels, skip link, focus-on-navigation, visible focus rings, labelled controls, keyboard-only simulation |
| `walkthrough.spec.ts` | the dashboard→board→player→matchup path, slate state surviving a reload, share links, the error/empty states, a full simulation |
| `responsive.spec.ts` | horizontal overflow at phone width, the fixed nav not covering content, the list replacing the table, 44px tap targets |
| `data-states.spec.ts` | K/DST refusals, nothing published, an empty board, slow and failed requests, a missing projection, a 400-player board |
| `weather.spec.ts` | a rain chance printed as a percentage on every screen that shows one, and the bad-weather flag following its threshold |
| `my-team.spec.ts` | a populated roster at 360, 390 and 412px and on desktop, both themes: no sideways scroll, every row's Start, Bench and Remove on screen; a press on a row not leaving the page |
| `search.spec.ts` | the first result being the player meant: projected players first, exact names first, retired players still listed |
| `board.spec.ts` | the board at every width: a range strip on every row, 40px rows and the remembered 48px choice, the toolbar and column header staying in view, the row as the link, headers that explain themselves, the table giving way to the list by measured room, nothing in a list row printed over anything else at 412, 390 and 360px on a graded and an ungraded week, an injury designation on the board |
| `player.spec.ts` | the player page: the bar following the page down with the name and the projection in it, each section link landing its section under the bar with the focus, the week stepper keeping the scroll position and the focus and saying why it stops at the last week, a projection tick for every game that had one, the table's difference column, a season choice the usage trend follows, earlier seasons loaded on request, a week with no projection; axe in both themes; no overflow at 1024, 820, 412, 390 and 360px; the one-line bar and 44px targets on a phone |
| `compare.spec.ts` | the comparison and the way to it: every range strip starting at one edge at one width, on a table and on a phone's list, with the scale named in the heading; one best mark per row and never the word; two players side by side on a phone with nothing to scroll, three scrolling in the table's own frame with the metric held; ticks on the board and My team living in the URL, crossing a position tab and surviving Back; a press beside a box ticking it without opening the player or moving the page; six as the most; the bar following the page and clearing the phone's navigation; axe in both themes; no overflow at 1024, 820, 390 and 360px |
| `simulation.spec.ts` | a finished simulation read from the top: the result first with the estimate, both ranges and the gaps in it, and the lineups, the controls and the rest under it in that order; the summary printing what the API returned; each lineup folded to a line that names its starters, opening and shutting from the keyboard with the focus kept and its players intact; the lineups folding as the run starts and the answer landing where the wait was; running again and "Adjust and run again"; a refused run opening the lineups; loading an earlier run; axe and the heading outline in both themes; at 1440, 1024, 820, 768, 412, 390 and 360px no overflow, nothing past the screen's edge, both ranges on one scale, every gap's numbers printed beside its bar; a 44px disclosure on a phone |
| `shell.spec.ts` | the sidebar's two groups and its foot, the page a reader is on being marked (a team's page marks Matchups), the rail folding to named icons and staying folded, the header no longer repeating the sidebar; every old address arriving with its filters, Reports and its two views, Teams as a view of Matchups, the palette listing every page; on a phone the slate chip saying the week and the scoring format, and the bottom bar keeping its five |
| `primitives.spec.ts` | the shared `Button`, `DataTable` and `FilterToolbar` on `/specimens`: sorting from the keyboard, the row link, the sticky header, row heights, target sizes, a loading button keeping its width and focus, a filter choice becoming a select only where it does not fit |
| `tables.spec.ts` | Live, Usage, Injuries, Teams and the draft board on the shared table and toolbar: filters working together and living in the URL, a filter leaving the sort alone, the row as the link, row groups announced as headings, a Live refresh keeping focus, scroll and filters, an empty filter told apart from no data, loading and failed requests; and all six screens (My team included) at 1440, 1024, 820, 768, 412, 390 and 360px: no page overflow, no clipped or wrapped control, no dropped column, the player column held while a table scrolls in its frame, and at the three phone widths the list in its place with every column of the table in each row, nothing printed over anything else, one link per row; every toolbar control 44px on a phone |

`capture.mjs` is not a test. It opens a visible browser and photographs a set
of routes at 1440, 820 and Pixel 7 widths in both themes (or at any width in
pixels: `--widths 1024,768,360`, with `--roster` to seed My team), flagging sideways
overflow and console errors, for looking at a change rather than asserting on
it. It prints each page's height and, where a page is too wide, the elements
that make it so. `--press "Run simulation"` presses that button first, for a
screen that only exists after an action, and `--fold` also saves the first
screenful. The whole verification sequence, with this in it, is the `frontend-verify`
skill in `.claude/skills`.

`token-contrast.mjs` is the one to run when touching the palette. It parses the
token blocks out of `styles/index.css` — not a copy of them — resolves every
`oklch()` through a real browser canvas, and checks every pairing the UI draws
in both themes. It prints the smallest lightness that would fix each failure and
exits non-zero, so it works as a pre-commit check. `axe` only sees the colours
on the page it is given; this sees the ones a future component will reach for.

Two workers, always. Every run goes through one API instance behind one cache,
and the default worker count measures contention rather than the app.

### Screenshots

`tests/visual` holds a picture of sixteen screens — dashboard, board, the
board with two players ticked to compare, player, game, team, My team, Live,
usage, injuries, compare, the simulation builder, a finished simulation, the
track record, the draft board and the specimen page — at 1440px and 412px,
with the dashboard, both boards, player page, Live, injuries, compare, the
finished simulation and specimens also in the dark theme. The seven screens
whose layout changes shape between a laptop and a phone (team, My team, Live,
usage, injuries, compare, the finished simulation) are also held at 820px. A
screen that only exists after an action names the button to press (`press` in
`SCREENS`): the finished simulation opens a matchup link and runs it. A token or primitive change touches every page, including the
ones nobody opened; these turn that into image diffs to approve.

```bash
npm run test:visual            # compare against the committed baselines
npm run test:visual:update     # accept the current pictures as the new baselines
npm run test:visual:record     # re-record the API fixtures (needs the local API), then update
npm run test:visual:record -- specimens draft-board   # the named screens only; the rest untouched
npm run test:visual:record -- --project visual-tablet team   # ...and at one width only
```

The API is recorded, not live. Each screen's traffic is saved once under
`tests/visual/fixtures` and replayed, so a picture moves only when the frontend
does and the comparison needs no backend. A request the recording does not hold
is aborted on purpose: a screen that starts calling a new endpoint shows an
error in its picture, and the fix is `test:visual:record`. Headshots and team
logos come from other hosts and are blocked, so avatars show initials on every
run.

Baselines are per platform (`__screenshots__/win32`, `__screenshots__/linux`)
because text is rasterised differently on each. The Windows set is the one
committed; CI produces the Linux set as an artifact until one is committed too.

Not every route and not every state is photographed. Behaviour belongs in
`tests/e2e`, where it is asserted rather than pictured.
