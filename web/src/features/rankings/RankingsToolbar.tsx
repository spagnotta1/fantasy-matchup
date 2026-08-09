import { LayoutGrid, Search, Table2, X } from 'lucide-react'

import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { SORT_OPTIONS, type SortKey } from '@/utils/board'
import type { ViewMode } from '@/features/players/PlayerFilters'

/**
 * Search, ordering and layout for the board.
 *
 * Narrower than the explorer's toolbar on purpose: position is chosen by the
 * tabs above and the team filter is deliberately absent. Rankings answer "who
 * do I start", and a ranking of one team's four projected players is not a
 * ranking — the explorer is where filtering to a team belongs.
 */
export function RankingsToolbar({
  query,
  onQueryChange,
  sort,
  onSortChange,
  view,
  onViewChange,
  resultCount,
  totalCount,
}: {
  query: string
  onQueryChange: (value: string) => void
  sort: SortKey
  onSortChange: (value: SortKey) => void
  view: ViewMode
  onViewChange: (value: ViewMode) => void
  resultCount: number
  totalCount: number
}) {
  return (
    <div className="mb-4 space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Input
          label="Search this board"
          hideLabel
          placeholder="Search by name or team…"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          icon={<Search className="size-4" />}
          className="min-w-0 flex-1 basis-56"
          type="search"
          trailing={
            query ? (
              <button
                type="button"
                onClick={() => onQueryChange('')}
                aria-label="Clear search"
                className="text-ink-muted hover:text-ink flex size-6 items-center justify-center rounded-md"
              >
                <X aria-hidden className="size-3.5" />
              </button>
            ) : undefined
          }
        />

        <Select
          label="Sort by"
          hideLabel
          value={sort}
          onChange={(event) => onSortChange(event.target.value as SortKey)}
          className="w-40"
          options={SORT_OPTIONS}
        />

        <SegmentedControl<ViewMode>
          label="Layout"
          value={view}
          onChange={onViewChange}
          className="hidden sm:inline-flex"
          options={[
            { value: 'table', label: 'Table', icon: <Table2 className="size-3.5" /> },
            { value: 'cards', label: 'Cards', icon: <LayoutGrid className="size-3.5" /> },
          ]}
        />
      </div>

      <p className="text-ink-muted text-xs" aria-live="polite">
        {resultCount === totalCount
          ? `${totalCount} ranked players`
          : `${resultCount} of ${totalCount} ranked players`}
      </p>
    </div>
  )
}
