import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

import { settle } from './helpers'

/**
 * Phase 8 accessibility pass.
 *
 * Two halves. `axe` catches the rule violations a machine can see — contrast,
 * names, roles, landmark structure. The rest of the file covers what it cannot:
 * whether focus goes somewhere sensible on navigation, whether Escape closes
 * what it opened, whether a keyboard alone can reach the primary action.
 *
 * Everything here runs against the deployed build with real data, because half
 * of these rules are about rendered colour and computed names — properties a
 * mocked fixture would answer for a screen nobody is actually shipping.
 */

const ROUTES = [
  { path: '/', name: 'dashboard' },
  { path: '/rankings', name: 'rankings (all)' },
  { path: '/rankings/rb', name: 'rankings (RB)' },
  { path: '/players', name: 'players' },
  { path: '/matchups', name: 'matchups' },
  { path: '/simulation', name: 'simulation' },
  { path: '/compare', name: 'compare' },
  { path: '/settings', name: 'settings' },
  { path: '/no-such-page', name: '404' },
]

/** Waits for the view to have real content rather than a skeleton. */

async function analyze(page: Page) {
  return new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
}

/** A readable one-line-per-violation summary; the raw axe dump is unusable. */
function summarize(violations: Awaited<ReturnType<typeof analyze>>['violations']) {
  return violations
    .map(
      (v) =>
        `\n[${v.impact}] ${v.id}: ${v.help}\n` +
        v.nodes
          .slice(0, 4)
          .map((n) => `    ${n.target.join(' ')}\n      ${n.failureSummary?.replace(/\n/g, '\n      ')}`)
          .join('\n'),
    )
    .join('\n')
}

for (const route of ROUTES) {
  test(`axe: ${route.name}`, async ({ page }) => {
    await page.goto(route.path)
    await settle(page)

    const { violations } = await analyze(page)
    expect(violations, summarize(violations)).toEqual([])
  })
}

test('every page has exactly one h1', async ({ page }) => {
  const offenders: string[] = []
  for (const route of ROUTES) {
    await page.goto(route.path)
    await settle(page)
    const count = await page.locator('h1').count()
    if (count !== 1) offenders.push(`${route.path} -> ${count}`)
  }
  expect(offenders, `routes whose <h1> count is not 1: ${offenders.join(', ')}`).toEqual([])
})

test('heading levels are not skipped', async ({ page }) => {
  const offenders: string[] = []
  for (const route of ROUTES) {
    await page.goto(route.path)
    await settle(page)
    const levels = await page.evaluate(() =>
      [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map((h) => Number(h.tagName[1])),
    )
    for (let i = 1; i < levels.length; i++) {
      if (levels[i] - levels[i - 1] > 1) {
        offenders.push(`${route.path}: h${levels[i - 1]} -> h${levels[i]}`)
        break
      }
    }
  }
  expect(offenders, `skipped heading levels: ${offenders.join(', ')}`).toEqual([])
})

test('the skip link is the first tab stop and moves focus to main', async ({ page }) => {
  await page.goto('/rankings')
  await settle(page)

  await page.keyboard.press('Tab')
  const skip = page.locator('a.skip-link')
  await expect(skip).toBeFocused()
  // A skip link that is invisible when focused helps nobody.
  await expect(skip).toBeInViewport()

  await page.keyboard.press('Enter')
  await expect(page.locator('#main')).toBeFocused()
})

test('route change moves focus to main and announces the new page', async ({ page }) => {
  await page.goto('/')
  await settle(page)

  await page.getByRole('link', { name: 'Rankings', exact: true }).first().click()
  await expect(page).toHaveURL(/\/rankings/)
  await settle(page)

  await expect(page.locator('#main')).toBeFocused()
  // RouteChrome's own region, not the several other polite ones on the page
  // (the board's result count keeps one of its own).
  await expect(page.locator('[aria-live="polite"][aria-atomic="true"]').first()).toContainText(
    /rankings, page loaded/i,
  )
})

test('every focusable control has a visible focus indicator', async ({ page }) => {
  await page.goto('/rankings')
  await settle(page)

  // Sample the interactive controls in the chrome and toolbar rather than all
  // 348 rows, which would take minutes and exercise one identical component.
  const controls = page.locator(
    'main button:visible, main a:visible, main select:visible, main input:visible',
  )
  const total = Math.min(await controls.count(), 25)

  const invisible: string[] = []
  for (let i = 0; i < total; i++) {
    const control = controls.nth(i)
    await control.focus()
    const style = await control.evaluate((el) => {
      const s = getComputedStyle(el)
      return { outlineWidth: s.outlineWidth, outlineStyle: s.outlineStyle, boxShadow: s.boxShadow }
    })
    const hasOutline = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0
    const hasRing = style.boxShadow !== 'none' && style.boxShadow !== ''
    if (!hasOutline && !hasRing) {
      invisible.push(await control.evaluate((el) => el.outerHTML.slice(0, 110)))
    }
  }
  expect(invisible, `controls with no focus indicator:\n${invisible.join('\n')}`).toEqual([])
})

test('the primary simulation action is reachable and operable by keyboard alone', async ({ page }) => {
  await page.goto('/simulation')
  await settle(page)

  const run = page.getByRole('button', { name: /run simulation/i })
  await expect(run).toBeVisible()
  // Correctly disabled while both lineups are empty — a disabled control is
  // not a tab stop, so it has to be made runnable before reachability means
  // anything. Both sides, because the run needs two teams.
  await expect(run).toBeDisabled()

  // Autofill stays disabled until the board arrives — it picks from it.
  const autofills = page.getByRole('button', { name: /autofill/i })
  await expect(autofills).toHaveCount(2)
  for (let i = 0; i < 2; i++) {
    await expect(autofills.nth(i)).toBeEnabled()
    await autofills.nth(i).click()
  }
  await expect(run).toBeEnabled()

  let reached = false
  for (let i = 0; i < 120 && !reached; i++) {
    await page.keyboard.press('Tab')
    reached = await run.evaluate((el) => el === document.activeElement)
  }
  expect(reached, 'Run simulation was not reachable by Tab once enabled').toBe(true)

  // And operable from the keyboard, not just focusable.
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: /simulating/i })).toBeVisible()
})

