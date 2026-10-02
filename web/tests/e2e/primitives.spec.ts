import { expect, test, type Locator } from '@playwright/test'

import { settle } from './helpers'

/**
 * The shared primitives, driven as a person would drive them.
 *
 * These run against `/specimens`, which renders the real `Button` and
 * `DataTable` with fixed sample rows — so what is asserted here is the
 * component, not this week's board. Unit tests cover what the markup says;
 * these cover what only a browser can answer: whether a header really stays
 * put, whether a key press sorts, whether a control is big enough to hit.
 */

/** The main sample table: the first one on the page. */
function sampleTable(page: import('@playwright/test').Page) {
  return page.getByRole('table', { name: /^Sample running backs/ }).first()
}

async function firstNames(table: Locator, count = 3) {
  const names = await table.getByRole('rowheader').getByRole('link').allInnerTexts()
  return names.slice(0, count)
}

test.beforeEach(async ({ page }) => {
  await page.goto('/specimens')
  await settle(page)
  await expect(page.getByRole('heading', { level: 1, name: 'Specimens' })).toBeVisible()
})

test('a header sorts from the keyboard, and says so', async ({ page }) => {
  const table = sampleTable(page)
  const projection = table.getByRole('columnheader', { name: /Projection/ })
  const player = table.getByRole('columnheader', { name: /Player/ })

  // Opens sorted by projection, largest first.
  await expect(projection).toHaveAttribute('aria-sort', 'descending')
  await expect(player).not.toHaveAttribute('aria-sort', /.+/)
  expect((await firstNames(table))[0]).toBe('Jahmyr Gibbs')

  // Enter on the sorted header reverses it.
  await projection.getByRole('button').focus()
  await page.keyboard.press('Enter')
  await expect(projection).toHaveAttribute('aria-sort', 'ascending')
  await expect(page).toHaveURL(/dir=asc/)

  // Space on another header moves the sort there, in that column's own first
  // direction: names open A to Z.
  await player.getByRole('button').focus()
  await page.keyboard.press('Space')
  await expect(player).toHaveAttribute('aria-sort', 'ascending')
  await expect(projection).not.toHaveAttribute('aria-sort', /.+/)
  expect((await firstNames(table))[0]).toBe('A rookie with no history')
  // The caption carries the sort for a reader who cannot see the arrow.
  await expect(table.locator('caption')).toHaveText(/sorted by player, ascending/)
})

test('a missing value sorts last in both directions', async ({ page }) => {
  const table = sampleTable(page)
  const lastNames = async () => (await table.getByRole('rowheader').getByRole('link').allInnerTexts()).slice(-3)

  expect(new Set(await lastNames())).toEqual(new Set(['A rookie with no history']))
  await table.getByRole('columnheader', { name: /Projection/ }).getByRole('button').click()
  await expect(table.getByRole('columnheader', { name: /Projection/ })).toHaveAttribute('aria-sort', 'ascending')
  expect(new Set(await lastNames())).toEqual(new Set(['A rookie with no history']))
})

test('the whole row follows its link, and a control inside it does not', async ({ page, isMobile }) => {
  const table = sampleTable(page)
  const row = table.getByRole('row').filter({ hasText: 'Derrick Henry' }).first()

  // A click on a plain cell — nowhere near the name — selects the row.
  await row.getByRole('cell').last().click()
  await expect(page).toHaveURL(/row=r03-0/)
  await expect(row).toHaveAttribute('aria-current', 'true')

  // One tab stop per row: the link, activated with Enter.
  const next = table.getByRole('row').filter({ hasText: 'Bijan Robinson' }).first()
  await next.getByRole('link').focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/row=r04-0/)
  await expect(next).toHaveAttribute('aria-current', 'true')
  await expect(row).not.toHaveAttribute('aria-current', 'true')

  // A button of its own inside a linked row does its own thing.
  const tiers = page.getByRole('table', { name: 'Sample running backs by tier' })
  const gibbs = tiers.getByRole('row').filter({ hasText: 'Jahmyr Gibbs' })
  const before = page.url()
  await gibbs.getByRole('button', { name: 'Bench' }).click()
  expect(page.url()).toBe(before)
  if (!isMobile) {
    await gibbs.getByRole('cell').nth(1).click()
    await expect(page).toHaveURL(/row=r01(?!-)/)
  }
})

