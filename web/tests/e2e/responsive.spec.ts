import { expect, test, type Page } from '@playwright/test'

import { settle } from './helpers'

/**
 * Phase 8 responsive QA.
 *
 * Runs at phone width only — at desktop these assertions are either trivially
 * true or meaningless, and running them there just doubles the time for no
 * signal.
 */

test.skip(({ isMobile }) => !isMobile, 'phone-width behaviour')

const ROUTES = ['/', '/rankings', '/rankings/rb', '/players', '/matchups', '/simulation', '/mock-draft', '/compare', '/settings']


/** How far the page scrolls sideways, and what is sticking out. */
function measureOverflow(page: Page) {
  return page.evaluate(() => {
    const doc = document.documentElement
    const offenders = [...document.querySelectorAll<HTMLElement>('body *')]
      .filter((el) => {
        const r = el.getBoundingClientRect()
        // Only elements that actually stick out past the right edge, and
        // that are not inside something designed to scroll sideways.
        if (r.right <= doc.clientWidth + 1) return false
        for (let p = el.parentElement; p; p = p.parentElement) {
          const o = getComputedStyle(p).overflowX
          if (o === 'auto' || o === 'scroll') return false
        }
        return true
      })
      .slice(0, 5)
      .map((el) => `${el.tagName}.${String(el.className).split(' ').slice(0, 3).join('.')} right=${Math.round(el.getBoundingClientRect().right)}`)
    return { scroll: doc.scrollWidth - doc.clientWidth, offenders }
  })
}

async function expectNoOverflow(page: Page) {
  const overflow = await measureOverflow(page)
  expect(
    overflow.scroll,
    `page scrolls horizontally by ${overflow.scroll}px. Offenders: ${overflow.offenders.join(' | ')}`,
  ).toBeLessThanOrEqual(0)
}

for (const route of ROUTES) {
  test(`no horizontal overflow: ${route}`, async ({ page }) => {
    await page.goto(route)
    await settle(page)
    await expectNoOverflow(page)
  })
}

// A game page and the draft board are reached by id or hold a wide table, so
// neither is in the list above. Both moved when secondary text grew from 12px
// to 13px: the game page's player list set its card wider than the screen, and
// the draft board is the first table that scrolls sideways on purpose — inside
// its own frame, never the page.
test('no horizontal overflow: a game page', async ({ page }) => {
  await page.goto('/matchups')
  await settle(page)
  const game = page.locator('main a[href^="/matchups/"]').first()
  await expect(game).toBeVisible()
  await game.click()
  await expect(page.getByRole('heading', { name: 'Projected players in this game' })).toBeVisible()
  await settle(page)
  await expectNoOverflow(page)
})

test('the draft board scrolls its table, not the page, and keeps the player column in view', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/draft-board')
  await settle(page)
  const frame = page.locator('[data-table-scrolls]')
  await expect(frame).toBeVisible({ timeout: 60_000 })
  await expectNoOverflow(page)

  // Every column is still there; the frame is what scrolls.
  await expect(frame.getByRole('columnheader', { name: /Per game × games/ })).toBeAttached()
  const first = frame.getByRole('rowheader').first()
  const before = await first.boundingBox()
  await frame.evaluate((el) => el.scrollTo({ left: 400 }))
  await expect.poll(() => frame.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0)
  const after = await first.boundingBox()
  expect(after?.x, 'the frozen player column should not move with the scroll').toBe(before?.x)
})

test('the mobile nav bar is present, fixed and holds the primary destinations', async ({ page }) => {
  await page.goto('/')
  await settle(page)

  const bar = page.locator('nav').filter({ has: page.getByRole('link', { name: /simulation/i }) }).last()
  await expect(bar).toBeVisible()

  const position = await bar.evaluate((el) => getComputedStyle(el).position)
  expect(position, 'the phone nav should stay put while the page scrolls').toBe('fixed')

  // Five destinations, per navigation.ts.
  await expect(bar.getByRole('link')).toHaveCount(5)
})

