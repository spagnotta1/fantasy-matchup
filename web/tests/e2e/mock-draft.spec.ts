import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import { settle } from './helpers'

/**
 * The mock draft, driven end to end against a real backend.
 *
 * The a11y and responsive suites already visit `/mock-draft` in its *empty*
 * state, which is the state a route-level sweep can reach. Everything
 * interesting about this screen only exists after a simulation has run — the
 * roster table, the reasoning disclosures, the availability verdicts, the
 * comparison chart — so this file runs one and then checks what appears.
 *
 * A simulation count of 100 is used throughout. It is above the API's floor,
 * it exercises every code path a larger run would, and it keeps a full
 * comparison of twelve seats inside the test timeout. What is being tested is
 * the wiring, not the statistics; the statistics are measured in
 * `scripts/phase8e_evaluate.py` against seasons that have actually happened.
 */

/** Configure the smallest run the API accepts, then analyse one seat. */
async function runAnalysis(page: import('@playwright/test').Page) {
  await page.goto('/mock-draft')
  await settle(page)

  const options = page.getByText('Simulation options')
  if (await options.isVisible()) await options.click()

  const simulations = page.getByLabel('Simulated drafts')
  if (await simulations.isVisible()) await simulations.selectOption('100')

  await page.getByRole('button', { name: /analyze draft position/i }).click()
  await expect(page.getByRole('heading', { name: /simulated roster/i })).toBeVisible({
    timeout: 120_000,
  })
}

test('the empty state explains itself rather than showing a blank page', async ({ page }) => {
  await page.goto('/mock-draft')
  await settle(page)

  await expect(page.getByRole('heading', { name: 'Mock draft', level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: /league settings/i })).toBeVisible()
  await expect(page.getByText(/nothing simulated yet/i)).toBeVisible()
})

test('the configuration refuses a draft too short for its lineup', async ({ page }) => {
  await page.goto('/mock-draft')
  await settle(page)

  // The rounds selector only offers values that can fill the roster, which is
  // the refusal expressed as an affordance rather than as an error.
  const rounds = page.getByLabel('Rounds')
  const values = await rounds.locator('option').evaluateAll((options) =>
    options.map((option) => Number((option as HTMLOptionElement).value)),
  )
  expect(Math.min(...values)).toBeGreaterThanOrEqual(7)
})

test('kickers and defences are declared unavailable, not silently missing', async ({ page }) => {
  await page.goto('/mock-draft')
  await settle(page)

  await expect(page.getByText(/Kicker and team-defence slots are not offered/i)).toBeVisible()

  // The roster form offers exactly the projected positions, and the accessible
  // name of each control is the string printed on it — the property WCAG 2.5.3
  // is about, and the one a speech-input user depends on.
  const roster = page.getByRole('group', { name: /starting roster/i })
  await expect(roster.getByLabel('QB', { exact: true })).toBeVisible()
  await expect(roster.getByLabel('FLEX', { exact: true })).toBeVisible()
  await expect(roster.getByLabel('K', { exact: true })).toHaveCount(0)
  await expect(roster.getByLabel('DST', { exact: true })).toHaveCount(0)
})

test('a simulated draft produces a roster where every pick explains itself', async ({ page }) => {
  test.slow()
  await runAnalysis(page)

  const roster = page.getByRole('table', { name: /round-by-round roster/i }).or(
    page.locator('table').filter({ hasText: 'Draft value' }).first(),
  )
  await expect(roster).toBeVisible()

  // Round 1 is expanded by default, so its reasoning is on screen already.
  await expect(
    page.getByText(/Fills a starting|Fills the flex|Adds \d+ points of depth/).first(),
  ).toBeVisible()

  // Every row offers its reasoning, and opening one reveals the numbers.
  const why = page.getByRole('button', { name: /^Why$/ })
  expect(await why.count()).toBeGreaterThan(5)
  await why.first().click()
  await expect(page.getByText(/Value added/i).first()).toBeVisible()
})

test('the result carries its methodology limits', async ({ page }) => {
  test.slow()
  await runAnalysis(page)

  // The notices are rendered plainly, not folded into the collapsed
  // methodology disclosure: a caveat behind a `<details>` nobody opens is a
  // caveat nobody reads.
  const notices = page.getByRole('complementary', {
    name: /what this does and does not claim/i,
  })
  await expect(notices).toBeVisible()
  await expect(notices).toContainText(/per-game rate/i)
  await expect(notices).toContainText(/rookies/i)
  await expect(notices).toContainText(/average-draft-position/i)
})

test('availability says whether a player can be waited on', async ({ page }) => {
  test.slow()
  await runAnalysis(page)

  await expect(page.getByRole('heading', { name: /player availability/i })).toBeVisible()
  // The verdict is a word, never colour alone.
  const verdicts = page.getByText(/Likely gone|Can wait|Coin flip/)
  expect(await verdicts.count()).toBeGreaterThan(0)
})

test('changing the seat holds the previous result on screen instead of blanking', async ({
  page,
}) => {
  test.slow()
  await runAnalysis(page)

  const before = await page.getByRole('heading', { name: /simulated roster/i }).textContent()
  await page.getByLabel('Your draft position').selectOption('7')
  await page.getByRole('button', { name: /analyze draft position/i }).click()

  // The old roster stays visible while the new one is computed — the
  // keepPreviousSubject behaviour the brief asks for.
  await expect(page.getByRole('heading', { name: /simulated roster/i })).toBeVisible()
  await expect(page.getByRole('heading', { name: /simulated roster/i })).toContainText(
    'position 7',
    { timeout: 120_000 },
  )
  expect(before).not.toBeNull()
})

test('a simulated result has no accessibility violations', async ({ page }) => {
  test.slow()
  await runAnalysis(page)

  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()

  expect(
    violations,
    violations
      .map((violation) => `[${violation.impact}] ${violation.id}: ${violation.help}`)
      .join('\n'),
  ).toEqual([])
})

test('the comparison ranks every seat and lets one be inspected', async ({ page }) => {
  test.slow()
  await page.goto('/mock-draft')
  await settle(page)

  const options = page.getByText('Simulation options')
  if (await options.isVisible()) await options.click()
  const simulations = page.getByLabel('Simulated drafts')
  if (await simulations.isVisible()) await simulations.selectOption('100')

  await page.getByRole('button', { name: /compare all draft positions/i }).click()
  await expect(page.getByRole('heading', { name: /draft position comparison/i })).toBeVisible({
    timeout: 180_000,
  })

  // One row per seat, each a real button so the keyboard can reach it.
  const seats = page.locator('button[aria-pressed]')
  expect(await seats.count()).toBe(12)

  await seats.nth(8).click()
  await expect(page.getByRole('heading', { name: /simulated roster/i })).toContainText(
    'position 9',
  )
})

test('the mobile board becomes a chronological list rather than a shrunken grid', async ({
  page,
}) => {
  test.slow()
  test.skip(
    (page.viewportSize()?.width ?? 0) > 767,
    'the compact board only exists below the md breakpoint',
  )
  await runAnalysis(page)

  await expect(page.getByRole('heading', { name: /draft board/i })).toBeVisible()
  await expect(page.getByText(/picks until your next/i).first()).toBeVisible()

  // And the page never scrolls sideways, at any point on it.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
})
