import { useLayoutEffect, useRef, type RefObject } from 'react'

import { prefersReducedMotion } from '@/utils/motion'

/** Rows followed. Deeper than any screen shows, far short of a full board. */
const TRACKED = 40

/**
 * Slide items to their new places when a list is re-sorted.
 *
 * FLIP: each tracked item's position is remembered after every reorder; on
 * the next one, an item that moved starts at its old place and eases into the
 * new one. The reader watches the order change instead of being handed a new
 * list to re-read from the top.
 *
 * Measured, not modelled, and cheap on purpose. The board is performance-
 * sensitive (`useRenderBudget`), so only the first 40 items with a
 * `data-flip-key` are read, only when `orderKey` changes, and positions are
 * stored against the document so a scroll between two sorts does not read as
 * every row moving. Skipped entirely under reduced motion.
 */
export function useReorderAnimation<T extends HTMLElement>(orderKey: string): RefObject<T | null> {
  const ref = useRef<T>(null)
  const previous = useRef<Map<string, number>>(new Map())

  useLayoutEffect(() => {
    const container = ref.current
    if (!container) return
    const items = [...container.querySelectorAll<HTMLElement>('[data-flip-key]')].slice(0, TRACKED)
    const now = new Map<string, number>()
    for (const item of items) now.set(item.dataset.flipKey!, item.getBoundingClientRect().top + window.scrollY)

    const before = previous.current
    previous.current = now
    if (before.size === 0 || prefersReducedMotion()) return

    const viewport = window.innerHeight
    for (const item of items) {
      const key = item.dataset.flipKey!
      const from = before.get(key)
      const to = now.get(key)!
      const onScreen = to - window.scrollY < viewport && to - window.scrollY > -100
      if (!onScreen) continue
      // A row arriving from outside the tracked set fades up rather than
      // flying in from nowhere.
      const keyframes =
        from === undefined
          ? [
              { opacity: 0, transform: 'translateY(8px)' },
              { opacity: 1, transform: 'none' },
            ]
          : from !== to
            ? [{ transform: `translateY(${from - to}px)` }, { transform: 'none' }]
            : null
      if (keyframes) item.animate(keyframes, { duration: 380, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' })
    }
  }, [orderKey])

  return ref
}
