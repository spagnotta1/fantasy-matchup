import { AlertTriangle } from 'lucide-react'

import type { Projection } from '@/api/schemas'
import { hasBandedIntervals } from '@/utils/board'
import { cn } from '@/utils/cn'
import { isCalibrated } from '@/utils/format'

/**
 * Said once per view, not once per row.
 *
 * Whether a published run stored calibrated means is a property of the run.
 * Marking every player individually turns a real caveat into wallpaper — a
 * warning that appears on 348 of 348 rows is one nobody reads. So the boards
 * stay clean and the caveat is stated here, plainly, with what it costs.
 *
 * This renders nothing when the run is properly calibrated, which is the state
 * it is designed to disappear in.
 */
export function CalibrationNotice({
  projections,
  className,
}: {
  projections: Projection[] | undefined
  className?: string
}) {
  if (!projections || projections.length === 0) return null

  const uncalibrated = projections.filter(
    (projection) => !isCalibrated(projection.prediction.points),
  )
  if (uncalibrated.length === 0) return null

  const all = uncalibrated.length === projections.length
  const banded = hasBandedIntervals(projections)

  return (
    <aside
      className={cn('bg-caution-soft rounded-[var(--radius-card)] px-4 py-3', className)}
      aria-label="Data quality notice"
    >
      <div className="flex gap-2.5">
        <AlertTriangle aria-hidden className="text-caution-text mt-0.5 size-4 shrink-0" />
        <div className="text-caution-text space-y-1.5 text-xs leading-relaxed">
          <p>
            <span className="font-semibold">
              {all ? 'This run' : `${uncalibrated.length} of ${projections.length} projections`} did not
              store a calibrated mean.
            </span>{' '}
            The projections shown are the model&apos;s raw output, which is conditionally biased by
            construction. Treat them as approximate rather than as the calibrated numbers the model
            was measured on.
          </p>
          {banded && (
            <p>
              The stored floor-to-ceiling ranges are also bucketed rather than per-player — groups
              of players share an identical spread. A range here describes the group a player was
              placed in, so read it as a rough band and not as that player&apos;s own volatility.
            </p>
          )}
        </div>
      </div>
    </aside>
  )
}
