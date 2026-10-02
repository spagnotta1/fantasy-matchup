import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Locator, type Page } from '@playwright/test'

import { expectRowsLegible, pageOverflow, seedRoster, settle } from './helpers'

/**
 * Compare, and the way to it from a list.
 *
 * What the redesign promised and a picture cannot hold it to: that every range
 * on the page is drawn on one scale from one left edge, on a phone as on a
 * desktop; that the numbers stay side by side on a phone with their labels in
 * view; that a row's best number is marked once and quietly; and that two
 * players ticked on the board or on My team arrive at the comparison without a
 * search box, with the ticks surviving what a reader does in between.
 */

interface BoardRow {
  projection: {
    player: { player_id: string; name: string; position: string | null }
    prediction: { points: { ceiling: number | null } }
  }
}

async function board(page: Page) {
  const response = await page.request.get('/api/v1/projections?limit=400')
  return ((await response.json()) as { data: BoardRow[] }).data
}

/** The first `count` players at a position, in board order. */
async function players(page: Page, position: string, count: number) {
  const rows = (await board(page)).filter((row) => row.projection.player.position === position).slice(0, count)
  expect(rows.length, `the board has ${count} at ${position}`).toBe(count)
  return rows.map((row) => ({ ...row.projection.player, ceiling: row.projection.prediction.points.ceiling ?? 0 }))
}

const tick = (page: Page, name: string) => page.getByRole('checkbox', { name: `Select ${name} to compare` })
const bar = (page: Page) => page.getByRole('region', { name: 'Players selected to compare' })
const ruler = (page: Page) => page.locator('[data-range-ruler]')
const strips = (page: Page) => ruler(page).getByRole('img', { name: /8 in 10 outcomes between/ })
const grid = (page: Page) => page.getByRole('table', { name: /Selected players compared/ })

async function openComparison(page: Page, ids: string[]) {
  await page.goto(`/compare?players=${ids.join(',')}`)
  await settle(page)
  await expect(page.getByRole('heading', { level: 2, name: 'Ranges on one scale' })).toBeVisible()
}

/** Every strip starts at one edge and is one width: the precondition for comparing them by eye. */
async function expectOneRuler(page: Page, count: number) {
  await expect(strips(page)).toHaveCount(count)
  const boxes = await strips(page).evaluateAll((elements) =>
    elements.map((element) => {
      const box = element.getBoundingClientRect()
      return { left: Math.round(box.left), width: Math.round(box.width) }
    }),
  )
  expect(new Set(boxes.map((box) => box.left)).size, `strips start at ${boxes.map((box) => box.left).join(', ')}`).toBe(1)
  expect(new Set(boxes.map((box) => box.width)).size, `strips are ${boxes.map((box) => box.width).join(', ')} wide`).toBe(1)
  expect(boxes[0].width, 'a strip wide enough to read').toBeGreaterThanOrEqual(80)
}

/** No row of the side-by-side table marks more than one number, and none says BEST. */
async function expectQuietMarks(page: Page) {
  const perRow = await grid(page)
    .locator('tbody tr')
    .evaluateAll((rows) => rows.map((row) => row.querySelectorAll('[data-best-mark]').length))
  expect(perRow.length).toBeGreaterThan(8)
  expect(Math.max(...perRow), 'marks in one row').toBeLessThanOrEqual(1)
  expect(perRow.some((count) => count === 1), 'some row has a leader').toBe(true)
  await expect(grid(page).getByText('Best', { exact: true })).toHaveCount(0)
}

