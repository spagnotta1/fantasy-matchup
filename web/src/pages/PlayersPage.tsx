import { useCallback, useEffect, useMemo, useState } from 'react'
import { SearchX } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { SkeletonCards, SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { CalibrationNotice } from '@/components/domain/CalibrationNotice'
import { ProjectionCards } from '@/components/domain/ProjectionCards'
import { ProjectionTable } from '@/components/domain/ProjectionTable'
import { PlayerFilters, type ExplorerFilters, type ViewMode } from '@/features/players/PlayerFilters'
import { useBoard } from '@/hooks/useProjections'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { matchesQuery, sortBoard, type SortDirection, type SortKey } from '@/utils/board'

const DEFAULT_FILTERS: ExplorerFilters = { query: '', position: '', team: '', sort: 'rank' }

/**
 * Browse every projected player for the week.
 *
 * Position and team are pushed to the API as query parameters; the name search
 * and the sort are applied in the browser. That split is deliberate rather than
 * lazy: the API can filter but not name-search a board, and it returns the
 * whole slate in one page — so client-side work here operates on the complete
 * set, never on a page of it.
 */
export default function PlayersPage() {
  const [filters, setFilters] = useState<ExplorerFilters>(DEFAULT_FILTERS)
  const [direction, setDirection] = useState<SortDirection>('asc')
  const [view, setView] = useState<ViewMode>('table')

  // Below `sm` the table is not offered at all, so the toggle cannot strand
  // someone on a layout their screen cannot show.
  const isCompact = useMediaQuery('(max-width: 639px)')
  const effectiveView: ViewMode = isCompact ? 'cards' : view

  const { data, isPending, isError, error, refetch, isPlaceholderData } = useBoard({
    positions: filters.position ? [filters.position] : undefined,
    teams: filters.team ? [filters.team] : undefined,
  })

  const entries = useMemo(() => {
    if (!data) return []
    const matched = data.data.filter((entry) => matchesQuery(entry, filters.query))
    return sortBoard(matched, filters.sort, direction)
  }, [data, filters.query, filters.sort, direction])

  const onSort = useCallback(
    (key: SortKey) => {
      if (key === filters.sort) {
        setDirection((current) => (current === 'asc' ? 'desc' : 'asc'))
        return
      }
      setFilters((current) => ({ ...current, sort: key }))
      // Rank and name read naturally low-to-high; every other column is a
      // "who is best" question, which is descending.
      setDirection(key === 'rank' || key === 'name' ? 'asc' : 'desc')
    },
    [filters.sort],
  )

  // Changing the sort from the dropdown should behave like clicking its header.
  useEffect(() => {
    setDirection(filters.sort === 'rank' || filters.sort === 'name' ? 'asc' : 'desc')
  }, [filters.sort])

  const total = data?.data.length ?? 0
  const filtered = filters.query.trim().length > 0 || filters.position !== '' || filters.team !== ''

  return (
    <>
      <PageHeader title="Players" question="Who is worth a look, and how do they compare?" />

      <div className="mb-4 space-y-3">
        <CalibrationNotice projections={data?.data.map((entry) => entry.projection)} />
        {data && <NoticeList notices={data.meta.notices} />}
      </div>

      <PlayerFilters
        filters={filters}
        onChange={setFilters}
        view={effectiveView}
        onViewChange={setView}
        resultCount={entries.length}
        totalCount={total}
      />

      <Card className="overflow-hidden">
        {isPending ? (
          effectiveView === 'table' ? (
            <SkeletonTable rows={12} columns={6} />
          ) : (
            <div className="p-4">
              <SkeletonCards count={6} />
            </div>
          )
        ) : isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : entries.length === 0 ? (
          <EmptyState
            icon={<SearchX aria-hidden className="size-5" />}
            title={filtered ? 'No players match these filters' : 'No projections for this week'}
            description={
              filtered
                ? 'Try a different position, team or search term.'
                : data.meta.model === null
                  ? 'No model run has been published for this week yet. Projections appear once the weekly job runs.'
                  : 'The published run holds no players for this week.'
            }
            action={
              filtered ? (
                <Button variant="secondary" size="sm" onClick={() => setFilters(DEFAULT_FILTERS)}>
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <Refreshing active={isPlaceholderData}>
            {effectiveView === 'table' ? (
              <ProjectionTable
                entries={entries}
                sort={filters.sort}
                direction={direction}
                onSort={onSort}
              />
            ) : (
              <div className="p-4">
                <ProjectionCards entries={entries} />
              </div>
            )}
          </Refreshing>
        )}
      </Card>
    </>
  )
}
