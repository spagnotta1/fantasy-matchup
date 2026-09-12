import { ArrowDown, ArrowUp } from 'lucide-react'

import { ConfidenceChip } from '@/components/domain/ConfidenceChip'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { cn } from '@/utils/cn'
import { boardCeiling, groupByTier } from '@/utils/board'
import type { SortDirection, SortKey } from '@/utils/board'
import type { RankedProjection } from '@/api/schemas'

interface Column {
  key: SortKey | null
  label: string
  className: string
  /** Numeric columns are right-aligned so digits line up down the column. */
  numeric?: boolean
}

const COLUMNS: Column[] = [
  { key: 'rank', label: '#', className: 'w-12' },
  { key: 'name', label: 'Player', className: 'min-w-56' },
  { key: null, label: 'Matchup', className: 'w-24' },
  // Range and the numeric Floor/Ceiling pair are the same information in two
  // forms, so they never appear together: the bar (which carries its own
  // endpoint labels) from `xl`, the bare numbers at `lg` where the bar has no
  // room to be readable. Both remain sortable from the toolbar dropdown.
  { key: null, label: 'Range', className: 'w-48 hidden xl:table-cell' },
  { key: 'floor', label: 'Floor', className: 'w-20 hidden lg:table-cell xl:hidden', numeric: true },
  { key: 'ceiling', label: 'Ceiling', className: 'w-20 hidden lg:table-cell xl:hidden', numeric: true },
  { key: 'confidence', label: 'Confidence', className: 'w-28 hidden md:table-cell' },
  { key: 'projection', label: 'Projection', className: 'w-24', numeric: true },
]

export interface ProjectionTableProps {
  entries: RankedProjection[]
  sort: SortKey
  direction: SortDirection
  onSort: (key: SortKey) => void
  /**
   * Which rank to print in the first column.
   *
   * `overall` is the board's rank across every position; `positional` is the
   * rank within the position. On a single-position board the two are the same
   * number, and on a mixed board only `overall` is meaningful.
   */
  rankMode?: 'overall' | 'positional'
  /**
   * Draw tier boundaries as separator rows.
   *
   * The caller is responsible for only enabling this on a list still in rank
   * order — see `groupByTier`.
   */
  showTiers?: boolean
  /** Adds a tier column, for boards where the rows are not grouped. */
  showTierColumn?: boolean
  caption?: string
}

/**
 * The dense board.
 *
 * A real `<table>` with a real `<caption>` and `scope`d headers, because that
 * is what makes several hundred rows navigable with a screen reader. Sorting is
 * on the header buttons and `aria-sort` follows it, so the current ordering is
 * announced rather than only drawn as an arrow.
 *
 * Columns drop out at narrower widths rather than the table scrolling
 * sideways — a horizontally scrolling spreadsheet on a laptop is the thing this
 * layout exists to avoid. Below `sm` the card view takes over entirely.
 *
 * Shared by the player explorer and the rankings board. They differ in which
 * rank they print and whether tiers are drawn, and in nothing else — keeping
 * two tables in step by hand is how a product ends up with two subtly different
 * ideas of what a row looks like.
 */
