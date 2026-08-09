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
    <div className="space-y-5">
      {sides.map((side) => (
        <div key={side.label}>
          <div className="mb-1.5 flex items-baseline justify-between gap-4 text-sm">
            <span className="text-ink truncate font-medium">{side.label}</span>
            <span className="text-ink-muted tnum shrink-0 text-xs">
              P10 {formatPoints(side.team.p10)} · P50 {formatPoints(side.team.median_score)} · P90{' '}
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

      <div className="text-ink-muted flex items-center gap-4 text-xs">
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="bg-chart-series/55 block h-2 w-6 rounded-full" />
          Middle half of outcomes (P25–P75)
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="bg-chart-series/25 block h-2 w-6 rounded-full" />
          P10–P90
        </span>
      </div>
    </div>
  )
}
