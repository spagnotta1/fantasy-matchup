import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useLocation } from 'react-router-dom'

import { getPageTitle, subscribeToPageTitle } from './page-title'

/**
 * The two things a single-page application has to do by hand on navigation.
 *
 * A real page load moves focus to the top of the new document and tells
 * assistive technology that something different is on screen. A client-side
 * route change does neither for free: without this component a keyboard user
 * tabs back into the *previous* page's navigation, and a screen reader
 * announces nothing at all — the view silently becomes a different view.
 *
 * Scroll position is not handled here. Router's `<ScrollRestoration />` already
 * does it with better semantics than a blanket jump to the top: a new
 * navigation starts at the top, and going *back* returns to where the reader
 * was on the page they left, which is the whole reason they pressed back.
 *
 * Renders nothing visible.
 */
export function RouteChrome() {
  const { pathname } = useLocation()
  const title = useSyncExternalStore(subscribeToPageTitle, getPageTitle, getPageTitle)

  const [announcement, setAnnouncement] = useState<{ text: string; id: number } | null>(null)

  // Both effects record the value they last acted on rather than a "have I run
  // before" flag. The first render is a real page load — the browser has
  // already put focus where it belongs, and stealing it from a deep link's
  // anchor is worse than doing nothing — but a flag gets consumed by
  // StrictMode's deliberate double-invoke in development, which would then
  // announce and grab focus on the initial load. Comparing values is idempotent
  // and behaves the same in both modes.
  const lastFocusedPath = useRef<string | null>(null)
  const lastAnnouncedTitle = useRef<string | null>(null)
  // Nothing is announced until the user has actually navigated once. On a real
  // document load the screen reader reads the title itself; saying it a second
  // time from a live region is noise on the one arrival that never needed help.
  const hasNavigated = useRef(false)

  useEffect(() => {
    if (lastFocusedPath.current === pathname) return
    const isInitialLoad = lastFocusedPath.current === null
    lastFocusedPath.current = pathname
    if (isInitialLoad) return
    hasNavigated.current = true

    // `<main>` carries tabIndex={-1} for exactly this: it can receive focus
    // programmatically without ever becoming a tab stop of its own. Focusing it
    // puts the next Tab press at the start of the new page's content.
    document.getElementById('main')?.focus({ preventScroll: true })
  }, [pathname])

  // The announcement follows the *title*, not the path. A page names itself
  // after it renders, so the path changes first and the name arrives a beat
  // later; waiting for the name is what makes this say "RB rankings" instead of
  // firing early against the previous page's name. It also covers the in-page
  // title changes — switching position tabs — that never touch the pathname.
  useEffect(() => {
    if (lastAnnouncedTitle.current === title) return
    lastAnnouncedTitle.current = title
    if (!hasNavigated.current) return

    setAnnouncement((previous) => ({ text: `${title}, page loaded`, id: (previous?.id ?? 0) + 1 }))
  }, [title])

  return (
    // Not `hidden` and not `display: none` — either removes the text from the
    // accessibility tree, and with it the announcement.
    <div aria-live="polite" aria-atomic="true" className="sr-only">
      {/*
        Keyed by a counter so returning to a page you were just on still
        announces. A live region fires on content *change*; re-rendering the
        identical string is not a change, and replacing the node is what makes
        Rankings → RB → Rankings speak all three times.
      */}
      {announcement && <span key={announcement.id}>{announcement.text}</span>}
    </div>
  )
}