test('form controls all have accessible names', async ({ page }) => {
  const offenders: string[] = []
  for (const path of ['/rankings', '/players', '/simulation', '/compare', '/settings']) {
    await page.goto(path)
    await settle(page)

    const unnamed = await page.evaluate(() => {
      const out: string[] = []
      for (const el of document.querySelectorAll<HTMLElement>(
        'input:not([type=hidden]), select, textarea',
      )) {
        if (el.offsetParent === null) continue
        const id = el.id
        const named =
          el.getAttribute('aria-label') ||
          el.getAttribute('aria-labelledby') ||
          el.getAttribute('title') ||
          (id && document.querySelector(`label[for="${CSS.escape(id)}"]`)) ||
          el.closest('label')
        if (!named) out.push(el.outerHTML.slice(0, 110))
      }
      return out
    })
    offenders.push(...unnamed.map((u) => `${path}: ${u}`))
  }
  expect(offenders, `unlabelled form controls:\n${offenders.join('\n')}`).toEqual([])
})

test('tooltips are never clipped by a scrolling or rounded ancestor', async ({ page }) => {
  // The board is the hard case: its chips sit inside an `overflow-x-auto`
  // table wrapper, inside a Card that clips its own corners, under a nav that
  // does the same. An absolutely-positioned bubble loses its first characters
  // to any one of them.
  await page.goto('/rankings')
  await settle(page)

  const triggers = page.locator('[aria-describedby], span[tabindex="0"]')
  const total = Math.min(await triggers.count(), 14)
  expect(total, 'expected tooltip triggers on the board').toBeGreaterThan(0)

  const clipped: string[] = []
  for (let i = 0; i < total; i++) {
    const trigger = triggers.nth(i)
    if (!(await trigger.isVisible())) continue
    await trigger.scrollIntoViewIfNeeded()
    await trigger.hover()

    const bubble = page.locator('[role="tooltip"]')
    if ((await bubble.count()) === 0) continue
    await expect(bubble.first()).toBeVisible()

    const verdict = await bubble.first().evaluate((tip) => {
      const r = tip.getBoundingClientRect()
      const vw = document.documentElement.clientWidth
      const vh = document.documentElement.clientHeight
      if (r.left < -0.5 || r.right > vw + 0.5 || r.top < -0.5 || r.bottom > vh + 0.5) {
        return `outside the viewport: ${JSON.stringify({ left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), vw })}`
      }
      // And not cut off by anything between it and the document.
      for (let el = tip.parentElement; el; el = el.parentElement) {
        const s = getComputedStyle(el)
        if (s.overflowX === 'visible' && s.overflowY === 'visible') continue
        const e = el.getBoundingClientRect()
        if (r.left < e.left - 0.5 || r.right > e.right + 0.5 || r.top < e.top - 0.5 || r.bottom > e.bottom + 0.5) {
          return `clipped by ${el.tagName}.${String(el.className).split(' ').slice(0, 2).join('.')}`
        }
      }
      return null
    })
    if (verdict) clipped.push(`${i}: ${verdict}`)

    // Move away so the next hover starts clean.
    await page.mouse.move(0, 0)
  }

  expect(clipped, `clipped tooltips:\n${clipped.join('\n')}`).toEqual([])
})
