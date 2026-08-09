import { LayoutGrid, Search, Table2, X } from 'lucide-react'

import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { usePositions, useTeams } from '@/hooks/useCatalog'
import { SORT_OPTIONS, type SortKey } from '@/utils/board'

export type ViewMode = 'table' | 'cards'

export interface ExplorerFilters {
  query: string
  position: string
  team: string
  sort: SortKey
}

/**
 * The explorer's controls.
 *
 * The position list is fetched rather than hard-coded — `/meta/positions` is
 * the authority on what is projected, and the day kickers ship the filter grows
 * a row with no change here. Unprojected positions are shown but disabled, so
 * a user looking for kickers learns they do not exist yet rather than assuming
 * the filter is broken.
 */
export function PlayerFilters({
  filters,
  onChange,
  view,
  onViewChange,
  resultCount,
  totalCount,
}: {
  filters: ExplorerFilters
  onChange: (next: ExplorerFilters) => void
  view: ViewMode
  onViewChange: (view: ViewMode) => void
  resultCount: number
  totalCount: number
}) {
  const positions = usePositions()
  const teams = useTeams()

  const set = <K extends keyof ExplorerFilters>(key: K, value: ExplorerFilters[K]) =>
    onChange({ ...filters, [key]: value })

  return (
    <div className="mb-4 space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Input
          label="Search players"
          hideLabel
          placeholder="Search by name or team…"
          value={filters.query}
          onChange={(event) => set('query', event.target.value)}
          icon={<Search className="size-4" />}
          className="min-w-0 flex-1 basis-56"
          type="search"
          trailing={
            filters.query ? (
              <button
                type="button"
                onClick={() => set('query', '')}
                aria-label="Clear search"
                className="text-ink-muted hover:text-ink flex size-6 items-center justify-center rounded-md"
              >
                <X aria-hidden className="size-3.5" />
              </button>
            ) : undefined
          }
        />

        <Select
          label="Position"
          hideLabel
          value={filters.position}
          onChange={(event) => set('position', event.target.value)}
          className="w-36"
          options={[
            { value: '', label: 'All positions' },
            ...(positions.data ?? []).map((position) => ({
              value: position.position,
              label: position.projected
                ? position.position
                : `${position.position} — not projected`,
              disabled: !position.projected,
            })),
          ]}
        />

        <Select
          label="Team"
          hideLabel
          value={filters.team}
          onChange={(event) => set('team', event.target.value)}
          className="w-32"
          options={[
            { value: '', label: 'All teams' },
            ...(teams.data ?? []).map((team) => ({ value: team.abbr, label: team.abbr })),
          ]}
        />

        <Select
          label="Sort by"
          hideLabel
          value={filters.sort}
          onChange={(event) => set('sort', event.target.value as SortKey)}
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
          ? `${totalCount} projected players`
          : `${resultCount} of ${totalCount} projected players`}
      </p>
    </div>
  )
}
