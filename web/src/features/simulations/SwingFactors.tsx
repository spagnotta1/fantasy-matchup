import { Link } from 'react-router-dom'

import { Badge } from '@/components/ui/Badge'
import { formatPoints } from '@/utils/format'
import type { SimulatedPlayer } from '@/api/schemas'

import { collectSwings, groupSwingsByWidth, type Swing } from './swing'

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
 * A player whose game is over is left out: their score is settled and they
 * cannot swing anything. Their published range is still a fact, but ranking it
 * here would point at a week that has already happened.
 *
 * Nor is it a sensitivity analysis. Nothing here re-runs the simulation with a
 * player removed; the ordering is by how wide each player's own range is, which
 * is the honest reading of "who could swing this".
 *
 * Widths tie, and often. Ranges are shared across groups of players with
 * similar projections, so several of a lineup's widest ranges can be exactly
 * the same width. Printing those in sequence would present a tie as a ranking,
 * so equal widths are grouped under one heading that says they are tied (see
 * `groupSwingsByWidth`).
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
  const groups = groupSwingsByWidth(
    [...collectSwings(playersA, labelA), ...collectSwings(playersB, labelB)],
    SHOWN,
  )
  const swings = groups.flatMap((group) => group.members)
  const anyTie = groups.some((group) => group.size > 1)

  const settled = [...playersA, ...playersB].filter((player) => player.final).length

  if (swings.length === 0) {
    return (
      <p className="text-ink-muted text-sm">
        {settled > 0
          ? 'Every player on both sides has finished their game, so nobody is left to swing it.'
          : 'No scoring ranges are available for these players, so there is nothing to rank.'}
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
        {groups.map((group) => (
          <li key={group.width}>
            {group.size > 1 && (
              <p className="text-ink-secondary mb-2 text-detail font-medium">
                Tied at {group.width} wide: {group.size} players, in lineup order
              </p>
            )}
            <ul className={group.size > 1 ? 'border-line space-y-3 border-l-2 pl-3' : 'space-y-3'}>
              {group.members.map((swing) => (
                <SwingRow key={`${swing.side}-${swing.player.player_id}`} swing={swing} at={at} />
              ))}
            </ul>
            {group.hidden > 0 && (
              <p className="text-ink-muted mt-2 text-detail">
                {group.hidden} more tied at {group.width} wide {group.hidden === 1 ? 'is' : 'are'} not
                listed.
              </p>
            )}
          </li>
        ))}
      </ul>

      <p className="text-ink-muted text-detail leading-relaxed">
        Ordered by the gap between each player&apos;s floor and ceiling — a bad week and a big one,
        each about 1 week in 10. The marker is the projection, which is often off-centre because a
        big week can run further above it than a bad week falls below it.
        {anyTie &&
          ' Players with the same gap are tied, not ranked against each other: ranges are shared across players with similar projections, so equal gaps are common.'}
        {settled > 0 &&
          ` ${settled} player${settled === 1 ? ' has' : 's have'} finished ${settled === 1 ? 'their game' : 'their games'} and ${settled === 1 ? 'is' : 'are'} left out.`}
      </p>
    </div>
  )
}

function SwingRow({ swing, at }: { swing: Swing; at: (value: number) => number }) {
  return (
    <li>
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <span className="flex min-w-0 items-baseline gap-2">
          <Link
            to={`/players/${encodeURIComponent(swing.player.player_id)}`}
            className="text-ink hover:text-accent-text truncate text-sm font-medium transition-colors"
          >
            {swing.player.name}
          </Link>
          <Badge tone="neutral">{swing.side}</Badge>
          <span className="text-ink-muted hidden text-detail sm:inline">
            {swing.player.slot}
          </span>
        </span>
        <span className="text-ink-muted tnum shrink-0 text-detail">
          {formatPoints(swing.spread)} wide
        </span>
      </div>

      <div className="flex items-center gap-2">
        <span className="tnum text-ink-muted w-9 shrink-0 text-right text-detail">
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
        <span className="tnum text-ink-muted w-9 shrink-0 text-detail">
          {formatPoints(swing.ceiling)}
        </span>
      </div>
    </li>
  )
}
