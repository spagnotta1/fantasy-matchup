import { expect, test } from '@playwright/test'

import { openSlateControls, settle } from './helpers'

/**
 * Phase 8 real-data UX.
 *
 * Every season the warehouse holds is fully published, so the interesting
 * states — no published week, a slow API, a partial slate — cannot be reached
 * by clicking. They are the states a user hits during a bad week, though, so
 * the responses are mocked at the network boundary and the real UI is left to
 * render them. K and DST need no mocking: the API genuinely refuses them.
 */


test('a position the model does not project explains itself instead of erroring', async ({ page }) => {
  await page.goto('/rankings/k')
  await settle(page)

  const main = page.locator('main')
  // The API refuses K with a long operator-facing rationale. The user gets an
  // explanation, not a stack trace and not a silent empty board.
  await expect(main).toContainText(/not projected|not yet|kicker/i)
  await expect(main).not.toContainText(/invalid_request|422|traceback/i)

  // And the rest of the board is still reachable from here.
  await expect(page.getByRole('link', { name: /^RB$/ }).or(page.getByRole('tab', { name: /^RB$/ })).first()).toBeVisible()
})

test('DST is handled the same way', async ({ page }) => {
  await page.goto('/rankings/dst')
  await settle(page)
  await expect(page.locator('main')).toContainText(/not projected|not yet|defen/i)
  await expect(page.locator('main')).not.toContainText(/invalid_request|traceback/i)
})

test('a deployment with nothing published says so rather than showing an empty board', async ({ page }) => {
  // An empty list, not a season carrying zero weeks. `/seasons` reports only
  // what is published and its contract states `published_weeks` is never
  // empty, so "nothing has been published" is the absence of the season —
  // mocking a season with no weeks would test a response the API cannot send.
  await page.route(/\/api\/v1\/seasons/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: [],
        meta: { window: null, scoring_profile: null, page: null, model: null, notices: [] },
      }),
    }),
  )

  await page.goto('/rankings')
  await settle(page)

  // The notice lives in the slate controls, which are behind a disclosure at
  // phone width — and it is rendered once per breakpoint copy of them.
  await openSlateControls(page)
  await expect(page.getByText(/no published weeks/i).filter({ visible: true }).first()).toBeVisible()
  // The claim must be about the data, never about a network failure.
  await expect(page.locator('main')).not.toContainText(/couldn't reach|offline/i)
})

test('an empty board for a published week names the reason', async ({ page }) => {
  await page.route(/\/api\/v1\/rankings\//, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: [],
        meta: { window: null, scoring_profile: 'half_ppr', page: null, model: null, notices: [] },
      }),
    }),
  )

  await page.goto('/rankings/rb')
  await settle(page)
  await expect(page.locator('main')).toContainText(/no board for this week|no model run/i)
})

test('a slow response shows a skeleton, never a blank screen', async ({ page }) => {
  await page.route(/\/api\/v1\/rankings\//, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 3000))
    await route.continue()
  })

  await page.goto('/rankings/rb', { waitUntil: 'commit' })

  // While it is in flight there is a loading affordance and a heading — the
  // page must never be an empty white rectangle.
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  const busy = page.locator('[class*="animate-shimmer"], [class*="animate-pulse"], [aria-busy="true"]')
  await expect(busy.first()).toBeVisible()

  await settle(page)
  await expect(page.locator('a[href^="/players/"]').first()).toBeVisible()
})

test('a network failure is reported in the user\'s terms with a retry', async ({ page }) => {
  let offline = true
  await page.route(/\/api\/v1\/rankings\//, (route) =>
    offline ? route.abort('internetdisconnected') : route.continue(),
  )

  await page.goto('/rankings/rb')
  await settle(page)

  const alert = page.getByRole('alert')
  await expect(alert).toBeVisible()
  await expect(alert).not.toContainText(/ERR_|net::|fetch failed/i)

  offline = false
  await alert.getByRole('button', { name: /try again/i }).click()
  await settle(page)
  await expect(page.locator('a[href^="/players/"]').first()).toBeVisible()
})

test('a player with no projection for the week does not break the detail view', async ({ page }) => {
  await page.goto('/rankings/rb')
  await settle(page)
  const href = await page.locator('a[href^="/players/"]').first().getAttribute('href')

  await page.route(/\/api\/v1\/projections\/[^/?]+/, (route) =>
    route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 'not_found',
        message: 'No published projection for this player and week.',
        field: null,
        remedy: null,
      }),
    }),
  )

  await page.goto(href!)
  await settle(page)

  // Either an explanatory empty state or an error state — but a rendered page
  // with the shell intact, not a crash boundary.
  await expect(page.locator('main')).toBeVisible()
  await expect(page.locator('main')).not.toContainText(/something went wrong.*reload/i)
  await expect(page.getByRole('link', { name: 'Rankings', exact: true }).first()).toBeVisible()
})

test('a large board renders fully and stays interactive', async ({ page }) => {
  await page.goto('/players')
  await settle(page)

  const links = await page.locator('a[href^="/players/"]').count()
  expect(links, 'the explorer should carry the whole slate').toBeGreaterThan(300)

  // Interaction after a big render must still be prompt.
  const search = page.getByLabel(/search/i).first()
  const started = Date.now()
  await search.fill('Jefferson')
  await expect(page.locator('a[href^="/players/"]')).not.toHaveCount(links)
  expect(Date.now() - started, 'filtering a full slate should feel immediate').toBeLessThan(4000)
})
