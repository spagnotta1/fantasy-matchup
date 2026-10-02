import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Locator, type Page } from '@playwright/test'

import { pageOverflow, settle } from './helpers'

/**
 * The player page as the place a week is read from.
 *
 * What the redesign promised and a picture cannot hold it to: a bar that
 * follows the page down with the name and the number in it, links that land a
 * section under that bar and not behind it, a week stepper that moves the page
 * a week without throwing away where the reader was, and a game log that shows
 * the projection made for each game beside what happened.
 */

interface BoardRow {
  projection: { player: { player_id: string; name: string; position: string | null } }
}

/** A running back near the top of this week's board: a long history and a projection. */
async function subject(page: Page) {
  const response = await page.request.get('/api/v1/projections?limit=200')
  const board = ((await response.json()) as { data: BoardRow[] }).data
  const row = board.find((entry) => entry.projection.player.position === 'RB')
  expect(row, 'the board has a running back').toBeTruthy()
  return row!.projection.player
}

async function openPlayer(page: Page, query = '') {
  const player = await subject(page)
  await page.goto(`/players/${player.player_id}${query}`)
  await settle(page)
  await expect(page.getByRole('heading', { level: 1, name: player.name })).toBeVisible()
  return player
}

const bar = (page: Page) => page.locator('[data-player-bar]')
const summary = (page: Page) => bar(page).locator('[aria-hidden="true"]').first()
const gameLog = (page: Page) => page.locator('#game-log')

/** The bottom edge of the two bars a section has to clear. */
async function underBars(page: Page) {
  const box = await bar(page).boundingBox()
  return box!.y + box!.height
}

