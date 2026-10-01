# Frontend review — 2026-09-26

A page-by-page assessment of the web app, what was changed in response, and
what is left. Reviewed against the local app on a copy of production (2026
week 3), at 1440px and 390px, light theme, plus forced loading, error and
empty states. Every page was captured full-length before and after.

The bar for a change: it must improve what a manager understands or can do
next. Cosmetic changes were not made for their own sake.

## Findings that cut across pages

| Finding | Severity | Resolution |
|---|---|---|
| API outage left every page on its loading skeleton forever. Pages wait for the season/week catalogue, and when it failed they never left "pending". Only a small sidebar note hinted at a problem. | Correctness | Fixed. The shell shows the error with a working retry in place of the page (Settings excepted, as it reports service health). |
| The week picker said "No weeks yet" while the catalogue was still loading. | Correctness | Fixed. It now appears only once the catalogue has loaded and really has no weeks. |
| A link to an unpublished week (e.g. `?week=9`) showed "Week 1" in the picker while the page said week 9 was not out. | Correctness | Fixed. The picker shows "Week 9 (not out)", and the empty board offers "Go to week 3, the latest published". |
| The "N of N matchups are not graded" notice appeared on Injuries and Usage, which show no grades. | Clarity | Fixed. It appears only on screens that draw a grade chip. |
| Thresholds read "chance of 20.0+" in five places. | Polish, but reads as a measurement | Fixed. Shown as "20+" everywhere. |
| No page connected the roster to the rest of the app: My team, Simulation and Compare each started cold. | Workflow | Fixed on the dashboard (below), the player page (Add to my team, Compare) and My team (a primary "Estimate my chance of winning"). |
| The Confidence column read "Low" or "Very low" on nearly every row early in the season. | Information | Replaced by "Chance of 20+" on the board, cards and team page. Since retired everywhere: the label graded range *width* and called it evidence, so the player page and Compare now say what the range is based on, and the sort option is gone (`docs/simulation-readiness.md`, "Range evidence"). |
| The draft pages showed the global Half PPR scoring above their own PPR setting. | Clarity | Fixed. The global controls are hidden on the draft pages, which never read them. |

## Page by page

Each entry: **purpose** · what the reader needs first · what was wrong · what changed.

### Dashboard
**Purpose:** what should I do before lineups lock. **Needs first:** my lineup, anything wrong with it, the next step.
**Was:** league-wide panels only. The schedule and an empty "Easiest matchups" card filled the top half. The one action (simulate) was at the bottom, and the model run appeared as `shrinkage_eb v1.0.0 · run 145`.
**Now:** *Your lineup for week N* comes first. It shows the projected total (skill positions only, stated beside the number), anyone ruled out, starters carrying a designation, empty slots and players with no projection. It also shows **your closest call** (the smallest gap between a starter and an eligible bench player, offered as "Compare them", not as a verdict) and a primary **Estimate my chance of winning** that opens the simulation with the lineup filled in. With no roster it becomes an invitation to add one. "Easiest matchups" collapses to one sentence when nothing is graded yet. The schedule moves last. "0 completed" became "Results recorded for 0 so far", because the count reflects loaded results, not the league (Live already showed ATL–GB final). The model line reads "Projections from model run 145, published Tue, Sep 22".

### Rankings (merged with Players)
**Purpose:** who to start, and how everyone compares. **Needs first:** rank, projection, range, chance of a big week.
**Was:** two near-identical boards. Players had a team filter and a position dropdown. Rankings had position tabs and tiers. Readers had to learn which page had which filter.
**Now:** one board at `/rankings` with position tabs, a team filter, search, sort and a table/cards toggle. Team filtering keeps each player's league-wide rank ("DET WR rankings" shows St. Brown as WR2, Williams as WR43). `/players?position=RB&team=KC` redirects to `/rankings/rb?team=KC`, so old links and bookmarks keep working. Player pages stay at `/players/:id`. The sidebar loses an entry, and My team takes the freed slot in the five-item mobile bar. The board also has field-strip ranges, Chance of 20+, sentence-case headers and a latest-week action when empty.

