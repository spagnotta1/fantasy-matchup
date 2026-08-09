import { Minus } from 'lucide-react'

import { formatPoints, formatSigned } from '@/utils/format'
import { cn } from '@/utils/cn'
import type { SimulatedPlayer } from '@/api/schemas'

/** QB, RB, WR, TE first; anything the API adds later keeps its own order after. */
const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE']

interface Edge {
  position: string
  a: number
  b: number
  difference: number
}

/**
 * Where each lineup's points come from, and where the gap is.
 *
 * This is a subtraction of published numbers and is named as one. The figure
 * summed is `simulated_mean`, not `expected_points`, for a specific reason: the
 * simulated means are what add up to the `expected_score` shown above, so the
 * parts here sum to the whole on the same screen. Using the projections instead
 * would produce a set of edges that quietly disagreed with the totals.
 *
 * Grouped by *position* rather than by slot, so a running back started at flex
 * counts toward the running back comparison — which is what a manager means by
 * "my running backs are better".
 *
 * An edge is not an advantage in the outcome. Two lineups can differ by twelve
 * points at running back and still be a coin flip, because these are averages
 * over distributions that overlap. The win probability is the only number on
 * this page that accounts for that, and it comes from the API.
 */
export function PositionalEdges({
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
  const edges = buildEdges(playersA, playersB)
  if (edges.length === 0) {
    return <p className="text-ink-muted text-sm">No positional breakdown is available.</p>
  }

  // One scale across every row, so a bar's length is comparable down the list.
  const widest = Math.max(...edges.map((edge) => Math.abs(edge.difference)), 0.001)

  return (
    <div className="space-y-3">
      {edges.map((edge) => {
        const share = (Math.abs(edge.difference) / widest) * 50
        const leadsA = edge.difference > 0
        const level = Math.abs(edge.difference) < 0.05

        return (
          <div key={edge.position} className="grid grid-cols-[2.5rem_1fr_5rem] items-center gap-3">
            <span className="text-ink-secondary text-xs font-semibold">{edge.position}</span>

            <div
              className="bg-surface-sunken relative h-6 overflow-hidden rounded-[var(--radius-control)]"
              role="img"
              aria-label={`${edge.position}: ${labelA} ${formatPoints(edge.a)} points, ${labelB} ${formatPoints(edge.b)}. ${
                level
                  ? 'Level.'
                  : `${leadsA ? labelA : labelB} ahead by ${formatPoints(Math.abs(edge.difference))}.`
              }`}
            >
              {/* A centre line with the bar growing toward whichever side leads.
                  The direction is the information; the length is the size. */}
              <span aria-hidden className="bg-line absolute inset-y-0 left-1/2 w-px" />
              {!level && (
                <span
                  aria-hidden
                  className={cn(
                    'absolute inset-y-1 rounded-[3px]',
                    leadsA ? 'bg-chart-series' : 'bg-chart-series/40',
                  )}
                  style={
                    leadsA
                      ? { left: '50%', width: `${share}%` }
                      : { right: '50%', width: `${share}%` }
                  }
                />
              )}
              <span className="text-ink-muted tnum absolute inset-y-0 left-2 flex items-center text-[0.6875rem]">
                {formatPoints(edge.b)}
              </span>
              <span className="text-ink-muted tnum absolute inset-y-0 right-2 flex items-center text-[0.6875rem]">
                {formatPoints(edge.a)}
              </span>
            </div>

            <span
              className={cn(
                'tnum flex items-center justify-end gap-1 text-sm font-medium',
                level ? 'text-ink-muted' : 'text-ink',
              )}
            >
              {level ? (
                <>
                  <Minus aria-hidden className="size-3" />
                  Level
                </>
              ) : (
                formatSigned(edge.difference)
              )}
            </span>
          </div>
        )
      })}

      <p className="text-ink-muted pt-1 text-xs leading-relaxed">
        Simulated mean points by position, {labelA} minus {labelB}. These sum to the totals above.
        A gap here is an average, not an outcome — the ranges behind these averages overlap, which
        is what the win probability accounts for and this breakdown does not.
      </p>
    </div>
  )
}

function buildEdges(playersA: SimulatedPlayer[], playersB: SimulatedPlayer[]): Edge[] {
  const totals = new Map<string, { a: number; b: number }>()

  const add = (players: SimulatedPlayer[], side: 'a' | 'b') => {
    for (const player of players) {
      const position = player.position ?? 'Other'
      const entry = totals.get(position) ?? { a: 0, b: 0 }
      entry[side] += player.simulated_mean
      totals.set(position, entry)
    }
  }

  add(playersA, 'a')
  add(playersB, 'b')

  return [...totals.entries()]
    .map(([position, value]) => ({
      position,
      a: value.a,
      b: value.b,
      difference: value.a - value.b,
    }))
    .sort((left, right) => {
      const l = POSITION_ORDER.indexOf(left.position)
      const r = POSITION_ORDER.indexOf(right.position)
      return (l === -1 ? POSITION_ORDER.length : l) - (r === -1 ? POSITION_ORDER.length : r)
    })
}
