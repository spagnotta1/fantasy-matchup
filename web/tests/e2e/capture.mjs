/**
 * Not a test — a look.
 *
 * Opens the app in a visible browser and photographs a set of routes at three
 * widths in both themes, so a change to a token or a primitive can be judged
 * with eyes rather than only with assertions. Alongside each picture it
 * reports what a picture hides: sideways overflow, console errors, failed
 * requests.
 *
 *   node tests/e2e/capture.mjs <baseURL> [--out dir] [--routes a,b] [--route "c?x=1,2"] [--headless]
 *                              [--themes light,dark] [--widths desktop,tablet,phone,1024,360]
 *                              [--roster id,id,id] [--press "Run simulation"] [--fold]
 *
 * `--press` clicks the button of that name once the page has loaded and waits
 * for what it started, for a screen that only exists after an action: a
 * finished simulation, from a matchup link (`--route "simulation?a=…&b=…"`).
 * `--fold` also saves the first screenful (`<name>.fold.png`), taken where the
 * page was left, for judging what a reader sees without scrolling. Every line
 * prints the page's height.
 *
 * The browser is headed by default, on purpose: the point is to watch the
 * pages load. `--headless` is for a quick re-run. See the `frontend-verify`
 * skill for where this sits in the sequence.
 */
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium, devices } from '@playwright/test'

const args = process.argv.slice(2)
const flag = (name) => {
  const index = args.indexOf(`--${name}`)
  return index === -1 ? undefined : args[index + 1]
}
const baseURL = args.find((arg) => /^https?:/.test(arg)) ?? 'http://localhost:5173'
const outDir = flag('out') ?? 'test-results/capture'
const headless = args.includes('--headless')

/** The screens a foundation change is judged on, plus the workbench. */
const DEFAULT_ROUTES = [
  '/',
  '/rankings/rb',
  '/draft-board',
  '/my-team',
  '/simulation',
  '/reports/usage',
  '/track-record',
  '/specimens',
]
// The leading slash is optional. Git Bash rewrites an argument that starts
// with one into a Windows path (`/specimens` arrives as
// `C:/Program Files/Git/specimens`), so from that shell write
// `--routes specimens,draft-board`.
//
// `--routes` splits on commas, so a route that holds one — a roster or a
// comparison in the query string — goes in its own `--route`, which may be
// repeated: `--route "my-team?roster=a,b,c"`.
const named = [
  ...(flag('routes')?.split(',') ?? []),
  ...args.flatMap((arg, index) => (arg === '--route' && args[index + 1] ? [args[index + 1]] : [])),
]
const routes = named.length ? named.map((route) => (route.startsWith('/') ? route : `/${route}`)) : DEFAULT_ROUTES

const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 } },
  tablet: { viewport: { width: 820, height: 1180 }, hasTouch: true },
  // Device metrics and touch, at one device pixel per CSS pixel: the layout is
  // what is under review, and a 2.6x picture of it is seven times the bytes.
  phone: { ...devices['Pixel 7'], deviceScaleFactor: 1 },
}
// A width may also be a number of CSS pixels (`--widths 1024,768,360`), for
// the widths between the three named ones: a laptop with the sidebar open, a
// small tablet, a narrow phone. Touch below the sidebar's 1,024px, as there.
const viewportFor = (width) =>
  VIEWPORTS[width] ?? { viewport: { width: Number(width), height: 900 }, hasTouch: Number(width) < 1024 }
const widths = flag('widths')?.split(',') ?? Object.keys(VIEWPORTS)
const themes = flag('themes')?.split(',') ?? ['light', 'dark']
// Seeds My team, for the screens that read it: `--roster id,id,id`.
const roster = flag('roster')?.split(',') ?? null
const press = flag('press') ?? null
const fold = args.includes('--fold')

