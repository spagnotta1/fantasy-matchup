import { expect, test, type Locator, type Page, type Route } from '@playwright/test'

import { expectRowsLegible, pageOverflow, seedRoster, settle } from './helpers'

/**
 * Live, Usage, Injuries, Teams, My team and the draft board on the shared
 * table and the shared filter toolbar, and the first four as a list where a
 * phone has no room for their columns.
 *
 * What moving five hand-built tables onto one could quietly break, and a
 * picture would not show: a filter that no longer lands in the URL, a row
 * that stopped being a link, a column dropped to make a table fit, a refresh
 * that throws away where the reader was, an empty table with nothing in it.
 *
 * None of the first five sorts from its headers. Each has one order that is
 * the point of the page — highest live points, largest change, designation,
 * then projection — so there is no `aria-sort` on them to assert, and that
 * absence is asserted instead. The draft board does sort, and its sort has to
 * survive a filter.
 */

const TEAM = 'BAL'

const TABLE = {
  live: /^Unofficial live fantasy points/,
  usage: /risers|fallers/,
  injuries: /^Injury report for week/,
  team: /projected players for the week/,
  draft: /season value against ADP/,
}

function playerRows(table: Locator) {
  return table.locator('tr:has(a[data-row-link])')
}

/** Replies with the real response after `change` has been applied to it. */
async function rewrite(page: Page, pattern: RegExp, change: (body: any, call: number) => void) {
  let calls = 0
  await page.route(pattern, async (route: Route) => {
    const response = await route.fetch()
    const body = await response.json()
    calls += 1
    change(body, calls)
    await route.fulfill({ response, json: body })
  })
  return () => calls
}

// ---------------------------------------------------------------------------
// Live
// ---------------------------------------------------------------------------

