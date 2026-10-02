import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

import { seedRoster, settle } from './helpers'

/**
 * My team with a roster on it.
 *
 * The responsive suite only ever opened this page empty, which is one card and
 * a search box and cannot overflow. With thirteen players saved, the bench
 * table was wider than a phone: the page scrolled sideways and the "Start in…"
 * control — the only way to promote a bench player — was cut off at the edge.
 *
 * So these seed a real roster from the published board and check that every
 * row's controls are on screen, at the widths phones actually have.
 */

/** Everything the page promises a manager can do to a row, measured. */
async function measure(page: Page) {
  return page.evaluate(() => {
    const doc = document.documentElement
    const width = doc.clientWidth
    const onScreen = (el: Element) => {
      const box = el.getBoundingClientRect()
      const style = getComputedStyle(el)
      return (
        style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        box.width > 0 &&
        box.left >= 0 &&
        box.right <= width + 1
      )
    }
    const visible = (selector: string) =>
      [...document.querySelectorAll(`main ${selector}`)].filter(
        (el) => el.getBoundingClientRect().width > 0,
      )
    const rows = [...document.querySelectorAll('main tbody tr')]
    const removes = visible('button[aria-label^="Remove "]')
    // The "Start…" / "Start in…" menus: a select whose first option is the prompt.
    const starts = visible('select').filter((el) =>
      (el as HTMLSelectElement).options[0]?.text.startsWith('Start'),
    )
    return {
      pageOverflow: doc.scrollWidth - width,
      innerScroll: [...document.querySelectorAll('main table')].map((table) => {
        const scroller = table.parentElement!
        return scroller.scrollWidth - scroller.clientWidth
      }),
      rows: rows.length,
      startSelects: starts.length,
      startSelectsOnScreen: starts.filter(onScreen).length,
      benchButtons: visible('button[aria-label$="to the bench"]').length,
      benchButtonsOnScreen: visible('button[aria-label$="to the bench"]').filter(onScreen).length,
      removes: removes.length,
      removesOnScreen: removes.filter(onScreen).length,
      smallestRemove: Math.min(
        ...removes.map((el) => Math.min(el.getBoundingClientRect().width, el.getBoundingClientRect().height)),
      ),
      // A grade chip or the "Not graded" note, once per player row.
      // The page's next step: the link that carries this lineup into the simulation.
      estimateOnScreen: visible('a[href^="/simulation"]').filter(onScreen).length,
      matchupsOnScreen: [...document.querySelectorAll('main tbody [data-matchup]')].filter(onScreen)
        .length,
      playerRows: rows.filter((row) => row.querySelector('a[href^="/players/"]')).length,
    }
  })
}

for (const width of [360, 390, 412]) {
  for (const theme of ['light', 'dark'] as const) {
    test.describe(`phone, ${width}px, ${theme}`, () => {
      test.skip(({ isMobile }) => !isMobile, 'phone-width behaviour')
      test.use({ viewport: { width, height: 860 } })

      test('every row control is on screen without sideways scrolling', async ({ page }) => {
        await seedRoster(page, theme)
        await page.goto('/my-team')
        await settle(page)
        await expect(page.getByRole('heading', { name: 'Bench' })).toBeVisible()

        const m = await measure(page)
        expect(m.pageOverflow, 'the page scrolls sideways').toBeLessThanOrEqual(0)
        expect(Math.max(...m.innerScroll), 'a roster table scrolls sideways').toBeLessThanOrEqual(0)

        expect(m.playerRows).toBe(13)
        // Starters can be benched, the bench can be started, anyone can be removed.
        expect(m.benchButtons).toBeGreaterThan(0)
        expect(m.benchButtonsOnScreen).toBe(m.benchButtons)
        expect(m.startSelects).toBeGreaterThan(0)
        expect(m.startSelectsOnScreen).toBe(m.startSelects)
        expect(m.removes).toBe(13)
        expect(m.removesOnScreen).toBe(13)
        // WCAG 2.5.8, and this one sits beside another control.
        expect(m.smallestRemove).toBeGreaterThanOrEqual(24)
        expect(m.matchupsOnScreen, 'each player row shows its matchup').toBe(13)
        expect(m.estimateOnScreen, 'the simulate link is not clipped').toBe(1)
      })
    })
  }
}

