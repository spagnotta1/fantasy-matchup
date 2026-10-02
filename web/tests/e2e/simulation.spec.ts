import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Locator, type Page } from '@playwright/test'

import { pageOverflow, settle } from './helpers'

/**
 * A finished simulation, read from the top.
 *
 * The result used to sit under both lineup builders and the run controls: a
 * screen and a half down a desktop, three down a phone. What the redesign
 * promised and a picture cannot hold it to: that the answer is the first thing
 * on the page, with the estimate, both score ranges and the position gaps in
 * it; that each lineup folds to a line that still says whose it is and who is
 * in it, behind a real disclosure; that the page prints what the API returned
 * and nothing else; and that building, re-running and a refused run all still
 * work.
 */

interface BoardRow {
  projection: { player: { player_id: string; name: string; position: string | null } }
}

interface TeamResult {
  expected_score: number
  median_score: number
  p10: number
  p90: number
  win_probability: number
  players: { position: string | null; simulated_mean: number }[]
}

interface SimulationBody {
  data: { week: number; simulation: { iterations: number }; team_a: TeamResult; team_b: TeamResult }
}

/** Two lineups from the top of the board, as the link a manager would share. */
async function matchup(page: Page) {
  const response = await page.request.get('/api/v1/projections?limit=400')
  const board = ((await response.json()) as { data: BoardRow[] }).data
  const at = (position: string, index: number) => {
    const row = board.filter((entry) => entry.projection.player.position === position)[index]
    expect(row, `the board has a ${position} at ${index}`).toBeTruthy()
    return row.projection.player
  }
  const a = [['QB', at('QB', 0)], ['RB', at('RB', 0)], ['RB', at('RB', 2)], ['WR', at('WR', 0)], ['WR', at('WR', 2)], ['TE', at('TE', 0)], ['FLEX', at('RB', 4)]] as const
  const b = [['QB', at('QB', 1)], ['RB', at('RB', 1)], ['RB', at('RB', 3)], ['WR', at('WR', 1)], ['WR', at('WR', 3)], ['TE', at('TE', 1)], ['FLEX', at('WR', 4)]] as const
  const encode = (side: typeof a | typeof b) => side.map(([slot, player]) => `${slot}:${player.player_id}`).join(',')
  return {
    // 2,000 draws: the layout is under test, not the estimate's steadiness.
    url: `/simulation?a=${encode(a)}&b=${encode(b)}&sim=2000&mode=independent&seed=7`,
    a: a.map(([, player]) => player.name),
    b: b.map(([, player]) => player.name),
  }
}

const summary = (page: Page) => page.locator('[data-simulation-summary]')
const estimate = (page: Page) => summary(page).getByRole('region', { name: 'Estimated win probability' })
const range = (page: Page, label: string) => summary(page).getByRole('img', { name: new RegExp(`^${label}: 10th percentile`) })
const gaps = (page: Page) => summary(page).getByRole('region', { name: 'Where the gap is' })
const lineup = (page: Page, side: 'you' | 'opponent') => page.locator(`[data-lineup="${side}"]`)
const disclosure = (page: Page, whose: string) => page.getByRole('button', { name: new RegExp(`^Edit lineup\\s*, ${whose}$`) })
const runButton = (page: Page) => page.getByRole('button', { name: /^Run simulation$/ })

async function openMatchup(page: Page) {
  const teams = await matchup(page)
  await page.goto(teams.url)
  await settle(page)
  await expect(runButton(page)).toBeEnabled()
  return teams
}

/** Runs the matchup on the page and returns what the API answered. */
async function run(page: Page) {
  const answered = page.waitForResponse(
    (response) => response.url().includes('/api/v1/simulations') && response.request().method() === 'POST',
  )
  await runButton(page).click()
  const body = (await (await answered).json()) as SimulationBody
  await expect(summary(page)).toBeVisible({ timeout: 45_000 })
  return body.data
}