test('the header stays in view while the page scrolls past it', async ({ page, isMobile }) => {
  const table = sampleTable(page)
  const header = table.getByRole('columnheader', { name: /Player/ })
  const lastRow = table.getByRole('row').last()

  if (isMobile) {
    // Too narrow for its columns: the table is its own scroller, and the
    // header sticks to the top of that.
    const frame = page.locator('[data-table-scrolls]').first()
    await expect(frame).toBeVisible()
    await lastRow.scrollIntoViewIfNeeded()
    await expect(lastRow).toBeInViewport()
    expect(await frame.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
    const [frameBox, headerBox] = [await frame.boundingBox(), await header.boundingBox()]
    expect(Math.round(headerBox!.y)).toBe(Math.round(frameBox!.y))
    return
  }

  await lastRow.scrollIntoViewIfNeeded()
  await expect(lastRow).toBeInViewport()
  await expect(header).toBeInViewport()
  // Directly under the application bar, not behind it.
  const bar = await page.locator('header').first().boundingBox()
  const box = await header.boundingBox()
  expect(Math.round(box!.y)).toBe(Math.round(bar!.y + bar!.height))
})

test('row height follows the density', async ({ page, isMobile }) => {
  test.skip(isMobile, 'cells wrap on a phone, so a row is as tall as its text')
  const table = sampleTable(page)
  const rowHeight = async () => Math.round((await table.getByRole('row').nth(1).boundingBox())!.height)

  expect(await rowHeight()).toBe(40)
  // The radio itself is visually hidden; its label is what a pointer hits.
  await page.getByText('Compact 32', { exact: true }).click()
  await expect(page).toHaveURL(/density=compact/)
  expect(await rowHeight()).toBe(32)
  await page.getByText('Comfortable 48', { exact: true }).click()
  await expect(page).toHaveURL(/density=comfortable/)
  expect(await rowHeight()).toBe(48)
  // The header is one height at every density.
  expect(Math.round((await table.getByRole('row').first().boundingBox())!.height)).toBe(32)
})

test('numbers are right-aligned in tabular figures, text is left-aligned', async ({ page }) => {
  const table = sampleTable(page)
  const row = table.getByRole('row').nth(1)
  const style = (cell: Locator) =>
    cell.evaluate((el) => {
      const computed = getComputedStyle(el)
      return { align: computed.textAlign, numeric: computed.fontVariantNumeric }
    })

  const projection = await style(row.getByRole('cell').last())
  expect(projection.align).toBe('right')
  expect(projection.numeric).toContain('tabular-nums')

  const status = await style(row.getByRole('cell').nth(1))
  expect(['left', 'start']).toContain(status.align)
  expect(status.numeric).not.toContain('tabular-nums')
})

test('every button can be hit: 24px at least, and 44px for a finger where it can grow', async ({ page, isMobile }) => {
  // WCAG 2.5.8 asks for 24 by 24. Measured on the box that receives the
  // press, which for the row-sized control includes its widened hit area.
  const sizes = await page.locator('main button:visible, main a[class*="inline-flex"]:visible').evaluateAll((controls) =>
    controls.map((control) => {
      const box = control.getBoundingClientRect()
      const hit = getComputedStyle(control, '::after')
      const grown = hit.position === 'absolute' && hit.content !== 'none'
      const extraX = grown ? -2 * parseFloat(hit.left) : 0
      const extraY = grown ? -2 * parseFloat(hit.top) : 0
      return {
        name: (control.getAttribute('aria-label') ?? control.textContent ?? '').trim().slice(0, 30),
        width: Math.round(box.width + extraX),
        height: Math.round(box.height + extraY),
        boxed: !control.className.includes('min-h-6'),
      }
    }),
  )
  expect(sizes.length).toBeGreaterThan(40)

  const tooSmall = sizes.filter((size) => size.height < 24 || size.width < 24)
  expect(tooSmall, `under 24px: ${JSON.stringify(tooSmall)}`).toEqual([])

  if (isMobile) {
    // Under a finger: 44px tall where the control grows, and 40px — one row —
    // for the row-sized control, which may not make its row taller.
    const cramped = sizes.filter((size) => size.boxed && size.height < 40)
    expect(cramped, `under 40px on touch: ${JSON.stringify(cramped)}`).toEqual([])
  }
})

test('a loading button keeps its width, stays focusable and refuses a second press', async ({ page }) => {
  const run = page.getByRole('button', { name: 'Run simulation' })
  const before = await run.boundingBox()

  await run.focus()
  await page.keyboard.press('Enter')
  await expect(run).toHaveAttribute('aria-busy', 'true')
  await expect(run).toBeDisabled()
  // Still focused: it did not use the `disabled` attribute to say so.
  await expect(run).toBeFocused()
  const after = await run.boundingBox()
  expect(Math.round(after!.width)).toBe(Math.round(before!.width))

  await page.getByRole('button', { name: 'Reset' }).click()
  await expect(run).not.toHaveAttribute('aria-busy', 'true')
})

test('an icon button is named, and the focus ring is visible on it', async ({ page }) => {
  const remove = page.getByRole('button', { name: 'Remove player' }).first()
  await expect(remove).toHaveAttribute('title', 'Remove player')
  await remove.focus()
  // Focused from script, so nudge the browser into keyboard modality first.
  await page.keyboard.press('Shift+Tab')
  await page.keyboard.press('Tab')
  const outline = await remove.evaluate((el) => {
    const computed = getComputedStyle(el)
    return { style: computed.outlineStyle, width: parseFloat(computed.outlineWidth) }
  })
  expect(outline.style).toBe('solid')
  expect(outline.width).toBeGreaterThanOrEqual(2)
})

test('a filter choice is a select only where its options do not fit the toolbar', async ({ page }) => {
  // The 20rem toolbar: position still fits, the four designations do not.
  const narrow = page.locator('[data-narrow-toolbar]')
  await expect(narrow.getByRole('radiogroup', { name: 'Position' })).toBeVisible()
  await expect(narrow.getByRole('radiogroup', { name: 'Designation' })).toHaveCount(0)
  const select = narrow.getByRole('combobox', { name: 'Designation' })
  await expect(select).toBeVisible()
  // A closed select shows one option, so each names what it chooses.
  await expect(select.locator('option')).toHaveText([
    'Designation: All',
    'Designation: Out & doubtful',
    'Designation: Questionable',
    'Designation: Practice only',
  ])

  // One value behind both drawings: the full-width toolbar follows the select.
  await select.selectOption({ label: 'Designation: Questionable' })
  const wide = page.getByRole('group', { name: 'Filter sample players', exact: true })
  const twin = wide.getByRole('combobox', { name: 'Designation' }).or(wide.getByRole('radio', { name: 'Questionable' }))
  await expect(twin.first()).toBeVisible()
  if ((await wide.getByRole('radio', { name: 'Questionable' }).count()) > 0) {
    await expect(wide.getByRole('radio', { name: 'Questionable' })).toBeChecked()
  } else {
    await expect(wide.getByRole('combobox', { name: 'Designation' })).toHaveValue('questionable')
  }

  // Nothing in either toolbar is wider than the toolbar it is in.
  for (const toolbar of [narrow.getByRole('group'), wide]) {
    const box = (await toolbar.boundingBox())!
    for (const control of await toolbar.locator(':is(input[type="search"], select, [role="radiogroup"])').all()) {
      const inner = (await control.boundingBox())!
      expect(Math.ceil(inner.x + inner.width)).toBeLessThanOrEqual(Math.ceil(box.x + box.width) + 1)
    }
  }
})

test('a filter chip removes its filter from a named button', async ({ page }) => {
  const remove = page.getByRole('button', { name: 'Show every game, not just DET at CAR' })
  await expect(remove).toBeVisible()
  const box = (await remove.boundingBox())!
  expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(24)
  await remove.click()
  await expect(remove).toHaveCount(0)
})
