/**
 * Not a test — a reconnaissance pass.
 *
 * Visits every route at two widths and reports what actually rendered: the
 * heading, console errors, failed requests, horizontal overflow, and how long
 * the view took to settle. Run it to find out what to assert, then assert it in
 * the spec files. `node tests/e2e/recon.mjs [baseURL]`
 */
import { chromium, devices } from '@playwright/test'

const baseURL = process.argv[2] ?? 'https://api-production-e5552.up.railway.app'

const ROUTES = [
  '/',
  '/rankings',
  '/rankings/rb',
  '/players',
  '/matchups',
  '/simulation',
  '/compare',
  '/settings',
  '/definitely-not-a-page',
]

const VIEWPORTS = [
  { name: 'desktop', viewport: { width: 1440, height: 900 }, isMobile: false },
  { name: 'mobile', ...devices['Pixel 7'] },
]

const browser = await chromium.launch()

for (const vp of VIEWPORTS) {
  const context = await browser.newContext(vp)
  console.log(`\n${'='.repeat(70)}\n${vp.name.toUpperCase()}  ${baseURL}\n${'='.repeat(70)}`)

  for (const route of ROUTES) {
    const page = await context.newPage()
    const consoleErrors = []
    const failedRequests = []
    const apiCalls = []

    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200))
    })
    page.on('pageerror', (e) => consoleErrors.push(`PAGEERROR: ${e.message}`.slice(0, 200)))
    page.on('requestfailed', (r) => failedRequests.push(`${r.url().slice(0, 100)} ${r.failure()?.errorText}`))
    page.on('response', (r) => {
      const u = new URL(r.url())
      if (u.pathname.startsWith('/api/')) apiCalls.push(`${r.status()} ${u.pathname}${u.search}`.slice(0, 120))
    })

    const started = Date.now()
    let status = 'ok'
    try {
      await page.goto(new URL(route, baseURL).href, { waitUntil: 'networkidle', timeout: 45_000 })
    } catch (e) {
      status = `NAV: ${e.message.split('\n')[0]}`
    }
    const elapsed = Date.now() - started

    const probe = await page.evaluate(() => {
      const text = (el) => (el?.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 90)
      const doc = document.documentElement
      return {
        title: document.title,
        h1: [...document.querySelectorAll('h1')].map(text),
        h2: [...document.querySelectorAll('h2')].map(text).slice(0, 6),
        // The whole-page horizontal overflow check Phase 8 asks about.
        overflowX: doc.scrollWidth - doc.clientWidth,
        // Any element wider than the viewport is the usual culprit behind it.
        widest: [...document.querySelectorAll('body *')]
          .filter((el) => el.getBoundingClientRect().width > doc.clientWidth + 1)
          .slice(0, 4)
          .map((el) => `${el.tagName}.${(el.className?.baseVal ?? el.className ?? '').toString().split(' ').slice(0, 3).join('.')} w=${Math.round(el.getBoundingClientRect().width)}`),
        landmarks: {
          main: !!document.querySelector('main'),
          nav: document.querySelectorAll('nav').length,
          h1count: document.querySelectorAll('h1').length,
        },
        bodyLen: document.body.innerText.length,
        // Empty/error/loading language, so recon says which state it caught.
        looksEmpty: /no results|nothing|not available|no data|unavailable/i.test(document.body.innerText),
        looksError: /something went wrong|error|failed|try again/i.test(document.body.innerText),
        skeletons: document.querySelectorAll('[class*="skeleton"],[class*="animate-pulse"]').length,
      }
    })

    console.log(`\n${route}  [${elapsed}ms] ${status !== 'ok' ? status : ''}`)
    console.log(`  title: ${probe.title}`)
    console.log(`  h1: ${JSON.stringify(probe.h1)}  (h1 count ${probe.landmarks.h1count}, nav ${probe.landmarks.nav}, main ${probe.landmarks.main})`)
    if (probe.h2.length) console.log(`  h2: ${JSON.stringify(probe.h2)}`)
    console.log(`  bodyLen=${probe.bodyLen} skeletons=${probe.skeletons} empty=${probe.looksEmpty} errorish=${probe.looksError}`)
    if (probe.overflowX > 0) console.log(`  !! OVERFLOW-X ${probe.overflowX}px  widest: ${JSON.stringify(probe.widest)}`)
    if (consoleErrors.length) console.log(`  !! CONSOLE: ${JSON.stringify(consoleErrors.slice(0, 4), null, 1)}`)
    if (failedRequests.length) console.log(`  !! REQFAIL: ${JSON.stringify(failedRequests.slice(0, 4))}`)
    if (apiCalls.length) console.log(`  api: ${JSON.stringify(apiCalls.slice(0, 8))}`)

    await page.close()
  }
  await context.close()
}

await browser.close()