test.describe('on a wide screen', () => {
  test.skip(({ isMobile }) => isMobile, 'the phone drawing is covered below')

  test('the ranges share one ruler, and the heading says what its scale is', async ({ page }) => {
    const backs = await players(page, 'RB', 3)
    await openComparison(page, backs.map((player) => player.player_id))

    await expect(ruler(page).getByRole('table')).toBeVisible()
    await expectOneRuler(page, 3)
    // The scale ends on the yard line above the highest ceiling being compared.
    const scale = Math.max(5, Math.ceil(Math.max(...backs.map((player) => player.ceiling)) / 5) * 5)
    await expect(ruler(page).getByRole('columnheader', { name: `Range, 0 to ${scale} points` })).toBeVisible()
    for (const player of backs) await expect(ruler(page).getByRole('rowheader', { name: new RegExp(player.name) })).toBeVisible()

    // The glance comes before the detail.
    const top = await ruler(page).boundingBox()
    const below = await grid(page).boundingBox()
    expect(top!.y).toBeLessThan(below!.y)
    // And the detail no longer draws a strip per column.
    await expect(grid(page).getByRole('img')).toHaveCount(0)
  })

  test('a row marks its best number once, with a dot and not the word', async ({ page }) => {
    const backs = await players(page, 'RB', 3)
    await openComparison(page, backs.map((player) => player.player_id))
    await expectQuietMarks(page)
    // Said in words to a reader who cannot see a dot.
    await expect(grid(page).locator('tbody tr').first().locator('.sr-only', { hasText: 'best in this row' })).toHaveCount(1)
  })

  test('two players ticked on the board are one press from their comparison', async ({ page }) => {
    const [first, second] = (await board(page)).slice(0, 2).map((row) => row.projection.player)
    await page.goto('/rankings')
    await settle(page)
    await expect(bar(page)).toHaveCount(0)

    await tick(page, first.name).check()
    await expect(bar(page)).toContainText('1 selected')
    // One player is not a comparison: the button is there and is not a link.
    await expect(bar(page).getByRole('button', { name: 'Compare' })).toBeDisabled()
    await expect(bar(page).getByRole('link')).toHaveCount(0)

    await tick(page, second.name).check()
    await expect(bar(page)).toContainText('2 selected')
    await expect(bar(page)).toContainText(first.name)
    await expect(bar(page).getByRole('link', { name: 'Compare 2' })).toHaveAttribute(
      'href',
      `/compare?players=${first.player_id},${second.player_id}`,
    )
    // The ticks are in the address, so a reload or a shared link keeps them.
    expect(new URL(page.url()).searchParams.get('compare')).toBe(`${first.player_id},${second.player_id}`)

    // It follows the page down: the second player may be forty rows below the first.
    await page.mouse.wheel(0, 2400)
    await expect(bar(page)).toBeInViewport()

    await bar(page).getByRole('link', { name: 'Compare 2' }).click()
    await expect(page).toHaveURL(/\/compare\?players=/)
    await expectOneRuler(page, 2)
  })

  test('a press beside the box ticks it, and does not open the player', async ({ page }) => {
    const [first] = (await board(page)).map((row) => row.projection.player)
    await page.goto('/rankings')
    await settle(page)

    const cell = tick(page, first.name).locator('xpath=ancestor::td')
    await cell.click({ position: { x: 3, y: 4 } })
    await expect(tick(page, first.name)).toBeChecked()
    await expect(page).toHaveURL(/\/rankings\?/)

    // Ticking a row deep in the board does not throw the page to its top.
    await page.mouse.wheel(0, 900)
    const before = await page.evaluate(() => window.scrollY)
    expect(before).toBeGreaterThan(300)
    await page.getByRole('checkbox', { name: /to compare$/ }).nth(24).check()
    await expect(bar(page)).toContainText('2 selected')
    expect(await page.evaluate(() => window.scrollY)).toBe(before)
  })

  test('the ticks cross a change of position, and are still there after Back', async ({ page }) => {
    const [back] = await players(page, 'RB', 1)
    const [receiver] = await players(page, 'WR', 1)
    await page.goto('/rankings/RB')
    await settle(page)
    await tick(page, back.name).check()

    await page.getByRole('navigation', { name: 'Position' }).getByRole('link', { name: 'WR', exact: true }).click()
    await expect(page).toHaveURL(/\/rankings\/WR\?compare=/)
    // The running back is not on this board, and the bar still says who he is.
    await expect(tick(page, back.name)).toHaveCount(0)
    await expect(bar(page)).toContainText('1 selected')

    await tick(page, receiver.name).check()
    await expect(bar(page)).toContainText(`${back.name}, ${receiver.name}`)
    await bar(page).getByRole('link', { name: 'Compare 2' }).click()
    await expect(page).toHaveURL(new RegExp(`/compare\\?players=${back.player_id},${receiver.player_id}`))
    await expectOneRuler(page, 2)

    await page.goBack()
    await expect(page).toHaveURL(/\/rankings\/WR\?compare=/)
    await expect(tick(page, receiver.name)).toBeChecked()
    await expect(bar(page)).toContainText('2 selected')

    await bar(page).getByRole('button', { name: 'Clear' }).click()
    await expect(bar(page)).toHaveCount(0)
    await expect(tick(page, receiver.name)).not.toBeChecked()
    expect(new URL(page.url()).searchParams.has('compare')).toBe(false)
  })

  test('six is the most, and the board says so before a seventh is refused', async ({ page }) => {
    const top = (await board(page)).slice(0, 7).map((row) => row.projection.player)
    await page.goto(`/rankings?compare=${top.slice(0, 6).map((player) => player.player_id).join(',')}`)
    await settle(page)

    await expect(bar(page)).toContainText('6 selected')
    await expect(bar(page)).toContainText('6 is the most that can be compared')
    await expect(tick(page, top[6].name)).toBeDisabled()
    await expect(tick(page, top[0].name)).toBeEnabled()

    await tick(page, top[0].name).uncheck()
    await expect(bar(page)).toContainText('5 selected')
    await expect(tick(page, top[6].name)).toBeEnabled()
  })

  test('the cards hold no box, and still offer a selection that arrived in the link', async ({ page }) => {
    const [first, second] = (await board(page)).slice(0, 2).map((row) => row.projection.player)
    await page.goto(`/rankings?view=cards&compare=${first.player_id},${second.player_id}`)
    await settle(page)
    await expect(page.getByRole('checkbox')).toHaveCount(0)
    await expect(bar(page).getByRole('link', { name: 'Compare 2' })).toBeVisible()
  })
})

