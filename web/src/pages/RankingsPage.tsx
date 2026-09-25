import { useCallback, useDeferredValue, useEffect, useMemo, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { Layers, SearchX } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { SkeletonCards, SkeletonTable } from '@/components/ui/Skeleton'
import { InfoTip } from '@/components/ui/Tooltip'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { CalibrationNotice } from '@/components/domain/CalibrationNotice'
import { ProjectionCards } from '@/components/domain/ProjectionCards'
import { ProjectionTable } from '@/components/domain/ProjectionTable'
import { PositionTabs } from '@/features/rankings/PositionTabs'
import { RankingsToolbar } from '@/features/rankings/RankingsToolbar'
import { UnprojectedPosition } from '@/features/rankings/UnprojectedPosition'
import type { ViewMode } from '@/features/players/PlayerFilters'
import { usePositions } from '@/hooks/useCatalog'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { boardNotices, useBoard, usePositionRankings } from '@/hooks/useProjections'
import { useUrlState } from '@/hooks/useUrlState'
import { useSlate } from '@/app/slate-context'
import { matchesQuery, sortBoard, type SortDirection, type SortKey } from '@/utils/board'
import { formatScoringProfile } from '@/utils/format'

interface RankingsPageState {
  query: string
  sort: SortKey
  direction: SortDirection
  view: ViewMode
}

const DEFAULT_STATE: RankingsPageState = {
  query: '',
  sort: 'rank',
  direction: 'asc',
  view: 'table',
}

/**
 * The weekly board.
 *
 * Two data sources behind one screen, chosen by the route. A position tab reads
 * `/rankings/{position}`, which re-ranks and re-tiers inside that position; the
 * All tab reads `/projections`, whose tiers span positions. That distinction
 * drives the layout: tier *bands* are drawn only on a single-position board,
 * where a tier means "these players are interchangeable at this roster spot".
 * Across positions the same number groups a quarterback with a wide receiver,
 * so it is shown as a column and not as a section heading.
 *
 * Tier bands also disappear the moment the user sorts by anything other than
 * rank. A tier is a statement about adjacent rows; drawn over a list ordered by
 * ceiling it would scatter one tier down the page and assert something the API
 * never said.
 */
export default function RankingsPage() {
  const { position: positionParam } = useParams<{ position: string }>()
  const position = positionParam ? positionParam.toUpperCase() : null

  const slate = useSlate()
  const positions = usePositions()
  const support = positions.data?.find((entry) => entry.position === position) ?? null
  const projected = position === null || support?.projected === true
  // A path segment the catalog does not recognise. Only knowable once the
  // catalog has answered — before that, an unknown position and a slow request
  // look identical.
  const unknownPosition = position !== null && positions.isSuccess && support === null

  const [state, setState] = useUrlState(DEFAULT_STATE)
  const { query, sort, direction, view } = state
  const setQuery = useCallback((value: string) => setState({ query: value }), [setState])
  const setView = useCallback((value: ViewMode) => setState({ view: value }), [setState])

  const isCompact = useMediaQuery('(max-width: 639px)')
  const effectiveView: ViewMode = isCompact ? 'cards' : view

  // Exactly one of these is ever enabled, so the screen makes one request.
  const board = useBoard({ enabled: position === null })
  const positionBoard = usePositionRankings(position, projected && positions.isSuccess)
  const active = position === null ? board : positionBoard

  // See `PlayersPage`: the input takes the keystroke, the board follows.
  const deferredQuery = useDeferredValue(query)
  const entries = useMemo(() => {
    if (!active.data) return []
    const matched = active.data.data.filter((entry) => matchesQuery(entry, deferredQuery))
    return sortBoard(matched, sort, direction)
  }, [active.data, deferredQuery, sort, direction])
  const projections = useMemo(
    () => active.data?.data.map((entry) => entry.projection),
    [active.data],
  )

  // Both keys land in one `setState` call: two calls in the same tick would
  // each read the same stale search params and the second would clobber the
  // first (see `hooks/useUrlState.ts`).
  const onSort = useCallback(
    (key: SortKey) => {
      if (key === sort) {
        setState({ direction: direction === 'asc' ? 'desc' : 'asc' })
        return
      }
      setState({ sort: key, direction: key === 'rank' || key === 'name' ? 'asc' : 'desc' })
    },
    [sort, direction, setState],
  )

  // Sorting from the dropdown should behave like clicking its header.
  const onSortChange = useCallback(
    (key: SortKey) =>
      setState({ sort: key, direction: key === 'rank' || key === 'name' ? 'asc' : 'desc' }),
    [setState],
  )

  // Reset the search when the board changes underneath it: a term that matched
  // four running backs matches nothing on the tight end board, and an empty
  // screen the user did not ask for reads as a broken page. Not on mount, so a
  // deep link with `?query=` intact — e.g. from Back/Forward or a shared URL —
  // isn't wiped the instant the page mounts.
  //
  // Compared against the last position acted on, not gated by a "first
  // render" flag. `setQuery` is rebuilt on every URL change (React Router's
  // `setSearchParams` depends on the current search params), so an effect that
  // ran whenever its dependencies changed fired on every keystroke and erased
  // the term being typed: search on this page did not work at all.
  const lastPosition = useRef(position)
  useEffect(() => {
    if (lastPosition.current === position) return
    lastPosition.current = position
    setQuery('')
  }, [position, setQuery])

  const showTiers = sort === 'rank' && direction === 'asc' && position !== null
  const total = active.data?.data.length ?? 0
  const filtered = query.trim().length > 0

  return (
    <>
      <PageHeader
        title={position && !unknownPosition ? `${position} rankings` : 'Rankings'}
        question="Who should I start at each position this week?"
      />

      <PositionTabs active={position} />

      {unknownPosition ? (
        <Card>
          <EmptyState
            title={`${position} is not a position we recognise`}
            description="Pick a position from the tabs above."
          />
        </Card>
      ) : !projected && support ? (
        <UnprojectedPosition support={support} />
      ) : (
        <>
          <div className="mb-4 space-y-3">
            <CalibrationNotice projections={projections} />
            {active.data && <NoticeList notices={boardNotices(active.data.meta)} />}
          </div>

          <RankingsToolbar
            query={query}
            onQueryChange={setQuery}
            sort={sort}
            onSortChange={onSortChange}
            view={effectiveView}
            onViewChange={setView}
            resultCount={entries.length}
            totalCount={total}
          />

          {showTiers && entries.length > 0 && <TierNote />}

          <Card className="overflow-hidden">
            {active.isPending ? (
              effectiveView === 'table' ? (
                <SkeletonTable rows={12} columns={6} />
              ) : (
                <div className="p-4">
                  <SkeletonCards count={6} />
                </div>
              )
            ) : active.isError ? (
              <ErrorState error={active.error} onRetry={() => void active.refetch()} />
            ) : !active.data || entries.length === 0 ? (
              <EmptyState
                icon={<SearchX aria-hidden className="size-5" />}
                title={filtered ? 'No players match that search' : 'No rankings for this week'}
                description={
                  filtered
                    ? 'Try a different name, or clear the search to see everyone.'
                    : active.data?.meta.model == null
                      ? 'Projections for this week are not out yet. Rankings appear after the weekly update runs.'
                      : `This week's projections include no ${position ?? 'projected'} players for week ${slate.week ?? '—'}.`
                }
                action={
                  filtered ? (
                    <Button variant="secondary" size="sm" onClick={() => setQuery('')}>
                      Clear search
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <Refreshing active={active.isPlaceholderData}>
                {effectiveView === 'table' ? (
                  <ProjectionTable
                    entries={entries}
                    sort={sort}
                    direction={direction}
                    onSort={onSort}
                    rankMode={position === null ? 'overall' : 'positional'}
                    showTiers={showTiers}
                    showTierColumn={position === null}
                    caption={`${position ?? 'Overall'} rankings for week ${slate.week ?? ''}, ${formatScoringProfile(slate.scoringProfile)}`}
                  />
                ) : (
                  <div className="p-4">
                    <ProjectionCards
                      entries={entries}
                      showRank
                      rankMode={position === null ? 'overall' : 'positional'}
                      showTiers={showTiers}
                    />
                  </div>
                )}
              </Refreshing>
            )}
          </Card>
        </>
      )}
    </>
  )
}

/**
 * What a tier boundary means, said once above the board.
 *
 * Worth the space because tiers are the most useful and least self-explanatory
 * thing on this page. The API draws a boundary where the next player down has
 * less than a 45% chance of outscoring the one above — so inside a tier the
 * ordering really is close to a coin flip, and a manager agonising over rank 6
 * versus rank 7 is agonising over noise.
 */
function TierNote() {
  return (
    <p className="text-ink-muted mb-3 flex items-start gap-1.5 text-xs leading-relaxed">
      <Layers aria-hidden className="mt-0.5 size-3.5 shrink-0" />
      <span>
        Players are grouped into tiers. Within a tier the order barely matters — any player could
        realistically outscore the one above. Where one tier ends and the next begins is the line
        worth paying attention to.
        <InfoTip
          label="How tiers are drawn"
          content="A new tier starts when the next player down has less than a 45% chance of outscoring the player above. It is based on those chances, not a fixed points gap."
        />
      </span>
    </p>
  )
}