const points = (value: number) => value.toFixed(1)
const percent = (value: number) => `${Math.round(value * 100)}%`
/** Where an element starts down the page, whatever the scroll position. */
const top = (locator: Locator) => locator.evaluate((element) => Math.round(element.getBoundingClientRect().top + window.scrollY))
/** Every row's remove button in the two lineups (the run history has its own). */
const rowButtons = (page: Page) =>
  page.locator('[data-lineup]').getByRole('button', { name: /^Remove .* from / }).filter({ visible: true })

test('before a run the page is the two lineups, open, with nothing to fold', async ({ page }) => {
  await openMatchup(page)
  await expect(summary(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Edit lineup/ })).toHaveCount(0)
  await expect(rowButtons(page)).toHaveCount(14)
  // What a run will produce, where the rest of a result will be.
  await expect(page.getByText('An estimated win probability')).toBeVisible()
})

test('a finished run puts the answer first: the estimate, both ranges and the gaps', async ({ page, isMobile }) => {
  await openMatchup(page)
  await run(page)

  // The page has come to the result, and the reader's next Tab starts from it.
  await expect(page.getByRole('heading', { level: 2, name: 'Result' })).toBeInViewport()
  await expect(estimate(page)).toBeInViewport()
  await expect(range(page, 'Your team')).toBeInViewport()
  await expect(range(page, 'Opponent')).toBeInViewport()
  await expect(gaps(page).getByRole('img')).toHaveCount(4)
  if (!isMobile) {
    // A desktop's first screen holds all of it, and both lineups under it.
    await expect(gaps(page).getByRole('img').last()).toBeInViewport()
    await expect(disclosure(page, 'Your team')).toBeInViewport()
    await expect(disclosure(page, 'Opponent')).toBeInViewport()
  } else {
    // A phone's holds the estimate and both ranges; the gaps start within it
    // or directly under it.
    const heading = await gaps(page).getByRole('heading', { level: 3 }).boundingBox()
    expect(heading!.y).toBeLessThan(page.viewportSize()!.height * 1.15)
  }

  // Result, then the lineups, then the controls, then the rest.
  const order = [
    await top(summary(page)),
    await top(lineup(page, 'you')),
    await top(lineup(page, 'opponent')),
    await top(runButton(page)),
    await top(page.getByRole('heading', { level: 2, name: 'Most unpredictable players' })),
    await top(page.getByRole('heading', { level: 2, name: 'What this simulation assumes' })),
  ]
  expect([...order].sort((a, b) => a - b), 'the order down the page').toEqual(order)
})

test('the summary prints what the API returned, and nothing it did not', async ({ page }) => {
  await openMatchup(page)
  const result = await run(page)
  const { team_a: a, team_b: b } = result

  await expect(summary(page)).toContainText(`Week ${result.week}`)
  await expect(summary(page)).toContainText(`${result.simulation.iterations.toLocaleString('en-US')} simulated weeks`)

  // The estimate, said for a reader of the markup as well as drawn.
  await expect(estimate(page).getByRole('img')).toHaveAttribute(
    'aria-label',
    `Your team wins ${percent(a.win_probability)} of simulated weeks, Opponent wins ${percent(b.win_probability)}.`,
  )
  await expect(estimate(page)).toContainText('estimated win probability')
  await expect(estimate(page)).toContainText('not a prediction of the result')
  await expect(estimate(page)).not.toContainText(/confidence/i)

  // Each range: its published low, middle and high, and its average.
  for (const [label, team] of [['Your team', a], ['Opponent', b]] as const) {
    await expect(summary(page)).toContainText(`${label}${points(team.expected_score)} pts on average`)
    await expect(summary(page)).toContainText(
      `Low ${points(team.p10)} · Middle ${points(team.median_score)} · High ${points(team.p90)}`,
    )
  }

  // Each gap: the two sides' simulated means at the position, and their difference.
  const total = (team: TeamResult, position: string) =>
    team.players.filter((player) => player.position === position).reduce((sum, player) => sum + player.simulated_mean, 0)
  for (const position of ['QB', 'RB', 'WR', 'TE']) {
    const bar = gaps(page).getByRole('img', { name: new RegExp(`^${position}:`) })
    await expect(bar).toHaveAttribute(
      'aria-label',
      new RegExp(`^${position}: Your team ${points(total(a, position)).replace('.', '\\.')} points, Opponent ${points(total(b, position)).replace('.', '\\.')}\\.`),
    )
  }
  // And the sentence that says what a gap is not is still beside them.
  await expect(gaps(page)).toContainText('Each gap is an average, not a guaranteed result')
})

