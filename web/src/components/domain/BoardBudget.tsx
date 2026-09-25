import { Button } from '@/components/ui/Button'
import type { RenderBudget } from '@/hooks/useRenderBudget'

/**
 * The footer under a budgeted board.
 *
 * Rendered whenever the board is larger than one step — including after
 * everything is shown — so the live region that announced "showing 200 of 640"
 * is still in the document to announce "showing all 640". A live region that
 * unmounts with its last message never says it.
 */
export function ShowMoreRows({ budget, noun = 'players' }: { budget: RenderBudget; noun?: string }) {
  if (budget.total <= budget.step) return null

  const next = Math.min(budget.step, budget.total - budget.shown)

  return (
    <div className="border-line flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3">
      <p className="text-ink-muted text-xs" aria-live="polite">
        {budget.hasMore
          ? `Showing the top ${budget.shown} of ${budget.total} ${noun}. Search and sort cover all ${budget.total}.`
          : `Showing all ${budget.total} ${noun}.`}
      </p>
      {budget.hasMore && (
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={budget.showMore} loading={budget.isPending}>
            Show {next} more
          </Button>
          <Button size="sm" variant="ghost" onClick={budget.showAll} disabled={budget.isPending}>
            Show all {budget.total}
          </Button>
        </div>
      )}
    </div>
  )
}
