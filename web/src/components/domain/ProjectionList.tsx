import { memo, useMemo } from 'react'

import { RowList, RowListGroup, RowListItem, RowListLine, RowListRows, RowListTitle } from '@/components/ui/RowList'
import { ShowMoreRows } from '@/components/domain/BoardBudget'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { RowFlags } from '@/components/domain/RowFlags'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { useReorderAnimation } from '@/hooks/useReorderAnimation'
import { useRenderBudget } from '@/hooks/useRenderBudget'
import { anyUngraded, boardCeiling, gameLine, groupByTier, orderSignature } from '@/utils/board'
import { cn } from '@/utils/cn'
import { formatPercent, formatThreshold } from '@/utils/format'
import type { Projection, RankedProjection } from '@/api/schemas'

/**
 * The board on a phone: the same rows as the table, in two lines each.
 *
 * Line one is who and how much — rank, name, game, projection. Line two is the
 * table's other three columns side by side: the matchup grade, the range strip
 * with its floor and ceiling printed either side, and the chance of 20+.
 * Nothing the table shows is left out, and the strip — the mark the whole
 * product is built around — is on every row.
 *
 * It replaces a card per player. A card was about 235px tall, which put one
 * and a half players on a phone screen and a hundred of them 25 screens deep;
 * a row is about 65px. The card grid is still there as a desktop view, for a
 * reader who wants one player at a time.
 *
 * A list and not a table. Two lines per row is not a grid of columns, and a
 * `<table>` laid out this way would announce cells that are not in the column
 * their header names. Each row is one link, read in order.
 *
 * Built from the shared row list (`components/ui/RowList`), which is this
 * list's frame, sections and rows taken out so that the other tables of
 * players can fold the same way. `ProjectionLine` is its second line, shared
 * with the team page for the same reason.
 */
export const ProjectionList = memo(function ProjectionList({
  entries,
  rankMode = 'overall',
  /** Breaks the list into tier sections. Rank order only — see `groupByTier`. */
  showTiers = false,
  /** Print the position beside the game, on a board that mixes positions. */
  showPosition = false,
}: {
  entries: RankedProjection[]
  rankMode?: 'overall' | 'positional'
  showTiers?: boolean
  showPosition?: boolean
}) {
  // One scale for every row, including across tiers and rows not yet revealed,
  // so a strip in tier 4 is comparable to one in tier 1 and nothing rescales
  // when more rows are shown.
  const scaleMax = useMemo(() => boardCeiling(entries), [entries])
  const tierSizes = useMemo(() => {
    const sizes = new Map<number, number>()
    for (const entry of entries) sizes.set(entry.tier, (sizes.get(entry.tier) ?? 0) + 1)
    return sizes
  }, [entries])

  const budget = useRenderBudget(entries.length)
  const visible = useMemo(() => entries.slice(0, budget.shown), [entries, budget.shown])
  const orderKey = useMemo(() => orderSignature(visible), [visible])
  const ref = useReorderAnimation<HTMLDivElement>(orderKey)

  const groups = showTiers ? groupByTier(visible) : [{ tier: 0, entries: visible }]
  const wordsForGrade = useMemo(() => anyUngraded(entries), [entries])

  return (
    <>
      {/* What the right-hand number is. A table has a column header to say
          so; a list has to be told once, above the first row. */}
      <RowList ref={ref} value="Projected points">
        {groups.map((group) => {
          const size = tierSizes.get(group.tier) ?? group.entries.length
          const rows = (
            <RowListRows>
              {group.entries.map((entry) => (
                <ListRow
                  key={entry.projection.player.player_id}
                  entry={entry}
                  rankMode={rankMode}
                  showPosition={showPosition}
                  scaleMax={scaleMax}
                  wordsForGrade={wordsForGrade}
                />
              ))}
            </RowListRows>
          )
          if (!showTiers) return <div key="all">{rows}</div>
          return (
            // h2: a tier is a top-level division of the board, and the page's
            // h1 is the only heading above it.
            <RowListGroup
              key={group.tier}
              id={`tier-${group.tier}`}
              as="h2"
              heading={`Tier ${group.tier}`}
              note={`${size} ${size === 1 ? 'player' : 'players'}`}
            >
              {rows}
            </RowListGroup>
          )
        })}
      </RowList>
      <ShowMoreRows budget={budget} />
    </>
  )
})

