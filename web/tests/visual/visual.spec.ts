import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test, type Page } from '@playwright/test'

/**
 * Visual baselines for the screens a redesign is judged on.
 *
 * A token, a primitive or a table change touches every page, including the
 * ones nobody opened. These hold a picture of nine screens so that such a
 * change arrives as image diffs to approve, and a page that moved by accident
 * fails instead of shipping.
 *
 * ## Why the API is recorded
 *
 * The board changes every week and the forecast every hour. A screenshot of
 * live data fails on Tuesday for reasons that have nothing to do with the
 * code. So each screen's API traffic is recorded once into `fixtures/` and
 * replayed: the pictures move only when the frontend does. Nothing here needs
 * a backend to run.
 *
 * A request the recording does not hold is aborted, on purpose. A screen that
 * starts calling a new endpoint shows an error in its picture, and the fix is
 * to re-record, which is one command:
 *
 *     npm run test:visual:record     # needs the local API; refreshes fixtures and baselines
 *     npm run test:visual:record -- specimens draft-board
 *                                    # the same, for the named screens only
 *     npm run test:visual            # compare against the committed baselines
 *     npm run test:visual:update     # accept the current pictures as the new baselines
 *
 * ## What is deliberately not here
 *
 * Not every route and not every state. Fourteen screens, six of them also in
 * the dark theme, at one desktop and one phone width, and the five built on
 * the shared table at a tablet width too: the board, the player page and the
 * shell are where the redesign lands, and the rest share their parts. `specimens` is the workbench — every primitive in every state — and
 * `draft-board` is the first page built on the shared table.
 * Behaviour — a control that works, a state that explains itself — belongs in
 * `tests/e2e`, where it is asserted rather than photographed.
 *
 * And not touch sizing. A full-page capture in Chromium's phone emulation
 * drops `(pointer: coarse)` as it is taken, so the phone pictures show the
 * phone *layout* with mouse-sized controls: a 32px toolbar button, not the
 * 44px one a finger gets. They are consistent about it, so they still catch
 * what moved. That controls grow under a finger is asserted where it can be
 * measured, in `primitives.spec.ts` and `board.spec.ts`.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FIXTURES = path.join(HERE, 'fixtures')
const SUBJECTS_FILE = path.join(FIXTURES, 'subjects.json')
const RECORD = process.env.VISUAL_RECORD === '1'

/** Who and what the screens show, chosen from the board at record time. */
interface Subjects {
  /** The instant the fixtures were recorded; the page clock is pinned to it. */
  recordedAt: string
  playerId: string
  gameId: string
  team: string
  compare: string[]
  roster: string[]
}

interface BoardRow {
  projection: { player: { player_id: string; position: string | null }; game_id: string | null; team: string | null }
}

function loadSubjects(): Subjects {
  return JSON.parse(fs.readFileSync(SUBJECTS_FILE, 'utf8')) as Subjects
}

/** Picks the subjects from whatever the local API is serving. Record mode only. */
async function chooseSubjects(page: Page): Promise<Subjects> {
  const response = await page.request.get('/api/v1/projections?limit=1000')
  const board = ((await response.json()) as { data: BoardRow[] }).data
  const at = (position: string, count: number) =>
    board.filter((row) => row.projection.player.position === position).slice(0, count)
  const [lead] = at('RB', 1)
  if (!lead?.projection.game_id || !lead.projection.team) throw new Error('the board has no running back to show')
  return {
    recordedAt: new Date().toISOString(),
    playerId: lead.projection.player.player_id,
    gameId: lead.projection.game_id,
    team: lead.projection.team,
    compare: at('RB', 3).map((row) => row.projection.player.player_id),
    roster: [...at('QB', 2), ...at('RB', 4), ...at('WR', 5), ...at('TE', 2)].map(
      (row) => row.projection.player.player_id,
    ),
  }
}

let subjects: Subjects

test.beforeAll(async ({ browser }) => {
  // Recording some screens only must not move the others: they replay against
  // the players and the clock already on file.
  if (!RECORD || process.env.VISUAL_KEEP_SUBJECTS === '1') {
    subjects = loadSubjects()
    return
  }
  fs.mkdirSync(FIXTURES, { recursive: true })
  // Both viewports replay one recording of who is on screen. The desktop
  // project records it; the phone project, which runs after, reads it back.
  if (fs.existsSync(SUBJECTS_FILE) && Date.now() - fs.statSync(SUBJECTS_FILE).mtimeMs < 10 * 60 * 1000) {
    subjects = loadSubjects()
    return
  }
  const page = await browser.newPage({ baseURL: test.info().project.use.baseURL })
  subjects = await chooseSubjects(page)
  await page.close()
  fs.writeFileSync(SUBJECTS_FILE, `${JSON.stringify(subjects, null, 2)}\n`)
})

