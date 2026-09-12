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
        <Tooltip content="This run did not store a calibrated mean, so the model's raw output is shown instead. Raw output is conditionally biased by construction — treat it as approximate.">
          <AlertTriangle
            aria-label="Uncalibrated projection"
            className="text-caution size-3.5"
          />
        </Tooltip>
      )}
      {actualPoints !== null && actualPoints !== undefined && (
        <Tooltip content="Actual: a recorded outcome from a completed game, not a prediction.">
          <span className="text-ink-muted tnum text-xs font-medium">
            actual {formatPoints(actualPoints)}
          </span>
        </Tooltip>
      )}
    </span>
  )
}

/**
 * The outcome range as a bar: floor, median, ceiling.
 *
 * The single most useful visualisation in the product and the reason it is a
 * primitive rather than a chart. It answers "how much can this move?" at a
 * glance, which a point estimate cannot, and it does it in a table row.
 *
 * The numeric endpoints are always rendered beside it, because a bar alone is
 * not readable to a screen reader or measurable by eye.
 */
export function OutcomeRange({
  floor,
  median,
  ceiling,
  /** Shared upper bound so bars in a list are comparable to each other. */
  scaleMax,
  className,
}: {
  floor: number | null | undefined
  median: number | null | undefined
  ceiling: number | null | undefined
  scaleMax?: number
  className?: string
}) {
  if (floor === null || floor === undefined || ceiling === null || ceiling === undefined) {
    return <span className="text-ink-muted text-xs">Range unavailable</span>
  }

  const max = scaleMax && scaleMax > 0 ? scaleMax : ceiling
  const clamp = (value: number) => Math.max(0, Math.min(100, (value / max) * 100))
  const start = clamp(floor)
  const end = clamp(ceiling)
  const width = Math.max(end - start, 1)
  const marker = median !== null && median !== undefined ? clamp(median) : null

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <span className="tnum text-ink-muted w-9 shrink-0 text-right text-xs">
        {formatPoints(floor)}
      </span>
      <div
        className="bg-surface-sunken relative h-1.5 min-w-16 flex-1 overflow-hidden rounded-full"
        role="img"
        aria-label={`Projected range ${formatPoints(floor)} to ${formatPoints(ceiling)} points, median ${formatPoints(median)}`}
      >
        <div
          className="bg-accent/45 absolute inset-y-0 rounded-full"
          style={{ left: `${start}%`, width: `${width}%` }}
        />
        {marker !== null && (
          <div
            className="bg-accent absolute inset-y-0 w-0.5 rounded-full"
            style={{ left: `${marker}%` }}
          />
        )}
      </div>
      <span className="tnum text-ink-muted w-9 shrink-0 text-xs">{formatPoints(ceiling)}</span>
    </div>
  )
}
