import { useState, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

import { Tooltip } from '@/components/ui/Tooltip'
import type { Points } from '@/api/schemas'
import { cn } from '@/utils/cn'
import { formatPoints, headlinePoints } from '@/utils/format'

/**
 * The projected-points number, with its honesty attached.
 *
 * Two things this deliberately does not do. It never renders a projection as a
 * prediction of what will happen — the label is always "projected". And when
 * the calibrated mean is missing and the raw model output is standing in, it
 * marks the number rather than passing it off as calibrated. The backend's own
 * fallback is mirrored in `headlinePoints`; the warning is this component's
 * job.
 */
export function ProjectionValue({
  points,
  size = 'md',
  /**
   * Show the uncalibrated marker inline.
   *
   * Off by default, and that is a considered choice rather than a shortcut.
   * Whether a run stored calibrated means is a property of the *run*, not of a
   * player — so on a board where it is missing, the marker appears on every
   * single row and stops being a signal. Views state it once, in a notice
   * (`CalibrationNotice`), and turn this on only where a single number is the
   * subject: the player-detail headline.
   */
  markUncalibrated = false,
  /**
   * What the player actually scored, provenance `actual`.
   *
   * Present only for a week that has already been played. Rendered beside the
   * projection rather than in place of it — the projection is still what the
   * model said beforehand, and the two numbers answer different questions.
   */
  actualPoints,
  className,
}: {
  points: Points | null | undefined
  size?: 'sm' | 'md' | 'lg' | 'xl' | 'hero'
  markUncalibrated?: boolean
  actualPoints?: number | null
  className?: string
}) {
  const { value, calibrated } = headlinePoints(points)

  const sizes = {
    sm: 'text-sm',
    md: 'text-base',
    lg: 'text-2xl',
    xl: 'text-4xl',
    hero: 'text-5xl leading-none font-bold sm:text-6xl',
  } as const

  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <span className={cn('tnum font-semibold tracking-tight', sizes[size])}>
        {formatPoints(value)}
      </span>
      {markUncalibrated && value !== null && !calibrated && (
        <Tooltip content="This number skipped the model's final adjustment step, so it may run a little high or low. Treat it as approximate.">
          <AlertTriangle
            aria-label="Approximate projection"
            className="text-caution size-3.5"
          />
        </Tooltip>
      )}
      {actualPoints !== null && actualPoints !== undefined && (
        <Tooltip content="What the player actually scored in this finished game.">
          <span className="text-ink-muted tnum text-xs font-medium">
            actual {formatPoints(actualPoints)}
          </span>
        </Tooltip>
      )}
    </span>
  )
}

/** Yard lines on the field, in points. */
const YARD_LINE_POINTS = 5

/**
 * The outcome range, drawn on the field.
 *
 * The single most useful visualisation in the product and the reason it is a
 * primitive rather than a chart. It answers "how much can this move?" at a
 * glance, which a point estimate cannot, and it does it in a table row.
 *
 * Read left to right on a strip ruled every five points: the thin line runs
 * from a bad week to a strong week (P10 to P90), the solid box holds the middle
 * half of outcomes (P25 to P75), and the tick inside it is the median. The
 * yellow line is the line to gain — the boom threshold the published
 * probability is measured against — so a reader can see how much of a range
 * lies past it before reading the percentage beside it.
 *
 * Every mark is a published percentile. Nothing here interpolates, smooths or
 * extends a tail the API did not send; a run without P25/P75 draws the line
 * and the median only.
 *
 * The numeric endpoints are always rendered beside it, because a strip alone
 * is not readable to a screen reader or measurable by eye.
 */