/** One row, memoised so a re-sort moves it instead of re-rendering it. */
const ListRow = memo(function ListRow({
  entry,
  rankMode,
  showPosition,
  scaleMax,
  wordsForGrade,
}: {
  entry: RankedProjection
  rankMode: 'overall' | 'positional'
  showPosition: boolean
  scaleMax: number
  wordsForGrade: boolean
}) {
  const { projection } = entry

  return (
    <RowListItem
      to={`/players/${encodeURIComponent(projection.player.player_id)}`}
      data-flip-key={projection.player.player_id}
      className="deferred-row"
    >
      <span className="text-ink-muted tnum text-detail">
        {rankMode === 'positional' ? entry.positional_rank : entry.rank}
      </span>
      <RowListTitle name={projection.player.name} meta={gameLine(projection, showPosition)}>
        <RowFlags projection={projection} />
      </RowListTitle>
      <ProjectionValue
        points={projection.prediction.points}
        actualPoints={projection.actual_points}
        className="justify-self-end"
      />
      <ProjectionLine projection={projection} scaleMax={scaleMax} wordsForGrade={wordsForGrade} />
    </RowListItem>
  )
})

/**
 * The table's other three columns, side by side under the name: the matchup
 * grade, the range strip with its floor and ceiling printed either side, and
 * the chance of 20+.
 *
 * The strips share one scale, so they have to share one left edge and one
 * width as well, or the yard lines of one row do not line up with the next and
 * the ranges stop being comparable by eye. What sits either side of the strip
 * is therefore a fixed width: wide enough for "Not graded" on a list that has
 * any ungraded matchup, and only as wide as a grade when none has.
 *
 * With the wide slot the three need 322px, which the list on a 412px phone has
 * and on a 390px one does not: there the ceiling was printed under the chance
 * of 20+. So a list narrower than that (23.5rem) gives the strip the whole
 * line and puts the grade and the chance on the next. Every row folds alike,
 * so the strips still line up. A list of graded matchups fits on one line down
 * to 360px and is left as it was.
 */
export function ProjectionLine({
  projection,
  scaleMax,
  wordsForGrade,
}: {
  projection: Projection
  scaleMax: number
  /** Some row's matchup is ungraded, so every row's grade slot is as wide as the words. */
  wordsForGrade: boolean
}) {
  const { points } = projection.prediction
  return (
    <RowListLine className={cn(wordsForGrade && '@max-[23.5rem]:flex-wrap')}>
      <span className={cn('flex shrink-0', wordsForGrade ? 'w-[5.25rem] @max-[23.5rem]:order-2' : 'w-8')}>
        <MatchupGradeChip
          grade={projection.matchup?.grade}
          opponent={projection.opponent}
          fpAllowed={projection.matchup?.fp_allowed_vs_position_l4}
        />
      </span>
      <OutcomeRange
        floor={points.floor}
        p25={points.p25}
        median={points.median}
        p75={points.p75}
        ceiling={points.ceiling}
        threshold={points.boom_threshold}
        scaleMax={scaleMax}
        className={cn('min-w-0 flex-1', wordsForGrade && '@max-[23.5rem]:order-1 @max-[23.5rem]:basis-full')}
      />
      <span
        className={cn(
          'text-ink-secondary tnum text-chip w-[4.5rem] shrink-0 text-right whitespace-nowrap',
          wordsForGrade && '@max-[23.5rem]:order-3 @max-[23.5rem]:ml-auto',
        )}
      >
        <span className="text-ink font-semibold">{formatPercent(points.boom_probability)}</span> of{' '}
        {formatThreshold(points.boom_threshold)}+
      </span>
    </RowListLine>
  )
}
