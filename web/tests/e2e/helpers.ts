import { expect, type Page } from '@playwright/test'

/** Waits for the view to hold real content rather than a skeleton. */
export async function settle(page: Page) {
  await page.waitForLoadState('networkidle')
  await expect(page.locator('main')).toBeVisible()
}

/**
 * Reveals the season/week/scoring selectors.
 *
 * They are inline in the header from `md` up and behind a disclosure below it,
 * so a test that reaches straight for the `<select>` passes on desktop and
 * times out on a phone against an app that is behaving correctly. Safe to call
 * at any width: on desktop the toggle is not rendered and this does nothing.
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
 * The header renders the controls twice — once inline for `md` and up, once
 * inside the phone disclosure — so the label matches two elements at every
 * width and exactly one of them is on screen. `.first()` alone picks the
 * desktop copy regardless of viewport, which is how a mobile run ends up
 * timing out on a hidden control.
 */
export function slateSelect(page: Page, name: RegExp) {
  return page.getByLabel(name).filter({ visible: true }).first()
}
