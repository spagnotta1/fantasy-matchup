import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { cn } from '@/utils/cn'
import type { SeatAnalysis } from '@/api/schemas'

/**
 * Where this seat's picks fall in the draft.
 *
 * Two genuinely different renderings rather than one that shrinks. A grid of
 * twelve columns is the right shape on a desktop — the snake is *visible* in
 * it, which is the whole reason a draft board is drawn as a grid — and it is
 * the wrong shape on a phone, where twelve columns is either unreadable or a
 * horizontal scroll through mostly-empty cells to find the two that are yours.
 *
 * So on small screens it becomes what a manager actually wants there: a
 * chronological list of *their* picks and the wait between them. That is not a
 * degraded board, it is the same information ordered by what the reader can act
 * on, which is what the responsive brief asks for.
 *
 * The grid is a table with real headers, because it is tabular: rounds down,
 * seats across. A screen-reader user reads "Round 3, position 4, your pick"
 * rather than a wall of unlabelled cells.
 */
export function DraftBoard({
  seat,
  teams,
  snake,
}: {
  seat: SeatAnalysis
  teams: number
  snake: boolean
}) {
  const compact = useMediaQuery('(max-width: 767px)')
  const rounds = seat.roster.length
  const picks = new Set(seat.picks)
  const byOverall = new Map(seat.roster.map((pick) => [pick.overall, pick]))

  return (
    <Card>
      <CardHeader
        title="Draft board"
        description={
          compact
            ? 'Your picks in order, with the wait between them.'
            : snake
              ? `${teams} seats, ${rounds} rounds. Your picks are marked; the snake is why the gap between them alternates.`
              : `${teams} seats, ${rounds} rounds, linear order — every round runs in the same direction.`
        }
        as="h2"
      />
      <CardBody className={compact ? undefined : 'p-0'}>
        {compact ? (
          <ol className="space-y-2">
            {seat.roster.map((pick, index) => (
              <li
                key={pick.player_id}
                className="border-line flex items-center gap-3 rounded-[var(--radius-control)] border p-2.5"
              >
                <span className="bg-accent-soft text-accent-text flex size-9 shrink-0 flex-col items-center justify-center rounded-[var(--radius-control)] text-[0.65rem] leading-none font-semibold">
                  <span>R{pick.round_number}</span>
                  <span className="text-[0.6rem]">#{pick.overall}</span>
                </span>
                <span className="min-w-0 flex-1">
                  <span className="text-ink block truncate text-sm font-medium">
                    {pick.position} {pick.name}
                  </span>
                  {index < seat.waits.length && (
                    <span className="text-ink-muted text-xs">
                      {seat.waits[index]} picks until your next
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          // Same reason as the availability panel: the grid holds no
          // interactive cells, so without a tab stop a keyboard user cannot
          // scroll a wide board at all.
          <div
            className="overflow-x-auto"
            tabIndex={0}
            role="region"
            aria-label="Draft board, scrollable"
          >
            <table className="w-full text-xs">
              <caption className="sr-only">
                Draft board: rounds down the side, draft positions across. Your seat is{' '}
                {seat.draft_position}.
              </caption>
              <thead>
                <tr className="text-ink-muted border-line border-b">
                  <th scope="col" className="px-2 py-1.5 text-left font-medium">
                    <span className="sr-only">Round</span>
                    <span aria-hidden>Rd</span>
                  </th>
                  {Array.from({ length: teams }, (_, index) => (
                    <th
                      key={index}
                      scope="col"
                      className={cn(
                        'px-1 py-1.5 text-center font-medium',
                        index + 1 === seat.draft_position && 'text-accent-text',
                      )}
                    >
                      {index + 1}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: rounds }, (_, roundIndex) => {
                  const round = roundIndex + 1
                  return (
                    <tr key={round} className="border-line/50 border-b last:border-0">
                      <th
                        scope="row"
                        className="text-ink-secondary px-2 py-1 text-left font-medium"
                      >
                        {round}
                      </th>
                      {Array.from({ length: teams }, (_, seatIndex) => {
                        const team = seatIndex + 1
                        const overall = overallPick(round, team, teams, snake)
                        const mine = picks.has(overall) && team === seat.draft_position
                        const pick = mine ? byOverall.get(overall) : undefined
                        return (
                          <td key={team} className="px-0.5 py-1">
                            <div
                              className={cn(
                                'flex h-8 items-center justify-center rounded px-1 text-center',
                                mine
                                  ? 'bg-accent-soft text-accent-text font-semibold'
                                  : 'bg-surface-sunken text-ink-muted',
                              )}
                            >
                              {pick ? (
                                <span className="truncate">
                                  <span className="sr-only">
                                    Your pick, round {round}, overall {overall}:{' '}
                                  </span>
                                  {pick.position} {lastName(pick.name)}
                                </span>
                              ) : (
                                // Full-strength muted ink, not a dimmed copy of
                                // it: these pick numbers are the only thing
                                // orienting a reader in a 180-cell grid, and at
                                // 50% opacity they measured below 4.5:1 against
                                // the sunken surface.
                                <span aria-hidden>{overall}</span>
                              )}
                            </div>
                          </td>
                        )
                      })}
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

/**
 * Overall pick number for a (round, seat) under a snake.
 *
 * Duplicated from the server's ordering, which is a real duplication and a
 * bounded one: the board draws every cell, including the ones nobody's pick
 * lands in, so it needs the mapping for seats the response says nothing about.
 * The seat's own picks come from the API and are what everything else keys on,
 * so a disagreement here shows up as a misaligned highlight rather than a wrong
 * roster.
 */
function overallPick(round: number, team: number, teams: number, snake: boolean): number {
  const position = snake && round % 2 === 0 ? teams - team + 1 : team
  return (round - 1) * teams + position
}

function lastName(name: string): string {
  const parts = name.split(' ')
  return parts.length > 1 ? (parts[parts.length - 1] ?? name) : name
}
