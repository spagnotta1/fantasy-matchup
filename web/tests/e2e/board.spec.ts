import { expect, test, type Page } from '@playwright/test'

import { expectRowsLegible, pageOverflow, settle } from './helpers'

/**
 * The board, at every width.
 *
 * What the redesign promised and a screenshot cannot hold it to: the range
 * strip on every row whatever the screen, a toolbar and a column header that
 * stay in view forty rows down, 40px rows, the whole row as the way into a
 * player, and nothing dropped to make any of it fit.
 */

const RANGE = /8 in 10 outcomes between/

async function openBoard(page: Page, path = '/rankings/rb') {
  await page.goto(path)
  await settle(page)
  await expect(page.locator('main a[href^="/players/"]').first()).toBeVisible()
}

test.describe('on a wide screen', () => {
  test.skip(({ isMobile }) => isMobile, 'the table is the wide-screen drawing')

  test('every row carries the range strip, with its floor and ceiling printed', async ({ page }) => {
    await openBoard(page)
    const rows = page.locator('main tbody tr:has(a[data-row-link])')
    const count = await rows.count()
    expect(count).toBeGreaterThan(10)
    await expect(page.locator('main tbody').getByRole('img', { name: RANGE })).toHaveCount(count)
    // "10.8 [strip] 33.1": two printed numbers in the range cell.
    const cell = rows.first().locator('td:has([role="img"])')
    expect((await cell.innerText()).match(/\d+\.\d/g)).toHaveLength(2)
  })

  test('rows are 40px, and 48px when asked, and the choice is remembered', async ({ page }) => {
    await openBoard(page)
    const row = page.locator('main tbody tr:has(a[data-row-link])').nth(1)
    const height = async () => Math.round((await row.boundingBox())!.height)

    expect(await height()).toBe(40)
    await page.getByText('Roomy', { exact: true }).click()
    await expect.poll(height).toBe(48)

    await page.reload()
    await settle(page)
    await expect(page.locator('main a[href^="/players/"]').first()).toBeVisible()
    expect(await height()).toBe(48)
    // A preference of this browser, not part of the link.
    expect(page.url()).not.toMatch(/roomy|comfortable|density/i)

    await page.getByText('Compact', { exact: true }).click()
    await expect.poll(height).toBe(40)
  })

  test('the toolbar and the column header stay in view down the board', async ({ page }) => {
    await openBoard(page)
    const header = page.getByRole('columnheader', { name: /Projection/ })
    const tabs = page.getByRole('navigation', { name: 'Position' })
    const search = page.getByRole('searchbox', { name: /search players/i })

    await page.locator('main tbody tr:has(a[data-row-link])').nth(60).scrollIntoViewIfNeeded()
    await page.mouse.wheel(0, 600)
    await expect(header).toBeInViewport()
    await expect(tabs).toBeInViewport()
    await expect(search).toBeInViewport()

    // Stacked, not overlapping: application bar, then the toolbar, then the
    // column header, each starting where the one above ends.
    const appBar = (await page.locator('header').first().boundingBox())!
    const bar = (await tabs.locator('xpath=..').boundingBox())!
    const head = (await header.boundingBox())!
    expect(Math.round(bar.y)).toBe(Math.round(appBar.y + appBar.height))
    expect(Math.round(head.y)).toBe(Math.round(bar.y + bar.height))
  })

  test('the whole row opens the player, and so does the keyboard', async ({ page }) => {
    await openBoard(page)
    const row = page.locator('main tbody tr:has(a[data-row-link])').nth(2)
    const href = await row.locator('a[data-row-link]').getAttribute('href')

    // A click on the chance-of-20+ cell, nowhere near the name.
    await row.locator('td:nth-last-child(2)').click()
    await expect(page).toHaveURL(new RegExp(`${href}$`))

    await page.goBack()
    await settle(page)
    const link = page.locator('main tbody tr:has(a[data-row-link])').nth(2).locator('a[data-row-link]')
    await link.focus()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(new RegExp(`${href}$`))
  })

  test('a header explains itself on hover and on focus, without an extra tab stop', async ({ page }) => {
    await openBoard(page)
    const header = page.getByRole('columnheader', { name: /Chance of 20\+/ })
    const sort = header.getByRole('button')

    await sort.hover()
    await expect(page.getByRole('tooltip')).toContainText('An estimate, not a promise')
    await page.mouse.move(0, 0)
    await expect(page.getByRole('tooltip')).toHaveCount(0)

    await sort.focus()
    await expect(page.getByRole('tooltip')).toContainText('An estimate, not a promise')
    // The explanation is the button's description, so it is read with it.
    await expect(sort).toHaveAccessibleDescription(/An estimate, not a promise/)
    // And the header holds one tab stop: the button.
    expect(await header.locator('[tabindex="0"]').count()).toBe(0)
  })

  test('sorting from a header reorders the board and drops the tier bands', async ({ page }) => {
    await openBoard(page)
    await expect(page.getByRole('rowheader', { name: /^Tier 1/ })).toBeVisible()

    const header = page.getByRole('columnheader', { name: /Chance of 20\+/ })
    await header.getByRole('button').click()
    await expect(header).toHaveAttribute('aria-sort', 'descending')
    await expect(page).toHaveURL(/sort=boom/)
    // A tier is a statement about neighbours in rank order, so the bands go.
    await expect(page.getByRole('rowheader', { name: /^Tier \d/ })).toHaveCount(0)

    const chances = await page.locator('main tbody tr:has(a[data-row-link]) td:nth-last-child(2)').allInnerTexts()
    const values = chances.slice(0, 20).map((text) => Number.parseFloat(text))
    expect(values).toEqual([...values].sort((a, b) => b - a))
  })

  test('the table gives way to the list before its rows would wrap', async ({ page }) => {
    // The sidebar takes 240px, so a 1,100px window has less room than an
    // 820px tablet. The board measures the room it has, not the window.
    await page.setViewportSize({ width: 1100, height: 800 })
    await openBoard(page, '/rankings')
    await expect(page.locator('main table')).toHaveCount(0)
    await expect(page.locator('main').getByRole('img', { name: RANGE }).first()).toBeVisible()

    await page.setViewportSize({ width: 1366, height: 768 })
    await expect(page.locator('main table')).toHaveCount(1)
    await expect(page.locator('main tbody').getByRole('img', { name: RANGE }).first()).toBeVisible()
    // And it fits: nothing is cut off at the card's edge.
    const overflow = await page.locator('main table').evaluate((table) => {
      const frame = table.parentElement!
      return frame.scrollWidth - frame.clientWidth
    })
    expect(overflow).toBeLessThanOrEqual(0)
  })

  test('cards are still a choice', async ({ page }) => {
    await openBoard(page)
    await page.getByText('Cards', { exact: true }).click()
    await expect(page).toHaveURL(/view=cards/)
    await expect(page.locator('main table')).toHaveCount(0)
    await expect(page.locator('main li.deferred-card').first()).toBeVisible()
  })
})

