import { useEffect } from 'react'

/**
 * Consecutive animation frames without a scroll event before the page counts
 * as settled: ~100 ms at 60 fps, and proportionally longer on a slow page.
 */
const SETTLE_FRAMES = 6

/**
 * Marks `<html data-scrolling>` while the page is being scrolled.
 *
 * Exists for one CSS rule (see `styles/index.css`): table rows drop their hover
 * highlight while this is set. A row's hover highlight is cheap on its own, but
 * a wheel scroll slides row after row under a stationary cursor, and every
 * hover change repaints the whole table. With the full slate drawn (~670 rows,
 * ~24,000 elements) that was measured at 123 ms per frame under a 4x CPU
 * throttle, against 25 ms with the highlight suppressed.
 *
 * The end of a scroll is counted in frames, not milliseconds, because this is
 * for pages slow enough to run 100+ ms frames. A 150 ms timer expired between
 * wheel steps there, and `scrollend` fires after every step's smooth-scroll
 * animation; either way the flag flickered off, the row under the cursor faded
 * its highlight back in, and each fade repainted the table — as costly as no
 * flag at all. Scroll events are dispatched at most once per frame, so a run of
 * frames without one means the scroll has actually stopped, at any frame rate.
 *
 * The attribute is written only when the state flips, so a scroll costs one
 * style invalidation at each end.
 */
export function useScrollingFlag() {
  useEffect(() => {
    const root = document.documentElement
    let idleFrames = 0
    let frame: number | undefined

    const tick = () => {
      idleFrames += 1
      if (idleFrames < SETTLE_FRAMES) {
        frame = requestAnimationFrame(tick)
        return
      }
      frame = undefined
      root.removeAttribute('data-scrolling')
    }

    const onScroll = () => {
      idleFrames = 0
      if (frame !== undefined) return
      root.setAttribute('data-scrolling', '')
      frame = requestAnimationFrame(tick)
    }

    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (frame !== undefined) cancelAnimationFrame(frame)
      root.removeAttribute('data-scrolling')
    }
  }, [])
}
