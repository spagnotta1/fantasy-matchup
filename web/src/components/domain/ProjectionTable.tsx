import { memo, useMemo } from 'react'

import {
  ColumnHeader,
  GroupHeaderRow,
  RowHeaderCell,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  type TableDensity,
} from '@/components/ui/DataTable'
import { ShowMoreRows } from '@/components/domain/BoardBudget'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { PlayerCell } from '@/components/domain/PlayerCell'
import { RowFlags } from '@/components/domain/RowFlags'
import { useReorderAnimation } from '@/hooks/useReorderAnimation'
import { useRenderBudget } from '@/hooks/useRenderBudget'
import { formatPercent } from '@/utils/format'
import { boardCeiling, gameLine, groupByTier, orderSignature } from '@/utils/board'
import type { SortDirection, SortKey } from '@/utils/board'
import type { RankedProjection } from '@/api/schemas'

const BOARD_HINTS = {
  matchup:
    'How easy the opponent is for this position, from A (easiest) to F (toughest), compared with every other matchup this week.',
  range:
    'The likely scoring range, ruled every 5 points. The thin line runs from a bad week to a strong week (8 in 10 outcomes), the solid box holds the middle half, and the tick is the middle outcome. The yellow line is 20 points. The numbers either side are the floor and the ceiling.',
  boom:
    'How often a week like this one reaches 20 points or more: the share of the range past the yellow line. An estimate, not a promise.',
  projection: 'Expected fantasy points this week under your scoring settings.',
  tier: 'Players in the same tier are close enough that either could outscore the other.',
} as const

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
  /** Row height. 40px unless the reader has asked for more room. */
  density?: TableDensity
  /** Where the column header stops under the page's own sticky toolbar. */
  stickyTop?: string
  caption?: string
}

/**
 * The board.
 *
 * Built from the shared table parts, so it reads like every other table in the
 * product: a real `<table>` with a caption and scoped headers, sort on the
 * header buttons with `aria-sort` following it, a header that stays put while
 * several hundred rows scroll under it, and the whole row following the
 * player's link.
 *
 * ## The range is on every row at every width
 *
 * The range strip is the reason this product exists, and it used to appear
 * only from 1,280px: a laptop at 1,100px saw two bare numbers, and a tablet
 * saw nothing. It is now a column at every width this table is drawn at. Its
 * width follows the table's own width rather than the viewport's — a container
 * query — so it is right whether the sidebar is open or not: about a third of
 * a wide table, and a fixed compact strip in a narrow one. Floor and ceiling
 * are printed either side of it at both sizes, which is why the separate
 * numeric Floor and Ceiling columns are gone: they were the strip's stand-in,
 * and the strip no longer needs one. Both still sort, from the toolbar.
 *
 * Nothing drops out as the table narrows, and it cannot outgrow its card: the
 * layout is fixed, every column but the player's has a width, and the player
 * takes what is left. Where what is left would not hold a name, this table is
 * not drawn at all — the page draws `ProjectionList`, the same rows in two
 * lines each.
 *
 * ## Density
 *
 * A row is one line: 24px avatar, name, then team and opponent in grey. That
 * is what brings it from 53px to 40px, and a laptop screen from ten players to
 * sixteen. A row grows only when its own content needs it — a long name beside
 * an injury designation in a narrow table.
 */