test('the mobile nav never covers the last row of content', async ({ page }) => {
  await page.goto('/rankings')
  await settle(page)

  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  await page.waitForTimeout(300)

  const clear = await page.evaluate(() => {
    const nav = [...document.querySelectorAll('nav')].find(
      (n) => getComputedStyle(n).position === 'fixed',
    )
    if (!nav) return { ok: true, detail: 'no fixed nav' }
    const navTop = nav.getBoundingClientRect().top
    // The last *rendered content*, not `main` itself — main carries the
    // bottom padding that does the clearing, so its own box is expected to
    // extend under the bar. What must not be under it is something readable.
    const main = document.querySelector('main')!
    let lowest = 0
    let culprit = 'none'
    for (const el of main.querySelectorAll<HTMLElement>('*')) {
      if (el.children.length > 0) continue
      const text = (el.textContent ?? '').trim()
      const r = el.getBoundingClientRect()
      if (!text || r.height === 0) continue
      if (r.bottom > lowest) {
        lowest = r.bottom
        culprit = `${el.tagName} "${text.slice(0, 30)}"`
      }
    }
    return {
      ok: lowest <= navTop + 1,
      detail: `lowest content ${culprit} ends at ${Math.round(lowest)}, nav starts at ${Math.round(navTop)}`,
    }
  })
  expect(clear.ok, `content runs under the fixed nav: ${clear.detail}`).toBe(true)
})

test('the board becomes cards rather than a squeezed table', async ({ page }) => {
  await page.goto('/rankings')
  await settle(page)

  await expect(page.locator('table')).toHaveCount(0)
  // And the whole board is still reachable, not a truncated slice: the first
  // paint is budgeted, the footer names the real total, and "Show all" draws it.
  await expect(page.getByText(/^Showing the top 100 of \d+ players\./)).toBeVisible()
  await page.getByRole('button', { name: /^Show all \d+$/ }).click()
  await expect(page.getByText(/^Showing all \d+ players\.$/)).toBeVisible()
  const links = await page.locator('a[href^="/players/"]').count()
  expect(links).toBeGreaterThan(100)
})

test('tap targets on the primary controls are at least 44px', async ({ page }) => {
  await page.goto('/simulation')
  await settle(page)

  const small = await page.evaluate(() => {
    const out: string[] = []
    const nav = [...document.querySelectorAll('nav')].find((n) => getComputedStyle(n).position === 'fixed')
    const targets = [
      ...(nav ? nav.querySelectorAll<HTMLElement>('a, button') : []),
      ...document.querySelectorAll<HTMLElement>('main button'),
    ]
    for (const el of targets) {
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) continue
      // 44x44 is the accepted floor; height is the one that usually fails.
      if (r.height < 44 && r.width < 44) out.push(`${el.tagName} "${(el.textContent ?? '').trim().slice(0, 24)}" ${Math.round(r.width)}x${Math.round(r.height)}`)
    }
    return out.slice(0, 10)
  })
  expect(small, `controls under 44px in both dimensions:\n${small.join('\n')}`).toEqual([])
})

test('the lineup builder and player search work at phone width', async ({ page }) => {
  await page.goto('/simulation')
  await settle(page)

  const autofills = page.getByRole('button', { name: /autofill/i })
  await expect(autofills.first()).toBeEnabled()
  await autofills.first().click()

  // A filled slot names a real player.
  await expect(page.locator('main')).toContainText(/QB|RB|WR|TE/)

  // The search field opens and returns results without leaving the viewport.
  const search = page.getByPlaceholder(/add /i).first()
  await search.click()
  await search.fill('Ma')
  const option = page.getByRole('option').first()
  await expect(option).toBeVisible()
  await expect(option).toBeInViewport()
})

test('the simulation controls and results stay usable at phone width', async ({ page }) => {
  await page.goto('/simulation')
  await settle(page)

  const autofills = page.getByRole('button', { name: /autofill/i })
  for (let i = 0; i < 2; i++) {
    await expect(autofills.nth(i)).toBeEnabled()
    await autofills.nth(i).click()
  }

  const run = page.getByRole('button', { name: /^run simulation$/i })
  await expect(run).toBeEnabled()
  await run.scrollIntoViewIfNeeded()
  await expect(run).toBeInViewport()
  await run.click()

  await expect(page.getByText(/%/).first()).toBeVisible({ timeout: 45_000 })

  // The distribution chart must fit the viewport rather than overflow it.
  const chart = page.locator('svg').last()
  await chart.scrollIntoViewIfNeeded()
  const fits = await chart.evaluate((el) => el.getBoundingClientRect().width <= document.documentElement.clientWidth + 1)
  expect(fits, 'the score distribution chart is wider than the phone viewport').toBe(true)
})

test('wide tables scroll inside their own container, not the page', async ({ page }) => {
  // The players explorer is the widest content in the product.
  await page.goto('/players')
  await settle(page)

  const pageScrolls = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(pageScrolls, 'the page body itself should never scroll sideways').toBeLessThanOrEqual(0)
})
