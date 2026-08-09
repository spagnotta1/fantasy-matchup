import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ShieldQuestion } from 'lucide-react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, Refreshing } from '@/components/feedback/States'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { usePositions } from '@/hooks/useCatalog'
import { useDefenseRankings } from '@/hooks/useMatchups'
import { cn } from '@/utils/cn'
import { formatPoints } from '@/utils/format'
import type { PositionMatchup } from '@/api/schemas'

interface DefenseRow {
  team: string
  matchup: PositionMatchup
}

type DefenseSort = 'rank' | 'fp' | 'targets' | 'carries' | 'yards' | 'team'

const COLUMNS: { key: DefenseSort; label: string; numeric: boolean; className?: string }[] = [
  { key: 'rank', label: 'Rank', numeric: false, className: 'w-16' },
  { key: 'team', label: 'Defence', numeric: false, className: 'w-24' },
  { key: 'fp', label: 'Pts allowed', numeric: true },
  { key: 'targets', label: 'Targets', numeric: true, className: 'hidden sm:table-cell' },
  { key: 'carries', label: 'Carries', numeric: true, className: 'hidden sm:table-cell' },
  { key: 'yards', label: 'Yards', numeric: true, className: 'hidden md:table-cell' },
]

/**
 * Every defence in the league against one position.
 *
 * The position selector is the whole point of this board. "A good defence" is
 * not one number — a front seven that erases running backs can be the softest
 * draw in the league for tight ends — and a single overall ranking hides
 * exactly the split a manager is trying to exploit.
 *
 * Ordered by the API's own rank by default, where 1 is the toughest. Sorting on
 * a column reorders the rows and nothing else: every figure here is served,
 * none is computed in the browser.
 */
