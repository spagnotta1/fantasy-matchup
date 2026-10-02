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
 *                              [--roster id,id,id]
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

const slug = (route) => route.replace(/^\//, '').replace(/[/?=&,]+/g, '-') || 'home'

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

      const overflow = await page.evaluate(() => {
        const doc = document.documentElement
        return doc.scrollWidth - doc.clientWidth
      })
      const file = join(outDir, `${slug(route)}.${width}.${theme}.png`)
      await page.screenshot({ path: file, fullPage: true, animations: 'disabled' })

      const notes = [
        overflow > 0 ? `OVERFLOW-X ${overflow}px` : null,
        errors.length ? `CONSOLE ${JSON.stringify(errors.slice(0, 3))}` : null,
      ].filter(Boolean)
      if (notes.length) problems += 1
      console.log(`${notes.length ? '!!' : 'ok'}  ${width.padEnd(7)} ${theme.padEnd(5)} ${route.padEnd(18)} ${file}${notes.length ? `\n      ${notes.join('\n      ')}` : ''}`)
    }
    await context.close()
  }
}

await browser.close()
console.log(`\n${routes.length * widths.length * themes.length} pictures in ${outDir}; ${problems} with something to look at.`)
process.exit(problems === 0 ? 0 : 1)