test.describe('on a wide screen', () => {
  test.skip(({ isMobile }) => isMobile, 'the one-line phone bar is covered below')

  test('the first screen holds the projection, its range and the start of the game log', async ({ page }) => {
    await openPlayer(page)
    const hero = page.getByRole('region', { name: /this week$/ })
    await expect(hero.locator('dt', { hasText: 'Projected' }).first()).toBeInViewport()
    await expect(hero.getByRole('img', { name: /8 in 10 outcomes between/ })).toBeInViewport()
    await expect(page.getByRole('heading', { level: 2, name: 'Projection' })).toBeInViewport()
    // 1440 by 900: the header beside the scoreboard is what makes the room.
    const projection = await page.locator('#this-week').boundingBox()
    expect(projection!.y, 'the projection card starts in the top half').toBeLessThan(470)
  })

  test('the bar follows the page down, and says who and how much once the header is gone', async ({ page }) => {
    const player = await openPlayer(page)
    // At the top the header says it, and the bar does not say it twice.
    await expect(summary(page)).not.toHaveAttribute('data-visible', 'true')
    await expect(bar(page).getByRole('button', { name: 'Add to my team' })).toHaveCount(0)
    const headline = await page.getByRole('region', { name: /this week$/ }).locator('dd .tnum').first().innerText()

    await gameLog(page).scrollIntoViewIfNeeded()
    await page.mouse.wheel(0, 500)
    await expect(summary(page)).toHaveAttribute('data-visible', 'true')
    await expect(bar(page)).toBeInViewport()
    await expect(summary(page)).toContainText(player.name)
    await expect(summary(page)).toContainText(headline)
    await expect(summary(page)).toContainText(/\d+% of \d+\+/)
    await expect(summary(page).getByRole('img', { includeHidden: true })).toHaveCount(1)

    // Stuck directly under the application bar.
    expect(Math.round((await bar(page).boundingBox())!.y)).toBe(57)
    // The header's two actions are within reach again.
    await expect(bar(page).getByRole('button', { name: 'Add to my team' }).or(bar(page).getByRole('link', { name: 'On your team' }))).toBeVisible()
    await expect(bar(page).getByRole('link', { name: 'Compare' })).toHaveAttribute('href', `/compare?players=${player.player_id}`)
  })

  test('each section link lands its section under the bar and hands it the focus', async ({ page }) => {
    await openPlayer(page)
    const links = bar(page).getByRole('navigation', { name: 'On this page' }).getByRole('link')
    await expect(links).toHaveText(['This week', 'Game log', 'Usage', 'Matchup', 'Context'])

    for (const id of ['game-log', 'usage', 'matchup', 'context', 'this-week']) {
      await bar(page).locator(`a[href="#${id}"]`).click()
      const section = page.locator(`#${id}`)
      await expect(section).toBeFocused()
      // Settled, and not hidden behind the bar. The last section may stop
      // short of the bar when the page ends first.
      await expect
        .poll(async () => {
          const top = (await section.boundingBox())!.y
          const clear = await underBars(page)
          const atEnd = await page.evaluate(
            () => window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2,
          )
          return top >= clear - 1 && (top <= clear + 24 || atEnd)
        })
        .toBe(true)
    }
    // By keyboard: Enter on a link, and Tab carries on from inside the section.
    await bar(page).locator('a[href="#game-log"]').focus()
    await page.keyboard.press('Enter')
    await expect(gameLog(page)).toBeFocused()
    await page.keyboard.press('Tab')
    expect(await gameLog(page).evaluate((section) => section.contains(document.activeElement))).toBe(true)
  })

  test('the stepper moves the page a week and keeps the place and the focus', async ({ page }) => {
    const seasons = (await (await page.request.get('/api/v1/seasons')).json()) as {
      data: { season: number; published_weeks: number[] }[]
    }
    const weeks = seasons.data[0].published_weeks
    test.skip(weeks.length < 2, 'one published week: nothing to step to')
    const latest = weeks.at(-1)!
    const before = weeks.at(-2)!

    const player = await openPlayer(page, `?season=${seasons.data[0].season}&week=${latest}`)
    const stepper = bar(page).getByRole('group', { name: 'Week' })
    await expect(stepper).toContainText(`Week ${latest}`)

    // At the newest week the way forward stays where it is, and says why.
    const forward = stepper.getByRole('button').last()
    await expect(forward).toHaveAccessibleName('No later week is published')
    await expect(forward).toHaveAttribute('aria-disabled', 'true')
    await forward.click({ force: true })
    await expect(page).toHaveURL(new RegExp(`week=${latest}`))

    await page.locator('#matchup').scrollIntoViewIfNeeded()
    await page.mouse.wheel(0, 300)
    const scrolled = await page.evaluate(() => window.scrollY)
    expect(scrolled).toBeGreaterThan(300)

    const back = stepper.getByRole('button', { name: `Previous week: week ${before}` })
    await back.focus()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(new RegExp(`week=${before}`))
    await expect(stepper).toContainText(`Week ${before}`)
    // Same player, same page: no skeleton, and the reader is still down it.
    await expect(page.getByRole('heading', { level: 1, name: player.name })).toBeAttached()
    await expect(page.locator('main [aria-busy="true"]')).toHaveCount(0)
    expect(await page.evaluate(() => window.scrollY), 'the page went back to its top').toBeGreaterThan(300)
    // The control that was pressed still has the focus, under its new name.
    expect(await stepper.evaluate((group) => group.contains(document.activeElement))).toBe(true)
    await expect(page.getByRole('region', { name: /this week$/ })).toContainText(`Week ${before}`)

    await stepper.getByRole('button', { name: `Next week: week ${latest}` }).click()
    await expect(page).toHaveURL(new RegExp(`week=${latest}`))
    await expect(stepper).toContainText(`Week ${latest}`)
  })

  test('the game log draws the projection made for each game, and the table gives the difference', async ({ page }) => {
    await openPlayer(page)
    const log = gameLog(page)
    const bars = log.locator('[data-chart-bar]')
    await expect(bars.first()).toBeVisible()
    const columns = await bars.count()
    const ticks = await log.locator('[data-chart-projection]').count()

    await log.getByRole('radiogroup', { name: 'Game log view' }).getByText('Table', { exact: true }).click()
    const table = log.getByRole('table', { name: /^Completed games, newest first/ })
    for (const name of ['Week', 'Opp', 'Points', 'Projected', 'Difference', 'Snaps', 'Tgt', 'Car']) {
      await expect(table.getByRole('columnheader', { name, exact: true })).toBeVisible()
    }
    const rows = table.locator('tbody tr')
    // The same games as the chart, and a tick for each one that had a projection.
    await expect(rows).toHaveCount(columns)
    const cells = await rows.evaluateAll((trs) =>
      trs.map((tr) => [...tr.children].map((cell) => (cell as HTMLElement).innerText.trim())),
    )
    expect(cells.filter((row) => row[3] !== '—')).toHaveLength(ticks)
    if (ticks > 0) await expect(log.getByText('Projected before the game')).toHaveCount(0) // the legend is the chart's

    // Newest first, with the week as each row's header.
    const order = cells.map((row) => {
      const found = row[0].match(/^(\d{4}) W(\d+)$/)!
      return Number(found[1]) * 100 + Number(found[2])
    })
    expect(order).toEqual([...order].sort((a, b) => b - a))
    await expect(rows.first().getByRole('rowheader')).toHaveCount(1)

    // Points minus projection, signed; a dash where no projection was stored.
    for (const row of cells) {
      if (row[3] === '—') {
        expect(row[4]).toBe('—')
        continue
      }
      const difference = Number(row[2]) - Number(row[3])
      expect(Math.abs(Number(row[4].replace('−', '-').replace('+', '')) - difference)).toBeLessThan(0.11)
      if (Math.abs(difference) >= 0.1) expect(row[4].startsWith(difference > 0 ? '+' : '−')).toBe(true)
    }

    // The page scrolls, not a box inside it.
    const frame = table.locator('xpath=..')
    await expect(frame).not.toHaveAttribute('data-table-scrolls', 'true')
    expect(await frame.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeLessThanOrEqual(1)
  })

  test('a season can be chosen, the usage trend follows it, and earlier seasons load on request', async ({ page }) => {
    await openPlayer(page)
    const log = gameLog(page)
    const choose = log.getByRole('combobox', { name: 'Games shown' })
    const options = await choose.locator('option').allInnerTexts()
    expect(options[0]).toBe('Last 17 games')
    test.skip(options.length < 2, 'no whole season is loaded for this player yet')

    const season = options[1].match(/^(\d{4}) season$/)![1]
    await choose.selectOption({ label: `${season} season` })
    await expect(log).toContainText(new RegExp(`the ${season} season, \\d+ games?\\.`))
    const games = Number((await log.innerText()).match(new RegExp(`the ${season} season, (\\d+) games?`))![1])
    await expect(log.locator('[data-chart-bar]')).toHaveCount(games)
    // The same games, column for column.
    await expect(page.locator('#usage')).toContainText(`the ${season} season, ${games} game`)

    const more = log.getByRole('button', { name: 'Load earlier seasons' })
    test.skip((await more.count()) === 0, 'this player has no earlier games to load')
    const request = page.waitForRequest((candidate) => /\/profile\?/.test(candidate.url()) && /weeks=120/.test(candidate.url()))
    await more.click()
    await request
    await expect(log.getByText(/games (on record )?are loaded/)).not.toContainText('The last 24 games')
    await expect(more).toHaveCount(0)
    expect((await choose.locator('option').count())).toBeGreaterThanOrEqual(options.length)
    // The choice survived the reload.
    await expect(choose).toHaveValue(season)
  })

  test('the three kinds of context sit side by side, each with its own caveat', async ({ page }) => {
    await openPlayer(page)
    const context = page.locator('#context')
    const tops = await context
      .getByRole('heading', { level: 3 })
      .evaluateAll((headings) => headings.map((heading) => Math.round(heading.getBoundingClientRect().top)))
    expect(tops).toHaveLength(3)
    expect(new Set(tops).size, 'injury, weather and the market start on one line').toBe(1)
    await expect(context.getByText(/factored into the projection/)).toBeVisible()
  })

  test('a week with no projection keeps the bar, the stepper and the past games', async ({ page }) => {
    await page.route(/\/api\/v1\/players\/[^/]+\/profile/, async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      body.data.current = null
      await route.fulfill({ response, json: body })
    })
    await openPlayer(page)
    await expect(page.getByRole('heading', { name: 'No projection for this week' })).toBeVisible()
    // Only the sections that exist are linked.
    await expect(bar(page).getByRole('navigation', { name: 'On this page' }).getByRole('link')).toHaveText(['Game log', 'Usage'])
    await expect(bar(page).getByRole('group', { name: 'Week' })).toBeVisible()
    await expect(gameLog(page).locator('[data-chart-bar]').first()).toBeVisible()
  })
})

