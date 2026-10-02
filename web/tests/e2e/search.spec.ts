import { expect, test, type Page } from '@playwright/test'

import { matchKind } from '../../src/utils/search'
import { settle } from './helpers'

/**
 * Search relevance.
 *
 * "gib" used to open on a quarterback who last played in 2009, because his
 * first name starts with it, ahead of this week's RB1, whose surname does. The
 * first result is the one Enter opens, so it has to be the player a manager
 * means.
 *
 * Nothing here names a player. Each check derives what it expects from the
 * board the API is serving, so it holds for any published week.
 */

interface BoardRow {
  projection: { player: { player_id: string; name: string } }
}

/** This week's projected players: name and points, in board order. */
async function board(page: Page) {
  const response = await page.request.get('/api/v1/projections?limit=1000')
  const rows = ((await response.json()) as { data: BoardRow[] }).data
  return rows.map((row) => row.projection.player.name)
}

async function openPalette(page: Page, isMobile: boolean) {
  await page.goto('/')
  await settle(page)
  if (isMobile) await page.getByRole('button', { name: /search and all pages/i }).click()
  else await page.keyboard.press('Control+k')
  await expect(page.getByRole('combobox', { name: /search players, teams and pages/i })).toBeVisible()
}

/** The names under "Players" in the palette, in the order shown. */
async function paletteSearch(page: Page, term: string) {
  const responded = page.waitForResponse((response) => response.url().includes('/api/v1/search'))
  await page.getByRole('combobox', { name: /search players, teams and pages/i }).fill(term)
  await responded
  // The board the ranking reads may still be arriving; the order settles with it.
  await page.waitForLoadState('networkidle')
  // Player rows carry an avatar; team and page rows carry a logo or an icon.
  await expect(page.locator('dialog [role="option"] span[class*="rounded-full"]').first()).toBeVisible()
  return page.evaluate(() =>
    [...document.querySelectorAll('dialog [role="option"]')]
      .filter((option) => option.querySelector('span[class*="rounded-full"]'))
      .map((option) => option.querySelector('span.block')?.textContent?.trim() ?? ''),
  )
}

/** A result may not come before another that matched better, or that is projected when it is not. */
function expectRelevanceOrder(results: string[], term: string, projected: Set<string>) {
  const keys = results.map((name) => [matchKind(name, term), projected.has(name) ? 0 : 1] as const)
  for (let index = 1; index < keys.length; index += 1) {
    const [prevKind, prevBoard] = keys[index - 1]!
    const [kind, onBoard] = keys[index]!
    const inOrder = prevKind < kind || (prevKind === kind && prevBoard <= onBoard)
    expect(inOrder, `"${results[index - 1]}" is listed before "${results[index]}" for "${term}"`).toBe(true)
  }
}

test('an ambiguous term opens on a player projected this week', async ({ page, isMobile }) => {
  const projected = new Set(await board(page))
  await openPalette(page, isMobile)

  const results = await paletteSearch(page, 'gib')
  expect(results.length).toBeGreaterThan(0)
  expect(projected.has(results[0]!), `first result for "gib" was ${results[0]}`).toBe(true)
  expectRelevanceOrder(results, 'gib', projected)
})

test('a common surname lists its highest-projected player first', async ({ page, isMobile }) => {
  const names = await board(page)
  const projected = new Set(names)
  // The board is in projection order, so the first match is the highest.
  const best = names.find((name) => matchKind(name, 'allen') === 1)
  test.skip(!best, 'nobody named Allen is projected this week')

  await openPalette(page, isMobile)
  const results = await paletteSearch(page, 'allen')
  expect(results[0]).toBe(best)
  expectRelevanceOrder(results, 'allen', projected)
})

test('a full name finds that player first', async ({ page, isMobile }) => {
  const names = await board(page)
  // Deep enough in the board that recency and projection would not put him first.
  const target = names[Math.min(60, names.length - 1)]!

  await openPalette(page, isMobile)
  const results = await paletteSearch(page, target)
  expect(results[0]).toBe(target)
})

test('players who are not projected are still listed, after those who are', async ({ page, isMobile }) => {
  const projected = new Set(await board(page))
  await openPalette(page, isMobile)

  // Broad enough that the dimension holds retired players for it.
  const results = await paletteSearch(page, 'smith')
  expect(results.length).toBeGreaterThan(1)
  expectRelevanceOrder(results, 'smith', projected)
})

test('the roster search field ranks the same way', async ({ page }) => {
  const projected = new Set(await board(page))
  await page.goto('/my-team')
  await settle(page)

  const responded = page.waitForResponse((response) => response.url().includes('/api/v1/search'))
  await page.getByRole('combobox', { name: /add a player/i }).fill('gib')
  await responded
  await page.waitForLoadState('networkidle')
  const options = page.getByRole('listbox', { name: /add a player/i }).getByRole('option')
  await expect(options.first()).toBeVisible()
  const results = await options.evaluateAll((nodes) =>
    nodes.map((node) => node.querySelector('span.block')?.textContent?.trim() ?? ''),
  )
  expect(projected.has(results[0]!), `first result for "gib" was ${results[0]}`).toBe(true)
  expectRelevanceOrder(results, 'gib', projected)
})
