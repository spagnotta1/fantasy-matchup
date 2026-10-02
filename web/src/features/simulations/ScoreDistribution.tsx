import { formatPoints } from '@/utils/format'
import type { TeamSimulation } from '@/api/schemas'

interface Side {
  label: string
  team: TeamSimulation
  /** The stronger fill is the side the reader is asking about. */
  emphasis: boolean
}

/**
 * Where each lineup's total lands, on one scale.
 *
 * This is the figure that explains the win probability, and it is the reason
 * the number above it is not a verdict: two ranges that overlap across most of
 * their width produce a 60/40, not a certainty. Seeing the overlap is what
 * stops "64%" from being read as "we win".
 *
 * Five published quantiles are drawn as five published quantiles. A smooth
 * density curve would look better and would be invented — the API returns
 * P10, P25, P50, P75 and P90 and nothing between them, so nothing between them
 * is drawn.
 *
 * One hue at two strengths, never two hues. The pair a reader must tell apart
 * is exactly the pair a red/green split makes indistinguishable under common
 * colour deficiencies; the labels and the printed numbers carry identity here.
 *
 * Each side's line also carries its average simulated score, the same
 * `expected_score` the totals further down print. It is what the position
 * gaps under this chart add up to, so the whole is on screen with its parts.
 * The line wraps: on a 360px phone the three range figures did not fit beside
 * the label, and pushed the page 18px wide.
 */
export function ScoreDistribution({
  labelA,
  teamA,
  labelB,
  teamB,
}: {
  labelA: string
  teamA: TeamSimulation
  labelB: string
  teamB: TeamSimulation
}) {
  const sides: Side[] = [
    { label: labelA, team: teamA, emphasis: true },
    { label: labelB, team: teamB, emphasis: false },
  ]

  // A shared axis with a little air either side, so a P10 sitting at the very
  // left edge does not read as zero.
  const low = Math.min(teamA.p10, teamB.p10)
  const high = Math.max(teamA.p90, teamB.p90)
  const pad = Math.max((high - low) * 0.08, 1)
  const min = low - pad
  const max = high + pad
  const at = (value: number) => ((value - min) / (max - min)) * 100

  return (
    <div className="space-y-4">
      {sides.map((side, index) => (
        // Drawn in one after the other, left to right, when a result arrives:
        // your range, then theirs, then the overlap is there to read.
        <div
          key={side.label}
          className="animate-wipe-in"
          style={{ animationDelay: `${150 + index * 220}ms` }}
        >
          <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="text-ink text-body truncate font-medium">{side.label}</span>
              <span className="text-ink tnum text-body font-semibold whitespace-nowrap">
                {formatPoints(side.team.expected_score)}
                <span className="text-ink-muted text-chip font-normal"> pts on average</span>
              </span>
            </span>
            <span className="text-ink-muted tnum text-detail whitespace-nowrap">
              Low {formatPoints(side.team.p10)} · Middle {formatPoints(side.team.median_score)} · High{' '}
              {formatPoints(side.team.p90)}
            </span>
          </div>

          <div
            className="relative h-8"
            role="img"
            aria-label={`${side.label}: 10th percentile ${formatPoints(side.team.p10)} points, 25th ${formatPoints(side.team.p25)}, median ${formatPoints(side.team.median_score)}, 75th ${formatPoints(side.team.p75)}, 90th ${formatPoints(side.team.p90)}.`}
          >
            {/* P10–P90: the range eight weeks in ten land inside. */}
            <div
              className={
                side.emphasis
                  ? 'bg-chart-series/25 absolute top-3 h-2 rounded-full'
                  : 'bg-chart-series/12 absolute top-3 h-2 rounded-full'
              }
              style={{ left: `${at(side.team.p10)}%`, width: `${at(side.team.p90) - at(side.team.p10)}%` }}
            />
            {/* P25–P75: the middle half. */}
            <div
              className={
                side.emphasis
                  ? 'bg-chart-series/55 absolute top-3 h-2 rounded-full'
                  : 'bg-chart-series/25 absolute top-3 h-2 rounded-full'
              }
              style={{ left: `${at(side.team.p25)}%`, width: `${at(side.team.p75) - at(side.team.p25)}%` }}
            />
            <div
              className={
                side.emphasis
                  ? 'bg-chart-series ring-surface absolute top-1 h-6 w-1 rounded-full ring-2'
                  : 'bg-chart-series/60 ring-surface absolute top-1 h-6 w-1 rounded-full ring-2'
              }
              style={{ left: `${at(side.team.median_score)}%` }}
            />
          </div>
        </div>
      ))}

      <div className="text-ink-muted flex flex-wrap items-center gap-x-4 gap-y-1 text-detail">
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="bg-chart-series/55 block h-2 w-6 rounded-full" />
          Half of simulated weeks land here
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="bg-chart-series/25 block h-2 w-6 rounded-full" />
          8 in 10 weeks land here
        </span>
      </div>
    </div>
  )
}