export const ProjectionTable = memo(function ProjectionTable({
  entries,
  sort,
  direction,
  onSort,
  rankMode = 'overall',
  showTiers = false,
  showTierColumn = false,
  density = 'default',
  stickyTop,
  caption,
}: ProjectionTableProps) {
  // The scale and the tier sizes come from the whole list, not the drawn
  // slice: range bars must not rescale when more rows are revealed, and a tier
  // heading states how many players the tier holds, not how many are on screen.
  const scaleMax = useMemo(() => boardCeiling(entries), [entries])
  const tierSizes = useMemo(() => {
    const sizes = new Map<number, number>()
    for (const entry of entries) sizes.set(entry.tier, (sizes.get(entry.tier) ?? 0) + 1)
    return sizes
  }, [entries])

  const budget = useRenderBudget(entries.length)
  const visible = useMemo(() => entries.slice(0, budget.shown), [entries, budget.shown])
  const orderKey = useMemo(() => orderSignature(visible), [visible])
  const tableRef = useReorderAnimation<HTMLTableElement>(orderKey)

  const groups = showTiers ? groupByTier(visible) : [{ tier: 0, entries: visible }]
  const columnCount = showTierColumn ? 7 : 6
  // A finished week prints "actual 18.4" beside each projection, which needs
  // the room a bare number does not.
  const hasActuals = useMemo(
    () => entries.some((entry) => entry.projection.actual_points != null),
    [entries],
  )
  const sortOf = (key: SortKey) => (key === sort ? direction : 'none')

  return (
    <>
      <Table
        ref={tableRef}
        // A query container, so the range column can size to the table.
        className="@container"
        caption={caption ?? 'Projected players for the selected week'}
        captionNote={`sorted by ${sort}, ${direction}ending`}
        density={density}
        stickyTop={stickyTop}
        layout="fixed"
      >
        <TableHead>
          <ColumnHeader className="w-12" sort={sortOf('rank')} onSort={() => onSort('rank')}>
            #
          </ColumnHeader>
          <ColumnHeader sort={sortOf('name')} onSort={() => onSort('name')}>
            Player
          </ColumnHeader>
          {showTierColumn && (
            <ColumnHeader className="w-12" tip={BOARD_HINTS.tier}>
              Tier
            </ColumnHeader>
          )}
          <ColumnHeader
            className="w-26"
            sort={sortOf('matchup')}
            onSort={() => onSort('matchup')}
            tip={BOARD_HINTS.matchup}
          >
            Matchup
          </ColumnHeader>
          <ColumnHeader className={RANGE_WIDTH} tip={BOARD_HINTS.range}>
            Range
          </ColumnHeader>
          <ColumnHeader
            numeric
            className="w-32"
            sort={sortOf('boom')}
            onSort={() => onSort('boom')}
            tip={BOARD_HINTS.boom}
          >
            Chance of 20+
          </ColumnHeader>
          <ColumnHeader
            numeric
            className={hasActuals ? 'w-40' : 'w-26'}
            sort={sortOf('projection')}
            onSort={() => onSort('projection')}
            tip={BOARD_HINTS.projection}
          >
            Projection
          </ColumnHeader>
        </TableHead>

        {groups.map((group) => {
          const size = tierSizes.get(group.tier) ?? group.entries.length
          return (
            // One `<tbody>` per tier. Multiple bodies are valid HTML and give
            // the separator a row group to head, which is what makes "Tier 3"
            // an announced heading rather than a decorative stripe.
            <TableBody key={showTiers ? group.tier : 'all'}>
              {showTiers && (
                <GroupHeaderRow colSpan={columnCount}>
                  Tier {group.tier}
                  <span className="text-ink-muted ml-2 font-normal">
                    {size} {size === 1 ? 'player' : 'players'}
                  </span>
                </GroupHeaderRow>
              )}

              {group.entries.map((entry) => (
                <BoardRow
                  key={entry.projection.player.player_id}
                  entry={entry}
                  rankMode={rankMode}
                  showTierColumn={showTierColumn}
                  scaleMax={scaleMax}
                />
              ))}
            </TableBody>
          )
        })}
      </Table>
      <ShowMoreRows budget={budget} />
    </>
  )
})

/**
 * The range column's width, by the table's own width.
 *
 * The strip takes the room the table has to spare, and no more: whatever is
 * left once the fixed columns (27rem) and a player cell wide enough for a
 * name, a game and an injury designation (21rem) are paid for. It is never
 * narrower than 13rem — a strip of about 100px between its two printed
 * endpoints, near the smallest at which the box and the line to gain are still
 * told apart — and never more than 38% of the table. `cqw` is the table's
 * frame, so this holds whether the sidebar is open or not.
 */
const RANGE_WIDTH = 'w-[clamp(13rem,calc(100cqw-48rem),38cqw)]'

/**
 * One board row, memoised.
 *
 * A re-sort hands every row the same `entry` object it had before, so React can
 * move the existing `<tr>` rather than re-render a chip, an avatar and a range
 * strip for each of them. `scaleMax` is computed over the whole board, so it is
 * stable across sorts and reveals too.
 */
const BoardRow = memo(function BoardRow({
  entry,
  rankMode,
  showTierColumn,
  scaleMax,
}: {
  entry: RankedProjection
  rankMode: 'overall' | 'positional'
  showTierColumn: boolean
  scaleMax: number
}) {
  const { projection } = entry
  const { points } = projection.prediction
  return (
    <TableRow data-flip-key={projection.player.player_id}>
      <TableCell className="text-ink-muted tnum text-detail">
        {rankMode === 'positional' ? entry.positional_rank : entry.rank}
      </TableCell>
      <RowHeaderCell>
        {/* On a mixed board the position is part of who the player is; on a
            position board every row would say the same thing. */}
        <PlayerCell player={projection.player} meta={gameLine(projection, showTierColumn)}>
          <RowFlags projection={projection} />
        </PlayerCell>
      </RowHeaderCell>
      {showTierColumn && <TableCell className="text-ink-secondary tnum text-detail">{entry.tier}</TableCell>}
      <TableCell>
        <MatchupGradeChip
          grade={projection.matchup?.grade}
          opponent={projection.opponent}
          fpAllowed={projection.matchup?.fp_allowed_vs_position_l4}
        />
      </TableCell>
      <TableCell>
        <OutcomeRange
          floor={points.floor}
          p25={points.p25}
          median={points.median}
          p75={points.p75}
          ceiling={points.ceiling}
          threshold={points.boom_threshold}
          scaleMax={scaleMax}
        />
      </TableCell>
      <TableCell numeric className="font-semibold">
        {formatPercent(points.boom_probability)}
      </TableCell>
      <TableCell numeric>
        <ProjectionValue points={points} actualPoints={projection.actual_points} />
      </TableCell>
    </TableRow>
  )
})