export function DefenseBoard() {
  const positions = usePositions()
  const projected = useMemo(
    () => (positions.data ?? []).filter((entry) => entry.projected),
    [positions.data],
  )
  const [position, setPosition] = useState<string | null>(null)
  const active = position ?? projected[0]?.position ?? null

  const { data, isPending, isError, error, refetch, isPlaceholderData } =
    useDefenseRankings(active)
  const [sort, setSort] = useState<DefenseSort>('rank')
  const [direction, setDirection] = useState<'asc' | 'desc'>('asc')

  const rows = useMemo<DefenseRow[]>(() => {
    if (!data) return []
    const flattened: DefenseRow[] = []
    for (const [team, matchups] of Object.entries(data.data)) {
      // The response carries one entry per position; with a position filter
      // applied that is a single-element array, but the shape does not change.
      const matchup = matchups.find((entry) => entry.position === active) ?? matchups[0]
      if (matchup) flattened.push({ team, matchup })
    }
    return sortRows(flattened, sort, direction)
  }, [data, active, sort, direction])

  const onSort = (key: DefenseSort) => {
    if (key === sort) {
      setDirection((current) => (current === 'asc' ? 'desc' : 'asc'))
      return
    }
    setSort(key)
    // Rank and team read low-to-high; the volume columns are "who gives up the
    // most", which is descending.
    setDirection(key === 'rank' || key === 'team' ? 'asc' : 'desc')
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader
        as="h2"
        title="Defensive form"
        description="What every defence has allowed to one position over its last four completed games. Rank 1 is the toughest draw."
        action={
          <div className="flex items-center gap-2">
            <ProvenanceBadge provenance="derived" />
            {projected.length > 0 && (
              <SegmentedControl
                label="Position"
                size="sm"
                value={active ?? ''}
                onChange={setPosition}
                options={projected.map((entry) => ({
                  value: entry.position,
                  label: entry.position,
                }))}
              />
            )}
          </div>
        }
      />

      {isPending ? (
        <SkeletonTable rows={12} columns={5} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<ShieldQuestion aria-hidden className="size-5" />}
          title="No defensive form for this week"
          description="Grades need completed games behind them. Early in a season, and in a week the warehouse has not ingested, there is nothing to rank."
        />
      ) : (
        <Refreshing active={isPlaceholderData}>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">
                Defences ranked against {active}, sorted by {sort}, {direction}ending.
              </caption>
              <thead>
                <tr className="border-line border-b">
                  {COLUMNS.map((column) => (
                    <th
                      key={column.key}
                      scope="col"
                      aria-sort={
                        sort === column.key
                          ? direction === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : undefined
                      }
                      className={cn(
                        'text-ink-muted px-3 py-2 text-xs font-medium tracking-wide uppercase',
                        column.numeric ? 'text-right' : 'text-left',
                        column.className,
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => onSort(column.key)}
                        className={cn(
                          'hover:text-ink inline-flex items-center gap-1 rounded-sm transition-colors',
                          sort === column.key && 'text-ink',
                        )}
                      >
                        {column.label}
                        {sort === column.key &&
                          (direction === 'asc' ? (
                            <ArrowUp aria-hidden className="size-3" />
                          ) : (
                            <ArrowDown aria-hidden className="size-3" />
                          ))}
                      </button>
                    </th>
                  ))}
                  <th
                    scope="col"
                    className="text-ink-muted w-24 px-3 py-2 text-right text-xs font-medium tracking-wide uppercase"
                  >
                    Matchup
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.team}
                    className="border-line hover:bg-surface-hover border-b transition-colors last:border-b-0"
                  >
                    <td className="text-ink-muted tnum px-3 py-2 text-xs">
                      {row.matchup.grade.defense_rank ?? '—'}
                    </td>
                    <th scope="row" className="text-ink px-3 py-2 text-left text-sm font-medium">
                      {row.team}
                    </th>
                    <td className="tnum text-ink px-3 py-2 text-right font-medium">
                      {formatPoints(row.matchup.fp_allowed_l4)}
                    </td>
                    <td className="tnum text-ink-secondary hidden px-3 py-2 text-right sm:table-cell">
                      {formatPoints(row.matchup.targets_allowed_l4)}
                    </td>
                    <td className="tnum text-ink-secondary hidden px-3 py-2 text-right sm:table-cell">
                      {formatPoints(row.matchup.carries_allowed_l4)}
                    </td>
                    <td className="tnum text-ink-secondary hidden px-3 py-2 text-right md:table-cell">
                      {formatPoints(row.matchup.yards_allowed_l4, 0)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <MatchupGradeChip
                        grade={row.matchup.grade}
                        opponent={row.team}
                        fpAllowed={row.matchup.fp_allowed_l4}
                        align="end"
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <CardBody className="border-line border-t py-3">
            <p className="text-ink-muted text-xs leading-relaxed">
              Points allowed are measured in the API&apos;s reference scoring format and do not
              change with your league&apos;s settings. Grades are percentiles across this week, and
              a defence with fewer than three completed games behind it is left ungraded rather
              than given a middle letter.
            </p>
          </CardBody>
        </Refreshing>
      )}
    </Card>
  )
}

/** Nulls sort last in both directions — a missing figure is not a low one. */
function sortRows(rows: DefenseRow[], key: DefenseSort, direction: 'asc' | 'desc'): DefenseRow[] {
  const sorted = [...rows]
  if (key === 'team') {
    sorted.sort((a, b) => (direction === 'asc' ? 1 : -1) * a.team.localeCompare(b.team))
    return sorted
  }

  const value = (row: DefenseRow): number | null => {
    switch (key) {
      case 'rank':
        return row.matchup.grade.defense_rank ?? null
      case 'fp':
        return row.matchup.fp_allowed_l4 ?? null
      case 'targets':
        return row.matchup.targets_allowed_l4 ?? null
      case 'carries':
        return row.matchup.carries_allowed_l4 ?? null
      case 'yards':
        return row.matchup.yards_allowed_l4 ?? null
      default:
        return null
    }
  }

  sorted.sort((a, b) => {
    const left = value(a)
    const right = value(b)
    if (left === null && right === null) return a.team.localeCompare(b.team)
    if (left === null) return 1
    if (right === null) return -1
    const result = direction === 'desc' ? right - left : left - right
    return result !== 0 ? result : a.team.localeCompare(b.team)
  })
  return sorted
}