// A file name from a route. A matchup link is two lineups long and holds
// colons, which Windows will not have in a name: cut at the first 40
// characters, which is the page and the start of what it was asked for.
const slug = (route) => route.replace(/^\//, '').replace(/[/?=&,:]+/g, '-').slice(0, 40).replace(/-$/, '') || 'home'

mkdirSync(outDir, { recursive: true })
const browser = await chromium.launch({ headless })
let problems = 0

for (const width of widths) {
  for (const theme of themes) {
    const context = await browser.newContext({ ...viewportFor(width), baseURL })
    await context.addInitScript(
      ([chosen, ids]) => {
        window.localStorage.setItem('nflfp.theme', chosen)
        if (ids) window.localStorage.setItem('nflfp.roster', JSON.stringify(ids))
      },
      [theme, roster],
    )
    const page = await context.newPage()
    const errors = []
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text().slice(0, 160))
    })
    page.on('pageerror', (error) => errors.push(`PAGEERROR ${error.message}`.slice(0, 160)))

    for (const route of routes) {
      errors.length = 0
      await page.goto(route, { waitUntil: 'networkidle', timeout: 60_000 }).catch((error) => {
        errors.push(`NAV ${error.message.split('\n')[0]}`)
      })
      await page.locator('main [role="status"]').first().waitFor({ state: 'detached', timeout: 30_000 }).catch(() => {})
      await page.evaluate(() => document.fonts.ready)

      if (press) {
        const button = page.getByRole('button', { name: press, exact: true }).first()
        if ((await button.count()) > 0 && (await button.isEnabled())) {
          await button.click()
          await page.waitForLoadState('networkidle', { timeout: 60_000 }).catch(() => {})
          await page.locator('main [aria-live="polite"] .animate-indeterminate').waitFor({ state: 'detached', timeout: 60_000 }).catch(() => {})
          // The page scrolls to what the press produced; let it arrive.
          await page.waitForTimeout(1200)
        } else {
          errors.push(`PRESS no enabled "${press}" button`)
        }
      }

      const overflow = await page.evaluate(() => {
        const doc = document.documentElement
        return doc.scrollWidth - doc.clientWidth
      })
      const height = await page.evaluate(() => document.documentElement.scrollHeight)
      // What is too wide, not only that something is: the innermost elements
      // that reach past the screen, which is where the fix goes.
      const culprits =
        overflow > 0
          ? await page.evaluate(() => {
              const edge = document.documentElement.clientWidth + 1
              const past = (element) => element.getBoundingClientRect().right > edge
              return [...document.querySelectorAll('main *')]
                .filter((element) => past(element) && ![...element.children].some(past))
                .slice(0, 3)
                .map(
                  (element) =>
                    `<${element.tagName.toLowerCase()} class="${String(element.getAttribute('class') ?? '').slice(0, 70)}"> "${(element.textContent ?? '').trim().slice(0, 32)}"`,
                )
            })
          : []
      const file = join(outDir, `${slug(route)}.${width}.${theme}.png`)
      // The first screenful before the full page: a full-page capture is free
      // to move the scroll position.
      if (fold) await page.screenshot({ path: file.replace(/\.png$/, '.fold.png'), animations: 'disabled' })
      await page.screenshot({ path: file, fullPage: true, animations: 'disabled' })

      const notes = [
        overflow > 0 ? `OVERFLOW-X ${overflow}px\n        ${culprits.join('\n        ')}` : null,
        errors.length ? `CONSOLE ${JSON.stringify(errors.slice(0, 3))}` : null,
      ].filter(Boolean)
      if (notes.length) problems += 1
      console.log(`${notes.length ? '!!' : 'ok'}  ${width.padEnd(7)} ${theme.padEnd(5)} ${String(height).padStart(5)}px ${route.slice(0, 40).padEnd(18)} ${file}${notes.length ? `\n      ${notes.join('\n      ')}` : ''}`)
    }
    await context.close()
  }
}

await browser.close()
console.log(`\n${routes.length * widths.length * themes.length} pictures in ${outDir}; ${problems} with something to look at.`)
process.exit(problems === 0 ? 0 : 1)