test.describe('phone, 412px', () => {
  test.skip(({ isMobile }) => !isMobile, 'phone-width behaviour')
  test.use({ viewport: { width: 412, height: 860 } })

  test('a bench player can be started and a player removed', async ({ page }) => {
    await seedRoster(page, 'light')
    await page.goto('/my-team')
    await settle(page)

    // The bench is the second roster table on the page. Promote its first
    // player into the first slot offered, using the control a phone shows.
    const start = page.locator('main table').last().locator('select').filter({ visible: true }).first()
    await expect(start).toBeVisible()
    const option = await start.locator('option').nth(1).getAttribute('value')
    await start.selectOption(option!)
    // The swap keeps thirteen players; the lineup is now a chosen one.
    await expect(page.getByRole('button', { name: /reset/i })).toBeVisible()

    const remove = page.getByRole('button', { name: /^Remove / }).filter({ visible: true }).first()
    await remove.tap()
    await expect(page.getByRole('button', { name: /^Remove / }).filter({ visible: true })).toHaveCount(12)
  })
})

test.describe('desktop', () => {
  test.skip(({ isMobile }) => isMobile, 'desktop layout')

  for (const theme of ['light', 'dark'] as const) {
    test(`every row control is on screen, ${theme}`, async ({ page }) => {
      await seedRoster(page, theme)
      await page.goto('/my-team')
      await settle(page)
      await expect(page.getByRole('heading', { name: 'Bench' })).toBeVisible()

      const m = await measure(page)
      expect(m.pageOverflow).toBeLessThanOrEqual(0)
      expect(Math.max(...m.innerScroll)).toBeLessThanOrEqual(0)
      expect(m.playerRows).toBe(13)
      expect(m.benchButtonsOnScreen).toBe(m.benchButtons)
      expect(m.startSelectsOnScreen).toBe(m.startSelects)
      expect(m.removesOnScreen).toBe(13)
      expect(m.smallestRemove).toBeGreaterThanOrEqual(24)
      expect(m.matchupsOnScreen).toBe(13)
    })
  }
})

test.describe('a row is not a link', () => {
  test.skip(({ isMobile }) => isMobile, 'the pointer case; the phone layout is covered above')

  // Everywhere else a click on a row opens its player. Here a row holds Bench,
  // Start and Remove, and a press that just misses one must not leave the page.
  test('a press on the row stays on the page, the name still opens the player', async ({ page }) => {
    await seedRoster(page, 'light')
    await page.goto('/my-team')
    await settle(page)
    const lineup = page.getByRole('table', { name: /^Starting lineup/ })
    const row = lineup.getByRole('row').nth(1)
    await expect(row.getByRole('rowheader').getByRole('link')).toBeVisible()
    await expect(row.locator('a[data-row-link]')).toHaveCount(0)

    // The projection cell, a few pixels from Bench.
    await row.getByRole('cell').nth(3).click()
    await expect(page).toHaveURL(/\/my-team/)

    const name = await row.getByRole('rowheader').getByRole('link').innerText()
    await row.getByRole('button', { name: `Move ${name} to the bench` }).click()
    await expect(page).toHaveURL(/\/my-team/)
    await expect(page.getByRole('button', { name: /reset/i })).toBeVisible()

    await page.getByRole('button', { name: `Remove ${name}` }).filter({ visible: true }).click()
    await expect(page).toHaveURL(/\/my-team/)
    await expect(page.getByRole('button', { name: /^Remove / }).filter({ visible: true })).toHaveCount(12)

    // Whoever now heads the lineup: the first slot may be the one just emptied.
    const link = lineup.locator('th[scope="row"] a').first()
    const href = await link.getAttribute('href')
    await link.click()
    await expect(page).toHaveURL(new RegExp(`${href}$`))
  })

  test('both roster tables are real tables with named columns and row headers', async ({ page }) => {
    await seedRoster(page, 'light')
    await page.goto('/my-team')
    await settle(page)
    for (const name of [/^Starting lineup/, /^Bench players/]) {
      const table = page.getByRole('table', { name })
      await expect(table).toBeVisible()
      for (const header of ['Slot', 'Player', 'Matchup', 'Projection', 'Move', 'Remove']) {
        await expect(table.getByRole('columnheader', { name: header, exact: true })).toBeAttached()
      }
      expect(await table.getByRole('rowheader').count()).toBeGreaterThan(0)
      await expect(table.locator('[aria-sort]')).toHaveCount(0)
    }
  })
})

for (const theme of ['light', 'dark'] as const) {
  // The accessibility pass opens this page empty too. The roster tables, the
  // phone's second line and the row controls only exist with players on it.
  test(`a populated roster has no WCAG AA violations, ${theme}`, async ({ page }) => {
    await seedRoster(page, theme)
    await page.goto('/my-team')
    await settle(page)
    await expect(page.getByRole('heading', { name: 'Bench' })).toBeVisible()

    const { violations } = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    expect(
      violations.map((violation) => `${violation.id}: ${violation.nodes[0]?.target.join(' ')}`),
    ).toEqual([])
  })
}
