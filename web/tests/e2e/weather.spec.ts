import { expect, test, type Page } from '@playwright/test'

import { settle } from './helpers'

/**
 * The rain chance is a 0–1 fraction on the wire and a percentage on screen.
 *
 * It used to arrive as 0–100 and be multiplied by 100 again: the player page,
 * the game page and the dashboard printed "6200%", and the Teams page — which
 * divided by 100 to compensate — was the only screen that got it right. The
 * same unit slip made every outdoor game with any rain in the forecast read as
 * bad weather.
 *
 * Forecasts change by the hour, so the weather block of every response is
 * replaced here with a fixed one. Everything else is the real API.
 */

interface Sample {
  playerId: string
  gameId: string
  team: string
}

/** Rewrites every weather block the API returns, whatever endpoint carries it. */
async function fixWeather(page: Page, rainChance: number) {
  const patch = (node: unknown): void => {
    if (Array.isArray(node)) {
      node.forEach(patch)
      return
    }
    if (node === null || typeof node !== 'object') return
    const record = node as Record<string, unknown>
    if ('precipitation_probability' in record && 'is_adverse' in record) {
      Object.assign(record, {
        is_indoor: false,
        temperature_f: 63,
        wind_mph: 3,
        precipitation_probability: rainChance,
        // The API's own rule: 20+ mph wind or a 60%+ rain chance, outdoors.
        is_adverse: rainChance >= 0.6,
        source: 'forecast',
      })
    }
    Object.values(record).forEach(patch)
  }

  await page.route(/\/api\/v1\/(projections|rankings|players|matchups|teams)/, async (route) => {
    const response = await route.fetch()
    if (!response.ok()) return route.fulfill({ response })
    const body: unknown = await response.json()
    patch(body)
    return route.fulfill({ response, json: body })
  })
}

/** A player, game and team that carry a weather block this week. */
async function sample(page: Page): Promise<Sample> {
  const response = await page.request.get('/api/v1/projections?limit=200')
  const body = (await response.json()) as {
    data: { projection: { player: { player_id: string }; game_id: string; team: string; context: { weather: unknown } } }[]
  }
  const entry = body.data.find((row) => row.projection.context.weather)
  expect(entry, 'at least one projected player has a weather block').toBeTruthy()
  const { projection } = entry!
  return { playerId: projection.player.player_id, gameId: projection.game_id, team: projection.team }
}

/** No percentage on the page runs past 100. "6200%" is the regression. */
async function expectNoImpossiblePercentages(page: Page) {
  const text = await page.locator('main').innerText()
  const impossible = [...text.matchAll(/(\d[\d,.]*)%/g)]
    .map((match) => Number(match[1]!.replace(/,/g, '')))
    .filter((value) => value > 100)
  expect(impossible, 'percentages above 100 on the page').toEqual([])
}

const CASES: [fraction: number, shown: string][] = [
  [0, '0%'],
  [0.01, '1%'],
  [0.02, '2%'],
  [0.05, '5%'],
  [0.62, '62%'],
  [1, '100%'],
]

for (const [fraction, shown] of CASES) {
  test(`the player page shows a ${shown} rain chance as ${shown}`, async ({ page }) => {
    const { playerId } = await sample(page)
    await fixWeather(page, fraction)
    await page.goto(`/players/${playerId}`)
    await settle(page)

    const row = page.locator('dt', { hasText: 'Chance of rain/snow' }).locator('xpath=..')
    await expect(row.locator('dd')).toHaveText(shown)
    await expectNoImpossiblePercentages(page)

    // The banner follows the documented threshold, not the mere presence of rain.
    const banner = page.getByText(/bad-weather game/i)
    if (fraction >= 0.6) await expect(banner).toBeVisible()
    else await expect(banner).toHaveCount(0)
  })
}

test('the game page shows the rain chance as a percentage', async ({ page }) => {
  const { gameId } = await sample(page)
  await fixWeather(page, 0.62)
  await page.goto(`/matchups/${gameId}`)
  await settle(page)

  const row = page.locator('dt', { hasText: 'Chance of rain/snow' }).locator('xpath=..')
  await expect(row.locator('dd')).toHaveText('62%')
  await expectNoImpossiblePercentages(page)
})

test('the team page shows the rain chance as a percentage', async ({ page }) => {
  const { team } = await sample(page)
  await fixWeather(page, 0.62)
  await page.goto(`/teams/${team}`)
  await settle(page)

  await expect(page.locator('main')).toContainText('62% precip')
  await expectNoImpossiblePercentages(page)
})

test('the dashboard weather list shows the rain chance as a percentage', async ({ page }) => {
  await fixWeather(page, 0.62)
  await page.goto('/')
  await settle(page)

  await page.getByRole('radiogroup', { name: /which risk to show/i }).getByText('Weather').click()
  await expect(page.locator('main')).toContainText('62% precipitation')
  await expectNoImpossiblePercentages(page)
})

test('a light rain chance does not put a game on the dashboard weather list', async ({ page }) => {
  await fixWeather(page, 0.02)
  await page.goto('/')
  await settle(page)

  await page.getByRole('radiogroup', { name: /which risk to show/i }).getByText('Weather').click()
  await expect(page.locator('main')).toContainText(/no weather concerns/i)
})