for (const theme of ['light', 'dark'] as const) {
  test(`axe: the player page, ${theme}`, async ({ page }) => {
    await page.addInitScript((chosen) => window.localStorage.setItem('nflfp.theme', chosen), theme)
    await openPlayer(page)
    const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(
      violations.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.target.join(' ')).join(' | ')}`),
    ).toEqual([])

    // And with the table drawn in place of the chart.
    await gameLog(page).getByRole('radiogroup', { name: 'Game log view' }).getByText('Table', { exact: true }).click()
    await expect(gameLog(page).getByRole('table')).toBeVisible()
    const table = await new AxeBuilder({ page }).include('#game-log').withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(table.violations.map((violation) => violation.id)).toEqual([])
  })
}

for (const width of [1024, 820, 412, 390, 360]) {
  test.describe(`at ${width}px`, () => {
    test.skip(({ isMobile }) => isMobile, 'the width is set here; the phone project adds nothing')
    test.use({ viewport: { width, height: 900 }, hasTouch: width < 1024 })

    test('nothing overflows, in either game log view, and the bar stays one or two lines', async ({ page }) => {
      await openPlayer(page)
      expect(await pageOverflow(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)

      await gameLog(page).scrollIntoViewIfNeeded()
      await page.mouse.wheel(0, 400)
      await expect(summary(page)).toHaveAttribute('data-visible', 'true')
      const box = await bar(page).boundingBox()
      expect(box!.height, 'the bar').toBeLessThanOrEqual(width < 720 ? 56 : 100)
      // The name is still a name, not squeezed out by what shares the bar.
      const name = await summary(page).locator('.truncate').boundingBox()
      expect(name!.width, 'the name in the bar').toBeGreaterThanOrEqual(64)
      // Nothing in the bar is pushed off its edge.
      const edges = await bar(page).evaluate((element) => {
        const right = element.getBoundingClientRect().right
        return [...element.querySelectorAll('button, a')].map((control) => Math.ceil(control.getBoundingClientRect().right) <= Math.ceil(right))
      })
      expect(edges.every(Boolean), 'a control runs past the bar').toBe(true)

      await gameLog(page).getByRole('radiogroup', { name: 'Game log view' }).getByText('Table', { exact: true }).click()
      const table = gameLog(page).getByRole('table')
      await expect(table).toBeVisible()
      expect(await pageOverflow(page), 'the page scrolls sideways with the table drawn').toBeLessThanOrEqual(0)
      await expectWeekHeld(table)
    })
  })
}

/** Where the game log table is too narrow for its columns, it scrolls in its frame with the week held. */
async function expectWeekHeld(table: Locator) {
  const frame = table.locator('xpath=..')
  const inner = await frame.evaluate((element) => element.scrollWidth - element.clientWidth)
  if (inner <= 0) return
  await expect(frame).toHaveAttribute('data-table-scrolls', 'true')
  const first = table.locator('th[scope="row"]').first()
  const before = await first.boundingBox()
  await frame.evaluate((element) => element.scrollTo({ left: element.scrollWidth }))
  await expect.poll(() => frame.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
  expect((await first.boundingBox())?.x, 'the week column moved with the scroll').toBe(before?.x)
  const last = await table.getByRole('columnheader').last().boundingBox()
  const edge = await frame.boundingBox()
  expect(Math.floor(last!.x + last!.width), 'the last column cannot be reached').toBeLessThanOrEqual(Math.ceil(edge!.x + edge!.width))
}

test.describe('on a phone', () => {
  test.skip(({ isMobile }) => !isMobile, 'the one-line bar is the narrow drawing')

  test('the bar is one line with the stepper in it, and the section links scroll away', async ({ page }) => {
    const player = await openPlayer(page)
    const links = page.getByRole('navigation', { name: 'On this page' })
    await expect(links).toHaveCount(1)
    // Under the bar, not in it.
    expect(await bar(page).evaluate((element, nav) => element.contains(nav), await links.elementHandle())).toBe(false)
    for (const link of await links.getByRole('link').all()) {
      expect(Math.round((await link.boundingBox())!.height)).toBeGreaterThanOrEqual(44)
    }

    await links.getByRole('link', { name: 'Game log' }).tap()
    await expect(gameLog(page)).toBeFocused()
    await expect.poll(async () => (await gameLog(page).boundingBox())!.y >= (await underBars(page)) - 1).toBe(true)

    await page.mouse.wheel(0, 300)
    await expect(links).not.toBeInViewport()
    await expect(bar(page)).toBeInViewport()
    expect(Math.round((await bar(page).boundingBox())!.height)).toBeLessThanOrEqual(56)
    await expect(summary(page)).toHaveAttribute('data-visible', 'true')
    // The name may be cut short; the number is not.
    await expect(summary(page)).toContainText(player.name.slice(0, 1))
    await expect(summary(page).locator('.tnum').first()).toBeInViewport()

    for (const button of await bar(page).getByRole('group', { name: 'Week' }).getByRole('button').all()) {
      const box = await button.boundingBox()
      expect(Math.round(box!.height)).toBeGreaterThanOrEqual(44)
      expect(Math.round(box!.width)).toBeGreaterThanOrEqual(44)
    }
    // And the game log's two controls are full touch targets.
    const controls = gameLog(page).getByRole('group', { name: 'Choose games and a view' }).locator(':is(select, [role="radiogroup"])')
    for (const control of await controls.all()) {
      expect(Math.round((await control.boundingBox())!.height)).toBe(44)
    }
    expect(await pageOverflow(page)).toBeLessThanOrEqual(0)
  })
})
