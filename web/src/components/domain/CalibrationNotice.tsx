import { AlertTriangle, Info } from 'lucide-react'

import type { Projection } from '@/api/schemas'
import { hasBandedIntervals } from '@/utils/board'
import { cn } from '@/utils/cn'
import { isCalibrated } from '@/utils/format'

/**
 * Said once per view, not once per row.
 *
 * Two properties of a published run, each stated only while it holds.
 *
 * Whether the run stored calibrated means. Marking every player individually
 * turns a real caveat into wallpaper — a warning that appears on 348 of 348
 * rows is one nobody reads. So the boards stay clean and the caveat is stated
 * here, plainly, with what it costs.
 *
 * Whether the ranges are shared across groups of players. This is independent
 * of the first, and used to be nested inside it: a calibrated run whose ranges
 * were still shared — run 146 has 2 distinct widths among 90 quarterbacks —
 * showed nothing at all, and a list ordered by range width read as a ranking.
 * It is a statement about what a width can be compared for, not a warning about
 * accuracy, so on its own it is set as information rather than caution.
 *
 * This renders nothing when the run is calibrated and its ranges are
 * per-player, which is the state it is designed to disappear in.
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
  const approximate = uncalibrated.length > 0
  const banded = hasBandedIntervals(projections)
  if (!approximate && !banded) return null

  const all = uncalibrated.length === projections.length
  const Icon = approximate ? AlertTriangle : Info
  const text = approximate ? 'text-caution-text' : 'text-info-text'

  return (
    <aside
      className={cn(
        'rounded-[var(--radius-card)] px-4 py-3',
        approximate ? 'bg-caution-soft' : 'bg-info-soft',
        className,
      )}
      aria-label={approximate ? 'Projection accuracy notice' : 'Scoring range notice'}
    >
      <div className="flex gap-2.5">
        <Icon aria-hidden className={cn('mt-0.5 size-4 shrink-0', text)} />
        <div className={cn('space-y-1.5 text-detail leading-relaxed', text)}>
          {approximate && (
            <p>
              <span className="font-semibold">
                {all
                  ? "This week's projections are approximate."
                  : `${uncalibrated.length} of ${projections.length} projections are approximate.`}
              </span>{' '}
              They skipped the model&apos;s final adjustment step, so they may run a little high or
              low. They are less reliable than the numbers on the Track record page.
            </p>
          )}
          {banded &&
            (approximate ? (
              <p>
                The floor-to-ceiling ranges are also shared across groups of similar players rather
                than worked out for each player. Read a range as a rough guide, not as a precise
                read on how boom-or-bust that player is.
              </p>
            ) : (
              <p>
                <span className="font-semibold">
                  The floor-to-ceiling ranges are shared across groups of similar players
                </span>{' '}
                rather than worked out for each player. A range shows how players with a similar
                projection have scored. It is not a read on how boom-or-bust this particular player
                is, so two players with the same range width are tied on it.
              </p>
            ))}
        </div>
      </div>
    </aside>
  )
}
