---
name: frontend-verify
description: Verify a frontend change in nfl-fantasy the standard way - local API plus Vite on a free port, a visible-browser pass at desktop, tablet and Pixel 7 in both themes, then the contrast audit, contract check, unit tests, local e2e and screenshot comparison. Use after any change under web/ (a token, a primitive, a page), before saying a UI change works, when asked to "check it in the browser", when screenshot baselines fail, or when adding a screen to the visual suite.
---

# Verifying a frontend change

A change under `web/` is not done when it compiles. It is done when it has been
looked at in a real browser at three widths in both themes, and the checks
below are green. This is the sequence; run all of it for a token or primitive
change, and at least steps 1 to 4 for anything smaller.

The reader is the user, who wants to watch progress rather than be told tests
passed: the browser in step 3 is headed on purpose.

## 1. Bring up the local stack

Two servers, both in the background (`run_in_background`), from the repo root:

```bash
# The API, against the local Postgres mirror (see the challenger-eval skill).
DATABASE_URL=postgresql://nflfp:nflfp@localhost:5432/nflfp \
  .venv/Scripts/python.exe -m nflfp.api --port 8010 --host 127.0.0.1

# Vite, on a port that is free. 5173 is usually the user's own dev server
# on this same checkout: leave it alone and do not kill it.
cd web && VITE_DEV_API_PROXY=http://127.0.0.1:8010 npx vite --port 5183 --strictPort
```

Wait for both: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8010/api/v1/health`
and the same for `http://localhost:5183/`. No local database? Point the proxy
at production instead (`VITE_DEV_API_PROXY=https://api-production-e5552.up.railway.app`);
steps 5 and 6 then need the local API or are skipped, and say so in the report.

Never start the API with `--reload` when verifying. It can keep serving old
code on Windows.

## 2. Static checks

From `web/`:

```bash
npx tsc -b          # types
npm run lint        # oxlint
npm test            # vitest: pure logic and markup, no browser
npm run build       # tsc -b && vite build; steps 6 and 7 test this bundle
```

## 3. Look at it

```bash
node tests/e2e/capture.mjs http://localhost:5183 --out <scratchpad>/capture
```

Opens a visible Chromium and photographs the default routes at 1440, 820 and
Pixel 7 widths in light and dark (48 pictures, about a minute). It prints one
line per picture and flags sideways overflow and console errors. Then **read
the pictures** with the Read tool. The flags find what a picture hides; only
looking finds a label that wraps, a card that lost its edge, a number that
moved.

- Add routes with `--routes usage,injuries` and, for one holding a comma,
  `--route "my-team?roster=a,b,c"`. Real ids for a player, game, team and
  roster are in `tests/visual/fixtures/subjects.json`.
- In Git Bash write routes without the leading slash. It rewrites `/specimens`
  into `C:/Program Files/Git/specimens`.
- `/specimens` is the workbench: every primitive in every state, with fixed
  sample rows. A change to a token or a primitive shows there first. It is
  routed but not in the navigation or the palette.
- Narrow it while iterating: `--widths phone --themes dark --routes specimens`.
- A width can be a number of pixels, for the ones between the three named:
  `--widths 1440,1024,820,768,412,390,360`. 1,024px is the one that catches
  the most, because the sidebar is open and the content is narrower than on a
  tablet.
