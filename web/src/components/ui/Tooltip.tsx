import { useCallback, useEffect, useId, useState, type ReactNode } from 'react'
import { Info } from 'lucide-react'

import { cn } from '@/utils/cn'

interface TooltipProps {
  /** The tooltip body. Kept short — anything longer belongs on the page. */
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'bottom'
  /**
   * Horizontal anchoring. `end` right-aligns the bubble to the trigger, which
   * is what a trigger in a right-hand column needs — a centred 16rem bubble on
   * a 2rem chip hangs half of itself off the edge of the screen.
   */
  align?: 'center' | 'end'
  className?: string
}

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
 * Never the only home for information that matters. This is for elaboration.
 */
export function Tooltip({ content, children, side = 'top', align = 'center', className }: TooltipProps) {
  const id = useId()
  // Only ever *suppresses* an otherwise-visible bubble. Showing stays in CSS,
  // so the common case — a pointer crossing a table full of chips — costs no
  // renders at all.
  const [dismissed, setDismissed] = useState(false)
  const [engaged, setEngaged] = useState(false)

  const restore = useCallback(() => {
    setEngaged(false)
    // Re-arm on the way out. Escape dismisses *this* showing, not the tooltip
    // for the rest of the session.
    setDismissed(false)
  }, [])

  // Bound to the document rather than the wrapper because hover alone puts no
  // element in the focus path — a keydown while pointing at a chip is
  // delivered to whatever is focused elsewhere on the page, or to <body>.
  useEffect(() => {
    if (!engaged) return

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDismissed(true)
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [engaged])

  return (
    <span
      className={cn('group/tooltip relative inline-flex', className)}
      onPointerEnter={() => setEngaged(true)}
      onPointerLeave={restore}
    >
      <span
        tabIndex={0}
        aria-describedby={dismissed ? undefined : id}
        className="inline-flex rounded-sm"
        onFocus={() => setEngaged(true)}
        onBlur={restore}
      >
        {children}
      </span>
      <span
        id={id}
        role="tooltip"
        className={cn(
          'bg-surface-raised border-line text-ink pointer-events-none absolute z-50 w-max max-w-64',
          'rounded-[var(--radius-control)] border px-2.5 py-1.5 text-xs leading-relaxed font-normal shadow-overlay',
          // `hidden`, not `invisible`. A visibility-hidden absolute element still
          // contributes to the document's scroll width, and a page full of
          // tooltips near the right edge silently gains a horizontal scrollbar.
          // Display toggling costs the fade and buys a page that does not move.
          dismissed ? 'hidden' : 'hidden group-hover/tooltip:block group-focus-within/tooltip:block',
          side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
          align === 'end' ? 'right-0' : 'left-1/2 -translate-x-1/2',
        )}
      >
        {content}
      </span>
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
