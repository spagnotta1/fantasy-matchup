import { GitCompareArrows } from 'lucide-react'

import { Button, ButtonLink } from '@/components/ui/Button'
import { MAX_COMPARISON_PLAYERS, MIN_COMPARISON_PLAYERS } from '@/hooks/useCompare'
import { compareHref, type CompareSelection } from '@/hooks/useCompareSelection'
import { usePlayers } from '@/hooks/useProjections'

/**
 * The players ticked on this list, and the way to the comparison of them.
 *
 * Absent until a box is ticked. It then stays at the foot of the screen for as
 * long as the list is, so the second player can be ticked forty rows below the
 * first and the button is still under the thumb. On a phone it sits above the
 * navigation bar, not behind it.
 *
 * It names who is ticked. A selection outlives a change of position tab, and a
 * running back ticked on one board is not on screen on the next; a count alone
 * would leave the reader to remember who the "1 selected" is. The names are
 * the same identity requests the comparison makes, so they are already in the
 * cache when it opens.
 *
 * It offers a comparison, not a verdict: the button goes to the screen that
 * lays the ranges on one scale, and nothing here says who to start.
 */
export function CompareBar({ selection }: { selection: CompareSelection }) {
  const { ids, full, clear } = selection
  const identities = usePlayers(ids)
  if (ids.length === 0) return null

  const names = identities.map((query) => query.data?.name).filter((name): name is string => Boolean(name))
  const ready = ids.length >= MIN_COMPARISON_PLAYERS

  return (
    <div
      role="region"
      aria-label="Players selected to compare"
      data-compare-bar=""
      className="pointer-events-none sticky bottom-[calc(4.25rem+env(safe-area-inset-bottom))] z-30 mt-4 flex justify-center lg:bottom-4"
    >
      <div className="bg-surface-raised border-line-strong shadow-overlay rounded-card pointer-events-auto flex max-w-full min-w-0 items-center gap-3 border py-2 pr-2 pl-3.5">
        <p className="min-w-0 flex-1 leading-tight" aria-live="polite">
          <span className="text-ink text-body block font-semibold whitespace-nowrap">
            {ids.length} selected
          </span>
          <span className="text-ink-muted text-chip block truncate">
            {!ready
              ? 'Tick one more to compare'
              : full
                ? `${MAX_COMPARISON_PLAYERS} is the most that can be compared`
                : names.join(', ')}
          </span>
        </p>
        <Button size="sm" variant="ghost" onClick={clear}>
          Clear
        </Button>
        {ready ? (
          <ButtonLink to={compareHref(ids)} variant="primary" size="sm" icon={<GitCompareArrows aria-hidden />}>
            Compare {ids.length}
          </ButtonLink>
        ) : (
          // Not a link yet: a comparison of one player is the empty screen.
          <Button variant="primary" size="sm" icon={<GitCompareArrows aria-hidden />} disabled>
            Compare
          </Button>
        )}
      </div>
    </div>
  )
}