export function ProjectionTable({
  entries,
  sort,
  direction,
  onSort,
  rankMode = 'overall',
  showTiers = false,
  showTierColumn = false,
  caption,
}: ProjectionTableProps) {
  const scaleMax = boardCeiling(entries)
  const columns = showTierColumn
    ? [
        ...COLUMNS.slice(0, 2),
        { key: null, label: 'Tier', className: 'w-16 hidden sm:table-cell' } satisfies Column,
        ...COLUMNS.slice(2),
      ]
    : COLUMNS
  const groups = showTiers ? groupByTier(entries) : [{ tier: 0, entries }]

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          {caption ?? 'Projected players for the selected week'}, sorted by {sort},{' '}
          {direction}ending.
        </caption>
        <thead>
          <tr className="border-line border-b">
            {columns.map((column) => {
              const active = column.key !== null && column.key === sort
              return (
                <th
                  key={column.label}
                  scope="col"
                  aria-sort={
                    active ? (direction === 'asc' ? 'ascending' : 'descending') : undefined
                  }
                  className={cn(
                    'text-ink-muted px-3 py-2 text-xs font-medium tracking-wide uppercase',
                    column.numeric ? 'text-right' : 'text-left',
                    column.className,
                  )}
                >
                  {column.key === null ? (
                    column.label
                  ) : (
                    <button
                      type="button"
                      onClick={() => onSort(column.key as SortKey)}
                      className={cn(
                        'hover:text-ink inline-flex items-center gap-1 rounded-sm transition-colors',
                        active && 'text-ink',
                      )}
                    >
                      {column.label}
                      {active &&
                        (direction === 'asc' ? (
                          <ArrowUp aria-hidden className="size-3" />
                        ) : (
                          <ArrowDown aria-hidden className="size-3" />
                        ))}
                    </button>
                  )}
                </th>
              )
            })}
          </tr>
        </thead>

        {groups.map((group) => (
          // One `<tbody>` per tier. Multiple bodies are valid HTML and give the
          // separator a row group to head, which is what makes "Tier 3" an
          // announced heading rather than a decorative stripe.
          <tbody key={showTiers ? group.tier : 'all'}>
            {showTiers && (
              <tr className="bg-surface-sunken">
                <th
                  scope="rowgroup"
                  colSpan={columns.length}
                  className="text-ink-secondary px-3 py-1.5 text-left text-xs font-semibold"
                >
                  Tier {group.tier}
                  <span className="text-ink-muted ml-2 font-normal">
                    {group.entries.length} {group.entries.length === 1 ? 'player' : 'players'}
                  </span>
                </th>
              </tr>
            )}

            {group.entries.map((entry) => {
              const { projection } = entry
              const { points } = projection.prediction
              return (
                <tr
                  key={projection.player.player_id}
                  className="border-line hover:bg-surface-hover border-b transition-colors last:border-b-0"
                >
                  <td className="text-ink-muted tnum px-3 py-2 text-xs">
                    {rankMode === 'positional' ? entry.positional_rank : entry.rank}
                  </td>
                  <td className="px-3 py-2">
                    <PlayerIdentity
                      player={projection.player}
                      team={projection.team}
                      size="sm"
                      subtitle={
                        <>
                          {projection.player.position} · {projection.team}{' '}
                          {projection.is_home ? 'vs' : '@'} {projection.opponent}
                        </>
                      }
                    />
                  </td>
                  {showTierColumn && (
                    <td className="text-ink-secondary tnum hidden px-3 py-2 text-xs sm:table-cell">
                      {entry.tier}
                    </td>
                  )}
                  <td className="px-3 py-2">
                    <MatchupGradeChip
                      grade={projection.matchup?.grade}
                      opponent={projection.opponent}
                      fpAllowed={projection.matchup?.fp_allowed_vs_position_l4}
                    />
                  </td>
                  <td className="hidden px-3 py-2 xl:table-cell">
                    <OutcomeRange
                      floor={points.floor}
                      median={points.median}
                      ceiling={points.ceiling}
                      scaleMax={scaleMax}
                    />
                  </td>
                  <td className="tnum text-ink-secondary hidden px-3 py-2 text-right lg:table-cell xl:hidden">
                    {points.floor?.toFixed(1) ?? '—'}
                  </td>
                  <td className="tnum text-ink-secondary hidden px-3 py-2 text-right lg:table-cell xl:hidden">
                    {points.ceiling?.toFixed(1) ?? '—'}
                  </td>
                  <td className="hidden px-3 py-2 md:table-cell">
                    <ConfidenceChip label={points.confidence_label} value={points.confidence} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <ProjectionValue points={points} actualPoints={projection.actual_points} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        ))}
      </table>
    </div>
  )
}
