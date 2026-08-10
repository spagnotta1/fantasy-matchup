import { useState } from 'react'
import { ChevronDown, Minus, TrendingDown, TrendingUp } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { cn } from '@/utils/cn'
import { formatNumber, formatPercent, formatPoints } from '@/utils/format'
import type { SeatAnalysis, SimulatedPick } from '@/api/schemas'

/**
 * The roster one simulated draft produced, round by round, with its reasoning.
 *
 * A semantic table, because that is what it is: fifteen rows with a stable
 * meaning per column, which a screen-reader user navigates by column header.
 * The expandable reasoning lives in a row beneath each pick rather than in a
 * tooltip — it runs to several sentences of arithmetic and a tooltip is the
 * wrong container for anything a reader needs to sit with.
 *
 * The heading says *median*, not *best*, and it matters: the API returns the
 * simulation closest to the median roster value, so this is a draft that
 * typically happens rather than the luckiest of ten thousand.
 */
export function SimulatedRoster({ seat }: { seat: SeatAnalysis }) {
  const [expanded, setExpanded] = useState<string | null>(
    seat.roster[0]?.player_id ?? null,
  )

  return (
    <Card>
      <CardHeader
        title={`Simulated roster — draft position ${seat.draft_position}`}
        description="The simulation whose roster value landed closest to the median, replayed with the reasoning behind every pick. Not the best of the run."
        as="h2"
        action={<ProvenanceBadge provenance="derived" />}
      />
      <CardBody className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[42rem] text-sm">
            <caption className="sr-only">
              Round-by-round roster from the median simulated draft at position{' '}
              {seat.draft_position}
            </caption>
            <thead>
              <tr className="text-ink-secondary border-line border-b text-xs">
                <th scope="col" className="py-2 pr-2 pl-4 text-left font-medium">
                  Rd
                </th>
                <th scope="col" className="py-2 pr-2 text-left font-medium">
                  Pick
                </th>
                <th scope="col" className="py-2 pr-2 text-left font-medium">
                  Player
                </th>
                <th scope="col" className="py-2 pr-2 text-right font-medium">
                  Projected
                </th>
                <th scope="col" className="py-2 pr-2 text-right font-medium">
                  Last season
                </th>
                <th scope="col" className="py-2 pr-2 text-right font-medium">
                  Draft value
                </th>
                <th scope="col" className="py-2 pr-4 text-right font-medium">
                  Why
                </th>
              </tr>
            </thead>
            <tbody>
              {seat.roster.map((pick) => (
                <RosterRow
                  key={pick.player_id}
                  pick={pick}
                  expanded={expanded === pick.player_id}
                  onToggle={() =>
                    setExpanded((current) =>
                      current === pick.player_id ? null : pick.player_id,
                    )
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      </CardBody>
    </Card>
  )
}

function RosterRow({
  pick,
  expanded,
  onToggle,
}: {
  pick: SimulatedPick
  expanded: boolean
  onToggle: () => void
}) {
  const previous = pick.historical?.seasons[0]
  const detailId = `why-${pick.player_id}`

  return (
    <>
      <tr className="border-line/60 border-b last:border-0">
        <th scope="row" className="text-ink-secondary tnum py-2 pr-2 pl-4 text-left font-medium">
          {pick.round_number}
        </th>
        <td className="text-ink-muted tnum py-2 pr-2 text-xs">#{pick.overall}</td>
        <td className="py-2 pr-2">
          <div className="flex items-center gap-2">
            <Badge tone="neutral">{pick.position}</Badge>
            <span className="text-ink font-medium">{pick.name}</span>
            {pick.is_starter ? (
              <Badge tone="accent">Starter</Badge>
            ) : (
              <Badge tone="neutral">Bench</Badge>
            )}
          </div>
          {pick.team && <span className="text-ink-muted text-xs">{pick.team}</span>}
        </td>
        <td className="text-ink tnum py-2 pr-2 text-right">
          <span className="font-semibold">{formatNumber(pick.season_value)}</span>
          <span className="text-ink-muted block text-xs">
            {formatPoints(pick.projected_points_per_game)}/g × {formatNumber(pick.expected_games)}
          </span>
        </td>
        <td className="tnum py-2 pr-2 text-right">
          {previous ? (
            <>
              <span className="text-ink-secondary">{formatNumber(previous.total_points)}</span>
              <span className="text-ink-muted block text-xs">
                {previous.season} · {previous.games_played}g
              </span>
            </>
          ) : (
            <span className="text-ink-muted text-xs">No prior season</span>
          )}
        </td>
        <td className="tnum py-2 pr-2 text-right">
          <span
            className={cn(
              'font-semibold',
              pick.value_over_replacement >= 0 ? 'text-ink' : 'text-ink-muted',
            )}
          >
            {formatNumber(pick.value_over_replacement)}
          </span>
        </td>
        <td className="py-2 pr-4 text-right">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-controls={detailId}
            className="text-ink-secondary hover:text-ink focus-visible:ring-accent inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs font-medium focus-visible:ring-2 focus-visible:outline-none"
          >
            {expanded ? 'Hide' : 'Why'}
            <ChevronDown
              aria-hidden
              className={cn('size-3.5 transition-transform', expanded && 'rotate-180')}
            />
          </button>
        </td>
      </tr>

      {expanded && (
        <tr id={detailId} className="border-line/60 border-b last:border-0">
          <td colSpan={7} className="bg-surface-sunken px-4 py-3">
            <PickReasoning pick={pick} />
          </td>
        </tr>
      )}
    </>
  )
}

/**
 * The reasoning, and the numbers it was assembled from.
 *
 * The sentence comes from the API and is built mechanically out of the values
 * beside it, so showing both is not redundancy — it is the reader being able to
 * check the claim against the arithmetic that produced it.
 */
function PickReasoning({ pick }: { pick: SimulatedPick }) {
  const rationale = pick.rationale
  const history = pick.historical

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_18rem]">
      <div className="space-y-3">
        {rationale ? (
          <>
            <p className="text-ink text-sm leading-relaxed">{rationale.explanation}</p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-3">
              <Figure label="Fills" value={rationale.slot} />
              <Figure
                label="Value added"
                value={`${formatNumber(rationale.marginal_value)} pts`}
              />
              <Figure
                label="Over next available"
                value={`${formatNumber(rationale.value_over_next_available)} pts`}
              />
              {rationale.next_pick_overall != null && (
                <Figure
                  label={`Survives to #${rationale.next_pick_overall}`}
                  value={formatPercent(rationale.survival_at_next_pick)}
                />
              )}
              {rationale.tier_index != null && (
                <Figure
                  label={`Tier ${rationale.tier_index}`}
                  value={`${rationale.tier_remaining ?? 0} of ${rationale.tier_size ?? 0} left`}
                />
              )}
              {rationale.runner_up_name && (
                <Figure
                  label="Chosen over"
                  value={`${rationale.runner_up_name} (+${formatNumber(rationale.runner_up_margin ?? 0)})`}
                />
              )}
            </dl>
          </>
        ) : (
          <p className="text-ink-secondary text-sm">
            No reasoning was captured for this pick.
          </p>
        )}
      </div>

      <HistoryPanel history={history} />
    </div>
  )
}

function HistoryPanel({ history }: { history: SimulatedPick['historical'] }) {
  if (!history || history.seasons.length === 0) {
    return (
      <div className="border-line rounded-[var(--radius-control)] border p-3">
        <p className="text-ink-secondary text-xs leading-relaxed">
          No completed season in the historical window, so expected games is the
          position prior rather than this player&rsquo;s own record.
        </p>
      </div>
    )
  }

  const TrendIcon =
    history.trend === 'rising' ? TrendingUp : history.trend === 'declining' ? TrendingDown : Minus

  return (
    <div className="border-line space-y-2 rounded-[var(--radius-control)] border p-3">
      <div className="flex items-center justify-between">
        <span className="text-ink-secondary text-xs font-semibold">Historical</span>
        <ProvenanceBadge provenance="actual" />
      </div>
      <dl className="space-y-1">
        {history.seasons.map((entry) => (
          <div key={entry.season} className="flex items-baseline justify-between gap-3 text-xs">
            <dt className="text-ink-muted">{entry.season}</dt>
            <dd className="text-ink tnum">
              {formatNumber(entry.total_points)} pts
              <span className="text-ink-muted"> · {entry.games_played}g</span>
            </dd>
          </div>
        ))}
      </dl>
      <div className="border-line/60 flex flex-wrap items-center gap-2 border-t pt-2 text-xs">
        {history.trend && (
          <span className="text-ink-secondary inline-flex items-center gap-1">
            <TrendIcon aria-hidden className="size-3.5" />
            {history.trend}
          </span>
        )}
        {history.consistency_label && (
          <span className="text-ink-secondary">
            {history.consistency_label} consistency
          </span>
        )}
        <span className="text-ink-muted">
          {formatNumber(history.expected_games)} games expected
        </span>
      </div>
      {history.trend_detail && (
        <p className="text-ink-muted text-xs leading-relaxed">{history.trend_detail}</p>
      )}
    </div>
  )
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="text-ink tnum font-medium">{value}</dd>
    </div>
  )
}
