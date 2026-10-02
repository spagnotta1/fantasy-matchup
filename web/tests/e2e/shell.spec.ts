import { expect, test, type Page } from '@playwright/test'

import { openSlateControls, pageOverflow, settle, slateSelect } from './helpers'

/**
 * The shell: the sidebar, the header, and where the pages that lost their
 * sidebar line went.
 *
 * Thirteen entries became nine and a foot. What that must not cost: any old
 * address, any filter carried in one, the page a reader is on being marked in
 * the navigation, or a way to reach every page by name.
 */

const sidebar = (page: Page) => page.getByRole('navigation', { name: 'Main' }).filter({ visible: true })

test.describe('the sidebar', () => {
  test.skip(({ isMobile }) => isMobile, 'a phone has the bottom bar instead')

  test('is two groups of the week and its tools, with the product\'s own pages at the foot', async ({ page }) => {
    await page.goto('/')
    await settle(page)
    const nav = sidebar(page)

    await expect(nav.getByRole('list', { name: 'This week' }).getByRole('link')).toHaveText([
      'Dashboard',
      'Rankings',
      'Matchups',
      'Live',
      'Reports',
    ])
    await expect(nav.getByRole('list', { name: 'Tools' }).getByRole('link')).toHaveText([
      /^My team/,
      'Simulation',
      'Compare',
      'Trade analyzer',
    ])
    await expect(nav.getByRole('list', { name: 'About and settings' }).getByRole('link')).toHaveText([
      'Track record',
      'Settings',
    ])
    // Nine, and two at the foot. It was thirteen.
    await expect(nav.getByRole('link')).toHaveCount(11)
    for (const gone of ['Teams', 'Injuries', 'Usage trends']) {
      await expect(nav.getByRole('link', { name: gone, exact: true })).toHaveCount(0)
    }
  })

  test('marks the page a reader is on, including the pages that live under another entry', async ({ page }) => {
    const cases: [string, string][] = [
      ['/', 'Dashboard'],
      ['/rankings/rb', 'Rankings'],
      ['/matchups?view=teams', 'Matchups'],
      ['/teams/BAL', 'Matchups'],
      ['/reports/usage', 'Reports'],
      ['/track-record', 'Track record'],
      ['/settings', 'Settings'],
    ]
    for (const [path, label] of cases) {
      await page.goto(path)
      await settle(page)
      const current = sidebar(page).locator('a[aria-current="page"]')
      await expect(current, path).toHaveCount(1)
      await expect(current, path).toHaveText(new RegExp(`^${label}`))
    }
  })

  test('folds to a rail of named icons, gives the page its width, and stays folded', async ({ page }) => {
    await page.goto('/rankings/rb')
    await settle(page)
    const nav = sidebar(page)
    const main = page.locator('main')
    const wide = (await nav.boundingBox())!.width
    const before = (await main.boundingBox())!.width
    expect(Math.round(wide)).toBe(240)

    const fold = nav.getByRole('button', { name: 'Collapse the sidebar' })
    await expect(fold).toHaveAttribute('aria-expanded', 'true')
    await fold.focus()
    await page.keyboard.press('Enter')

    await expect(nav).toHaveAttribute('data-rail', 'true')
    expect(Math.round((await nav.boundingBox())!.width)).toBe(56)
    expect(Math.round((await main.boundingBox())!.width - before)).toBe(184)
    // The same control, still focused, now says what it will do next.
    const unfold = nav.getByRole('button', { name: 'Expand the sidebar' })
    await expect(unfold).toBeFocused()
    await expect(unfold).toHaveAttribute('aria-expanded', 'false')

    // Every destination is still there and still has a name, without its words.
    const links = nav.getByRole('link')
    await expect(links).toHaveCount(11)
    for (const name of ['Dashboard', 'Rankings', 'Matchups', 'Live', 'Reports', 'Simulation', 'Compare', 'Settings']) {
      const link = nav.getByRole('link', { name, exact: true })
      await expect(link).toBeVisible()
      await expect(link).toHaveAttribute('title', name)
      const box = await link.boundingBox()
      expect(Math.round(box!.width)).toBeGreaterThanOrEqual(40)
      expect(Math.round(box!.height)).toBeGreaterThanOrEqual(40)
    }
    await expect(nav.locator('a[aria-current="page"]')).toHaveAccessibleName('Rankings')
    expect(await pageOverflow(page)).toBeLessThanOrEqual(0)

    // A preference of this browser: it survives a reload and a navigation.
    await page.reload()
    await settle(page)
    await expect(sidebar(page)).toHaveAttribute('data-rail', 'true')
    await sidebar(page).getByRole('link', { name: 'Matchups', exact: true }).click()
    await expect(page).toHaveURL(/\/matchups$/)
    await expect(sidebar(page)).toHaveAttribute('data-rail', 'true')

    await sidebar(page).getByRole('button', { name: 'Expand the sidebar' }).click()
    await expect(sidebar(page)).not.toHaveAttribute('data-rail', 'true')
    await expect(sidebar(page).getByRole('link', { name: 'Matchups', exact: true })).toHaveText('Matchups')
  })

  test('the header no longer repeats the sidebar, or shows an account that does not exist', async ({ page }) => {
    await page.goto('/')
    await settle(page)
    const header = page.locator('header')
    await expect(header.getByRole('link', { name: /compare/i })).toHaveCount(0)
    await expect(header.getByRole('link', { name: /settings/i })).toHaveCount(0)
    await expect(header.getByText('Not signed in')).toHaveCount(0)
    // What is left: the slate, search, and the theme.
    await expect(header.getByRole('button', { name: /season, week and scoring/i })).toBeVisible()
    await expect(header.getByRole('button')).toHaveCount(3)
    await expect(header.getByRole('button', { name: /^Search/ })).toBeVisible()
    await expect(header.getByRole('button', { name: /^Theme:/ })).toBeVisible()
  })
})