export function OutcomeRange({
  floor,
  p25,
  median,
  p75,
  ceiling,
  threshold,
  /** Shared upper bound so strips in a list are comparable to each other. */
  scaleMax,
  /** `lg` where one range is the subject of the screen, as on a player page. */
  size = 'md',
  /**
   * Points actually scored, provenance `actual`, drawn as the ball.
   *
   * The Live page's reason for being: the ball moves down the field the
   * player's projection was drawn on, so "ahead of his range" or "past the
   * line" is visible before any number is read. It is a different kind of
   * number from everything else on the strip and is labelled as such.
   */
  actual,
  /**
   * Leave out the printed floor and ceiling beside the strip. Only for a
   * caller that prints them elsewhere in the same row, as the Live table's
   * projection cell does; a strip on its own is not readable without them.
   */
  hideEndpoints = false,
  className,
}: {
  floor: number | null | undefined
  p25?: number | null
  median: number | null | undefined
  p75?: number | null
  ceiling: number | null | undefined
  /** The boom threshold, drawn as the line to gain. Omitted: no line. */
  threshold?: number | null
  scaleMax?: number
  size?: 'md' | 'lg'
  actual?: number | null
  hideEndpoints?: boolean
  className?: string
}) {
  const large = size === 'lg'
  if (floor === null || floor === undefined || ceiling === null || ceiling === undefined) {
    return <span className="text-ink-muted text-xs">Range unavailable</span>
  }

  // Round the scale up to a whole yard line so the rules land on 5, 10, 15…
  // rather than wherever the board's highest ceiling happens to fall.
  const rawMax = scaleMax && scaleMax > 0 ? scaleMax : ceiling
  const max = Math.max(YARD_LINE_POINTS, Math.ceil(rawMax / YARD_LINE_POINTS) * YARD_LINE_POINTS)
  const at = (value: number) => Math.max(0, Math.min(100, (value / max) * 100))
  const has = (value: number | null | undefined): value is number =>
    value !== null && value !== undefined && Number.isFinite(value)

  const start = at(floor)
  const width = Math.max(at(ceiling) - start, 1)
  const box = has(p25) && has(p75) ? { left: at(p25), width: Math.max(at(p75) - at(p25), 1) } : null
  const marker = has(median) ? at(median) : null
  const line = has(threshold) && threshold > 0 && threshold < max ? at(threshold) : null
  // Kept a hair inside the strip so a ball at zero, or past the end of the
  // scale, is drawn whole rather than half clipped by the rounded edge. The
  // exact number is in the label and beside the strip.
  const ball = has(actual) ? Math.max(2, Math.min(98, at(actual))) : null

  const label = [
    ball !== null ? `${formatPoints(actual)} points scored so far` : null,
    `8 in 10 outcomes between ${formatPoints(floor)} and ${formatPoints(ceiling)} points`,
    box ? `middle half ${formatPoints(p25)} to ${formatPoints(p75)}` : null,
    has(median) ? `median ${formatPoints(median)}` : null,
    line !== null ? `line at ${formatPoints(threshold)}` : null,
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <div className={cn('flex items-center gap-2', className)}>
      {!hideEndpoints && (
        <span className="tnum text-ink-muted w-9 shrink-0 text-right text-xs">
          {formatPoints(floor)}
        </span>
      )}
      <YardReadout max={max}>
      <div
        className={cn('bg-field relative w-full overflow-hidden rounded-md', large ? 'h-11' : 'h-6')}
        style={{
          backgroundImage: `repeating-linear-gradient(to right, var(--color-field-line) 0 1px, transparent 1px ${(YARD_LINE_POINTS / max) * 100}%)`,
        }}
        role="img"
        aria-label={label}
      >
        <div
          className="bg-range-whisker absolute top-1/2 h-0.5 -translate-y-1/2"
          style={{ left: `${start}%`, width: `${width}%` }}
        />
        {box && (
          <div
            className={cn('bg-range-box absolute top-1/2 -translate-y-1/2 rounded-[3px]', large ? 'h-5' : 'h-3')}
            style={{ left: `${box.left}%`, width: `${box.width}%` }}
          />
        )}
        {marker !== null && (
          <div
            className={cn(
              'absolute top-1/2 w-0.5 -translate-x-1/2 -translate-y-1/2',
              large ? 'h-5' : 'h-3',
              box ? 'bg-range-median' : 'bg-range-box',
            )}
            style={{ left: `${marker}%` }}
          />
        )}
        {line !== null && (
          <div
            className="bg-line-to-gain absolute inset-y-0 w-1 -translate-x-1/2"
            style={{
              left: `${line}%`,
              boxShadow:
                '-1px 0 0 var(--color-line-to-gain-edge), 1px 0 0 var(--color-line-to-gain-edge)',
            }}
          />
        )}
        {ball !== null && (
          // Ink with a field-coloured halo, so it reads over the whisker and
          // the box alike. Slides when the score changes; the reduced-motion
          // rule turns the slide into a jump.
          <svg
            aria-hidden
            viewBox="0 0 22 14"
            className={cn(
              'absolute top-1/2 -translate-x-1/2 -translate-y-1/2 drop-shadow-sm transition-[left] duration-700 ease-out',
              large ? 'w-7' : 'w-5',
            )}
            style={{ left: `${ball}%` }}
          >
            <ellipse cx="11" cy="7" rx="10" ry="6" fill="var(--color-ink)" stroke="var(--color-field)" strokeWidth="1.5" />
            <path
              d="M7 7h8M9 5.4v3.2M11 5.4v3.2M13 5.4v3.2"
              stroke="var(--color-field)"
              strokeWidth="1.1"
              strokeLinecap="round"
            />
          </svg>
        )}
      </div>
      </YardReadout>
      {!hideEndpoints && (
        <span className="tnum text-ink-muted w-9 shrink-0 text-xs">{formatPoints(ceiling)}</span>
      )}
    </div>
  )
}

/**
 * A yard marker that follows the mouse along a strip: where on the scale the
 * pointer is, in points.
 *
 * The strip is a ruler with a line every five points and no numbers on it;
 * this is the numbers, on demand. It reads the scale and nothing else — it
 * never claims a probability for the spot it points at, because the API
 * publishes five percentiles, not a curve to look one up on.
 *
 * Mouse only. On touch the first tap is a navigation (rows and cards are
 * links), and a readout that sticks after the finger lifts is noise.
 */
function YardReadout({ max, children }: { max: number; children: ReactNode }) {
  const [at, setAt] = useState<number | null>(null)
  return (
    <div
      className="relative min-w-20 flex-1"
      onPointerMove={(event) => {
        if (event.pointerType !== 'mouse') return
        const box = event.currentTarget.getBoundingClientRect()
        setAt(Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)))
      }}
      onPointerLeave={() => setAt(null)}
    >
      {children}
      {at !== null && (
        <>
          <span
            aria-hidden
            className="bg-ink/60 pointer-events-none absolute inset-y-0 w-px"
            style={{ left: `${at * 100}%` }}
          />
          <span
            aria-hidden
            className="bg-ink text-surface tnum pointer-events-none absolute -top-5 z-10 -translate-x-1/2 rounded px-1.5 py-px text-[0.625rem] font-semibold whitespace-nowrap shadow-card"
            style={{ left: `${at * 100}%` }}
          >
            {Math.round(at * max)} pts
          </span>
        </>
      )}
    </div>
  )
}
