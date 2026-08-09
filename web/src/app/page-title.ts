import { useEffect } from 'react'

/**
 * The current page's name, as one value.
 *
 * Two things need it and they need it to agree: the browser tab, and the live
 * region that tells a screen reader the view changed. Deriving them separately
 * is how they drift, so a page declares its name once and both read from here.
 *
 * A tiny external store rather than context because the writer is deep in the
 * tree (a page) and the reader is above it (the shell). Context would need a
 * provider above both and a setter threaded down through every page.
 */

const PRODUCT = 'Fourth & Probable'

let currentTitle = PRODUCT
const listeners = new Set<() => void>()

export function subscribeToPageTitle(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getPageTitle(): string {
  return currentTitle
}

function setPageTitle(title: string): void {
  if (title === currentTitle) return
  currentTitle = title
  // The product name goes last. A tab strip truncates from the right, so the
  // part that distinguishes one open tab from another has to come first.
  document.title = title === PRODUCT ? PRODUCT : `${title} — ${PRODUCT}`
  for (const listener of listeners) listener()
}

/**
 * Names the current page.
 *
 * Called once per view. `PageHeader` does it for every screen built around a
 * heading; a screen whose heading is a player's name calls it directly.
 *
 * Passing `null` — which is what a page does while its subject is still
 * loading — deliberately leaves the previous title in place rather than
 * flashing the bare product name for one frame between two real titles.
 */
export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    if (!title) return
    setPageTitle(title)
  }, [title])
}
