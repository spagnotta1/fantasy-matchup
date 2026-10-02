import { expect, type Locator, type Page } from '@playwright/test'

/** Waits for the view to hold real content rather than a skeleton. */
export async function settle(page: Page) {
  await page.waitForLoadState('networkidle')
  await expect(page.locator('main')).toBeVisible()
}

interface BoardRow {
  projection: { player: { player_id: string; position: string | null } }
}

/**
 * Saves a thirteen-player roster drawn from the published board, and the
 * theme, before the page loads: two quarterbacks, four backs, five receivers,
 * two tight ends — starters and a bench.
 */
export async function seedRoster(page: Page, theme: 'light' | 'dark' = 'light') {
  const response = await page.request.get('/api/v1/projections?limit=1000')
  const board = ((await response.json()) as { data: BoardRow[] }).data
  const pick = (position: string, count: number) =>
    board
      .filter((row) => row.projection.player.position === position)
      .slice(0, count)
      .map((row) => row.projection.player.player_id)
  const roster = [...pick('QB', 2), ...pick('RB', 4), ...pick('WR', 5), ...pick('TE', 2)]
  expect(roster.length, 'a full roster could be drawn from the board').toBe(13)

  await page.addInitScript(
    ([ids, chosenTheme]) => {
      window.localStorage.setItem('nflfp.roster', JSON.stringify(ids))
      window.localStorage.setItem('nflfp.theme', chosenTheme as string)
    },
    [roster, theme] as const,
  )
  return roster
}

/** How far the page scrolls sideways. A table scrolling inside its own frame does not count. */
export function pageOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
}

/**
 * Reveals the season/week/scoring selectors.
 *
 * They are behind the header's slate button at every width, so a test that
 * reaches straight for a `<select>` times out against an app that is behaving
 * correctly. Safe to call when they are already showing, and on the draft
 * pages, which have no slate button: it does nothing there. A navigation
 * closes them again.
 */
export async function openSlateControls(page: Page) {
  const toggle = page.getByRole('button', { name: /season, week and scoring/i })
  if ((await toggle.count()) === 0) return
  const first = toggle.first()
  if (!(await first.isVisible())) return
  if ((await first.getAttribute('aria-expanded')) !== 'true') await first.click()
}

/**
 * The visible slate selector.
 *
 * By its label, and only if it is on screen: the draft pages have a "Season"
 * of their own, and the header's is hidden until `openSlateControls` shows it.
 */
export function slateSelect(page: Page, name: RegExp) {
  return page.getByLabel(name).filter({ visible: true }).first()
}

/**
 * Nothing in a list row is printed over anything else, or past the row's edge.
 *
 * A line's parts are fixed widths around one that flexes. When they do not fit,
 * the flexing part is squeezed narrower than what is in it and its last number
 * is drawn under its neighbour: no overflow, no error, two numbers on top of
 * each other. So this measures the words themselves, not their boxes.
 *
 * `rows` are the row links of a row list (`components/ui/RowList`).
 */
export async function expectRowsLegible(rows: Locator, width: number) {
  const problems = await rows.evaluateAll(
    (links, viewport) =>
      links.slice(0, 12).flatMap((link, index) => {
        const found: string[] = []
        const box = link.getBoundingClientRect()
        if (box.left < 0 || box.right > viewport) found.push(`row ${index} runs off screen`)
        if (box.height < 44) found.push(`row ${index} is ${Math.round(box.height)}px tall`)

        // Every run of text in the row, as drawn: clipped to the box of a name
        // that truncates, and left out where it is for a screen reader only.
        const runs: { text: string; rect: DOMRect }[] = []
        const walker = document.createTreeWalker(link, NodeFilter.SHOW_TEXT)
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          const parent = node.parentElement
          if (!node.textContent?.trim() || !parent || parent.closest('.sr-only')) continue
          const range = document.createRange()
          range.selectNodeContents(node)
          const clip = parent.closest('.truncate')?.getBoundingClientRect()
          for (const rect of range.getClientRects()) {
            const right = clip ? Math.min(rect.right, clip.right) : rect.right
            if (right - rect.left < 1) continue
            runs.push({ text: node.textContent.trim().slice(0, 16), rect: new DOMRect(rect.left, rect.top, right - rect.left, rect.height) })
          }
        }
        for (const run of runs) {
          if (run.rect.right > box.right + 0.5) found.push(`row ${index}: "${run.text}" runs past the row`)
        }
        for (let a = 0; a < runs.length; a++) {
          for (let b = a + 1; b < runs.length; b++) {
            const one = runs[a].rect
            const two = runs[b].rect
            const across = Math.min(one.right, two.right) - Math.max(one.left, two.left)
            const down = Math.min(one.bottom, two.bottom) - Math.max(one.top, two.top)
            // More than a pixel each way: glyph boxes of neighbours on one line may touch.
            if (across > 1 && down > 4) found.push(`row ${index}: "${runs[a].text}" is printed over "${runs[b].text}"`)
          }
        }
        return found
      }),
    width,
  )
  expect(problems).toEqual([])
}
