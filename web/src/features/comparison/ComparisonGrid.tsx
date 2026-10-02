import { Link } from 'react-router-dom'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import {
  ColumnHeader,
  RowHeaderCell,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from '@/components/ui/DataTable'
import { EvidenceChip } from '@/components/domain/EvidenceChip'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { cn } from '@/utils/cn'
import { formatPercent, formatPoints } from '@/utils/format'
import type { ComparisonEntry } from '@/api/schemas'

/**
 * A row of the comparison, and how to read it.
 *
 * `better` is what makes the "Best" marker honest. Most rows are "higher wins",
 * bust risk is "lower wins", and several rows — matchup, range evidence,
 * opponent — have no winner at all: a range built from more past weeks is not a
 * better projection, so marking it would teach the reader something false.
 */
interface Metric {
  label: string
  hint?: string
  better: 'higher' | 'lower' | null
  value: (entry: ComparisonEntry) => number | null
  render?: (entry: ComparisonEntry) => React.ReactNode
  /** Rows in the second block are context rather than the projection itself. */
  group: 'projection' | 'context'
}

const METRICS: Metric[] = [
  {
    label: 'Projected',
    hint: 'points',
    better: 'higher',
    group: 'projection',
    value: (entry) => entry.expected ?? null,
  },
  {
    label: 'Actual',
    hint: 'if played',
    better: 'higher',
    group: 'projection',
    value: (entry) => entry.projection.actual_points ?? null,
  },
  {
    label: 'Floor',
    hint: 'a bad week',
    better: 'higher',
    group: 'projection',
    value: (entry) => entry.floor ?? null,
  },
  {
    label: 'Ceiling',
    hint: 'a strong week',
    better: 'higher',
    group: 'projection',
    value: (entry) => entry.ceiling ?? null,
  },
  {
    label: 'Boom chance',
    hint: 'chance of a big week',
    better: 'higher',
    group: 'projection',
    value: (entry) => entry.projection.prediction.points.boom_probability ?? null,
    render: (entry) => formatPercent(entry.projection.prediction.points.boom_probability),
  },
  {
    label: 'Bust risk',
    hint: 'chance of a dud',
    better: 'lower',
    group: 'projection',
    value: (entry) => entry.projection.prediction.points.bust_probability ?? null,
    render: (entry) => formatPercent(entry.projection.prediction.points.bust_probability),
  },
  {
    label: 'Based on',
    hint: 'what sizes the range',
    better: null,
    group: 'projection',
    value: () => null,
    render: (entry) => (
      <EvidenceChip
        evidence={entry.projection.prediction.points.evidence}
        note={entry.projection.prediction.points.evidence_note}
        samples={entry.projection.prediction.points.samples}
      />
    ),
  },
  {
    label: 'Matchup',
    better: null,
    group: 'context',
    value: () => null,
    render: (entry) => (
      <MatchupGradeChip
        grade={entry.projection.matchup?.grade}
        opponent={entry.projection.opponent}
        fpAllowed={entry.projection.matchup?.fp_allowed_vs_position_l4}
      />
    ),
  },
  {
    label: 'Opponent',
    better: null,
    group: 'context',
    value: () => null,
    render: (entry) => (
      <span className="text-ink-secondary text-sm">
        {entry.projection.is_home ? 'vs' : 'at'} {entry.projection.opponent ?? '—'}
      </span>
    ),
  },
  {
    label: 'Snap share',
    hint: 'last 4',
    better: 'higher',
    group: 'context',
    value: (entry) => entry.projection.usage.snap_pct_l4 ?? null,
    render: (entry) => formatPercent(entry.projection.usage.snap_pct_l4),
  },
  {
    label: 'Target share',
    hint: 'last 4',
    better: 'higher',
    group: 'context',
    value: (entry) => entry.projection.usage.target_share_l4 ?? null,
    render: (entry) => formatPercent(entry.projection.usage.target_share_l4),
  },
  {
    label: 'Points per game',
    hint: 'last 4',
    better: 'higher',
    group: 'context',
    value: (entry) => entry.projection.usage.fp_l4 ?? null,
  },
]

/** The metric column at its narrowest, and each player's column, in rem. */
const METRIC_COLUMN = 6.5
const PLAYER_COLUMN = 8.5

/**
 * The players side by side.
 *
 * A metric-per-row table rather than a card per player, because the whole task
 * is reading *across*: floor against floor, ceiling against ceiling. Cards put
 * the two numbers a manager is comparing at opposite ends of the screen.
 *
 * It is side by side on a phone too. It used to stack there, one list per
 * player, which is the card layout by another name: comparing two floors meant
 * scrolling between them. Now two players fit a phone as they are, and with
 * more the table scrolls sideways inside its own frame with the metric column
 * held at the left (`freezeFirstColumn`), so a number never loses its label.
 *
 * The ranges are not here. They are the ruler above this table
 * (`RangeRuler`), where they share an axis; a strip per column cannot.
 *
 * ## The best number in a row
 *
 * Marked once per row, by weight and a small dot. It was a tinted cell and the
 * word BEST, and when one player led most rows the word ran down a column
 * seven times and read as a verdict on the player. The mark is now as quiet as
 * what it says: this number is the largest (or, for bust risk, the smallest)
 * in its row. Weight and a dot are both there without colour, and a screen
 * reader is told in words.
 */
export function ComparisonGrid({ entries }: { entries: ComparisonEntry[] }) {
  return (
    // `clip`, not `hidden`, so the column header can stick to the page.
    <Card className="overflow-clip">
      <CardHeader
        as="h2"
        title="Side by side"
        description="Every number for the selected week and scoring format, straight from the projections."
        action={<ProvenanceBadge provenance="model" />}
      />

      <Table
        // A query container, so the metric column can size to the table.
        className="@container"
        caption="Selected players compared across projection, matchup and recent usage"
        layout="fixed"
        minWidth={`${METRIC_COLUMN + entries.length * PLAYER_COLUMN}rem`}
        freezeFirstColumn
      >
        <TableHead>
          <ColumnHeader className="w-[clamp(6.5rem,20cqw,13rem)] align-bottom">Metric</ColumnHeader>
          {entries.map((entry) => (
            <ColumnHeader
              key={entry.projection.player.player_id}
              // A name is not a column label: it wraps rather than widening
              // its column past the others.
              className="py-1.5 align-bottom whitespace-normal"
            >
              <PlayerColumnHeader entry={entry} />
            </ColumnHeader>
          ))}
        </TableHead>
        <TableBody>
          {METRICS.map((metric) => {
            const leader = leaderId(metric, entries)
            return (
              <TableRow key={metric.label}>
                <RowHeaderCell className="text-ink-secondary">
                  {/* Two items, so in a narrow column the hint goes under the
                      label whole and does not break in the middle of it. */}
                  <span className="flex flex-wrap items-baseline gap-x-1.5">
                    <span>{metric.label}</span>
                    {metric.hint && <span className="text-ink-muted text-chip">{metric.hint}</span>}
                  </span>
                </RowHeaderCell>
                {entries.map((entry) => (
                  <TableCell key={entry.projection.player.player_id}>
                    <MetricCell
                      metric={metric}
                      entry={entry}
                      isLeader={leader === entry.projection.player.player_id}
                    />
                  </TableCell>
                ))}
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      <CardBody className="border-line border-t py-3">
        <p className="text-ink-muted text-detail leading-relaxed">
          <BestMark className="mr-1.5 align-middle" />
          The dot marks the best number in that row, not a recommendation. The gap between two
          projections is usually much smaller than how much either player&apos;s score can swing —
          the head-to-head chances below take that into account.
        </p>
      </CardBody>
    </Card>
  )
}

/** The dot beside a row's best number. Decorative: the words are beside it. */
function BestMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      data-best-mark=""
      className={cn('bg-accent inline-block size-1.5 shrink-0 rounded-full', className)}
    />
  )
}

function MetricCell({
  metric,
  entry,
  isLeader,
}: {
  metric: Metric
  entry: ComparisonEntry
  isLeader: boolean
}) {
  const rendered = metric.render ? metric.render(entry) : formatPoints(metric.value(entry))

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn('tnum text-ink', isLeader && 'font-semibold')}>{rendered}</span>
      {/* Weight and a dot, neither of which needs colour to be seen, and the
          words for a reader who sees neither. After the number, so the numbers
          of a column still start on one edge. */}
      {isLeader && (
        <>
          <BestMark />
          <span className="sr-only">best in this row</span>
        </>
      )}
    </span>
  )
}

/**
 * Which player leads a row, or nobody: at most one mark per row.
 *
 * Returns null on a tie as well as on an unrankable row. Two identical values
 * marked "best" twice says nothing, and marking the first of them says
 * something untrue.
 */
function leaderId(metric: Metric, entries: ComparisonEntry[]): string | null {
  if (metric.better === null) return null

  let best: { id: string; value: number } | null = null
  let tied = false

  for (const entry of entries) {
    const value = metric.value(entry)
    if (value === null) continue
    if (best === null) {
      best = { id: entry.projection.player.player_id, value }
      continue
    }
    if (value === best.value) {
      tied = true
      continue
    }
    const wins = metric.better === 'higher' ? value > best.value : value < best.value
    if (wins) {
      best = { id: entry.projection.player.player_id, value }
      tied = false
    }
  }

  return best && !tied ? best.id : null
}

/**
 * Who a column is. The name and what places the player, without a headshot:
 * the ruler above has one, and 32px is a quarter of a phone's column. A
 * designation stays, beside the name, because every number under it is that
 * player's.
 */
function PlayerColumnHeader({ entry }: { entry: ComparisonEntry }) {
  const { player } = entry.projection

  return (
    <span className="flex flex-col items-start gap-0.5">
      <Link
        to={`/players/${encodeURIComponent(player.player_id)}`}
        className="text-ink hover:text-accent-text text-body rounded-sm font-semibold transition-colors"
      >
        {player.name}
      </Link>
      <span className="text-ink-muted text-chip font-normal whitespace-nowrap">
        {[player.position, entry.projection.team].filter(Boolean).join(' · ')}
      </span>
      <InjuryBadge injury={entry.projection.context.injury} />
    </span>
  )
}
