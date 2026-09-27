import { useSlate } from '@/app/slate-context'
import { Button } from '@/components/ui/Button'

/**
 * The way out of an unpublished week.
 *
 * A link to a week whose projections are not out yet opens an empty board,
 * and "not out yet" on its own leaves the reader to find the week picker and
 * work out which weeks do exist. This offers the newest published week of the
 * same season in one click. Renders nothing when the current week is already
 * published or when no week of the season is.
 */
export function LatestWeekButton() {
  const slate = useSlate()
  const latest = slate.availableWeeks.length > 0 ? Math.max(...slate.availableWeeks) : null
  if (latest === null || slate.hasPublishedBoard || slate.week === latest) return null

  return (
    <Button variant="primary" size="sm" onClick={() => slate.setWeek(latest)}>
      Go to week {latest}, the latest published
    </Button>
  )
}
