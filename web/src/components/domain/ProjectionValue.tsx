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
  size?: 'sm' | 'md' | 'lg' | 'xl'
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

  const label = [
    `8 in 10 outcomes between ${formatPoints(floor)} and ${formatPoints(ceiling)} points`,
    box ? `middle half ${formatPoints(p25)} to ${formatPoints(p75)}` : null,
    has(median) ? `median ${formatPoints(median)}` : null,
    line !== null ? `line at ${formatPoints(threshold)}` : null,
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <span className="tnum text-ink-muted w-9 shrink-0 text-right text-xs">
        {formatPoints(floor)}
      </span>
      <div
        className={cn('bg-field relative min-w-20 flex-1 overflow-hidden rounded-md', large ? 'h-11' : 'h-6')}
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
      </div>
      <span className="tnum text-ink-muted w-9 shrink-0 text-xs">{formatPoints(ceiling)}</span>
    </div>
  )
}
