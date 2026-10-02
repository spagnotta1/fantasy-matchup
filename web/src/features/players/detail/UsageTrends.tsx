import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { formatPoints } from '@/utils/format'
import type { HistoricalWeek } from '@/api/schemas'

interface Metric {
  key: 'snap_pct' | 'targets' | 'carries'
  label: string
  format: (value: number) => string
  /** An average of counts needs a decimal a single game does not. */
  average: (value: number) => string
}

const METRICS: Metric[] = [
  {
    key: 'snap_pct',
    label: 'Snap share',
    format: (v) => `${Math.round(v * 100)}%`,
    average: (v) => `${Math.round(v * 100)}%`,
  },
  { key: 'targets', label: 'Targets', format: (v) => formatPoints(v, 0), average: (v) => formatPoints(v, 1) },
  { key: 'carries', label: 'Carries', format: (v) => formatPoints(v, 0), average: (v) => formatPoints(v, 1) },
]

/**
 * Role over time: snap share, targets and carries, game by game.
 *
 * Small multiples rather than one chart with three series: the three are on
 * different scales (a share and two counts), and a shared axis would need a
 * second y-scale — which is exactly the dual-axis chart that misleads. Each
 * panel has its own scale and the same columns, oldest to newest, so a change
 * in role lines up vertically across them.
 *
 * These are recorded outcomes (`actual`). Every value is also in the game log's
 * table view, which is the accessible form; the panels are a summary of it.
 *
 * It draws the games the game log is showing, so the two read column for
 * column whichever window is chosen.
 */
export function UsageTrends({
  games,
  window,
  endsAtLatest,
}: {
  /** The games of the chosen window, oldest first: the game log's own. */
  games: HistoricalWeek[]
  /** The window in words, as the game log's description gives it. */
  window: string
  /**
   * The window ends at the player's newest game. Only then are its last four
   * games the four the projection is built from, and marked as such.
   */
  endsAtLatest: boolean
}) {
  const panels = METRICS.map((metric) => {
    const values = games.map((g) => g[metric.key] ?? null)
    const present = values.filter((v): v is number => v !== null)
    // A panel of zeros (carries for a receiver) is not a trend; leave it out.
    if (present.length === 0 || present.every((v) => v === 0)) return null
    return { metric, values, present }
  }).filter((panel) => panel !== null)

  if (games.length < 2 || panels.length === 0) return null

  return (
    <Card>
      <CardHeader
        as="h2"
        title="Usage trend"
        description={`Snap share, targets and carries, ${window}, oldest to newest. Changes in role often show up here before they show up in points.`}
        action={<ProvenanceBadge provenance="actual" />}
      />
      <CardBody className="grid gap-5 md:grid-cols-3">
        {panels.map(({ metric, values, present }) => {
          // A share is drawn on its full 0-100% scale; a count on its own maximum.
          const max = metric.key === 'snap_pct' ? 1 : Math.max(...present, 1)
          const average = present.reduce((a, b) => a + b, 0) / present.length
          const recent = present.slice(-4)
          const recentAverage = recent.reduce((a, b) => a + b, 0) / recent.length
          const last = values.at(-1) ?? null
          return (
            <figure key={metric.key} aria-label={`${metric.label} by game`}>
              <figcaption className="mb-1.5 flex items-baseline justify-between gap-2">
                <span className="text-ink-muted text-caption font-medium tracking-wide uppercase">{metric.label}</span>
                <span className="text-ink-secondary text-detail">
                  {endsAtLatest ? 'Last 4' : 'Final 4'}:{' '}
                  <span className="text-ink tnum font-semibold">{metric.average(recentAverage)}</span>
                  <span className="text-ink-muted">
                    {' '}
                    · {games.length} games: {metric.average(average)}
                  </span>
                </span>
              </figcaption>
              <div className="flex h-16 items-end gap-0.5" aria-hidden>
                {values.map((value, index) => (
                  <div
                    key={`${games[index]?.season}-${games[index]?.week}`}
                    title={
                      value === null
                        ? `${games[index]?.season} W${games[index]?.week}: not recorded`
                        : `${games[index]?.season} W${games[index]?.week}: ${metric.format(value)}`
                    }
                    className="bg-chart-series min-h-px flex-1 rounded-t-[2px]"
                    style={{
                      height: value === null ? 0 : `${Math.max(2, (value / max) * 100)}%`,
                      opacity: !endsAtLatest || index >= values.length - 4 ? 1 : 0.55,
                    }}
                  />
                ))}
              </div>
              <p className="sr-only">
                {metric.label}: average over the {endsAtLatest ? 'last' : 'final'} four games{' '}
                {metric.average(recentAverage)}, over{' '}
                {games.length} games {metric.average(average)}, most recent game{' '}
                {last === null ? 'not recorded' : metric.format(last)}.
              </p>
            </figure>
          )
        })}
      </CardBody>
      {endsAtLatest && (
        <p className="text-ink-muted px-5 pb-4 text-detail">
          The last four games, which the projection is built from, are shown in full colour.
        </p>
      )}
    </Card>
  )
}