interface Screen {
  name: string
  path: (subjects: Subjects) => string
  /** Seed My team, for screens that read it. */
  roster?: boolean
  /** The first screenful only, for a page too long to be worth a full picture. */
  foldOnly?: boolean
  /** Also photographed in the dark theme. */
  dark?: boolean
  /**
   * Also photographed at 820px. For the screens whose table changes shape
   * between a laptop and a phone: it scrolls inside its frame, or folds its
   * rows. The rest look at 820px as they do at 1440px, only narrower.
   */
  tablet?: boolean
}

const SCREENS: Screen[] = [
  { name: 'dashboard', path: () => '/', roster: true, dark: true },
  { name: 'rankings', path: () => '/rankings/rb', foldOnly: true, dark: true },
  { name: 'player', path: (s) => `/players/${s.playerId}`, dark: true },
  { name: 'game', path: (s) => `/matchups/${s.gameId}` },
  { name: 'team', path: (s) => `/teams/${s.team}`, tablet: true },
  { name: 'my-team', path: () => '/my-team', roster: true, tablet: true },
  // The first screenful: a full week is a hundred rows of the same row.
  { name: 'live', path: () => '/live', roster: true, foldOnly: true, dark: true, tablet: true },
  { name: 'usage', path: () => '/reports/usage', tablet: true },
  { name: 'injuries', path: () => '/reports/injuries', dark: true, tablet: true },
  { name: 'compare', path: (s) => `/compare?players=${s.compare.join(',')}` },
  { name: 'simulation', path: () => '/simulation', roster: true },
  { name: 'track-record', path: () => '/track-record' },
  { name: 'draft-board', path: () => '/draft-board' },
  { name: 'specimens', path: () => '/specimens', dark: true },
]

async function open(page: Page, screen: Screen, theme: 'light' | 'dark') {
  const project = test.info().project.name
  // One recording per screen and viewport: a phone asks for different things
  // than a desktop does, and a screen can be re-recorded without the others.
  const archive = path.join(FIXTURES, `${screen.name}-${theme}.${project}.zip`)

  // Headshots and team logos come from other hosts. They are not the app's to
  // control, so they are left out: avatars fall back to initials, identically
  // on every run.
  await page.route(
    (url) => !['localhost', '127.0.0.1'].includes(url.hostname),
    (route) => route.abort(),
  )
  await page.routeFromHAR(archive, {
    url: '**/api/v1/**',
    update: RECORD,
    notFound: 'abort',
  })
  await page.clock.setFixedTime(new Date(subjects.recordedAt))
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(
    ([chosenTheme, roster]) => {
      window.localStorage.setItem('nflfp.theme', chosenTheme as string)
      if (roster) window.localStorage.setItem('nflfp.roster', JSON.stringify(roster))
    },
    [theme, screen.roster ? subjects.roster : null] as const,
  )

  await page.goto(screen.path(subjects))
  await page.waitForLoadState('networkidle')
  await expect(page.locator('main')).toBeVisible()
  await expect(page.locator('main [role="status"]')).toHaveCount(0)
  await page.evaluate(() => document.fonts.ready)
}

for (const screen of SCREENS) {
  for (const theme of ['light', 'dark'] as const) {
    if (theme === 'dark' && !screen.dark) continue

    test(`${screen.name}, ${theme}`, async ({ page }) => {
      test.skip(test.info().project.name === 'visual-tablet' && !screen.tablet, 'not photographed at tablet width')
      await open(page, screen, theme)
      // Recording writes the archive when this test's browser context closes;
      // the picture is taken by the comparison run that follows.
      if (RECORD) return
      await expect(page).toHaveScreenshot(`${screen.name}-${theme}.png`, {
        fullPage: !screen.foldOnly,
        animations: 'disabled',
        // A budget in pixels, not a ratio. On a 1440px full-page picture a
        // ratio of 0.2% is four thousand pixels, which is more than every card
        // corner on the page: a radius change passed under it. Fifty pixels
        // absorbs a stray antialiased glyph edge and nothing designed.
        maxDiffPixels: 50,
        // How different one pixel must be to count. The default (0.2) is
        // tuned for photographs; this product is white cards on a paper ground
        // one step darker, and at 0.2 a card corner going from 14px to 4px
        // changed 2,401 pixels and counted none of them.
        threshold: 0.03,
      })
    })
  }
}
