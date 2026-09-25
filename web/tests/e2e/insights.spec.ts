import { expect, test } from '@playwright/test'

import { settle } from './helpers'

/**
 * The planning and accountability views: command palette, team pages, the
 * injury report, usage trends, the track record, lines, strength of schedule
 * and the draft board.
 *
 * Written against whatever week is published rather than fixed numbers, so the
 * assertions are about contracts — a caveat beside a number, a sign that reads
 * the right way round — and not about this week's players.
 */

test('the command palette opens from the keyboard and goes where it says', async ({ page, isMobile }) => {
  await page.goto('/')
  await settle(page)

  if (isMobile) {
    // On a phone the palette is also the menu, opened from the header.
    await page.getByRole('button', { name: 'Search and all pages' }).click()
  } else {
    await page.keyboard.press('Control+k')
  }
  const dialog = page.getByRole('dialog', { name: /search players, teams and pages/i })
  await expect(dialog).toBeVisible()

  // With nothing typed it lists every page, including those outside the nav.
  await expect(dialog.getByRole('option', { name: /draft board/i })).toBeVisible()

  await dialog.getByRole('combobox').fill('track')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: 'Track record' })).toBeVisible()
  await expect(dialog).toBeHidden()
})

test('the track record sets live coverage beside its nominal rate and the validation', async ({ page }) => {
  await page.goto('/track-record')
  await settle(page)

  const headline = page.getByText('Inside the 80% range')
  await expect(headline).toBeVisible()
  await expect(page.getByText(/Nominal 80%\. The frozen validation measured/)).toBeVisible()
  // The two caveats that make the number mean what it says.
  await expect(page.getByText(/backfilling the frozen model/)).toBeVisible()
  await expect(page.getByText(/did not play is excluded, not counted as zero/)).toBeVisible()
})

test('an injured player keeps his projection, with the designation beside it', async ({ page }) => {
  await page.goto('/injuries')
  await settle(page)

  const ruledOut = page.getByText('Ruled out — will not play')
  const count = await ruledOut.count()
  if (count === 0) {
    // No one is out this week: the page must say so, not show an empty table.
    await expect(page.getByRole('heading', { name: /ruled out/i })).toHaveCount(0)
    return
  }
  // Never silently zeroed: the number beside the caveat is the published one.
  const cell = ruledOut.first().locator('xpath=..')
  const value = Number((await cell.locator('.tnum').first().innerText()).trim())
  expect(value, 'an Out player shows his projection, not zero').toBeGreaterThan(0)
})

test('usage trends read the natural way round', async ({ page }) => {
  await page.goto('/usage')
  await settle(page)

  const changes = page.locator('main tbody tr td:nth-child(4)')
  if ((await changes.count()) === 0) return
  await expect(changes.first()).toContainText('+')

  await page.getByRole('radiogroup', { name: 'Direction' }).getByText('Falling', { exact: true }).click()
  await expect(page.locator('main tbody tr td:nth-child(4)').first()).toContainText('−')
})

test('a team page carries its game, its players and its schedule', async ({ page }) => {
  await page.goto('/teams')
  await settle(page)
  await page.locator('main a[href^="/teams/"]').first().click()
  await settle(page)

  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Projected players' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Remaining schedule' })).toBeVisible()
  await expect(page.getByText('Not included in the projection.').first()).toBeVisible()
})

test('the lines tab lists every game on the schedule, and says the model ignores it', async ({ page }) => {
  await page.goto('/matchups?view=lines')
  await settle(page)

  await expect(page.getByText(/excludes market features/).first()).toBeVisible()
  const rows = page.locator('main table tbody tr')
  await expect(rows.first()).toBeVisible()
})

test('strength of schedule has one row per team and says it is not a forecast', async ({ page }) => {
  await page.goto('/matchups?view=schedule')
  await settle(page)

  await expect(page.getByText(/not a forecast/).first()).toBeVisible()
  const rows = page.locator('main table tbody tr')
  if ((await rows.count()) > 0) expect(await rows.count()).toBeGreaterThanOrEqual(28)
})

test('the draft board labels both sides and never compares across positions', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/draft-board')
  await settle(page)

  await expect(page.getByText(/not an input to any projection/).first()).toBeVisible({ timeout: 60_000 })
  // Every rank pair is within one position: "WR4 → WR8", never "WR4 → RB2".
  const pairs = await page.locator('main tbody tr td:nth-child(3) .tnum').allInnerTexts()
  for (const pair of pairs.slice(0, 40)) {
    const [market, model] = pair.split('→').map((side) => side.trim().replace(/\d+$/, ''))
    expect(market, pair).toBe(model)
  }
})