test('each lineup folds to a line that says whose it is and who is in it', async ({ page }) => {
  const teams = await openMatchup(page)
  await run(page)

  for (const [side, whose, names] of [['you', 'Your team', teams.a], ['opponent', 'Opponent', teams.b]] as const) {
    const card = lineup(page, side)
    await expect(disclosure(page, whose)).toHaveAttribute('aria-expanded', 'false')
    await expect(card.getByRole('heading', { level: 2, name: whose })).toBeVisible()
    await expect(card).toContainText('7/7')
    // The starters, in lineup order, on the line; the rows themselves put away.
    await expect(card.locator('.truncate').filter({ visible: true }).first()).toHaveText(names.join(', '))
    await expect(card.getByRole('button', { name: /^Remove / }).filter({ visible: true })).toHaveCount(0)
    const box = await card.boundingBox()
    expect(box!.height, `${whose}, folded`).toBeLessThanOrEqual(110)
  }
})

test('a lineup opens and shuts from the keyboard, and keeps its players', async ({ page }) => {
  const teams = await openMatchup(page)
  await run(page)

  const button = disclosure(page, 'Your team')
  const card = lineup(page, 'you')
  const rows = card.getByRole('button', { name: /^Remove / }).filter({ visible: true })
  const controlled = page.locator(`[id="${await button.getAttribute('aria-controls')}"]`)
  await expect(controlled).toBeHidden()

  await button.focus()
  await page.keyboard.press('Enter')
  await expect(button).toHaveAttribute('aria-expanded', 'true')
  await expect(controlled).toBeVisible()
  // The button that was pressed is the one that is there afterwards.
  await expect(button).toBeFocused()
  await expect(rows).toHaveCount(7)
  for (const name of teams.a) await expect(card.getByText(name, { exact: true }).first()).toBeVisible()
  // Its own actions are back with its rows, and the other lineup is as it was.
  await expect(card.getByRole('button', { name: 'Clear Your team' })).toBeVisible()
  await expect(disclosure(page, 'Opponent')).toHaveAttribute('aria-expanded', 'false')

  await page.keyboard.press('Space')
  await expect(button).toHaveAttribute('aria-expanded', 'false')
  await expect(controlled).toBeHidden()
  await expect(button).toBeFocused()
  await expect(rows).toHaveCount(0)

  // A pointer works too, on the other lineup.
  await disclosure(page, 'Opponent').click()
  await expect(disclosure(page, 'Opponent')).toHaveAttribute('aria-expanded', 'true')
  for (const name of teams.b) await expect(lineup(page, 'opponent').getByText(name, { exact: true }).first()).toBeVisible()
})