test.describe('the slate', () => {
  test('is one button that says the season, the week and the scoring format, at every width', async ({ page }) => {
    await page.goto('/rankings/rb')
    await settle(page)
    const header = page.locator('header')
    const chip = header.getByRole('button', { name: /season, week and scoring/i })
    await expect(chip).toBeVisible()
    await expect(chip).toHaveText(/^\D*\d{4} · Wk \d+ · .+$/)
    // The words on it are in its name, so saying what is on it presses it.
    const shown = (await chip.innerText()).replace(/\s+/g, ' ').trim()
    await expect(chip).toHaveAccessibleName(new RegExp(shown.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
    // No selector is on screen until it is asked for.
    await expect(header.getByRole('combobox')).toHaveCount(0)

    await expect(chip).toHaveAttribute('aria-expanded', 'false')
    await chip.focus()
    await page.keyboard.press('Enter')
    await expect(chip).toHaveAttribute('aria-expanded', 'true')
    const panel = page.locator('#slate-controls')
    await expect(panel).toBeVisible()
    for (const name of [/^season$/i, /^week$/i, /^scoring$/i]) await expect(panel.getByLabel(name)).toBeVisible()
    // The selectors come next in the tab order.
    await page.keyboard.press('Tab')
    await expect(panel.getByLabel(/^season$/i)).toBeFocused()
    // On screen and inside the window.
    const box = await panel.boundingBox()
    const viewport = page.viewportSize()!
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width)

    // Escape closes it and gives the button its focus back.
    await page.keyboard.press('Escape')
    await expect(panel).toBeHidden()
    await expect(chip).toBeFocused()
    await expect(chip).toHaveAttribute('aria-expanded', 'false')

    // So does a press anywhere else.
    await chip.click()
    await expect(panel).toBeVisible()
    // (Dispatched, not clicked: the panel lies over the top of the page, and a
    // real click lower down would land on whatever row is there.)
    await page.locator('main').dispatchEvent('pointerdown')
    await expect(panel).toBeHidden()
    expect(await pageOverflow(page)).toBeLessThanOrEqual(0)
  })

  test('changing the week or the scoring changes what the button says, and stays open for the next change', async ({ page }) => {
    await page.goto('/rankings/rb')
    await settle(page)
    const chip = page.locator('header').getByRole('button', { name: /season, week and scoring/i })
    await openSlateControls(page)
    const week = slateSelect(page, /^week$/i)
    const values = await week.locator('option').evaluateAll((all) => all.map((option) => (option as HTMLOptionElement).value))
    test.skip(values.length < 2, 'one published week')
    const current = await week.inputValue()
    const target = values.find((value) => value !== current)!

    await week.selectOption(target)
    await expect(chip).toHaveText(new RegExp(`· Wk ${target} ·`))
    await expect(page).toHaveURL(new RegExp(`week=${target}`))
    // Still open: the scoring format is one more choice, not another trip.
    await expect(page.locator('#slate-controls')).toBeVisible()
    await slateSelect(page, /^scoring$/i).selectOption('ppr')
    await expect(chip).toHaveText(/· PPR$/)
    await expect(page).toHaveURL(/scoring=ppr/)

    // Going somewhere else closes it, and the button still says the slate.
    await page.goto('/matchups')
    await settle(page)
    await expect(page.locator('#slate-controls')).toBeHidden()
  })

  test('the draft pages, which have their own season and scoring, show no slate button', async ({ page }) => {
    await page.goto('/draft-board')
    await settle(page)
    await expect(page.locator('header').getByRole('button', { name: /season, week and scoring/i })).toHaveCount(0)
  })
})

test.describe('pages that moved', () => {
  test('the injury report and the usage trends are two views of Reports', async ({ page }) => {
    await page.goto('/reports')
    await settle(page)
    await expect(page).toHaveURL(/\/reports\/injuries$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Injury report' })).toBeVisible()

    const switcher = page.getByRole('radiogroup', { name: 'Report' })
    await expect(switcher.getByRole('radio', { name: 'Injuries' })).toBeChecked()
    await switcher.getByText('Usage', { exact: true }).click()
    await expect(page).toHaveURL(/\/reports\/usage$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Usage trends' })).toBeVisible()
    await expect(page).toHaveTitle(/Usage trends/)
    await expect(page.getByRole('radiogroup', { name: 'Report' }).getByRole('radio', { name: 'Usage' })).toBeChecked()

    // Each view is an address: back is the other report.
    await page.goBack()
    await expect(page).toHaveURL(/\/reports\/injuries$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Injury report' })).toBeVisible()
  })

  test('switching report keeps the week and scoring and drops the other report\'s filters', async ({ page }) => {
    const seasons = (await (await page.request.get('/api/v1/seasons')).json()) as {
      data: { season: number; published_weeks: number[] }[]
    }
    const { season, published_weeks: weeks } = seasons.data[0]
    const week = weeks[0]
    await page.goto(`/reports/injuries?season=${season}&week=${week}&scoring=ppr&status=serious&position=WR`)
    await settle(page)
    await page.getByRole('radiogroup', { name: 'Report' }).getByText('Usage', { exact: true }).click()
    await expect(page).toHaveURL(/\/reports\/usage\?/)
    const url = new URL(page.url())
    expect(url.searchParams.get('week')).toBe(String(week))
    expect(url.searchParams.get('scoring')).toBe('ppr')
    expect(url.searchParams.get('status')).toBeNull()
    expect(url.searchParams.get('position')).toBeNull()
    await expect(page.getByRole('heading', { level: 1, name: 'Usage trends' })).toBeVisible()
  })

  test('every old address still arrives, with its filters', async ({ page }) => {
    await page.goto('/usage?metric=target&direction=down&position=WR')
    await settle(page)
    await expect(page).toHaveURL(/\/reports\/usage\?/)
    const usage = new URL(page.url())
    expect(Object.fromEntries(usage.searchParams)).toMatchObject({ metric: 'target', direction: 'down', position: 'WR' })
    await expect(page.getByRole('heading', { name: 'Target share: falling' })).toBeVisible()

    await page.goto('/injuries?status=questionable')
    await settle(page)
    await expect(page).toHaveURL(/\/reports\/injuries\?status=questionable$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Injury report' })).toBeVisible()

    await page.goto('/teams')
    await settle(page)
    await expect(page).toHaveURL(/\/matchups\?view=teams$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Matchups' })).toBeVisible()
    await expect(page.locator('main a[href^="/teams/"]')).toHaveCount(32)

    // A report this page does not have is the injury report, not a blank.
    await page.goto('/reports/weather')
    await settle(page)
    await expect(page).toHaveURL(/\/reports\/injuries$/)
  })

  test('Teams is a view of Matchups, and a team\'s page leads back to it', async ({ page }) => {
    await page.goto('/matchups')
    await settle(page)
    const view = page.getByRole('group', { name: 'Choose a matchup view' })
    const select = view.getByRole('combobox', { name: 'Matchup view' })
    if ((await select.count()) > 0) await select.selectOption({ label: 'Matchup view: Teams' })
    else await view.getByText('Teams', { exact: true }).click()
    await expect(page).toHaveURL(/view=teams/)
    await expect(page.getByRole('heading', { level: 2, name: 'AFC East' })).toBeVisible()

    await page.locator('main a[href="/teams/BAL"]').click()
    await settle(page)
    await expect(page.getByRole('heading', { name: 'Projected players' })).toBeVisible()
    await page.getByRole('link', { name: 'All teams' }).click()
    await expect(page).toHaveURL(/\/matchups\?view=teams$/)
    await expect(page.getByRole('heading', { level: 2, name: 'AFC East' })).toBeVisible()
    expect(await pageOverflow(page)).toBeLessThanOrEqual(0)
  })

  test('the palette still lists every page by its own name', async ({ page, isMobile }) => {
    await page.goto('/')
    await settle(page)
    if (isMobile) await page.getByRole('button', { name: 'Search and all pages' }).click()
    else await page.keyboard.press('Control+K')
    const palette = page.getByRole('dialog')
    await expect(palette).toBeVisible()
    for (const name of [
      'Dashboard',
      'Rankings',
      'Matchups',
      'Live',
      'Reports',
      'My team',
      'Simulation',
      'Compare',
      'Trade analyzer',
      'Injuries',
      'Usage trends',
      'Teams',
      'Mock draft',
      'Draft board',
      'Track record',
      'Settings',
    ]) {
      await expect(palette.getByRole('option', { name: new RegExp(`^${name}`) }).first()).toBeAttached()
    }

    await palette.getByRole('combobox').fill('usage')
    await palette.getByRole('option', { name: /^Usage trends/ }).click()
    await expect(page).toHaveURL(/\/reports\/usage$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Usage trends' })).toBeVisible()
  })
})

test.describe('on a phone', () => {
  test.skip(({ isMobile }) => !isMobile, 'the header chip and the bottom bar are the narrow drawing')

  test('the header says which week and scoring format the page is for, and opens the way to change them', async ({ page }) => {
    await page.goto('/rankings/rb')
    await settle(page)
    const chip = page.getByRole('button', { name: /season, week and scoring/i })
    await expect(chip).toBeVisible()
    // The words on it are the season, the week and the format, and they are in its name.
    await expect(chip).toHaveText(/\d{4} · Wk \d+ · .+/)
    const shown = (await chip.innerText()).replace(/\s+/g, ' ').trim()
    await expect(chip).toHaveAccessibleName(new RegExp(shown.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
    expect(Math.round((await chip.boundingBox())!.height)).toBeGreaterThanOrEqual(44)

    await expect(chip).toHaveAttribute('aria-expanded', 'false')
    await openSlateControls(page)
    await expect(chip).toHaveAttribute('aria-expanded', 'true')
    const week = slateSelect(page, /^week$/i)
    await expect(week).toBeVisible()

    // Changing the week changes what the chip says.
    const options = await week.locator('option').evaluateAll((all) => all.map((option) => (option as HTMLOptionElement).value))
    const other = options.find((value) => !shown.includes(`Wk ${value} `))
    test.skip(other === undefined, 'one published week')
    await week.selectOption(other!)
    await expect(chip).toHaveText(new RegExp(`Wk ${other} · `))
    // The whole button fits the header beside the menu and the theme.
    const box = await chip.boundingBox()
    expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width - 88)

    // No account badge, and nothing in the header runs off it.
    await expect(page.locator('header').getByText('Not signed in')).toHaveCount(0)
    expect(await pageOverflow(page)).toBeLessThanOrEqual(0)
  })

  test('the bottom bar keeps its five, and marks Matchups on a team\'s page', async ({ page }) => {
    await page.goto('/teams/BAL')
    await settle(page)
    const bar = sidebar(page)
    await expect(bar.getByRole('link')).toHaveText(['Dashboard', 'Rankings', 'Matchups', 'Simulation', /^My team/])
    await expect(bar.locator('a[aria-current="page"]')).toHaveText('Matchups')
  })
})

for (const width of [1280, 1024]) {
  test.describe(`at ${width}px`, () => {
    test.skip(({ isMobile }) => isMobile, 'the width is set here')
    test.use({ viewport: { width, height: 800 } })

    test('the sidebar fits the height of the screen, folded and unfolded', async ({ page }) => {
      await page.goto('/')
      await settle(page)
      const nav = sidebar(page)
      for (const rail of [false, true]) {
        if (rail) await nav.getByRole('button', { name: 'Collapse the sidebar' }).click()
        const box = await nav.boundingBox()
        expect(Math.round(box!.height)).toBe(800)
        // The foot is on screen without scrolling the sidebar.
        await expect(nav.getByRole('link', { name: 'Settings', exact: true })).toBeInViewport()
        expect(await pageOverflow(page)).toBeLessThanOrEqual(0)
      }
    })
  })
}