### Player page
**Purpose:** should I trust this projection. **Needs first:** projection, range, risk, and what to do with it.
**Was:** thorough but action-less, and the range used a different drawing from every other page.
**Now:** **Add to my team** (updates the remembered roster without rewriting the player's link) and **Compare**. The range is the same field strip at a larger size. The actions wrap to their own row on a phone, where they had squeezed the name into a one-word column.

### Matchups → game page
**Purpose:** who benefits from this game. **Was:** "Too few games to grade" eight times, and the player list scrolled inside a clipped card.
**Now:** ungraded rows show the fact that exists: "29.2 pts/gm allowed over 2 games, too few to grade". The list shows 12 players with "Show all N" instead of an inner scrollbar.

### Teams → team page
**Now:** Chance of 20+ replaces Confidence, and the range column is wider.

### Injuries, Usage trends
**Now:** the irrelevant grading banner is gone.
**Usage:** 9 of the top 25 "rising snap share" rows were quarterbacks, backups who started one game. A quarterback's snap share is all or nothing, so a jump means a change of starter, not a growing role. Quarterbacks now appear under the QB tab rather than in All, and the page says so. A projection threshold was considered and rejected: the low-projected risers (Olszewski 26%→84%, Granson 33%→77%) are exactly the waiver targets the page is for, because their projection is built from the four-game average and has not caught up with the new role.

### Simulation
**Purpose:** do I win. **Strong already:** the headline estimated win probability, positional edges, swing players and reproducibility.
**Was:** three blue alert boxes under the result, the third repeating the assumptions panel further down.
**Now:** every notice is still shown, each once. The headline carries one sentence built from the structured assumption flags ("covers QB, RB, WR and TE only…, simulates each player's score on its own and does not adjust for injury designations"), with a link to the panel. Notes about each lineup's own players (stacks, designations, same-game pairs) sit in one "About these lineups" card, split by side. The engine's run-wide notes appear verbatim at the end of the assumptions panel. The total-mismatch warning was rewritten in plain words ("Why the two totals above differ") with the same substance.

### My team
**Now:** a primary **Estimate my chance of winning**. The lineup logic moved into a shared `useMyLineup` hook, so the dashboard and My team cannot disagree about who starts.

### Compare, Trade, Live, Track record, Settings, Mock draft, Draft board, 404
- **Compare:** already strong, and reachable in one click from the dashboard's closest call and the player page.
- **Trade:** clear empty state. Future: offer "from your team" for the "You give" side.
- **Live:** clear. It is the only screen with same-day results.
- **Track record:** the by-position table was clipped behind a horizontal scroll in a half-width card. It now stacks below 2xl.
- **Settings:** the model card showed four scalars and nothing about how the model was validated. It now states, in plain words from `/meta/model`, **how this model was checked** and **what a replacement must prove**, including that the baseline comparison uses the same seasons.
- **Mock draft / Draft board:** global controls hidden (see above).
- **404:** fine.

### States
- **Loading:** skeletons match the layout. The week picker no longer claims "No weeks yet" while loading.
- **Error:** the outage path is fixed (above). Per-panel errors already had retries.
- **Empty:** every empty state names why and, where there is one, the way out.
- **Partial data:** unpublished weeks, ungraded matchups, unprojected rostered players and ruled-out players are each named where they apply.

## Verification

- Backend: 1,099 unit tests pass (11 new for the challenger, 9 for acceptance edge cases).
- Frontend: build, lint, token contrast in both themes, and the 51-check API contract pass.
- End to end, against the local app: 159 passed, 0 failed, 17 skipped. That includes a new test pinning the `/players` redirect. The scoring-profile test that failed on the original code was a race in the test (it read the request log once the network went idle, which can happen before the re-render fires the new request). It now waits for the request itself. The app was re-requesting correctly all along.

## Assumptions
- The pasted brief referred to an "LLM prompt used in the Challenger step". There is no LLM anywhere in this codebase. The challenger is a LightGBM model, so the work targeted its evaluation and the `ACCEPTANCE` check.
- "Closest call" uses the headline projection gap. It is presented as a pair to compare, never a recommendation.
- A roster is per browser, as before. No persistence was added.

## Future iterations
1. Cut the sidebar further, from 13 items to about 5 job-based entries (This week, My team, Rankings, Matchups, Behind the numbers), keeping every page reachable.
2. Trade: pre-fill "You give" from the roster.
3. The lineup builder accepts a share link that puts a player in a slot their position cannot fill (e.g. a WR at QB). The API rejects the run, but the builder should flag it first.
4. Header casing: several tables still use ALL-CAPS column labels (My team, Teams, Usage, Track record); move them to one table-header component.
5. `npm run test:e2e` defaults to the production URL. Consider defaulting to local and requiring an explicit flag for production.
