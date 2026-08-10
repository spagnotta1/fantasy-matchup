import { expect, test } from '@playwright/test'

import { openSlateControls, settle, slateSelect } from './helpers'

/**
 * Phase 8 product walkthrough.
 *
 * The path a real user takes — dashboard, board, player, matchup, simulation —
 * plus the two things a single-page app most often gets wrong: whether state
 * survives a reload, and whether a link someone sends actually reopens what
 * the sender was looking at.
 */

test('dashboard to rankings to player to matchup', async ({ page }) => {
  await page.goto('/')
  await settle(page)
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/week \d+/i)

  await page.getByRole('link', { name: 'Rankings', exact: true }).first().click()
  await settle(page)
  await expect(page).toHaveURL(/\/rankings/)

  // Into a player from the board. Match on the href rather than on scraped
  // text: the row and the card lay their text out differently, so the first
  // line is the name in one and the rank in the other.
  const firstPlayer = page.locator('a[href^="/players/"]').first()
  const href = await firstPlayer.getAttribute('href')
  await firstPlayer.click()
  await settle(page)
  await expect(page).toHaveURL(new RegExp(`${href}$`))
  await expect(page.getByRole('heading', { level: 1 })).not.toBeEmpty()

  await page.getByRole('link', { name: 'Matchups', exact: true }).first().click()
  await settle(page)
  await expect(page).toHaveURL(/\/matchups/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/matchups/i)
})

test('the slate selection is in the URL and survives a reload', async ({ page }) => {
  await page.goto('/rankings')
  await settle(page)

  // Change the week through the real control.
  //
  // By value, not by index, and only once the catalog has actually arrived.
  // `/seasons` decides which weeks exist, so until it resolves the control
  // holds a single placeholder option — selecting index 3 against that list
  // races the response and picks a different week on a slow run than a fast
  // one.
  await openSlateControls(page)
  const week = slateSelect(page, /^week$/i)
  await expect
    .poll(async () => week.locator('option').count(), { timeout: 20_000 })
    .toBeGreaterThan(3)

  const current = await week.inputValue()
  const target = (await week.locator('option').evaluateAll((options) =>
    options.map((o) => (o as HTMLOptionElement).value),
  )).find((value) => value !== current)!

  await week.selectOption(target)

  // Wait on the URL, not on `networkidle`. The selection is applied to the
  // query string by React, and the network can fall idle a frame before that
  // commit lands — which is how reading the control back here returned the
  // previous week under load while passing on an unloaded machine.
  await expect(page).toHaveURL(new RegExp(`week=${target}(&|$)`))
  await settle(page)

  const url = page.url()

  await page.reload()
  await settle(page)
  expect(page.url()).toBe(url)

  // The disclosure closes on reload, so reopen it before reading the control
  // back — and assert it holds the week the URL names, which is the actual
  // claim: the URL, not component state, is what restores the selection.
  await openSlateControls(page)
  await expect(slateSelect(page, /^week$/i)).toHaveValue(target)
})

test('a scoring profile change is reflected in the URL and the request', async ({ page }) => {
  const requests: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/')) requests.push(r.url())
  })

  await page.goto('/rankings/rb')
  await settle(page)

  await openSlateControls(page)
  await slateSelect(page, /^scoring$/i).selectOption('ppr')

  // Same reason as the week test: wait for the commit, not for the network.
  await expect(page).toHaveURL(/scoring=ppr/)
  await settle(page)
  expect(
    requests.some((u) => u.includes('scoring_profile=ppr')),
    'the board should be re-requested in the new scoring profile',
  ).toBe(true)
})

test('a deep link to a position board opens that board directly', async ({ page }) => {
  await page.goto('/rankings/wr')
  await settle(page)
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/wr/i)
  // And the board is actually WR, not the overall list.
  const positions = await page.locator('main').innerText()
  expect(positions).toMatch(/WR/)
})

test('an unknown route shows the 404 view rather than a blank page', async ({ page }) => {
  const response = await page.goto('/nope/not/a/route')
  // The SPA fallback serves index.html with a 200; the *view* is what 404s.
  expect(response?.status()).toBe(200)
  await settle(page)
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/doesn't exist/i)
  await page.getByRole('link', { name: /back to this week/i }).click()
  await settle(page)
  await expect(page).toHaveURL(/\/$/)
})