- `--roster id,id,...` seeds My team (and Live's "My team" rows) from
  `subjects.json`'s `roster`.

For a first or risky change, look at more than the default routes. Every
route at all three widths is about four minutes.

## 4. Contrast

```bash
npm run test:contrast
```

Reads the token blocks straight out of `src/styles/index.css` and checks every
pairing the UI draws, in both themes. A new colour token used for text or for a
control needs a line in `PAIRS` in `tests/e2e/token-contrast.mjs`, or it is not
being checked.

## 5. Contract

```bash
npm run contract-check      # needs the local API on 8010
```

## 6. Behaviour, in a browser

```bash
VITE_DEV_API_PROXY=http://127.0.0.1:8010 npm run test:e2e
```

Desktop and Pixel 7, against `vite preview` of the bundle from step 2 (it
starts the preview itself on 4173) and the local API. Includes axe on every
route, the phone-width overflow checks and `primitives.spec.ts`, which drives
the shared `Button` and `DataTable` on `/specimens`. Two workers, about nine
minutes. Rebuild first: this tests `dist/`, not the dev server.

## 7. Screenshots

```bash
npm run test:visual
```

Replays recorded API responses, so it needs no backend and only moves when the
frontend does. When it fails:

1. Open `playwright-report/index.html` and read each expected/actual pair. A
   failure is either the change you meant or one you did not.
2. If any picture is not what you meant, fix the code, not the baseline.
3. Only then `npm run test:visual:update`, and say in your report that the
   baselines were re-accepted and for which screens.

The baselines under `tests/visual/__screenshots__/` have been untracked files
at times. If `git ls-files web/tests/visual` is empty, copy that folder to the
scratchpad before step 3 of any change that will move them, or the "before"
is gone. A before/after report worth keeping goes under `data/frontend-review/`
(ignored by git).

Adding a screen: add it to `SCREENS` in `tests/visual/visual.spec.ts`, then
record just that one, which leaves every other archive and picture alone:

```bash
VITE_DEV_API_PROXY=http://127.0.0.1:8010 node tests/visual/record.mjs specimens draft-board
```

`npm run test:visual:record` with no names re-records everything from whatever
the local API serves today, and every baseline changes with the data. Do that
only when the contract changed.

## 8. Backend, if the change reached it

```bash
DATABASE_URL=postgresql://nflfp:nflfp@localhost:5432/nflfp \
  .venv/Scripts/python.exe -m pytest -q        # about six minutes; background it
```

## Things that have bitten

- **A truncating line still counts at full width.** `truncate` text inside a
  grid item sets the item's minimum width unless the item has `min-w-0`. Making
  secondary text 13px pushed the game page 39px wide on a phone this way.
- **`main` has a tabindex.** `element.closest('[tabindex]')` from inside the
  page always finds it. Scope the search to the container you mean.
- **Unknown `text-*` classes are colours to tailwind-merge.** A new type token
  must be registered in `src/utils/cn.ts` or `cn()` drops it beside
  `text-ink`. `cn.test.ts` pins this.
- **`overflow-hidden` on a card kills a sticky table header.** It makes the
  card a scroll container. Use `overflow-clip`.
- **A hidden radio cannot be clicked.** `SegmentedControl` hides its inputs;
  in a test click the label text.
- **Playwright's `-g` matches "project file title"**, so `^` never matches a
  test title.
- **Phone screenshots show mouse-sized controls.** A full-page capture in
  phone emulation drops `(pointer: coarse)`, so `pointer-coarse:` styles are
  not in the visual baselines. Assert touch sizes in an e2e spec instead, and
  do not read a 32px button in a phone baseline as a bug.
- **A table that must not outgrow its card** needs `layout="fixed"` on
  `Table` and a width on every column but one. In the default layout a long
  cell widens its column and the card clips the last one.
- **The window is not the room.** The sidebar takes 240px from 1,024px up, so
  a 1,100px laptop has less content width than an 820px tablet. A component
  that chooses what to draw by width measures itself (`useElementSize`); a
  viewport media query gets the laptop wrong.
- **Edit scripts and line endings.** Files here are a mix of LF and CRLF. A
  scripted find-and-replace across a line break must normalise first, or it
  silently matches nothing in half the files.
- **Hidden text can make the page taller than its scroller.** `sr-only` is
  absolutely positioned. Inside a table that scrolls in its own frame it is
  placed against whatever positioned ancestor it finds, and if that is outside
  the frame the page grows as tall as the unbounded table (Live was 6,253px on
  a phone). `Table`'s frame is `relative` for this reason; keep it.
- **A group heading is a `rowheader` too.** `getByRole('rowheader').first()`
  in a grouped table is "Ruled out", not a player. Use `th[scope="row"]`.
- **A viewport-sized phone screenshot keeps `(pointer: coarse)`.** Only
  full-page captures drop it, so a `foldOnly` screen (rankings, live) shows
  44px controls in its phone baseline and the others show 32px.
- **A squeezed flex item prints its last number under its neighbour.** A line
  of fixed-width parts around one that flexes (`min-w-0 flex-1`) does not
  overflow when it runs out of room: the flexing part shrinks below what is
  in it. The board's phone rows printed the ceiling under the chance of 20+
  at 390px this way, with no overflow to flag. `expectRowsLegible` in
  `tests/e2e/helpers.ts` measures the words, not the boxes; and look at
  390px and 360px, not only the Pixel 7's 412px.
- **`useElementSize` measures the element the ref held at mount.** A ref on
  something drawn only after loading is never measured. Put the hook in the
  component that owns that element (`useRowList` is used this way).
- **The local database moves.** A week can roll over mid-session (a new week
  published, actuals loaded), so a before and an after picture show different
  data. Pin both with `?season=2026&week=3`. On a Friday Live holds one game.
- **A search-param change scrolls the page to its top.** The router's
  `ScrollRestoration` treats `setSearchParams` as a new page unless it is
  passed `preventScrollReset: true`. The slate's setters pass it; a control
  that changes the URL from half-way down a page has to as well.
- **A stale page is `inert`.** `Refreshing` makes what it wraps inert while
  it dims it, so a control that caused the refresh (a stepper) has to sit
  outside it or it loses the keyboard's focus.
- **The player page is not in `a11y.spec.ts`'s route list** (it needs an id).
  `player.spec.ts` runs axe on it in both themes.
- **The local API can stop.** If `contract-check` or e2e fails with
  `ECONNREFUSED 127.0.0.1:8010`, start it again as in step 1.
- **Shell scripts with backticks.** Do not put CSS or TSX containing backticks
  inside a double-quoted `node -e "..."`: bash runs them. Write the script to
  the scratchpad and run the file.

## Reporting

State what was run and what it returned, with counts: unit tests, e2e passed
and failed, screenshots compared. If a step was skipped, say which and why. If
baselines were re-accepted, say so. Copy shown to a user is governed by
`CLAUDE.md`: a caveat states what was measured, and changing one goes through
the `challenger-eval` skill.
