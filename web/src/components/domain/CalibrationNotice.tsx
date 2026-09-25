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
      aria-label="Projection accuracy notice"
    >
      <div className="flex gap-2.5">
        <AlertTriangle aria-hidden className="text-caution-text mt-0.5 size-4 shrink-0" />
        <div className="text-caution-text space-y-1.5 text-xs leading-relaxed">
          <p>
            <span className="font-semibold">
              {all
                ? "This week's projections are approximate."
                : `${uncalibrated.length} of ${projections.length} projections are approximate.`}
            </span>{' '}
            They skipped the model&apos;s final adjustment step, so they may run a little high or
            low. They are less reliable than the numbers on the Track record page.
          </p>
          {banded && (
            <p>
              The floor-to-ceiling ranges are also shared across groups of similar players rather
              than worked out for each player. Read a range as a rough guide, not as a precise read
              on how boom-or-bust that player is.
            </p>
          )}
        </div>
      </div>
    </aside>
  )
}