test('an API failure shows the error state with a working retry', async ({ page }) => {
  // Fail only the board request, so the shell still renders — this is the
  // realistic failure, not a total outage. It has to keep failing until the
  // user retries: the query client retries on its own, and a mock that fails
  // once is simply absorbed before anything reaches the screen.
  let failing = true
  await page.route(/\/api\/v1\/rankings\//, async (route) => {
    if (failing) return route.fulfill({ status: 500, contentType: 'application/json', body: '{"code":"internal"}' })
    return route.continue()
  })

  await page.goto('/rankings/rb')
  await settle(page)

  const alert = page.getByRole('alert')
  await expect(alert).toBeVisible()
  // Never a raw status code in front of a user.
  await expect(alert).not.toContainText(/500|internal server error/i)

  failing = false
  await alert.getByRole('button', { name: /try again/i }).click()
  await settle(page)
  await expect(page.locator('a[href^="/players/"]').first()).toBeVisible()
})

test('a search that matches nothing explains itself and offers a way out', async ({ page }) => {
  await page.goto('/rankings')
  await settle(page)

  await page.getByLabel(/search this board/i).fill('zzzzzznotaplayer')
  await expect(page.getByText(/no players match that search/i)).toBeVisible()

  // The toolbar's inline X carries the same name; the empty state's is the
  // one being tested, so scope to it.
  await page.getByRole('alert').or(page.locator('main')).getByRole('button', { name: /clear search/i }).last().click()
  await expect(page.locator('a[href^="/players/"]').first()).toBeVisible()
})

test('a full simulation runs and reports a result', async ({ page }) => {
  await page.goto('/simulation')
  await settle(page)

  const autofills = page.getByRole('button', { name: /autofill/i })
  await expect(autofills).toHaveCount(2)
  for (let i = 0; i < 2; i++) {
    await expect(autofills.nth(i)).toBeEnabled()
    await autofills.nth(i).click()
  }

  // Both lineups are now mirrored into the URL — this is the share link.
  expect(page.url()).toMatch(/a=|team_a=/)

  const run = page.getByRole('button', { name: /^run simulation$/i })
  await expect(run).toBeEnabled()
  await run.click()

  // A win probability, and the provenance the product is built around.
  await expect(page.getByText(/%/).first()).toBeVisible({ timeout: 45_000 })
  await expect(page.locator('main')).toContainText(/iterations|seed/i)
})

test('a shared matchup link rebuilds both lineups', async ({ page, context }) => {
  await page.goto('/simulation')
  await settle(page)

  const autofills = page.getByRole('button', { name: /autofill/i })
  for (let i = 0; i < 2; i++) {
    await expect(autofills.nth(i)).toBeEnabled()
    await autofills.nth(i).click()
  }
  const shared = page.url()
  const namesBefore = await page.locator('main').innerText()

  // A genuinely fresh tab, which is what the recipient of a link has.
  const other = await context.newPage()
  await other.goto(shared)
  await settle(other)

  const namesAfter = await other.locator('main').innerText()
  // The same players are on screen; compare a stable slice rather than the
  // whole page, which carries timestamps.
  const players = (text: string) => (text.match(/[A-Z]\.? ?[A-Za-z']+ ·/g) ?? []).slice(0, 8)
  expect(players(namesAfter)).toEqual(players(namesBefore))
  await other.close()
})

test('results offer a way back to the controls without scrolling the page', async ({ page }) => {
  await page.goto('/simulation')
  await settle(page)

  const autofills = page.getByRole('button', { name: /autofill/i })
  for (let i = 0; i < 2; i++) {
    await expect(autofills.nth(i)).toBeEnabled()
    await autofills.nth(i).click()
  }
  await page.getByRole('button', { name: /^run simulation$/i }).click()
  await expect(page.getByText(/%/).first()).toBeVisible({ timeout: 45_000 })

  const adjust = page.getByRole('button', { name: /adjust and run again/i })
  await adjust.scrollIntoViewIfNeeded()
  await expect(adjust).toBeVisible()
  await adjust.click()

  // The run control is back on screen and focus has followed, so the next Tab
  // lands in the controls rather than back in the results.
  await expect(page.getByRole('button', { name: /^run simulation$/i })).toBeInViewport()
  await expect(page.getByRole('button', { name: /^run simulation$/i })).toBeEnabled()
})