test.describe('on a phone', () => {
  test.skip(({ isMobile }) => !isMobile, 'the wide drawing is covered above')

  test('two players: one ruler, and the numbers side by side with nothing to scroll', async ({ page }) => {
    const backs = await players(page, 'RB', 2)
    await openComparison(page, backs.map((player) => player.player_id))
    const width = page.viewportSize()!.width

    // The ruler is the board's two-line row, and the strips still line up.
    await expect(ruler(page).getByRole('table')).toHaveCount(0)
    await expectOneRuler(page, 2)
    await expectRowsLegible(ruler(page).locator('li > a'), width)

    // One table, both players' columns on screen: nobody is a second list.
    await expect(grid(page)).toBeVisible()
    await expect(grid(page).locator('xpath=..')).not.toHaveAttribute('data-table-scrolls', 'true')
    for (const player of backs) {
      const header = await grid(page).getByRole('columnheader', { name: new RegExp(player.name) }).boundingBox()
      expect(header!.x).toBeGreaterThanOrEqual(0)
      expect(Math.floor(header!.x + header!.width), `${player.name}'s column`).toBeLessThanOrEqual(width)
    }
    await expectQuietMarks(page)
    expect(await pageOverflow(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)
  })

  test('three players: the table scrolls in its own frame and the metric column stays', async ({ page }) => {
    const backs = await players(page, 'RB', 3)
    await openComparison(page, backs.map((player) => player.player_id))
    await expectOneRuler(page, 3)
    expect(await pageOverflow(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)
    await expectMetricHeld(grid(page))
  })

  test('two rows ticked on My team reach their comparison, with the bar clear of the navigation', async ({ page }) => {
    const roster = await seedRoster(page)
    await page.goto('/my-team')
    await settle(page)

    const boxes = page.getByRole('checkbox', { name: /to compare$/ })
    await expect(boxes).toHaveCount(roster.length)
    // The box's hit area is the cell: a finger's width, a row's height.
    const target = await boxes.first().locator('xpath=ancestor::label').boundingBox()
    expect(target!.width, 'the tick target').toBeGreaterThanOrEqual(44)
    expect(target!.height, 'the tick target').toBeGreaterThanOrEqual(40)

    await boxes.nth(1).check()
    await boxes.nth(2).check()
    await expect(bar(page)).toBeInViewport()
    await expect(bar(page)).toContainText('2 selected')
    expect(new URL(page.url()).searchParams.get('compare')?.split(',')).toHaveLength(2)

    // Above the navigation bar, not behind it, and inside the screen.
    const panel = await bar(page).locator('> div').boundingBox()
    const nav = await page.getByRole('navigation', { name: 'Main' }).filter({ visible: true }).boundingBox()
    expect(Math.floor(panel!.y + panel!.height), 'the bar reaches into the navigation').toBeLessThanOrEqual(Math.ceil(nav!.y))
    expect(panel!.x).toBeGreaterThanOrEqual(0)
    expect(Math.floor(panel!.x + panel!.width)).toBeLessThanOrEqual(page.viewportSize()!.width)
    expect(await pageOverflow(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)

    await bar(page).getByRole('link', { name: 'Compare 2' }).click()
    await expect(page).toHaveURL(/\/compare\?players=/)
    await expectOneRuler(page, 2)
  })

  test('the board list has no boxes, and its rows are as they were', async ({ page }) => {
    await page.goto('/rankings/RB')
    await settle(page)
    await expect(page.getByRole('checkbox')).toHaveCount(0)
    await expect(bar(page)).toHaveCount(0)
  })
})

/** Where the side-by-side table is wider than its frame, it scrolls there with the metric held. */
async function expectMetricHeld(table: Locator) {
  const frame = table.locator('xpath=..')
  await expect(frame).toHaveAttribute('data-table-scrolls', 'true')
  const first = table.locator('th[scope="row"]').first()
  const before = await first.boundingBox()
  await frame.evaluate((element) => element.scrollTo({ left: element.scrollWidth }))
  await expect.poll(() => frame.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
  expect((await first.boundingBox())?.x, 'the metric column moved with the scroll').toBe(before?.x)
  const last = await table.getByRole('columnheader').last().boundingBox()
  const edge = await frame.boundingBox()
  expect(Math.floor(last!.x + last!.width), 'the last player cannot be reached').toBeLessThanOrEqual(Math.ceil(edge!.x + edge!.width))
}

for (const width of [1024, 820, 390, 360]) {
  test.describe(`at ${width}px`, () => {
    test.skip(({ isMobile }) => isMobile, 'the width is set here; the phone project adds nothing')
    test.use({ viewport: { width, height: 900 }, hasTouch: width < 1024 })

    test('three players fit the page, on one ruler, with every column reachable', async ({ page }) => {
      const backs = await players(page, 'RB', 3)
      await openComparison(page, backs.map((player) => player.player_id))
      expect(await pageOverflow(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)
      await expectOneRuler(page, 3)
      if (width < 640) await expectRowsLegible(ruler(page).locator('li > a'), width)

      const frame = grid(page).locator('xpath=..')
      const inner = await frame.evaluate((element) => element.scrollWidth - element.clientWidth)
      if (inner > 0) await expectMetricHeld(grid(page))
    })
  })
}

for (const theme of ['light', 'dark'] as const) {
  test(`axe: a comparison, and a list with players ticked, ${theme}`, async ({ page, isMobile }) => {
    const roster = await seedRoster(page, theme)
    const backs = await players(page, 'RB', 3)
    const rules = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']
    const violations = async () =>
      (await new AxeBuilder({ page }).withTags(rules).analyze()).violations.map(
        (violation) => `${violation.id}: ${violation.nodes.map((node) => node.target.join(' ')).join(' | ')}`,
      )

    await openComparison(page, backs.map((player) => player.player_id))
    expect(await violations()).toEqual([])

    await page.goto(`/my-team?compare=${roster.slice(2, 4).join(',')}`)
    await settle(page)
    await expect(bar(page)).toContainText('2 selected')
    expect(await violations()).toEqual([])

    if (isMobile) return
    await page.goto(`/rankings/RB?compare=${backs[0].player_id}`)
    await settle(page)
    await expect(tick(page, backs[0].name)).toBeChecked()
    expect(await violations()).toEqual([])
  })
}