test.describe('Live', () => {
  test.skip(({ isMobile }) => isMobile, 'behaviour, asserted once; widths are covered below')

  test('is a real table: named columns, a row header per player, numbers right-aligned', async ({ page }) => {
    await page.goto('/live')
    await settle(page)
    const table = page.getByRole('table', { name: TABLE.live })
    await expect(table).toBeVisible()

    for (const name of ['Player', 'Live', 'Projected', 'Final vs proj.', 'On the field', 'Stat line']) {
      await expect(table.getByRole('columnheader', { name, exact: true })).toBeVisible()
    }
    const rows = playerRows(table)
    expect(await rows.count()).toBeGreaterThan(10)
    await expect(rows.first().getByRole('rowheader')).toHaveCount(1)
    // The order is the page's, stated in the caption; no header sorts.
    await expect(table.locator('caption')).toContainText('highest live points first')
    await expect(table.locator('[aria-sort]')).toHaveCount(0)

    const style = (cell: Locator) =>
      cell.evaluate((el) => ({ align: getComputedStyle(el).textAlign, numeric: getComputedStyle(el).fontVariantNumeric }))
    for (const index of [0, 1, 2]) {
      const cell = await style(rows.first().getByRole('cell').nth(index))
      expect(cell.align).toBe('right')
      expect(cell.numeric).toContain('tabular-nums')
    }
    expect(['left', 'start']).toContain((await style(rows.first().getByRole('cell').nth(4))).align)

    // Highest first, as the caption says.
    const points = (await rows.locator('td:nth-child(2) .sr-only').allInnerTexts()).slice(0, 20).map(Number)
    expect(points).toEqual([...points].sort((a, b) => b - a))
  })

  test('position, search and the count work together, and live in the URL', async ({ page }) => {
    await page.goto('/live')
    await settle(page)
    const table = page.getByRole('table', { name: TABLE.live })
    const toolbar = page.getByRole('group', { name: 'Filter players' })
    const count = toolbar.locator('[aria-live]')
    await expect(count).toHaveText(/^\d+ players$/)
    const everyone = Number.parseInt(await count.innerText())

    // A radio group: the arrow keys move the choice.
    await toolbar.getByRole('radio', { name: 'All', exact: true }).focus()
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('ArrowRight')
    await expect(page).toHaveURL(/position=RB/)
    await expect(toolbar.getByRole('radio', { name: 'RB' })).toBeChecked()
    await expect(count).toHaveText(new RegExp(`^\\d+ of ${everyone} players$`))

    const team = (await playerRows(table).first().getByRole('rowheader').innerText()).match(/RB · (\w+)/)![1]
    await toolbar.getByRole('searchbox', { name: 'Search players' }).fill(team)
    await expect(page).toHaveURL(new RegExp(`query=${team}`))
    await expect(page).toHaveURL(/position=RB/)
    const headers = await playerRows(table).getByRole('rowheader').allInnerTexts()
    expect(headers.length).toBeGreaterThan(0)
    for (const header of headers) expect(header).toContain(`RB · ${team}`)

    // The link is the state: opening it again draws the same rows.
    await page.goto(page.url())
    await settle(page)
    await expect(page.getByRole('searchbox', { name: 'Search players' })).toHaveValue(team)
    await expect(playerRows(page.getByRole('table', { name: TABLE.live }))).toHaveCount(headers.length)

    await page.getByRole('button', { name: 'Clear search' }).click()
    await expect(page).not.toHaveURL(/query=/)
    await expect(page).toHaveURL(/position=RB/)
  })

  test('a game from the ticker becomes a chip in the toolbar, and the chip removes it', async ({ page }) => {
    await page.goto('/live')
    await settle(page)
    const tile = page.getByRole('list', { name: 'Games this week' }).getByRole('button').first()
    await tile.click()
    await expect(page).toHaveURL(/game=\d+/)
    await expect(tile).toHaveAttribute('aria-pressed', 'true')

    const remove = page.getByRole('group', { name: 'Filter players' }).getByRole('button', { name: /^Show every game/ })
    await expect(remove).toBeVisible()
    await remove.click()
    await expect(page).not.toHaveURL(/game=/)
    await expect(tile).toHaveAttribute('aria-pressed', 'false')
  })

  test('filters that match nobody say so, and offer the way back', async ({ page }) => {
    await page.goto('/live?query=zzzzzz&position=TE')
    await settle(page)
    await expect(page.getByRole('heading', { name: 'No players match' })).toBeVisible()
    await expect(page.locator('main table')).toHaveCount(0)
    await page.getByRole('button', { name: 'Clear filters' }).click()
    await expect(page).not.toHaveURL(/query=|position=/)
    await expect(page.getByRole('table', { name: TABLE.live })).toBeVisible()
  })

  test('the whole row opens the player', async ({ page }) => {
    await page.goto('/live')
    await settle(page)
    const row = playerRows(page.getByRole('table', { name: TABLE.live })).nth(3)
    const href = await row.locator('a[data-row-link]').getAttribute('href')
    await row.getByRole('cell').nth(1).click()
    await expect(page).toHaveURL(new RegExp(`${href}$`))
  })

  test('a game in progress is marked in words and a refresh keeps focus, scroll and filters', async ({ page }) => {
    // The first RB's game is put in progress, and each later reply gives him
    // six more points — enough to notice, not enough to reorder the table.
    let subject = ''
    const calls = await rewrite(page, /\/api\/v1\/live/, (body, call) => {
      const player = body.data.players.find((p: { position: string }) => p.position === 'RB')
      subject = player.player_id
      const game = body.data.games.find((g: { event_id: string }) => g.event_id === player.event_id)
      game.state = 'in'
      game.detail = '4:12 - 3rd Quarter'
      if (call > 1) player.live_points = Math.round((player.live_points + 6) * 10) / 10
    })
    await page.clock.install()
    await page.goto('/live?position=RB')
    await settle(page)

    const table = page.getByRole('table', { name: TABLE.live })
    const row = table.locator(`tbody tr:has(a[href="/players/${subject}"])`)
    await expect(row.getByRole('rowheader')).toContainText('In progress, 4:12 - 3rd Quarter')
    await expect(page.getByText(/Live · updates every 60s/)).toBeVisible()
    const before = Number(await row.locator('td:nth-child(2) .sr-only').innerText())

    // The seventh row, or the last on a Friday, when one game has been played
    // and the table is four backs long and too short to scroll.
    const link = playerRows(table)
      .nth(Math.min(6, (await playerRows(table).count()) - 1))
      .locator('a[data-row-link]')
    await link.focus()
    const room = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight)
    await page.evaluate(() => window.scrollTo(0, 420))
    const scrolled = await page.evaluate(() => window.scrollY)
    if (room > 0) expect(scrolled).toBeGreaterThan(0)
    const rowCount = await playerRows(table).count()

    await page.clock.fastForward(61_000)
    await expect.poll(calls).toBeGreaterThan(1)
    await expect(row.locator('td:nth-child(2) .sr-only')).toHaveText(String(Math.round((before + 6) * 10) / 10))

    await expect(link).toBeFocused()
    expect(await page.evaluate(() => window.scrollY)).toBe(scrolled)
    await expect(page).toHaveURL(/position=RB/)
    await expect(playerRows(table)).toHaveCount(rowCount)
  })

  test('loading, no games and a failed request each say what they are', async ({ page }) => {
    let mode: 'slow' | 'empty' | 'fail' = 'slow'
    await page.route(/\/api\/v1\/live/, async (route) => {
      if (mode === 'fail') return route.abort('internetdisconnected')
      const response = await route.fetch()
      const body = await response.json()
      if (mode === 'slow') await new Promise((resolve) => setTimeout(resolve, 2500))
      if (mode === 'empty') {
        body.data.games = []
        body.data.players = []
      }
      await route.fulfill({ response, json: body })
    })

    await page.goto('/live', { waitUntil: 'commit' })
    await expect(page.getByRole('heading', { level: 1, name: 'Live' })).toBeVisible()
    await expect(page.getByRole('status', { name: 'Loading data' })).toBeVisible()
    await expect(page.getByRole('table', { name: TABLE.live })).toBeVisible()

    mode = 'empty'
    await page.reload()
    await settle(page)
    await expect(page.getByRole('heading', { name: 'No games found for this week' })).toBeVisible()
    await expect(page.locator('main table')).toHaveCount(0)

    mode = 'fail'
    await page.reload()
    const alert = page.getByRole('alert')
    await expect(alert).toBeVisible({ timeout: 30_000 })
    await expect(alert.getByRole('button', { name: /try again/i })).toBeVisible()
  })
})

// ---------------------------------------------------------------------------
// Usage
// ---------------------------------------------------------------------------