test('the lineups fold when the run starts, so nothing moves when the answer lands', async ({ page }) => {
  await openMatchup(page)
  // Held long enough to look at the page while it waits.
  await page.route('**/api/v1/simulations', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500))
    await route.continue()
  })
  await runButton(page).click()

  const waiting = page.getByText(/^Simulating [\d,]+ weeks…$/)
  await expect(waiting).toBeInViewport()
  await expect(disclosure(page, 'Your team')).toHaveAttribute('aria-expanded', 'false')
  await expect(disclosure(page, 'Opponent')).toHaveAttribute('aria-expanded', 'false')
  // Reported where the result will be: above the lineups.
  expect(await top(waiting)).toBeLessThan(await top(lineup(page, 'you')))
  const slot = await top(waiting.locator('xpath=ancestor::div[contains(@class,"rounded-card")][1]'))
  const heightWhileWaiting = await page.evaluate(() => document.documentElement.scrollHeight)

  await expect(summary(page)).toBeVisible({ timeout: 45_000 })
  // The answer takes the waiting card's place, and the page grows under it;
  // it does not collapse from a tall page to a short one.
  expect(Math.abs((await top(summary(page))) - slot), 'the result landed where the wait was').toBeLessThanOrEqual(2)
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeGreaterThanOrEqual(heightWhileWaiting)
  await expect(page.getByRole('heading', { level: 2, name: 'Result' })).toBeInViewport()
})

test('running again and adjusting still work, from a folded page', async ({ page }) => {
  await openMatchup(page)
  await run(page)
  await expect(summary(page)).toContainText('· Standard')

  // The way back to the controls is still at the end of the result.
  const adjust = page.getByRole('button', { name: /adjust and run again/i })
  await adjust.scrollIntoViewIfNeeded()
  await adjust.click()
  await expect(runButton(page)).toBeInViewport()

  // A different question, asked from there.
  await page.getByText('Linked (experimental)', { exact: true }).click()
  await run(page)
  await expect(summary(page)).toContainText('· Linked (experimental)')
  await expect(page.getByRole('heading', { level: 2, name: 'Result' })).toBeInViewport()
  await expect(disclosure(page, 'Your team')).toHaveAttribute('aria-expanded', 'false')
  expect(new URL(page.url()).searchParams.get('mode')).toBe('game_environment')
})

test('a refused run says so at the top and opens the lineups again', async ({ page }) => {
  await openMatchup(page)
  await page.route('**/api/v1/simulations', (route) =>
    route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 'unprojected_player',
        message: 'A starter has no projection for this week.',
        field: 'team_a',
        remedy: 'Replace the starter and run again.',
      }),
    }),
  )
  await runButton(page).click()

  await expect(page.locator('main').getByText('A starter has no projection for this week.')).toBeInViewport()
  await expect(summary(page)).toHaveCount(0)
  // A refusal is a thing to fix in a lineup: both are open, with every row.
  await expect(page.getByRole('button', { name: /^Edit lineup/ })).toHaveCount(0)
  await expect(rowButtons(page)).toHaveCount(14)
})

test('loading an earlier run goes back to building', async ({ page }) => {
  await openMatchup(page)
  await run(page)
  await page.getByRole('button', { name: 'Load', exact: true }).first().click()
  await expect(summary(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Edit lineup/ })).toHaveCount(0)
  await expect(rowButtons(page)).toHaveCount(14)
  await expect(runButton(page)).toBeEnabled()
})

test.describe('on a phone', () => {
  test.skip(({ isMobile }) => !isMobile, 'touch sizes are a phone\'s')

  test('the disclosure is a thumb\'s size, and the summary line takes its own line', async ({ page }) => {
    const teams = await openMatchup(page)
    await run(page)
    const button = disclosure(page, 'Your team')
    await button.scrollIntoViewIfNeeded()
    const target = await button.boundingBox()
    expect(target!.height, 'the disclosure button').toBeGreaterThanOrEqual(44)

    // Names under the title, not squeezed beside it.
    const names = lineup(page, 'you').locator('.truncate').filter({ visible: true }).first()
    await expect(names).toContainText(teams.a[0])
    expect((await names.boundingBox())!.y).toBeGreaterThan(target!.y + target!.height - 4)
    expect((await names.boundingBox())!.width).toBeGreaterThan(250)
  })
})

