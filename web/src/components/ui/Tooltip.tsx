import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { Info } from 'lucide-react'

import { cn } from '@/utils/cn'

interface TooltipProps {
  /** The tooltip body. Kept short — anything longer belongs on the page. */
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'bottom'
  /**
   * Preferred horizontal anchoring. `end` right-aligns the bubble to the
   * trigger, which reads better for a trigger in a right-hand column. Both are
   * a starting point, not a guarantee: whichever is asked for, the bubble is
   * then clamped inside the viewport.
   */
  align?: 'center' | 'end'
  className?: string
}

/** Distance between the trigger and the bubble. */
const GAP = 6
/** Closest the bubble may come to the edge of the viewport. */
const EDGE = 8

/**
 * A hover/focus tooltip.
 *
 * Shown on focus as well as hover, and wired with `aria-describedby` so the
 * text is announced rather than merely drawn. A tooltip that only appears on
 * hover is invisible to keyboard and touch users, which is most of the point of
 * having one.
 *
 * Dismissible with Escape without moving the pointer or the focus, which
 * WCAG 1.4.13 requires: a bubble anchored to a chip in a dense table can cover
 * the very rows the reader is comparing it against, and a magnifier user may
 * have no way to move away from the trigger without losing their place.
 *
 * ## Why this is a portal
 *
 * It used to be an absolutely-positioned sibling, which is smaller and simpler
 * and cannot be made to work. `position: absolute` is clipped by any ancestor
 * that scrolls or hides its overflow, and the triggers here live inside three
 * of them: the board's `overflow-x-auto` table wrapper, the position tabs, and
 * every `Card` that clips its own rounded corners. The symptom was a bubble
 * with its first few characters sliced off at a card edge — the text most worth
 * reading, since these explain what a number means.
 *
 * No amount of `z-index` fixes that; clipping is not a stacking question. So
 * the bubble is rendered into `document.body` and positioned in viewport
 * coordinates against the trigger's measured rect, where nothing can clip it.
 * It is then clamped to the viewport, which the old version also needed and did
 * not do: a centred 16rem bubble on a chip near the right edge hung half of
 * itself off the screen.
 *
 * The bubble is mounted only while it is shown. That is what the previous
 * `hidden`-not-`invisible` comment was protecting against — an absolute element
 * still contributes scroll width — and it now also means a 400-player board
 * carries no tooltip nodes at all until one is asked for, instead of the ~700
 * it used to hold permanently.
 *
 * Never the only home for information that matters. This is for elaboration.
 */
export function Tooltip({ content, children, side = 'top', align = 'center', className }: TooltipProps) {
  const id = useId()
  const triggerRef = useRef<HTMLSpanElement>(null)
  const bubbleRef = useRef<HTMLSpanElement>(null)

  const [engaged, setEngaged] = useState(false)
  // Only ever *suppresses* an otherwise-visible bubble.
  const [dismissed, setDismissed] = useState(false)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)

  const visible = engaged && !dismissed

  const restore = useCallback(() => {
    setEngaged(false)
    // Re-arm on the way out. Escape dismisses *this* showing, not the tooltip
    // for the rest of the session.
    setDismissed(false)
  }, [])

  const place = useCallback(() => {
    const trigger = triggerRef.current
    const bubble = bubbleRef.current
    if (!trigger || !bubble) return

    const anchor = trigger.getBoundingClientRect()
    const box = bubble.getBoundingClientRect()
    const viewportWidth = document.documentElement.clientWidth
    const viewportHeight = document.documentElement.clientHeight

    // Flip only when the preferred side genuinely has no room *and* the other
    // side has more. Flipping toward an equally cramped side just moves the
    // problem and makes the bubble jump around as the page scrolls.
    const roomAbove = anchor.top
    const roomBelow = viewportHeight - anchor.bottom
    const needed = box.height + GAP + EDGE
    let placement = side
    if (side === 'top' && roomAbove < needed && roomBelow > roomAbove) placement = 'bottom'
    if (side === 'bottom' && roomBelow < needed && roomAbove > roomBelow) placement = 'top'

    const top = placement === 'top' ? anchor.top - box.height - GAP : anchor.bottom + GAP

    const preferred =
      align === 'end' ? anchor.right - box.width : anchor.left + anchor.width / 2 - box.width / 2
    // `Math.max` last so that a bubble wider than the viewport pins to the left
    // edge rather than to a negative one.
    const left = Math.max(EDGE, Math.min(preferred, viewportWidth - box.width - EDGE))

    setPosition({ top, left })
  }, [side, align])

  // Before paint, so the bubble never shows at its pre-measurement position.
  useLayoutEffect(() => {
    if (!visible) {
      setPosition(null)
      return
    }
    place()
  }, [visible, place, content])

  useEffect(() => {
    if (!visible) return

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDismissed(true)
    }
    const reposition = () => place()

    // Bound to the document rather than the wrapper because hover alone puts no
    // element in the focus path — a keydown while pointing at a chip is
    // delivered to whatever is focused elsewhere on the page, or to <body>.
    document.addEventListener('keydown', onKeyDown)
    // Capture, so a scroll inside the board's own scroller counts and not just
    // one on the window. A fixed bubble does not travel with its trigger.
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', reposition)
    }
  }, [visible, place])

  return (
    <span
      className={cn('relative inline-flex', className)}
      onPointerEnter={() => setEngaged(true)}
      onPointerLeave={restore}
    >
      <span
        ref={triggerRef}
        tabIndex={0}
        // Only while the bubble is mounted: an `aria-describedby` pointing at
        // an element that is not in the document describes nothing.
        aria-describedby={visible ? id : undefined}
        className="inline-flex rounded-sm"
        onFocus={() => setEngaged(true)}
        onBlur={restore}
      >
        {children}
      </span>

      {visible &&
        createPortal(
          <span
            ref={bubbleRef}
            id={id}
            role="tooltip"
            style={{
              top: position?.top ?? 0,
              left: position?.left ?? 0,
              // Never wider than the screen it has to fit on.
              maxWidth: `min(16rem, calc(100vw - ${EDGE * 2}px))`,
              // Hidden for the one frame between mount and measurement.
              // `visibility`, not `display`: an unrendered box has no size to
              // measure, which is the thing being waited for.
              visibility: position ? 'visible' : 'hidden',
            }}
            className={cn(
              'bg-surface-raised border-line text-ink pointer-events-none fixed z-50 w-max',
              'rounded-[var(--radius-control)] border px-2.5 py-1.5 text-xs leading-relaxed font-normal shadow-overlay',
            )}
          >
            {content}
          </span>,
          document.body,
        )}
    </span>
  )
}

/**
 * The standard "what does this number mean?" affordance.
 *
 * This product shows a lot of numbers that are easy to misread — a matchup
 * grade is a percentile, confidence is not quality — and an info icon beside
 * them is how that gets said without cluttering the layout.
 */
export function InfoTip({ label, content }: { label: string; content: ReactNode }) {
  return (
    <Tooltip content={content}>
      <Info aria-label={label} className="text-ink-muted hover:text-ink-secondary size-3.5" />
    </Tooltip>
  )
}