test.describe('Usage', () => {
  test.skip(({ isMobile }) => isMobile, 'behaviour, asserted once; widths are covered below')

  const changes = async (table: Locator) =>
    (await playerRows(table).locator('td:nth-child(2)').allInnerTexts()).map((text) =>
      Number.parseInt(text.replace('−', '-').replace(/[^\d+-]/g, '')),
    )

  test('every column is there, the bar included, and the header explains it without an icon', async ({ page }) => {
    await page.goto('/usage')
    await settle(page)
    const table = page.getByRole('table', { name: TABLE.usage })
    for (const name of ['Player', 'Change, pct. pts', 'Avg → last', 'Projection']) {
      await expect(table.getByRole('columnheader', { name, exact: true })).toBeVisible()
    }
    const rows = playerRows(table)
    expect(await rows.count()).toBeGreaterThan(0)
    expect(await rows.count()).toBeLessThanOrEqual(25)
    await expect(table.getByRole('img', { name: /^Four-game average \d+%, last game \d+%$/ })).toHaveCount(await rows.count())

    const header = table.getByRole('columnheader', { name: 'Avg → last' })
    await expect(header.locator('svg')).toHaveCount(0)
    await header.getByText('Avg → last').hover()
    await expect(page.getByRole('tooltip')).toContainText('four-game average')
  })

  test('direction and position filter together, in the URL, largest change first', async ({ page }) => {
    await page.goto('/usage')
    await settle(page)
    const table = page.getByRole('table', { name: TABLE.usage })
    const rising = await changes(table)
    expect(rising.every((value) => value > 0)).toBe(true)
    expect(rising).toEqual([...rising].sort((a, b) => b - a))

    await page.getByRole('group', { name: /Choose a share/ }).getByText('Falling', { exact: true }).click()
    await expect(page).toHaveURL(/direction=down/)
    await expect(page.getByRole('heading', { name: 'Snap share: falling' })).toBeVisible()
    await page.getByRole('group', { name: /Choose a share/ }).getByText('WR', { exact: true }).click()
    await expect(page).toHaveURL(/position=WR/)
    await expect(page).toHaveURL(/direction=down/)

    const falling = await changes(page.getByRole('table', { name: TABLE.usage }))
    expect(falling.length).toBeGreaterThan(0)
    expect(falling.every((value) => value < 0)).toBe(true)
    expect(falling).toEqual([...falling].sort((a, b) => a - b))
    for (const header of await playerRows(page.getByRole('table', { name: TABLE.usage })).getByRole('rowheader').allInnerTexts()) {
      expect(header).toContain('WR · ')
    }
    // A minus sign and an arrow, not a colour alone.
    await expect(playerRows(page.getByRole('table', { name: TABLE.usage })).first().locator('td:nth-child(2)')).toContainText('−')
  })

  test('the whole row opens the player', async ({ page }) => {
    await page.goto('/usage')
    await settle(page)
    const row = playerRows(page.getByRole('table', { name: TABLE.usage })).nth(2)
    const href = await row.locator('a[data-row-link]').getAttribute('href')
    await row.getByRole('cell').last().click()
    await expect(page).toHaveURL(new RegExp(`${href}$`))
  })

  test('a filter that matches nobody is told apart from a week with nothing to compare', async ({ page }) => {
    // Quarterbacks have no target share, so this link matches nobody while the
    // board is full of players who do.
    await page.goto('/usage?metric=target&position=QB')
    await settle(page)
    const table = page.getByRole('table', { name: TABLE.usage })
    await expect(table.getByRole('columnheader', { name: 'Player' })).toBeVisible()
    await expect(page.getByRole('heading', { name: "No QB's target share is rising" })).toBeVisible()
    await page.getByRole('button', { name: 'Show every position' }).click()
    await expect(page).not.toHaveURL(/position=/)
    await expect(playerRows(page.getByRole('table', { name: TABLE.usage })).first()).toBeVisible()
  })

  test('nothing to compare, a slow board and a failed one each say what they are', async ({ page }) => {
    let mode: 'slow' | 'bare' | 'fail' = 'slow'
    await page.route(/\/api\/v1\/projections\?/, async (route) => {
      if (mode === 'fail') return route.abort('internetdisconnected')
      const response = await route.fetch()
      const body = await response.json()
      if (mode === 'slow') await new Promise((resolve) => setTimeout(resolve, 2500))
      if (mode === 'bare') {
        for (const row of body.data) row.projection.usage = { provenance: 'derived' }
      }
      await route.fulfill({ response, json: body })
    })

    await page.goto('/usage', { waitUntil: 'commit' })
    // The real header over placeholder rows, so nothing moves when rows arrive.
    const loading = page.getByRole('table', { name: TABLE.usage })
    await expect(loading).toHaveAttribute('aria-busy', 'true')
    await expect(loading.getByRole('columnheader', { name: 'Projection' })).toBeVisible()
    await expect(playerRows(page.getByRole('table', { name: TABLE.usage })).first()).toBeVisible()

    mode = 'bare'
    await page.reload()
    await settle(page)
    await expect(page.getByRole('heading', { name: 'No movement to show' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Show every position' })).toHaveCount(0)

    mode = 'fail'
    await page.reload()
    await expect(page.getByRole('alert')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('alert').getByRole('button', { name: /try again/i })).toBeVisible()
  })
})

// ---------------------------------------------------------------------------
// Injuries
// ---------------------------------------------------------------------------

/** One questionable quarterback on the report, and nobody else. */
function oneQuestionable(body: any) {
  let kept = false
  for (const row of body.data) {
    if (!kept && row.projection.player.position === 'QB') {
      kept = true
      row.projection.context.injury = {
        provenance: 'context',
        applied_to_projection: false,
        unapplied_reason: 'The model does not adjust for injuries.',
        report_status: 'Questionable',
        practice_status: 'Limited Participation in Practice',
        detail: 'Ankle',
        will_not_play: false,
        is_questionable_or_worse: true,
      }
    } else {
      row.projection.context.injury = null
    }
  }
}

test.describe('Injuries', () => {
  test.skip(({ isMobile }) => isMobile, 'behaviour, asserted once; widths are covered below')

  test('one table, grouped by designation, each group announced as a heading for its rows', async ({ page }) => {
    await page.goto('/injuries')
    await settle(page)
    const table = page.getByRole('table', { name: TABLE.injuries })
    await expect(table).toHaveCount(1)
    for (const name of ['Player', 'Injury', 'Practice', 'Projection']) {
      await expect(table.getByRole('columnheader', { name, exact: true })).toBeVisible()
    }

    const groups = table.locator('tbody')
    const total = await groups.count()
    expect(total).toBeGreaterThan(0)
    let players = 0
    for (let index = 0; index < total; index++) {
      const group = groups.nth(index)
      const heading = group.locator('th[scope="rowgroup"]')
      await expect(heading).toHaveText(/^(Ruled out|Doubtful|Questionable|On the practice report only)\s*\d+ players?$/)
      const rows = await playerRows(group).count()
      expect(await heading.innerText()).toContain(`${rows} player`)
      players += rows
    }

    // The toolbar's count is the same people.
    const summary = await page.getByRole('group', { name: 'Filter the report' }).locator('[aria-live]').innerText()
    expect(summary.match(/\d+/g)!.map(Number).reduce((a, b) => a + b, 0)).toBe(players)
  })

  test('a designation is said in words and marked by shape, beside the number it qualifies', async ({ page }) => {
    await page.goto('/injuries')
    await settle(page)
    const table = page.getByRole('table', { name: TABLE.injuries })
    const out = table.locator('tbody').filter({ has: page.locator('th[scope="rowgroup"]', { hasText: 'Ruled out' }) })
    test.skip((await out.count()) === 0, 'nobody is ruled out this week')

    const row = playerRows(out).first()
    const badge = row.getByRole('cell').nth(0).locator('span.rounded-full')
    await expect(badge).toHaveText(/out/i)
    await expect(badge.locator('svg')).toHaveCount(1)
    // The projection is still printed, with the caveat beside it.
    await expect(row.getByRole('cell').last()).toContainText(/\d+\.\d/)
    await expect(row.getByRole('cell').last()).toContainText('Ruled out — will not play')
  })

  test('position and designation filter together and live in the URL', async ({ page }) => {
    await page.goto('/injuries')
    await settle(page)
    const toolbar = page.getByRole('group', { name: 'Filter the report' })
    await toolbar.getByText('Questionable', { exact: true }).click()
    await expect(page).toHaveURL(/status=questionable/)
    await toolbar.getByText('WR', { exact: true }).click()
    await expect(page).toHaveURL(/position=WR/)
    await expect(page).toHaveURL(/status=questionable/)

    const table = page.getByRole('table', { name: TABLE.injuries })
    test.skip((await table.count()) === 0, 'no questionable receiver this week')
    await expect(table.locator('th[scope="rowgroup"]')).toHaveCount(1)
    await expect(table.locator('th[scope="rowgroup"]')).toContainText('Questionable')
    for (const header of await playerRows(table).getByRole('rowheader').allInnerTexts()) {
      expect(header).toContain('WR · ')
    }
  })

  test('a row opens the player, and a team inside it opens the team', async ({ page }) => {
    await page.goto('/injuries')
    await settle(page)
    const row = playerRows(page.getByRole('table', { name: TABLE.injuries })).first()
    const href = await row.locator('a[data-row-link]').getAttribute('href')

    const team = row.getByRole('rowheader').locator('a[href^="/teams/"]').first()
    const teamHref = await team.getAttribute('href')
    await team.click()
    await expect(page).toHaveURL(new RegExp(`${teamHref}$`))

    await page.goBack()
    await settle(page)
    await playerRows(page.getByRole('table', { name: TABLE.injuries })).first().getByRole('cell').nth(1).click()
    await expect(page).toHaveURL(new RegExp(`${href}$`))
  })

  test('filters that match nobody are told apart from an empty report', async ({ page }) => {
    let mode: 'one' | 'none' | 'fail' = 'one'
    await page.route(/\/api\/v1\/projections\?/, async (route) => {
      if (mode === 'fail') return route.abort('internetdisconnected')
      const response = await route.fetch()
      const body = await response.json()
      if (mode === 'one') oneQuestionable(body)
      else for (const row of body.data) row.projection.context.injury = null
      await route.fulfill({ response, json: body })
    })

    // It used to draw nothing at all here: no rows, and no word about why.
    await page.goto('/injuries?status=practice')
    await settle(page)
    await expect(page.getByRole('heading', { name: 'No players match these filters' })).toBeVisible()
    await expect(page.locator('main')).toContainText("1 player is on this week's report")
    await page.getByRole('button', { name: 'Clear filters' }).click()
    await expect(page).not.toHaveURL(/status=/)
    await expect(playerRows(page.getByRole('table', { name: TABLE.injuries }))).toHaveCount(1)

    mode = 'none'
    await page.reload()
    await settle(page)
    await expect(page.getByRole('heading', { name: 'No one on the report' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Clear filters' })).toHaveCount(0)

    mode = 'fail'
    await page.reload()
    await expect(page.getByRole('alert')).toBeVisible({ timeout: 30_000 })
  })
})

// ---------------------------------------------------------------------------
// Teams
// ---------------------------------------------------------------------------

test.describe('Teams', () => {
  test.skip(({ isMobile }) => isMobile, 'behaviour, asserted once; widths are covered below')

  test('the projected players are grouped by position, in the board\'s columns', async ({ page }) => {
    await page.goto(`/teams/${TEAM}`)
    await settle(page)
    const table = page.getByRole('table', { name: TABLE.team })
    for (const name of ['Player', 'Matchup', 'Range', 'Chance of 20+', 'Projection']) {
      await expect(table.getByRole('columnheader', { name, exact: true })).toBeVisible()
    }
    await expect(table.locator('[aria-sort]')).toHaveCount(0)

    const headings = await table.locator('th[scope="rowgroup"]').allInnerTexts()
    const names = headings.map((text) => text.replace(/\s*\d+ players?$/, ''))
    const order = ['Quarterbacks', 'Running backs', 'Wide receivers', 'Tight ends']
    expect(names).toEqual(order.filter((name) => names.includes(name)))
    expect(names.length).toBeGreaterThan(1)

    // The strip is on every row, whatever the card's width.
    const rows = await playerRows(table).count()
    await expect(table.getByRole('img', { name: /8 in 10 outcomes between/ })).toHaveCount(rows)

    // Within a position, the board's order: highest projection first.
    const first = table.locator('tbody').first()
    const points = (await playerRows(first).locator('td:last-child').allInnerTexts()).map((text) => Number.parseFloat(text))
    expect(points).toEqual([...points].sort((a, b) => b - a))
  })

  test('a row opens the player, and the other team opens from the page', async ({ page }) => {
    await page.goto(`/teams/${TEAM}`)
    await settle(page)
    const row = playerRows(page.getByRole('table', { name: TABLE.team })).first()
    const href = await row.locator('a[data-row-link]').getAttribute('href')
    await row.getByRole('cell').nth(2).click()
    await expect(page).toHaveURL(new RegExp(`${href}$`))
  })

  test('the schedule position stays in the URL beside the team', async ({ page }) => {
    await page.goto(`/teams/${TEAM}`)
    await settle(page)
    const schedule = page.getByRole('radiogroup', { name: 'Position' })
    await schedule.getByText('RB', { exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/teams/${TEAM}\\?sospos=RB`))
    await expect(page.getByRole('table', { name: TABLE.team })).toBeVisible()
  })

  test('a team with no projections, and a failed request, each say what they are', async ({ page }) => {
    let mode: 'empty' | 'fail' = 'empty'
    await page.route(/\/api\/v1\/teams\/\w+\/outlook/, async (route) => {
      if (mode === 'fail') return route.abort('internetdisconnected')
      const response = await route.fetch()
      const body = await response.json()
      body.data.players = []
      await route.fulfill({ response, json: body })
    })
    await page.goto(`/teams/${TEAM}`)
    await settle(page)
    await expect(page.getByRole('heading', { name: 'No projected players' })).toBeVisible()
    await expect(page.getByRole('table', { name: TABLE.team })).toHaveCount(0)

    mode = 'fail'
    await page.reload()
    await expect(page.getByRole('alert')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('link', { name: 'All teams' })).toBeVisible()
  })
})

// ---------------------------------------------------------------------------
// Draft board
// ---------------------------------------------------------------------------

test.describe('Draft board', () => {
  test.skip(({ isMobile }) => isMobile, 'behaviour, asserted once; widths are covered below')
  // The value board is the slowest response in the product on a cold cache.
  test.describe.configure({ timeout: 120_000 })

  const open = async (page: Page, query = '') => {
    await page.goto(`/draft-board${query}`)
    await settle(page)
    const table = page.getByRole('table', { name: TABLE.draft })
    await expect(table).toBeVisible({ timeout: 60_000 })
    return table
  }

  test('its filters are the shared toolbar: one named group, each control named', async ({ page }) => {
    await open(page)
    const toolbar = page.getByRole('group', { name: 'Choose a season and filter the board' })
    await expect(toolbar).toBeVisible()

    // The season is named in its options, since its label is not drawn.
    const season = toolbar.getByRole('combobox', { name: 'Season' })
    await expect(season.locator('option:checked')).toHaveText(/^\d{4} season$/)
    await expect(toolbar.getByRole('radiogroup', { name: 'Position' })).toBeVisible()
    await expect(toolbar.getByRole('radiogroup', { name: 'Show' })).toBeVisible()

    // One height, on one line.
    const tops = await toolbar
      .locator(':is(select, [role="radiogroup"])')
      .evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect()).map((box) => [box.top, box.height]))
    expect(new Set(tops.map(([, height]) => Math.round(height))).size).toBe(1)
    expect(new Set(tops.map(([top]) => Math.round(top))).size).toBe(1)

    await toolbar.getByRole('link', { name: 'Run a mock draft on this pool' }).click()
    await expect(page).toHaveURL(/\/mock-draft$/)
  })

  test('position and lens filter together, by keyboard, and live in the URL', async ({ page }) => {
    const table = await open(page)
    const toolbar = page.getByRole('group', { name: 'Choose a season and filter the board' })
    const everyone = await playerRows(table).count()

    // A radio group: the arrow keys move the choice.
    await toolbar.getByRole('radiogroup', { name: 'Position' }).getByRole('radio', { name: 'All', exact: true }).focus()
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('ArrowRight')
    await expect(page).toHaveURL(/position=RB/)
    await expect(toolbar.getByRole('radio', { name: 'RB' })).toBeChecked()
    await expect(toolbar.getByRole('radio', { name: 'RB' })).toBeFocused()

    await toolbar.getByText('We rank higher', { exact: true }).click()
    await expect(page).toHaveURL(/lens=value/)
    await expect(page).toHaveURL(/position=RB/)

    const rows = playerRows(table)
    const shown = await rows.count()
    expect(shown).toBeLessThan(everyone)
    if (shown > 0) {
      for (const header of await rows.getByRole('rowheader').allInnerTexts()) expect(header).toContain('RB · ')
      // "We rank higher" is a gap of three places or more, and says so.
      for (const gap of await rows.locator('td:nth-child(3)').allInnerTexts()) expect(gap).toMatch(/\+\d+/)
    }

    // The link is the state: opening it again draws the same rows.
    await page.goto(page.url())
    await settle(page)
    await expect(playerRows(page.getByRole('table', { name: TABLE.draft }))).toHaveCount(shown, { timeout: 60_000 })
    await expect(page.getByRole('radio', { name: 'RB' })).toBeChecked()
    await expect(page.getByRole('radio', { name: 'We rank higher' })).toBeChecked()
  })

  test('a filter leaves the sort alone, and a sort leaves the filters alone', async ({ page }) => {
    const table = await open(page)
    const toolbar = page.getByRole('group', { name: 'Choose a season and filter the board' })
    // The board opens the way a draft runs: by ADP, first pick first.
    await expect(table.getByRole('columnheader', { name: 'ADP' })).toHaveAttribute('aria-sort', 'ascending')

    await table.getByRole('button', { name: 'Season value' }).click()
    await expect(page).toHaveURL(/sort=value/)
    await expect(page).toHaveURL(/dir=desc/)

    await toolbar.getByText('WR', { exact: true }).click()
    await expect(page).toHaveURL(/position=WR/)
    await expect(page).toHaveURL(/sort=value/)
    await expect(table.getByRole('columnheader', { name: 'Season value' })).toHaveAttribute('aria-sort', 'descending')
    const values = (await playerRows(table).locator('td:nth-child(4)').allInnerTexts()).map(Number)
    expect(values.length).toBeGreaterThan(5)
    expect(values).toEqual([...values].sort((a, b) => b - a))

    await table.getByRole('button', { name: 'ADP' }).click()
    await expect(page).toHaveURL(/position=WR/)
    await expect(page).not.toHaveURL(/sort=/)
  })

  test('a lens that matches nobody says so, and a row still opens the player', async ({ page }) => {
    let empty = true
    await rewrite(page, /\/api\/v1\/mock-draft\/value-board/, (body) => {
      if (empty) for (const entry of body.data.entries) entry.rank_gap = 0
    })
    await open(page, '?lens=value')
    await expect(page.getByRole('heading', { name: 'No players match' })).toBeVisible()

    empty = false
    const table = await open(page)
    const row = playerRows(table).nth(2)
    const href = await row.locator('a[data-row-link]').getAttribute('href')
    await row.getByRole('cell').nth(2).click()
    await expect(page).toHaveURL(new RegExp(`${href}$`))
  })
})

// ---------------------------------------------------------------------------
// Every width
// ---------------------------------------------------------------------------

/**
 * What a row of each list must still say. A table drawn as a list has no
 * header row, so what the columns held has to be found in the row itself.
 */
const LISTS: Record<string, { value: string; row: RegExp[]; strips?: RegExp; everyRow?: boolean; groups?: RegExp }> = {
  Live: {
    value: 'Live points',
    // Where the game stands, the projection, and a stat line.
    row: [/(QB|RB|WR|TE) · \w+ · /, /Proj\. (\d+\.\d|—)/, /yds|No offensive stats yet/],
    // A player with no published range has no strip to draw the ball on.
    strips: /points scored so far, 8 in 10 outcomes between/,
  },
  Usage: {
    value: 'Change, pct. pts',
    row: [/(QB|RB|WR|TE) · \w+/, /[+−]\d+/, /\d+%[\s\S]*\d+%/, /Projection\s*\d+\.\d/],
    strips: /^Four-game average \d+%, last game \d+%$/,
    everyRow: true,
  },
  Injuries: {
    value: 'Projection',
    // Both teams, the designation's own words, and the number it qualifies.
    row: [/(QB|RB|WR|TE) · \w+ (vs|@) \w+/, /Out|Doubtful|Questionable|No designation/, /\d+\.\d/],
    groups: /^(Ruled out|Doubtful|Questionable|On the practice report only)\s*\d+ players?$/,
  },
  Teams: {
    value: 'Projected points',
    row: [/\d+\.\d/, /\d+% of 20\+/],
    strips: /8 in 10 outcomes between/,
    everyRow: true,
    groups: /^(Quarterbacks|Running backs|Wide receivers|Tight ends)\s*\d+ players?$/,
  },
}

/** The room under which a table of players is a list: `ROW_LIST_BELOW`, plus the page's gutters and the card's border. */
const LIST_BELOW = 480 + 34

const SCREENS: { name: string; path: string; table: RegExp; roster?: boolean; scrolls: boolean; slow?: boolean }[] = [
  { name: 'Live', path: '/live', table: TABLE.live, scrolls: true },
  { name: 'Usage', path: '/usage', table: TABLE.usage, scrolls: true },
  { name: 'Injuries', path: '/injuries', table: TABLE.injuries, scrolls: true },
  { name: 'Teams', path: `/teams/${TEAM}`, table: TABLE.team, scrolls: true },
  // Sorted from its headers, which a list has none of: it stays a table at
  // every width, scrolling inside its frame.
  { name: 'Draft board', path: '/draft-board', table: TABLE.draft, scrolls: true, slow: true },
  // My team never scrolls sideways: its rows fold onto two lines instead, so
  // Start, Bench and Remove are always on screen.
  { name: 'My team', path: '/my-team', table: /^Starting lineup/, roster: true, scrolls: false },
]

/** Every filter control is whole and on screen, and none wraps inside itself. */
async function expectFiltersFit(page: Page, width: number) {
  const controls = await page
    .locator('main [role="group"] :is(input[type="search"], select, [role="radiogroup"], button)')
    .evaluateAll((elements) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect()
        return {
          name: element.getAttribute('aria-label') ?? element.tagName,
          left: Math.floor(box.left),
          right: Math.ceil(box.right),
          height: Math.round(box.height),
        }
      }),
    )
  for (const control of controls) {
    expect(control.left, `${control.name} starts off screen`).toBeGreaterThanOrEqual(0)
    expect(control.right, `${control.name} runs off screen`).toBeLessThanOrEqual(width)
    // One line: a segmented control whose labels wrapped would be taller.
    expect(control.height, `${control.name} wrapped`).toBeLessThanOrEqual(44)
  }
}

for (const width of [1440, 1024, 820, 768, 412, 390, 360]) {
  test.describe(`at ${width}px`, () => {
    test.skip(({ isMobile }) => isMobile, 'the width is set here; the phone project adds nothing')
    test.use({ viewport: { width, height: 900 }, hasTouch: width < 1024 })

    for (const screen of SCREENS) {
      const list = width < LIST_BELOW ? LISTS[screen.name] : undefined

      test(
        list
          ? `${screen.name}: a list, with every column of the table in each row and nothing overlapping`
          : `${screen.name}: nothing overflows the page, no control is clipped, no column is dropped`,
        async ({ page }) => {
          if (screen.slow) test.setTimeout(120_000)
          if (screen.roster) await seedRoster(page)
          await page.goto(screen.path)
          await settle(page)
          const table = page.getByRole('table', { name: screen.table })

          if (list) {
            const frame = page.locator('main [data-row-list]')
            await expect(frame).toBeVisible()
            await expect(table).toHaveCount(0)
            // The page is the only thing that scrolls: no table in a frame of
            // its own, capped at the height of the screen.
            await expect(page.locator('main [data-table-scrolls]')).toHaveCount(0)
            expect(await pageOverflow(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)
            await expectFiltersFit(page, width)

            // A list has no header row, so it says once what its number is.
            await expect(frame.getByText(list.value, { exact: true })).toBeVisible()
            const rows = frame.locator('li > a[href^="/players/"]')
            const count = await rows.count()
            expect(count).toBeGreaterThan(0)
            for (const index of [0, Math.min(3, count - 1)]) {
              for (const part of list.row) await expect(rows.nth(index)).toContainText(part)
            }
            if (list.strips) {
              const strips = frame.getByRole('img', { name: list.strips })
              if (list.everyRow) await expect(strips).toHaveCount(count)
              else expect(await strips.count()).toBeGreaterThan(count / 2)
            }
            if (list.groups) {
              const headings = await frame.getByRole('heading', { level: 3 }).allInnerTexts()
              expect(headings.length).toBeGreaterThan(0)
              for (const heading of headings) expect(heading).toMatch(list.groups)
              // Each group is a region named by its heading.
              await expect(frame.locator('section[aria-labelledby]')).toHaveCount(headings.length)
            }
            await expectRowsLegible(rows, width)

            // One link per row, and it opens the player, by keyboard too.
            await expect(rows.first().locator('a, button')).toHaveCount(0)
            const href = await rows.nth(1).getAttribute('href')
            await rows.nth(1).focus()
            await page.keyboard.press('Enter')
            await expect(page).toHaveURL(new RegExp(`${href}$`))
            return
          }

          await expect(table).toBeVisible({ timeout: screen.slow ? 60_000 : undefined })
          expect(await pageOverflow(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)
          await expectFiltersFit(page, width)

          const frame = table.locator('xpath=..')
          const inner = await frame.evaluate((element) => element.scrollWidth - element.clientWidth)
          if (inner <= 0) {
            await expect(frame).not.toHaveAttribute('data-table-scrolls', 'true')
          } else {
            // Too narrow for its columns: it scrolls inside its own frame, the
            // player stays put, and the last column is still there to reach.
            expect(screen.scrolls, `${screen.name} must never scroll sideways`).toBe(true)
            await expect(frame).toHaveAttribute('data-table-scrolls', 'true')
            const first = table.locator('th[scope="row"]').first()
            const before = await first.boundingBox()
            await frame.evaluate((element) => element.scrollTo({ left: element.scrollWidth }))
            await expect.poll(() => frame.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
            expect((await first.boundingBox())?.x, 'the player column moved with the scroll').toBe(before?.x)
            const lastHeader = await table.getByRole('columnheader').last().boundingBox()
            const edge = await frame.boundingBox()
            expect(Math.floor(lastHeader!.x + lastHeader!.width), 'the last column cannot be reached').toBeLessThanOrEqual(
              Math.ceil(edge!.x + edge!.width),
            )
            // Enough of the frame is left beside the frozen column to read a number in.
            const frameBox = await frame.boundingBox()
            expect(frameBox!.width - before!.width, 'the frozen column leaves no room').toBeGreaterThanOrEqual(96)
          }

          // A name is never squeezed to a sliver.
          // (`th[scope="row"]`: a group heading is a row header too, to a browser.)
          const player = table.locator('th[scope="row"]').first()
          const name = await player.getByRole('link').first().boundingBox()
          expect(name!.width).toBeGreaterThanOrEqual(48)
          const cell = await player.boundingBox()
          expect(cell!.width, 'the player column').toBeGreaterThanOrEqual(140)
        },
      )
    }

    test('Injuries: the designation filter fits, as a segmented control or as a select', async ({ page }) => {
      await page.goto('/injuries')
      await settle(page)
      const toolbar = page.getByRole('group', { name: 'Filter the report' })
      const select = toolbar.getByRole('combobox', { name: 'Designation' })
      if ((await select.count()) > 0) {
        // Named in every option, since a closed select shows only one.
        await expect(select.locator('option').first()).toHaveText('Designation: All')
        await select.selectOption({ label: 'Designation: Questionable' })
      } else {
        await toolbar.getByRole('radiogroup', { name: 'Designation' }).getByText('Questionable', { exact: true }).click()
      }
      await expect(page).toHaveURL(/status=questionable/)
      expect(await pageOverflow(page)).toBeLessThanOrEqual(0)
    })

    test('Draft board: the lens filter fits, as a segmented control or as a select', async ({ page }) => {
      test.setTimeout(120_000)
      await page.goto('/draft-board')
      await settle(page)
      const toolbar = page.getByRole('group', { name: 'Choose a season and filter the board' })
      const select = toolbar.getByRole('combobox', { name: 'Show' })
      if ((await select.count()) > 0) {
        // It used to stay a segmented control here and wrap its labels onto two lines.
        await expect(select.locator('option').first()).toHaveText('Show: Everyone')
        await select.selectOption({ label: 'Show: Drafters rank higher' })
      } else {
        await toolbar.getByRole('radiogroup', { name: 'Show' }).getByText('Drafters rank higher', { exact: true }).click()
      }
      await expect(page).toHaveURL(/lens=reach/)
      await expectFiltersFit(page, width)
      expect(await pageOverflow(page)).toBeLessThanOrEqual(0)
    })
  })
}

test.describe('between a phone and a tablet', () => {
  test.skip(({ isMobile }) => isMobile, 'the width is set here')
  test.use({ viewport: { width: 600, height: 900 }, hasTouch: true })

  test('a table scrolls inside its frame with the group heading held in view', async ({ page }) => {
    await page.goto('/injuries')
    await settle(page)
    const table = page.getByRole('table', { name: TABLE.injuries })
    const frame = table.locator('xpath=..')
    await expect(frame).toHaveAttribute('data-table-scrolls', 'true')
    // Reachable by keyboard, since it scrolls.
    await expect(frame).toHaveAttribute('tabindex', '0')
    const heading = table.locator('th[scope="rowgroup"] > span').first()
    const before = await heading.boundingBox()
    await frame.evaluate((element) => element.scrollTo({ left: 300 }))
    await expect.poll(() => frame.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
    expect((await heading.boundingBox())?.x).toBe(before?.x)
    expect(await pageOverflow(page)).toBeLessThanOrEqual(0)
  })

  test('the drawing follows the room: a list when it narrows, the table again when it widens', async ({ page }) => {
    await page.goto('/usage')
    await settle(page)
    const table = page.getByRole('table', { name: TABLE.usage })
    const list = page.locator('main [data-row-list]')
    await expect(table).toBeVisible()
    const players = await playerRows(table).count()

    await page.setViewportSize({ width: 390, height: 900 })
    await expect(list).toBeVisible()
    await expect(table).toHaveCount(0)
    // The same players, in the same order.
    await expect(list.locator('li')).toHaveCount(players)

    await page.setViewportSize({ width: 600, height: 900 })
    await expect(table).toBeVisible()
    await expect(list).toHaveCount(0)
  })
})

test('on a phone every filter is a full touch target', async ({ page, isMobile }) => {
  test.skip(!isMobile, 'touch sizes exist only under a coarse pointer')
  test.setTimeout(120_000)
  for (const path of ['/rankings', '/live', '/usage', '/injuries', '/draft-board']) {
    await page.goto(path)
    await settle(page)
    const controls = page.locator('main [role="group"] :is(input[type="search"], select, [role="radiogroup"])')
    await expect(controls.first()).toBeVisible({ timeout: 60_000 })
    const sizes = await controls.evaluateAll((elements) =>
      elements.map((element) => ({
        name: element.getAttribute('aria-label') ?? element.id,
        height: Math.round(element.getBoundingClientRect().height),
      })),
    )
    expect(sizes.length, path).toBeGreaterThan(1)
    for (const size of sizes) expect(size.height, `${path} ${size.name}`).toBe(44)
  }
})

test('on a phone a status is said in words in the list, beside the number it qualifies', async ({ page, isMobile }) => {
  test.skip(!isMobile, 'the narrow drawing')
  await page.goto('/injuries')
  await settle(page)
  const frame = page.locator('main [data-row-list]')
  await expect(frame).toBeVisible()
  const out = frame.locator('section').filter({ has: page.getByRole('heading', { name: /^Ruled out/ }) })
  test.skip((await out.count()) === 0, 'nobody is ruled out this week')

  const row = out.locator('li > a').first()
  // The report's word and a glyph, not a colour alone.
  const badge = row.locator('span.rounded-full:has(svg)')
  await expect(badge).toHaveText(/out/i)
  // The projection is still printed, and the caveat is on screen with it,
  // where the table had it two columns away.
  await expect(row).toContainText(/\d+\.\d/)
  const caveat = row.getByText('Ruled out — will not play')
  await expect(caveat).toBeInViewport()
  const number = await row.locator(':scope > .justify-self-end').boundingBox()
  const words = await caveat.boundingBox()
  expect(words!.y - (number!.y + number!.height), 'the caveat is under the number').toBeLessThan(40)
  expect(Math.abs(words!.x + words!.width - (number!.x + number!.width)), 'at the same edge').toBeLessThanOrEqual(2)
})
