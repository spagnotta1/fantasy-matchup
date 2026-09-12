import { Link } from 'react-router-dom'

import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { ConfidenceChip } from '@/components/domain/ConfidenceChip'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { OutcomeRange } from '@/components/domain/ProjectionValue'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { cn } from '@/utils/cn'
import { formatPercent, formatPoints } from '@/utils/format'
import type { ComparisonEntry } from '@/api/schemas'

/**
 * A row of the comparison, and how to read it.
 *
 * `better` is what makes the "Best" marker honest. Most rows are "higher wins",
 * bust risk is "lower wins", and several rows — matchup, confidence, opponent —
 * have no winner at all: a high-confidence projection is not a better one, so
 * marking it would teach the reader something false.
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
    hint: 'P10',
    better: 'higher',
    group: 'projection',
    value: (entry) => entry.floor ?? null,
  },
  {
    label: 'Ceiling',
    hint: 'P90',
    better: 'higher',
    group: 'projection',
    value: (entry) => entry.ceiling ?? null,
  },
  {
    label: 'Boom chance',
    hint: 'over the boom line',
    better: 'higher',
    group: 'projection',
    value: (entry) => entry.projection.prediction.points.boom_probability ?? null,
    render: (entry) => formatPercent(entry.projection.prediction.points.boom_probability),
  },
  {
    label: 'Bust risk',
    hint: 'under the bust line',
    better: 'lower',
    group: 'projection',
    value: (entry) => entry.projection.prediction.points.bust_probability ?? null,
    render: (entry) => formatPercent(entry.projection.prediction.points.bust_probability),
  },
  {
    label: 'Confidence',
    hint: 'how much the model knew',
    better: null,
    group: 'projection',
    value: () => null,
    render: (entry) => (
      <ConfidenceChip
        label={entry.projection.prediction.points.confidence_label}
        value={entry.projection.prediction.points.confidence}
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

/**
 * The players side by side.
 *
 * A metric-per-row table rather than a card per player, because the whole task
 * is reading *across*: floor against floor, ceiling against ceiling. Cards put
 * the two numbers a manager is comparing at opposite ends of the screen.
 *
 * The first column is sticky, so with five or six players the labels stay put
 * while the columns scroll. Below `sm` the same data stacks per player, where a
 * six-column scroll is unusable.
 */
export function ComparisonGrid({ entries }: { entries: ComparisonEntry[] }) {
  // One scale for every range bar, so the widths mean something relative to
  // each other rather than each filling its own cell.
  const scaleMax = entries.reduce((max, entry) => Math.max(max, entry.ceiling ?? 0), 0)

  return (
    <Card className="overflow-hidden">
      <CardHeader
        as="h2"
        title="Side by side"
        description="Every figure as the API published it for the selected week and scoring format."
        action={<ProvenanceBadge provenance="model" />}
      />

      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">
            Selected players compared across projection, outcome range, matchup and recent usage.
          </caption>
          <thead>
            <tr className="border-line border-b">
              <th
                scope="col"
                className="bg-surface text-ink-muted sticky left-0 z-10 w-40 px-4 py-3 text-left text-xs font-medium tracking-wide uppercase"
              >
                Metric
              </th>
              {entries.map((entry) => (
                <th
                  key={entry.projection.player.player_id}
                  scope="col"
                  className="min-w-40 px-4 py-3 text-left"
                >
                  <PlayerColumnHeader entry={entry} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-line border-b">
              <th
                scope="row"
                className="bg-surface text-ink-secondary sticky left-0 z-10 px-4 py-3 text-left text-sm font-normal"
              >
                Range
                <span className="text-ink-muted ml-1 text-xs">floor to ceiling</span>
              </th>
              {entries.map((entry) => (
                <td key={entry.projection.player.player_id} className="px-4 py-3">
                  <OutcomeRange
                    floor={entry.floor}
                    median={entry.projection.prediction.points.median}
                    ceiling={entry.ceiling}
                    scaleMax={scaleMax}
                  />
                </td>
              ))}
            </tr>

            {METRICS.map((metric) => {
              const leader = leaderId(metric, entries)
              return (
                <tr key={metric.label} className="border-line border-b last:border-b-0">
                  <th
                    scope="row"
                    className="bg-surface text-ink-secondary sticky left-0 z-10 px-4 py-3 text-left text-sm font-normal"
                  >
                    {metric.label}
                    {metric.hint && <span className="text-ink-muted ml-1 text-xs">{metric.hint}</span>}
                  </th>
                  {entries.map((entry) => (
                    <td
                      key={entry.projection.player.player_id}
                      className={cn(
                        'px-4 py-3',
                        leader === entry.projection.player.player_id && 'bg-accent-soft/40',
                      )}
                    >
                      <MetricCell
                        metric={metric}
                        entry={entry}
                        isLeader={leader === entry.projection.player.player_id}
                      />
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Stacked on a phone. Same numbers, one player at a time. */}
      <div className="divide-line divide-y sm:hidden">
        {entries.map((entry) => (
          <div key={entry.projection.player.player_id} className="p-4">
            <PlayerColumnHeader entry={entry} />
            <div className="mt-3">
              <OutcomeRange
                floor={entry.floor}
                median={entry.projection.prediction.points.median}
                ceiling={entry.ceiling}
                scaleMax={scaleMax}
              />
            </div>
            <dl className="mt-3 space-y-1.5">
              {METRICS.map((metric) => (
                <div
                  key={metric.label}
                  className="border-line flex items-center justify-between gap-4 border-b py-1 last:border-b-0"
                >
                  <dt className="text-ink-secondary text-sm">{metric.label}</dt>
                  <dd className="shrink-0">
                    <MetricCell
                      metric={metric}
                      entry={entry}
                      isLeader={leaderId(metric, entries) === entry.projection.player.player_id}
                    />
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>

      <CardBody className="border-line border-t py-3">
        <p className="text-ink-muted text-xs leading-relaxed">
          The highlighted cell is simply the best published value in that row. It is not a
          recommendation: the gap between two projections is usually far smaller than either
          player&apos;s own range, which is what the head-to-head probabilities below account for.
        </p>
      </CardBody>
    </Card>
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
      <span className="tnum text-ink text-sm font-medium">{rendered}</span>
      {/* A label, not only a background tint — the highlight must survive a
          reader who cannot see the colour. */}
      {isLeader && (
        <Badge tone="accent" className="uppercase">
          Best
        </Badge>
      )}
    </span>
  )
}

/**
 * Which player leads a row, or nobody.
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

function PlayerColumnHeader({ entry }: { entry: ComparisonEntry }) {
  const { player } = entry.projection

  return (
    <span className="flex items-center gap-2">
      <PlayerAvatar player={player} size="sm" />
      <span className="min-w-0">
        <Link
          to={`/players/${encodeURIComponent(player.player_id)}`}
          className="text-ink hover:text-accent-text block truncate text-sm font-medium transition-colors"
        >
          {player.name}
        </Link>
        <span className="text-ink-muted block truncate text-xs font-normal">
          {[player.position, entry.projection.team].filter(Boolean).join(' · ')}
        </span>
      </span>
    </span>
  )
}
