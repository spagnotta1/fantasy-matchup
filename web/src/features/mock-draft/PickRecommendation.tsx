import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { formatNumber, formatPercent } from '@/utils/format'
import type { SeatAnalysis } from '@/api/schemas'

/**
 * The first pick, and what the engine nearly took instead.
 *
 * The wording is load-bearing. This is what the engine *most often selected*
 * from this seat across the simulations — a frequency, which the number beside
 * it states — and never "the pick you should make". The alternatives are not
 * runners-up in a beauty contest either: they are the other players this seat's
 * opening pick actually went to in other simulated drafts, with how often.
 *
 * Round 1 is the only round this is shown for. Later rounds depend entirely on
 * what the first eleven managers did, so "your round 4 pick" has no meaning
 * outside a particular draft — which is what the roster table shows.
 */
export function PickRecommendation({ seat }: { seat: SeatAnalysis }) {
  const opener = seat.roster[0]
  if (!opener) return null

  const firstRound = seat.round_positions
    .filter((entry) => entry.round_number === 1)
    .sort((a, b) => b.share - a.share)

  return (
    <Card>
      <CardHeader
        title={`Opening pick at position ${seat.draft_position}`}
        description={`Pick #${opener.overall} overall. Shown from the median simulated draft; the position mix below is across all ${seat.simulations.toLocaleString()}.`}
        as="h2"
        action={<ProvenanceBadge provenance="derived" />}
      />
      <CardBody className="space-y-4">
        <div className="bg-surface-sunken flex flex-wrap items-baseline gap-x-4 gap-y-2 rounded-[var(--radius-control)] p-4">
          <Badge tone="accent">{opener.position}</Badge>
          <span className="text-ink text-xl font-semibold">{opener.name}</span>
          {opener.team && <span className="text-ink-muted text-sm">{opener.team}</span>}
          <span className="ml-auto text-right">
            <span className="text-ink tnum block text-lg font-semibold">
              {formatNumber(opener.season_value)}
            </span>
            <span className="text-ink-muted text-xs">projected season points</span>
          </span>
        </div>

        {opener.rationale && (
          <div className="space-y-2">
            <h3 className="text-ink text-sm font-semibold">Why</h3>
            <p className="text-ink-secondary text-sm leading-relaxed">
              {opener.rationale.explanation}
            </p>
          </div>
        )}

        {firstRound.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-ink text-sm font-semibold">
              What this seat opens with, across the run
            </h3>
            <ul className="flex flex-wrap gap-2">
              {firstRound.map((entry) => (
                <li
                  key={entry.position}
                  className="border-line flex items-baseline gap-2 rounded-[var(--radius-control)] border px-2.5 py-1.5"
                >
                  <span className="text-ink text-sm font-medium">{entry.position}</span>
                  <span className="text-ink-secondary tnum text-xs">
                    {formatPercent(entry.share)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-ink-muted text-xs leading-relaxed">
              Share of simulated drafts in which this seat&rsquo;s first pick went to each
              position. A single position near 100% means the board reliably falls the
              same way here; a spread means it does not.
            </p>
          </div>
        )}
      </CardBody>
    </Card>
  )
}

/**
 * Position-by-position strength of the rosters this seat builds.
 *
 * The number that explains a seat's total: two seats with the same roster value
 * can get there very differently, and this is where a receiver-heavy seat and a
 * back-heavy one become visibly different rather than merely equal.
 */
export function PositionStrength({ seat }: { seat: SeatAnalysis }) {
  if (seat.position_strength.length === 0) return null
  const peak = Math.max(...seat.position_strength.map((entry) => entry.mean_starter_points))

  return (
    <Card>
      <CardHeader
        title="Position strength"
        description="Mean projected points contributed by each position's starters, across the run."
        as="h2"
      />
      <CardBody>
        <table className="w-full text-sm">
          <caption className="sr-only">
            Mean starting points and value over replacement by position
          </caption>
          <thead>
            <tr className="text-ink-secondary border-line border-b text-xs">
              <th scope="col" className="py-1.5 pr-3 text-left font-medium">
                Position
              </th>
              <th scope="col" className="py-1.5 pr-3 text-left font-medium">
                <span className="sr-only">Relative share</span>
              </th>
              <th scope="col" className="py-1.5 pr-3 text-right font-medium">
                Points
              </th>
              <th scope="col" className="py-1.5 text-right font-medium">
                Over replacement
              </th>
            </tr>
          </thead>
          <tbody>
            {seat.position_strength.map((entry) => (
              <tr key={entry.position} className="border-line/60 border-b last:border-0">
                <th scope="row" className="text-ink py-2 pr-3 text-left font-medium">
                  {entry.position}
                  <span className="text-ink-muted ml-1.5 text-xs font-normal">
                    {formatNumber(entry.mean_starters)} starters
                  </span>
                </th>
                <td className="py-2 pr-3">
                  <span className="bg-surface-sunken block h-2 w-full overflow-hidden rounded-full">
                    <span
                      aria-hidden
                      className="bg-chart-series/60 block h-full rounded-full"
                      style={{
                        width: `${Math.max(2, (entry.mean_starter_points / peak) * 100)}%`,
                      }}
                    />
                  </span>
                </td>
                <td className="text-ink tnum py-2 pr-3 text-right font-medium">
                  {formatNumber(entry.mean_starter_points)}
                </td>
                <td className="text-ink-secondary tnum py-2 text-right">
                  {formatNumber(entry.mean_value_over_replacement)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardBody>
    </Card>
  )
}
