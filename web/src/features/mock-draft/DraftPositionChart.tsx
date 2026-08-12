import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Tooltip } from '@/components/ui/Tooltip'
import { cn } from '@/utils/cn'
import { formatNumber } from '@/utils/format'
import type { DraftComparison } from '@/api/schemas'

/**
 * Every draft position, ranked, as a chart you can click.
 *
 * Bars rather than a plotted line, and buttons rather than SVG, because the
 * primary interaction is *selecting a seat* — a line chart with click targets
 * bolted on is worse at that than the thing that is already a list of buttons,
 * and it comes with keyboard and focus behaviour for free.
 *
 * Two honesty properties are structural rather than editorial:
 *
 * **The best seat is never marked by colour alone.** It carries a text badge
 * and is named in the summary above the chart, because a reader who cannot
 * distinguish the accent fill would otherwise have no way to find it.
 *
 * **When the spread is inside the simulation's own error, nothing wins.** The
 * API says so in `spread_is_resolvable`, and the component drops the winner
 * marking entirely rather than pointing at a seat that is ahead by noise. That
 * is the whole reason the field exists.
 *
 * The bars are scaled from the *worst* seat rather than from zero. A zero
 * baseline would render twelve near-identical bars and hide the only thing the
 * chart is for; the axis label says what the floor is, and the printed value
 * beside every bar carries the magnitude.
 */
export function DraftPositionChart({
  comparison,
  selected,
  onSelect,
}: {
  comparison: DraftComparison
  selected: number
  onSelect: (position: number) => void
}) {
  const { seats, best_position: best, spread_is_resolvable: resolvable } = comparison
  const values = seats.map((seat) => seat.roster_value.mean)
  const floor = Math.min(...values)
  const ceiling = Math.max(...values)
  const range = Math.max(ceiling - floor, 1e-6)

  return (
    <Card>
      <CardHeader
        title="Draft position comparison"
        description={
          resolvable
            ? `Highest simulated roster value at position ${best}, ${formatNumber(comparison.spread)} points clear of the lowest. Simulated, not predicted.`
            : 'The gap between the best and worst position is smaller than the simulation’s own error, so no position is marked as best. Raise the simulation count to resolve it.'
        }
        as="h2"
        action={
          <Badge tone={resolvable ? 'accent' : 'neutral'}>
            {comparison.settings.simulations.toLocaleString()} drafts per seat
          </Badge>
        }
      />
      <CardBody>
        <ul className="space-y-1.5">
          {seats.map((seat) => {
            const value = seat.roster_value.mean
            const width = 6 + ((value - floor) / range) * 94
            const isBest = resolvable && seat.draft_position === best
            const isSelected = seat.draft_position === selected

            return (
              <li key={seat.draft_position}>
                <button
                  type="button"
                  onClick={() => onSelect(seat.draft_position)}
                  aria-pressed={isSelected}
                  className={cn(
                    'group flex w-full items-center gap-3 rounded-[var(--radius-control)] px-2 py-1.5 text-left',
                    'focus-visible:ring-accent focus-visible:ring-2 focus-visible:outline-none',
                    isSelected ? 'bg-surface-sunken' : 'hover:bg-surface-hover',
                  )}
                >
                  <span
                    className={cn(
                      'text-ink-secondary tnum w-6 shrink-0 text-right text-xs font-semibold',
                      isSelected && 'text-ink',
                    )}
                  >
                    {seat.draft_position}
                  </span>

                  <span className="bg-surface-sunken relative h-5 flex-1 overflow-hidden rounded-full">
                    <span
                      aria-hidden
                      className={cn(
                        'absolute inset-y-0 left-0 rounded-full transition-[width] duration-300',
                        isBest
                          ? 'bg-chart-series'
                          : isSelected
                            ? 'bg-chart-series/70'
                            : 'bg-chart-series/35 group-hover:bg-chart-series/50',
                      )}
                      style={{ width: `${width}%` }}
                    />
                  </span>

                  <span className="text-ink tnum w-16 shrink-0 text-right text-sm font-semibold">
                    {formatNumber(value)}
                  </span>

                  <span className="w-14 shrink-0 text-right">
                    {isBest && <Badge tone="accent">Best</Badge>}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>

        <p className="text-ink-muted mt-4 text-xs leading-relaxed">
          Bars are scaled from {formatNumber(floor)} — the lowest seat — so the
          differences are visible. Values are mean draft value (roster points above
          replacement level) across{' '}
          {comparison.settings.simulations.toLocaleString()} simulated drafts per seat,
          with a Monte Carlo error of about{' '}
          <Tooltip content="One standard error on the mean. Two seats closer together than roughly twice this are not distinguishable at this simulation count.">
            <span className="decoration-line-strong underline decoration-dotted underline-offset-2">
              ±{formatNumber(averageError(comparison), 2)}
            </span>
          </Tooltip>
          .
        </p>

        {/* The same numbers, for a reader who cannot use the bars. */}
        <details className="mt-3">
          <summary className="text-ink-secondary hover:text-ink cursor-pointer text-xs font-medium">
            View as a table
          </summary>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">
                Mean simulated roster value and projected points by draft position
              </caption>
              <thead>
                <tr className="text-ink-secondary border-line border-b text-xs">
                  <th scope="col" className="py-1.5 pr-3 text-left font-medium">
                    Position
                  </th>
                  <th scope="col" className="py-1.5 pr-3 text-right font-medium">
                    Draft value
                  </th>
                  <th scope="col" className="py-1.5 pr-3 text-right font-medium">
                    ± error
                  </th>
                  <th scope="col" className="py-1.5 text-right font-medium">
                    Projected points
                  </th>
                </tr>
              </thead>
              <tbody>
                {seats.map((seat) => (
                  <tr key={seat.draft_position} className="border-line/60 border-b last:border-0">
                    <th scope="row" className="text-ink py-1.5 pr-3 text-left font-medium">
                      {seat.draft_position}
                      {resolvable && seat.draft_position === best && ' (best)'}
                    </th>
                    <td className="text-ink tnum py-1.5 pr-3 text-right">
                      {formatNumber(seat.roster_value.mean)}
                    </td>
                    <td className="text-ink-muted tnum py-1.5 pr-3 text-right">
                      {formatNumber(seat.roster_value.standard_error, 2)}
                    </td>
                    <td className="text-ink-secondary tnum py-1.5 text-right">
                      {formatNumber(seat.starter_points.mean)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </CardBody>
    </Card>
  )
}

function averageError(comparison: DraftComparison): number {
  const errors = comparison.seats.map((seat) => seat.roster_value.standard_error)
  return errors.reduce((total, value) => total + value, 0) / Math.max(1, errors.length)
}
