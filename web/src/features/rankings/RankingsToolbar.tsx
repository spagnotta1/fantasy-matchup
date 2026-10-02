import { LayoutGrid, Table2 } from 'lucide-react'

import { FilterSearch, FilterToolbar } from '@/components/ui/FilterToolbar'
import { Select } from '@/components/ui/Select'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useTeams } from '@/hooks/useCatalog'
import type { BoardDensity } from '@/hooks/useBoardDensity'
import { SORT_OPTIONS, type SortKey } from '@/utils/board'
import { cn } from '@/utils/cn'

export type ViewMode = 'table' | 'cards'

/**
 * Search, team and ordering for the board: the controls that change which rows
 * are on it and in what order.
 *
 * Three 32px controls on one line, built to sit beside the position tabs in
 * the bar that stays in view while the board scrolls. A reader forty rows down
 * who wants a different team should not have to scroll back up to say so.
 */
export function RankingsFilters({
  query,
  onQueryChange,
  team,
  onTeamChange,
  sort,
  onSortChange,
  stacked = false,
  className,
}: {
  query: string
  onQueryChange: (value: string) => void
  /** Team abbreviation, or '' for every team. */
  team: string
  onTeamChange: (value: string) => void
  sort: SortKey
  onSortChange: (value: SortKey) => void
  /**
   * Search on a line of its own, team and sort sharing the next. For a phone,
   * where three controls on one line leave the search box too narrow to read
   * what was typed into it.
   */
  stacked?: boolean
  className?: string
}) {
  const teams = useTeams()

  return (
    <FilterToolbar label="Filter and sort players" className={className}>
      <FilterSearch
        label="Search players"
        placeholder="Search by name or team…"
        value={query}
        onChange={onQueryChange}
        className={cn('max-w-none', stacked ? 'basis-full' : 'basis-40')}
      />

      <Select
        label="Team"
        hideLabel
        size="sm"
        value={team}
        onChange={(event) => onTeamChange(event.target.value)}
        className={stacked ? 'min-w-0 flex-1' : 'w-28 shrink-0'}
        options={[
          { value: '', label: 'All teams' },
          ...(teams.data ?? []).map((entry) => ({ value: entry.abbr, label: entry.abbr })),
        ]}
      />

      <Select
        label="Sort by"
        hideLabel
        size="sm"
        value={sort}
        onChange={(event) => onSortChange(event.target.value as SortKey)}
        className={stacked ? 'min-w-0 flex-1' : 'w-36 shrink-0'}
        options={SORT_OPTIONS}
      />
    </FilterToolbar>
  )
}

/**
 * How many players the board is showing, and how it is drawn.
 *
 * Layout and row height change how the board looks, not what is on it, so they
 * stay with the count above the table rather than in the sticky bar: they are
 * set once, not reached for forty rows down.
 */
export function RankingsViewBar({
  resultCount,
  totalCount,
  view,
  onViewChange,
  density,
  onDensityChange,
  /** The list on a narrow screen has one layout and one row height. */
  showControls,
}: {
  resultCount: number
  totalCount: number
  view: ViewMode
  onViewChange: (value: ViewMode) => void
  density: BoardDensity
  onDensityChange: (value: BoardDensity) => void
  showControls: boolean
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <p className="text-ink-muted text-detail" aria-live="polite">
        {resultCount === totalCount
          ? `${totalCount} ranked players`
          : `${resultCount} of ${totalCount} ranked players`}
      </p>

      {showControls && (
        <div className="flex items-center gap-2">
          {view === 'table' && (
            <SegmentedControl<BoardDensity>
              label="Row height"
              size="sm"
              value={density}
              onChange={onDensityChange}
              options={[
                { value: 'default', label: 'Compact' },
                { value: 'comfortable', label: 'Roomy' },
              ]}
            />
          )}
          <SegmentedControl<ViewMode>
            label="Layout"
            size="sm"
            value={view}
            onChange={onViewChange}
            options={[
              { value: 'table', label: 'Table', icon: <Table2 className="size-3.5" /> },
              { value: 'cards', label: 'Cards', icon: <LayoutGrid className="size-3.5" /> },
            ]}
          />
        </div>
      )}
    </div>
  )
}
