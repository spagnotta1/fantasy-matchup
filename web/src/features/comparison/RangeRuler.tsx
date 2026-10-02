import { Card, CardHeader } from '@/components/ui/Card'
import {
  ColumnHeader,
  RowHeaderCell,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from '@/components/ui/DataTable'
import { RowList, RowListItem, RowListRows, RowListTitle } from '@/components/ui/RowList'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { PlayerCell } from '@/components/domain/PlayerCell'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { ProjectionLine } from '@/components/domain/ProjectionList'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { RowFlags } from '@/components/domain/RowFlags'
import { useElementSize } from '@/hooks/useElementSize'
import { fieldScaleMax, gameLine } from '@/utils/board'
import { formatPercent, formatThreshold } from '@/utils/format'
import type { ComparisonEntry } from '@/api/schemas'

/**
 * The room under which the ruler is drawn as the board's two-line rows. A
 * strip between its two printed endpoints needs 13rem, the two numbers beside
 * it 13rem, and what is left has to hold a headshot, a name and a game.
 */
const TABLE_MIN_WIDTH = 640

/**
 * The range column's width, by the table's own width: what is left once the
 * two columns of numbers (13rem) and a player cell (16rem) are paid for, never
 * under 13rem and never over 40rem. The strip is what this table is for, so it
 * takes the slack before the names do. In container units, not a percentage:
 * a percentage inside `calc()` is no width at all to a fixed table layout.
 */
const RANGE_WIDTH = 'w-[clamp(13rem,calc(100cqw-29rem),40rem)]'

/** The same sum on a finished week, when "actual 18.4" is printed beside each projection. */
const RANGE_WIDTH_WITH_ACTUALS = 'w-[clamp(13rem,calc(100cqw-33rem),40rem)]'

/**
 * Every selected player's range on one ruler.
 *
 * The comparison used to give each player a column and draw their strip inside
 * it, so three ranges sat side by side on three separate axes: the eye could
 * not run down a common edge to see whose floor was higher, which is the one
 * thing a strip is for. Here the players are rows and the strips share a left
 * edge, a width and a scale, so a floor is further right or it is not. It is
 * the board's row, deliberately: the mark a reader learned on Rankings is the
 * mark that answers the question on Compare.
 *
 * The scale runs from zero to the yard line above the highest ceiling among
 * the players being compared, and the heading says so. It is this comparison's
 * scale, not the board's: three running backs fill the strip, where on the
 * board they share it with a quarterback's ceiling.
 *
 * On a phone it is the same ruler. The rows fold to the board's two lines —
 * who and how much, then the strip — and the strips still line up, where the
 * old layout became one list per player and a floor was compared with another
 * by scrolling between them.
 *
 * Every mark is a published percentile, and the order is the API's own
 * (by expectation). Nothing is ranked or highlighted here. The two tips say
 * what the board's say about the same marks, in the board's words.
 */
export function RangeRuler({ entries }: { entries: ComparisonEntry[] }) {
  const [ref, size] = useElementSize<HTMLDivElement>()
  const asList = size.width > 0 && size.width < TABLE_MIN_WIDTH

  const highest = entries.reduce((max, entry) => Math.max(max, entry.projection.prediction.points.ceiling ?? 0), 0)
  const scale = `0 to ${fieldScaleMax(highest)} points`
  const threshold = sharedThreshold(entries)
  const mark = threshold === null ? 'the big-week mark' : `${formatThreshold(threshold)} points`
  const rangeKey = `The thin line runs from a bad week to a strong week (8 in 10 outcomes), the solid box holds the middle half, and the tick is the middle outcome. Ruled every 5 points. The yellow line is ${mark}.`
  const wordsForGrade = entries.some((entry) => !entry.projection.matchup?.grade.graded)
  const hasActuals = entries.some((entry) => entry.projection.actual_points != null)

  return (
    // `clip`, not `hidden`: see `DataTable` on what a hidden overflow does to
    // a sticky header.
    <Card className="overflow-clip">
      <CardHeader
        as="h2"
        title="Ranges on one scale"
        description={`Each player's likely scoring range for the selected week and scoring format, drawn from ${scale} so they can be compared by eye.`}
        action={<ProvenanceBadge provenance="model" />}
      />

      <div ref={ref} data-range-ruler="">
        {asList ? (
          <RowList value="Projected points" note={`Every range is drawn from ${scale}. The yellow line is ${mark}.`}>
            <RowListRows>
              {entries.map((entry) => {
                const { projection } = entry
                return (
                  <RowListItem
                    key={projection.player.player_id}
                    to={`/players/${encodeURIComponent(projection.player.player_id)}`}
                  >
                    <PlayerAvatar player={projection.player} size="xs" />
                    <RowListTitle name={projection.player.name} meta={gameLine(projection, true)}>
                      <RowFlags projection={projection} />
                    </RowListTitle>
                    <ProjectionValue
                      points={projection.prediction.points}
                      actualPoints={projection.actual_points}
                      className="justify-self-end"
                    />
                    <ProjectionLine projection={projection} scaleMax={highest} wordsForGrade={wordsForGrade} />
                  </RowListItem>
                )
              })}
            </RowListRows>
          </RowList>
        ) : (
          <Table
            // A query container, so the range column can size to the table.
            className="@container"
            caption={`Scoring ranges of the selected players, on one scale from ${scale}`}
            layout="fixed"
          >
            <TableHead>
              <ColumnHeader>Player</ColumnHeader>
              <ColumnHeader className={hasActuals ? RANGE_WIDTH_WITH_ACTUALS : RANGE_WIDTH} tip={rangeKey}>
                Range, {scale}
              </ColumnHeader>
              <ColumnHeader
                numeric
                className="w-28"
                tip={`How often a week like this one reaches ${threshold === null ? mark : `${mark} or more`}: the share of the range past the yellow line. An estimate, not a promise.`}
              >
                {threshold === null ? 'Boom chance' : `Chance of ${formatThreshold(threshold)}+`}
              </ColumnHeader>
              <ColumnHeader numeric className={hasActuals ? 'w-40' : 'w-24'}>
                Projection
              </ColumnHeader>
            </TableHead>
            <TableBody>
              {entries.map((entry) => {
                const { projection } = entry
                const { points } = projection.prediction
                return (
                  <TableRow key={projection.player.player_id}>
                    <RowHeaderCell>
                      {/* The grade rides with the game it grades, as it does
                          in the board's list: a column of three chips would
                          take a hundred pixels from the strip. */}
                      <PlayerCell player={projection.player} meta={gameLine(projection, true)}>
                        <MatchupGradeChip
                          grade={projection.matchup?.grade}
                          opponent={projection.opponent}
                          fpAllowed={projection.matchup?.fp_allowed_vs_position_l4}
                        />
                        <RowFlags projection={projection} />
                      </PlayerCell>
                    </RowHeaderCell>
                    <TableCell>
                      <OutcomeRange
                        floor={points.floor}
                        p25={points.p25}
                        median={points.median}
                        p75={points.p75}
                        ceiling={points.ceiling}
                        threshold={points.boom_threshold}
                        scaleMax={highest}
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
              })}
            </TableBody>
          </Table>
        )}
      </div>
    </Card>
  )
}

/**
 * The boom threshold, when the players share one.
 *
 * It is published per player. Where every player's is the same the column can
 * name it ("Chance of 20+"); where they differ, a single number in the heading
 * would be wrong for someone, and the column says only what it is.
 */
function sharedThreshold(entries: ComparisonEntry[]): number | null {
  const thresholds = new Set(entries.map((entry) => entry.projection.prediction.points.boom_threshold ?? null))
  const [only] = thresholds
  return thresholds.size === 1 && only !== null && only !== undefined ? only : null
}
