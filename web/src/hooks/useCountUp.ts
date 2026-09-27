import { useEffect, useRef, useState } from 'react'

import { prefersReducedMotion } from '@/utils/motion'

/**
 * A number that counts from its previous value to its new one.
 *
 * Only a *change* counts. The first value is shown as it is, so a page that
 * loads with a score of 18.5 shows 18.5 rather than racing up from zero — that
 * would be motion nobody asked for, and would briefly show numbers that were
 * never true. Under reduced motion every change is a jump.
 *
 * The count is presentation only. Anything a reader or a screen reader can
 * act on should be given the real value, not this one (see the `aria` uses).
 */
export function useCountUp(
  value: number,
  duration = 600,
  /**
   * Where the very first value counts from, when a starting point has a
   * meaning of its own — a win probability revealed from even odds, the
   * reading before any simulation has been run. Omitted, the first value is
   * shown as it is.
   */
  initial?: number,
): number {
  const [shown, setShown] = useState(initial ?? value)
  // What is on screen right now. Counting from here rather than from the last
  // *target* means an interrupted count carries on from where the eye is, and
  // a development double-run of the effect cannot skip the count entirely.
  const current = useRef(initial ?? value)

  useEffect(() => {
    const start = current.current
    if (start === value || prefersReducedMotion()) {
      current.current = value
      setShown(value)
      return
    }

    let frame = 0
    const began = performance.now()
    const step = (now: number) => {
      const t = Math.min(1, (now - began) / duration)
      // Ease out: quick at first, settling on the final digit.
      const eased = 1 - (1 - t) ** 3
      current.current = start + (value - start) * eased
      setShown(current.current)
      if (t < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [value, duration])

  return shown
}

/**
 * Restart a CSS animation class on an element.
 *
 * Adding a class that is already present does not replay its animation, and a
 * second score in the same row is exactly that case. Removing the class and
 * forcing a style flush before adding it back is the standard reset.
 */
export function replayAnimation(element: Element | null, className: string) {
  if (!element) return
  element.classList.remove(className)
  // Reading layout flushes the removal, so the re-add starts a new animation.
  void (element as HTMLElement).offsetWidth
  element.classList.add(className)
}