test.describe('on a phone', () => {
  test.skip(({ isMobile }) => !isMobile, 'the two-line list is the narrow-screen drawing')

  test('each player is two lines, with the strip, the grade and the chance of 20+', async ({ page }) => {
    await openBoard(page)
    const rows = page.locator('main li.deferred-row')
    const count = await rows.count()
    expect(count).toBeGreaterThan(10)

    // Everything the table shows, on every row.
    await expect(page.locator('main').getByRole('img', { name: RANGE })).toHaveCount(count)
    const first = rows.first()
    await expect(first).toContainText(/\d+% of 20\+/)
    await expect(first).toContainText(/ (vs|@) /)
    expect((await first.innerText()).match(/\d+\.\d/g)!.length).toBeGreaterThanOrEqual(3)

    // About 65px, where a card was about 235px.
    const height = (await rows.nth(3).boundingBox())!.height
    expect(height).toBeGreaterThan(48)
    expect(height).toBeLessThan(90)

    // And the number on the right is labelled for what it is.
    await expect(page.locator('main').getByText('Projected points', { exact: true })).toBeVisible()
  })

  test('the position tabs stay in view, and a row opens the player', async ({ page }) => {
    await openBoard(page)
    const tabs = page.getByRole('navigation', { name: 'Position' })
    const rows = page.locator('main li.deferred-row')

    await rows.nth(30).scrollIntoViewIfNeeded()
    await expect(tabs).toBeInViewport()

    const href = await rows.nth(30).locator('a').getAttribute('href')
    await rows.nth(30).locator('a').click()
    await expect(page).toHaveURL(new RegExp(`${href}$`))
  })

  test('the tabs and the three filters are big enough to hit', async ({ page }) => {
    await openBoard(page)
    const tab = page.getByRole('navigation', { name: 'Position' }).getByRole('link').first()
    expect(Math.round((await tab.boundingBox())!.height)).toBeGreaterThanOrEqual(44)
    // 44px, the height the tabs above them have and every other toolbar's
    // controls have under a finger. They were 32px here, beside 44px tabs.
    for (const name of [/search players/i, /^team$/i, /^sort by$/i]) {
      const control = page.getByLabel(name).filter({ visible: true }).first()
      expect(Math.round((await control.boundingBox())!.height), String(name)).toBeGreaterThanOrEqual(44)
    }
  })
})