for (const width of [1440, 1024, 820, 768, 412, 390, 360]) {
  test.describe(`at ${width}px`, () => {
    test.skip(({ isMobile }) => isMobile, 'the width is set here; the phone project adds nothing')
    test.use({ viewport: { width, height: 900 }, hasTouch: width < 1024 })

    test('a finished result fits the page, with the answer in the first screen', async ({ page }) => {
      await openMatchup(page)
      await run(page)
      expect(await pageOverflow(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)

      await expect(estimate(page)).toBeInViewport()
      await expect(range(page, 'Your team')).toBeInViewport()

      // The two ranges: one scale, each wide enough to read, each named.
      const bars = await Promise.all([range(page, 'Your team').boundingBox(), range(page, 'Opponent').boundingBox()])
      expect(bars[0]!.x).toBe(bars[1]!.x)
      expect(bars[0]!.width).toBe(bars[1]!.width)
      expect(bars[0]!.width, 'a range wide enough to read').toBeGreaterThanOrEqual(200)

      // Nothing in the summary or a folded lineup runs past the screen.
      const edges = await page.evaluate((screen) => {
        const cards = [...document.querySelectorAll('[data-simulation-summary], [data-lineup]')]
        return cards.flatMap((card) =>
          [card, ...card.querySelectorAll('button, a, [role="img"], h2, h3, p')]
            .filter((element) => {
              const box = element.getBoundingClientRect()
              return box.width > 0 && (box.left < -0.5 || box.right > screen + 0.5)
            })
            .map((element) => `${element.tagName} "${(element.textContent ?? '').trim().slice(0, 30)}"`),
        )
      }, width)
      expect(edges).toEqual([])

      // Each position's two numbers and its gap are printed, not drawn over.
      const rows = await gaps(page).getByRole('img').evaluateAll((tracks) =>
        tracks.map((track) => ({
          inside: (track.textContent ?? '').trim(),
          before: (track.previousElementSibling?.textContent ?? '').trim(),
          after: (track.nextElementSibling?.textContent ?? '').trim(),
          width: track.getBoundingClientRect().width,
        })),
      )
      expect(rows).toHaveLength(4)
      for (const row of rows) {
        expect(row.inside).toBe('')
        expect(row.before).toMatch(/^\d+\.\d$/)
        expect(row.after).toMatch(/^\d+\.\d$/)
        expect(row.width, 'a gap bar wide enough to read').toBeGreaterThanOrEqual(60)
      }

      // An opened lineup still fits.
      await disclosure(page, 'Your team').click()
      await expect(disclosure(page, 'Your team')).toHaveAttribute('aria-expanded', 'true')
      expect(await pageOverflow(page), 'the page scrolls sideways with a lineup open').toBeLessThanOrEqual(0)
    })
  })
}

for (const theme of ['light', 'dark'] as const) {
  test(`axe and the outline: a finished result, ${theme}`, async ({ page }) => {
    await page.addInitScript((chosen) => window.localStorage.setItem('nflfp.theme', chosen), theme)
    await openMatchup(page)
    await run(page)
    // One lineup open, one folded: both states are on the page.
    await disclosure(page, 'Opponent').click()
    await expect(disclosure(page, 'Opponent')).toHaveAttribute('aria-expanded', 'true')

    const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(
      violations.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.target.join(' ')).join(' | ')}`),
    ).toEqual([])

    // One h1, and no level skipped on the way down.
    const levels = await page.locator('main').locator('h1, h2, h3, h4').evaluateAll((headings) =>
      headings.filter((heading) => heading.getBoundingClientRect().width > 0).map((heading) => Number(heading.tagName[1])),
    )
    expect(levels.filter((level) => level === 1)).toHaveLength(1)
    const skipped = levels.filter((level, index) => index > 0 && level - levels[index - 1] > 1)
    expect(skipped, `heading levels ${levels.join(' ')}`).toEqual([])

    // The parts of the summary are named for a screen reader's region list.
    await expect(summary(page).getByRole('region')).toHaveCount(3)
    await expect(summary(page).getByRole('region', { name: 'Where the scores land' })).toBeVisible()
  })
}
