import { useSyncExternalStore } from 'react'

/**
 * Subscribe to a CSS media query.
 *
 * `useSyncExternalStore` rather than `useState` + an effect: the value is read
 * during render from the live `MediaQueryList`, so there is no first paint at
 * the wrong breakpoint and nothing to keep in sync. The server snapshot returns
 * false, which is the right default for "is this a small screen" — a desktop
 * layout that narrows is better than a mobile layout that widens.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = (onChange: () => void) => {
    const list = window.matchMedia(query)
    list.addEventListener('change', onChange)
    return () => list.removeEventListener('change', onChange)
  }

  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  )
}
