import { Link } from 'react-router-dom'

import { Badge } from '@/components/ui/Badge'
import { formatPoints } from '@/utils/format'
import type { SimulatedPlayer } from '@/api/schemas'

interface Swing {
  player: SimulatedPlayer
  side: string
  floor: number
  ceiling: number
  spread: number
}

/** More than this and the list stops being "the ones that matter". */
const SHOWN = 6

/**
 * The players whose weeks are least settled.
 *
 * Deliberately *not* presented as "±9.2". A symmetric tolerance around the
 * projection would be a statistic this API never published: the stored
 * distributions are asymmetric — the gap from projection to ceiling is
 * routinely twice the gap down to floor — so a single ± would misdescribe both
 * ends. What is shown instead is the published P10 and P90 and the distance
 * between them, which is a subtraction of two numbers the API returned.
 *
 * Nor is it a sensitivity analysis. Nothing here re-runs the simulation with a
 * player removed; the ordering is by how wide each player's own range is, which
 * is the honest reading of "who could swing this".
 */
export function SwingFactors({
  labelA,
  labelB,
  playersA,
  playersB,
}: {
  labelA: string
  labelB: string
  playersA: SimulatedPlayer[]
  playersB: SimulatedPlayer[]
}) {
  const swings = [
    ...collect(playersA, labelA),
    ...collect(playersB, labelB),
  ]
    .sort((left, right) => right.spread - left.spread)
    .slice(0, SHOWN)

  if (swings.length === 0) {
    return (
      <p className="text-ink-muted text-sm">
        No outcome ranges were stored for these players, so there is nothing to rank.
      </p>
    )
  }

  // One scale, so the bars compare to each other rather than each filling its row.
  const max = Math.max(...swings.map((swing) => swing.ceiling))
  const min = Math.min(...swings.map((swing) => swing.floor), 0)
  const at = (value: number) => ((value - min) / Math.max(max - min, 0.001)) * 100

  return (
    <div className="space-y-3">
      <ul className="space-y-3">
        {swings.map((swing) => (
          <li key={`${swing.side}-${swing.player.player_id}`}>
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <span className="flex min-w-0 items-baseline gap-2">
                <Link
                  to={`/players/${encodeURIComponent(swing.player.player_id)}`}
                  className="text-ink hover:text-accent-text truncate text-sm font-medium transition-colors"
                >
                  {swing.player.name}
                </Link>
                <Badge tone="neutral">{swing.side}</Badge>
                <span className="text-ink-muted hidden text-xs sm:inline">
                  {swing.player.slot}
                </span>
              </span>
              <span className="text-ink-muted tnum shrink-0 text-xs">
                {formatPoints(swing.spread)} wide
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="tnum text-ink-muted w-9 shrink-0 text-right text-xs">
                {formatPoints(swing.floor)}
              </span>
              <div
                className="bg-surface-sunken relative h-2 flex-1 overflow-hidden rounded-full"
                role="img"
                aria-label={`${swing.player.name}, ${swing.side}: 10th percentile ${formatPoints(swing.floor)} points, expected ${formatPoints(swing.player.expected_points)}, 90th percentile ${formatPoints(swing.ceiling)}.`}
              >
                <span
                  aria-hidden
                  className="bg-chart-series/45 absolute inset-y-0 rounded-full"
                  style={{
                    left: `${at(swing.floor)}%`,
                    width: `${Math.max(at(swing.ceiling) - at(swing.floor), 1)}%`,
                  }}
                />
                {swing.player.expected_points !== null &&
                  swing.player.expected_points !== undefined && (
                    <span
                      aria-hidden
                      className="bg-chart-series absolute inset-y-0 w-0.5 rounded-full"
                      style={{ left: `${at(swing.player.expected_points)}%` }}
                    />
                  )}
              </div>
              <span className="tnum text-ink-muted w-9 shrink-0 text-xs">
                {formatPoints(swing.ceiling)}
              </span>
            </div>
          </li>
        ))}
      </ul>

      <p className="text-ink-muted text-xs leading-relaxed">
        Ranked by the width of each player&apos;s published P10–P90 range — the distance between a
        bad week and a big one. The marker is the projection, which sits off-centre because these
        distributions are not symmetric.
      </p>
    </div>
  )
}

function collect(players: SimulatedPlayer[], side: string): Swing[] {
  const swings: Swing[] = []
  for (const player of players) {
    const { floor, ceiling } = player
    if (floor === null || floor === undefined || ceiling === null || ceiling === undefined) continue
    swings.push({ player, side, floor, ceiling, spread: ceiling - floor })
  }
  return swings
}
