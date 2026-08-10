import { useState } from 'react'

import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { cn } from '@/utils/cn'
import { formatNumber, formatPercent } from '@/utils/format'
import type { SeatAnalysis } from '@/api/schemas'

type Filter = 'all' | 'QB' | 'RB' | 'WR' | 'TE'

/**
 * Can I wait, or am I losing him?
 *
 * The percentage is anchored to *this seat's* picks, which is the only way it
 * means anything: "72% available" is unanswerable without saying when. Each row
 * therefore names the pick the decision happens at and the pick you would be
 * waiting for, and gives the probability the player survives between them.
 *
 * The status word is not decoration and is not derived from colour. "Likely
 * gone" and "Can wait" are the two states a manager acts on, and a reader who
 * cannot distinguish the chip fills still gets the word and the number.
 */
export function AvailabilityPanel({ seat }: { seat: SeatAnalysis }) {
  const [filter, setFilter] = useState<Filter>('all')

  const rows = seat.availability.filter(
    (entry) => filter === 'all' || entry.position === filter,
  )

  return (
    <Card>
      <CardHeader
        title="Player availability"
        description="How often each player is still on the board when this seat picks, across the simulated drafts."
        as="h2"
        action={
          <SegmentedControl
            label="Filter by position"
            value={filter}
            onChange={setFilter}
            size="sm"
            options={[
              { value: 'all', label: 'All' },
              { value: 'QB', label: 'QB' },
              { value: 'RB', label: 'RB' },
              { value: 'WR', label: 'WR' },
              { value: 'TE', label: 'TE' },
            ]}
          />
        }
      />
      <CardBody className="p-0">
        {rows.length === 0 ? (
          <p className="text-ink-secondary px-4 py-8 text-center text-sm">
            No players at this position are near enough to the top of the board for
            availability to be a decision.
          </p>
        ) : (
          // A scroll container with no focusable content inside it is
          // unreachable by keyboard: the rows can be seen but never scrolled
          // to without a pointer. `tabIndex` makes the region itself a tab
          // stop, which is what the arrow keys then act on, and it needs a
          // name and a role once it is one.
          <div
            className="max-h-[28rem] overflow-auto"
            tabIndex={0}
            role="region"
            aria-label="Player availability, scrollable"
          >
            <table className="w-full min-w-[34rem] text-sm">
              <caption className="sr-only">
                Probability each player is still available at draft position{' '}
                {seat.draft_position}&rsquo;s picks
              </caption>
              <thead className="bg-surface sticky top-0 z-10">
                <tr className="text-ink-secondary border-line border-b text-xs">
                  <th scope="col" className="py-2 pr-2 pl-4 text-left font-medium">
                    Player
                  </th>
                  <th scope="col" className="py-2 pr-2 text-right font-medium">
                    Value
                  </th>
                  <th scope="col" className="py-2 pr-2 text-right font-medium">
                    Typically goes
                  </th>
                  <th scope="col" className="py-2 pr-2 text-right font-medium">
                    Available next
                  </th>
                  <th scope="col" className="py-2 pr-4 text-left font-medium">
                    Verdict
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => {
                  const waitable = entry.next_pick_probability >= 0.6
                  const gone = entry.next_pick_probability <= 0.25
                  return (
                    <tr
                      key={entry.player_id}
                      className="border-line/60 border-b last:border-0"
                    >
                      <th scope="row" className="py-2 pr-2 pl-4 text-left font-normal">
                        <span className="flex items-center gap-2">
                          <Badge tone="neutral">{entry.position}</Badge>
                          <span className="text-ink font-medium">{entry.name}</span>
                        </span>
                      </th>
                      <td className="text-ink-secondary tnum py-2 pr-2 text-right">
                        {formatNumber(entry.season_value)}
                      </td>
                      <td className="text-ink-muted tnum py-2 pr-2 text-right text-xs">
                        {entry.mean_selection_pick == null
                          ? 'Undrafted'
                          : `#${formatNumber(entry.mean_selection_pick, 0)}`}
                      </td>
                      <td className="tnum py-2 pr-2 text-right">
                        {entry.next_reference_pick == null ? (
                          <span className="text-ink-muted text-xs">No later pick</span>
                        ) : (
                          <>
                            <span
                              className={cn(
                                'font-semibold',
                                waitable ? 'text-positive-text' : gone ? 'text-negative-text' : 'text-ink',
                              )}
                            >
                              {formatPercent(entry.next_pick_probability)}
                            </span>
                            <span className="text-ink-muted block text-xs">
                              at #{entry.next_reference_pick}
                            </span>
                          </>
                        )}
                      </td>
                      <td className="py-2 pr-4">
                        {entry.next_reference_pick == null ? (
                          <span className="text-ink-muted text-xs">—</span>
                        ) : gone ? (
                          <Badge tone="negative">Likely gone</Badge>
                        ) : waitable ? (
                          <Badge tone="positive">Can wait</Badge>
                        ) : (
                          <Badge tone="caution">Coin flip</Badge>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