// A 412px phone is the widest; most are 390px and some 360px. On a week with
// an ungraded matchup the grade's slot is as wide as the words "Not graded",
// and below 412px the row's second line no longer held it, the strip and the
// chance of 20+: the ceiling was printed under the chance.
for (const width of [412, 390, 360]) {
  test.describe(`on a ${width}px phone`, () => {
    test.skip(({ isMobile }) => isMobile, 'the width is set here; the phone project is 412px')
    test.use({ viewport: { width, height: 900 }, hasTouch: true })

    for (const week of ['this week', 'week 1, which is ungraded by design'] as const) {
      test(`nothing in a row is printed over anything else: ${week}`, async ({ page }) => {
        const seasons = (await (await page.request.get('/api/v1/seasons')).json()) as { data: { season: number }[] }
        const ungraded = week !== 'this week'
        await openBoard(page, ungraded ? `/rankings/rb?season=${seasons.data[0].season}&week=1` : '/rankings/rb')
        const rows = page.locator('main li.deferred-row > a')
        expect(await rows.count()).toBeGreaterThan(10)
        if (ungraded) await expect(rows.first()).toContainText('Not graded')

        // Everything the table shows is still on the row.
        await expect(rows.first().getByRole('img', { name: RANGE })).toHaveCount(1)
        await expect(rows.first()).toContainText(/\d+% of 20\+/)
        await expectRowsLegible(rows, width)
        expect(await pageOverflow(page)).toBeLessThanOrEqual(0)

        // The strips share one scale, so they share one left edge and one width.
        const strips = await page
          .locator('main li.deferred-row')
          .getByRole('img', { name: RANGE })
          .evaluateAll((elements) =>
            elements.slice(0, 12).map((element) => {
              const box = element.getBoundingClientRect()
              return `${Math.round(box.left)}+${Math.round(box.width)}`
            }),
          )
        expect(new Set(strips).size, strips.join(' ')).toBe(1)
      })
    }
  })
}

test('a ruled-out or questionable player carries the designation on the board', async ({ page }) => {
  await openBoard(page, '/rankings')
  // Whoever on this week's first hundred is flagged; a week with nobody
  // flagged has nothing to assert, and says so.
  const flagged = await page.evaluate(async () => {
    const response = await fetch('/api/v1/projections?limit=1000')
    const body = (await response.json()) as {
      data: { projection: { player: { player_id: string }; context: { injury: { is_questionable_or_worse?: boolean; report_status?: string | null } | null } } }[]
    }
    const entry = body.data.slice(0, 100).find((row) => row.projection.context.injury?.is_questionable_or_worse)
    return entry
      ? { id: entry.projection.player.player_id, status: entry.projection.context.injury?.report_status ?? 'Questionable' }
      : null
  })
  test.skip(flagged === null, 'nobody in the top hundred has a designation this week')

  const link = page.locator(`main a[href="/players/${flagged!.id}"]`).first()
  await expect(link).toBeVisible()
  // In the table the row is the `<tr>`; in the list the link is the row.
  const row = page.locator(`main tr:has(a[href="/players/${flagged!.id}"]), main li:has(a[href="/players/${flagged!.id}"])`).first()
  await expect(row).toContainText(flagged!.status)
})
