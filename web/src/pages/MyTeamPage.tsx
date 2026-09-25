import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDownToLine, Copy, RotateCcw, Shuffle, Trash2, UserRound } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Select } from '@/components/ui/Select'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { PlayerSearchField } from '@/components/domain/PlayerSearchField'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { useSlate } from '@/app/slate-context'
import { autofillLineup, eligiblePositions, emptyLineup, type LineupRow } from '@/features/simulations/lineupFormat'
import { encodeLineup, TEAM_A_PARAM } from '@/features/simulations/shareLink'
import { useBoard, usePlayers } from '@/hooks/useProjections'
import { useLineupChoice, useRoster } from '@/hooks/useRoster'
import { useLineupCatalog } from '@/hooks/useSimulation'
import { boardCeiling } from '@/utils/board'
import { formatPoints, headlinePoints } from '@/utils/format'
import type { LineupSlot, Player, RankedProjection } from '@/api/schemas'

const FANTASY_POSITIONS = ['QB', 'RB', 'WR', 'TE']

/**
 * My team: a roster, this week's projections for it, and the highest-projected
 * lineup it can field.
 *
 * The roster is a list in the URL (see `useRoster`) — no account, no saved
 * league. The lineup is the simulation builder's own autofill run over just
 * these players, in the board's projected order, and it says what it is: a
 * starting point filled slot by slot, not an optimiser.
 *
 * The manager can override it: bench a starter, or start a bench player in
 * any slot their position is eligible for. The choice lives in the link beside
 * the roster (`useLineupChoice`), and the page keeps saying how the chosen
 * lineup compares with the highest-projected one rather than hiding it.
 *
 * Two kinds of player are kept out of the lineup, and both are named rather
 * than dropped: anyone ruled out (the designation is a hard caveat; they keep
 * their projection, they just do not play) and anyone with no projection this
 * week (a bye, an inactive listing, or a run that does not cover them).
 */
export default function MyTeamPage() {
  const slate = useSlate()
  const [ids, setIds] = useRoster()
  const [choice, setChoice] = useLineupChoice()
  const board = useBoard()
  const catalog = useLineupCatalog()
  const identities = usePlayers(ids)
  const [copied, setCopied] = useState(false)

  const byId = useMemo(() => {
    const map = new Map<string, RankedProjection>()
    for (const entry of board.data?.data ?? []) map.set(entry.projection.player.player_id, entry)
    return map
  }, [board.data])

  const roster = useMemo(() => {
    return ids.map((id, index) => {
      const entry = byId.get(id)
      const player: Player | undefined = entry?.projection.player ?? identities[index]?.data
      return { id, entry, player }
    })
  }, [ids, byId, identities])

  const projected = roster
    .filter((r) => r.entry)
    .map((r) => r.entry as RankedProjection)
    .sort((a, b) => a.rank - b.rank)
  const ruledOut = projected.filter((e) => e.projection.context.injury?.will_not_play)
  const available = projected.filter((e) => !e.projection.context.injury?.will_not_play)
  const unprojected = roster.filter((r) => !r.entry)

  const best = useMemo(
    () =>
      catalog.isPending ? [] : autofillLineup(emptyLineup(catalog.format), available, catalog.slots, []),
    [catalog.isPending, catalog.format, catalog.slots, available],
  )
  const lineup = useMemo(
    () =>
      catalog.isPending
        ? []
        : (chosenLineup(emptyLineup(catalog.format), choice, available, catalog.slots) ?? best),
    [catalog.isPending, catalog.format, catalog.slots, choice, available, best],
  )
  const customised = !sameLineup(lineup, best)
  const starters = new Set(lineup.map((row) => row.player?.player_id).filter(Boolean))
  const bench = available.filter((e) => !starters.has(e.projection.player.player_id))
  const total = lineupPoints(lineup, byId)
  const bestTotal = lineupPoints(best, byId)
  const openSlots = lineup.filter((row) => !row.player).length

  // Every change writes the whole lineup, slot by slot, so the link always
  // describes exactly what is on screen. Landing back on the default clears it.
  const writeLineup = (players: (Player | null)[]) => {
    const next = players.map((player) => player?.player_id ?? '')
    setChoice(sameIds(next, lineupIds(best)) ? null : next)
  }
  const benchSlot = (index: number) =>
    writeLineup(lineup.map((row, i) => (i === index ? null : row.player)))
  const startInSlot = (index: number, playerId: string) => {
    const player = byId.get(playerId)?.projection.player ?? null
    writeLineup(
      lineup.map((row, i) => {
        if (i === index) return player
        // A starter moved into another slot leaves their old one empty.
        return row.player?.player_id === playerId ? null : row.player
      }),
    )
  }
  const fits = (entry: RankedProjection, slot: string) => {
    const position = entry.projection.player.position
    return position ? eligiblePositions(catalog.slots, slot).includes(position) : false
  }
  const slotOptions = (entry: RankedProjection) =>
    lineup.flatMap((row, index) =>
      fits(entry, row.slot)
        ? [
            {
              value: String(index),
              label: row.player ? `${row.slot} — replace ${row.player.name}` : `${row.slot} — empty slot`,
            },
          ]
        : [],
    )
  const benchOptions = (slot: string) =>
    bench
      .filter((entry) => fits(entry, slot))
      .map((entry) => ({ value: entry.projection.player.player_id, label: entry.projection.player.name }))
  const scaleMax = boardCeiling(projected)

  const simulateHref = `/simulation?${TEAM_A_PARAM}=${encodeURIComponent(
    encodeLineup(lineup.filter((r) => r.player).map((r) => ({ slot: r.slot, player_id: r.player?.player_id as string }))),
  )}`

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <>
      <PageHeader
        title="My team"
        question={`Who should I start from my roster in week ${slate.week ?? '—'}?`}
        action={
          ids.length > 0 && (
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => void copyLink()}>
                <Copy aria-hidden className="size-3.5" />
                {copied ? 'Link copied' : 'Copy link'}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setIds([])
                  setChoice(null)
                }}
              >
                <Trash2 aria-hidden className="size-3.5" />
                Clear
              </Button>
            </div>
          )
        }
      />

      <NoticeList
        className="mb-4"
        notices={[
          'Your roster lives in this page’s link and in this browser — there is no account and nothing is stored on a server. Copy the link to keep it or open it elsewhere.',
        ]}
      />

      <Card className="mb-6">
        <CardBody>
          <PlayerSearchField
            label="Add a player"
            placeholder="Search QB, RB, WR or TE…"
            positions={FANTASY_POSITIONS}
            excludeIds={ids}
            onSelect={(player) => setIds([...ids, player.player_id])}
          />
        </CardBody>
      </Card>

      {ids.length === 0 ? (
        <Card>
          <EmptyState
            titleAs="h2"
            icon={<UserRound aria-hidden className="size-5" />}
            title="Add your roster"
            description="Search for your players above. We will show their projections, fill in your highest-projected lineup and flag anyone ruled out."
          />
        </Card>
      ) : board.isPending || catalog.isPending ? (
        <Card>
          <SkeletonTable rows={8} columns={5} />
        </Card>
      ) : board.isError ? (
        <Card>
          <ErrorState error={board.error} onRetry={() => void board.refetch()} />
        </Card>
      ) : (
        <Refreshing active={board.isPlaceholderData}>
          {(ruledOut.length > 0 || unprojected.length > 0) && (
            <Card className="mb-6">
              <CardHeader as="h2" title="Not in the lineup" description="Kept out of the lineup below, with the reason." />
              <ul className="divide-line divide-y">
                {ruledOut.map((entry) => (
                  <li key={entry.projection.player.player_id} className="flex items-center gap-3 px-4 py-2.5">
                    <PlayerIdentity player={entry.projection.player} team={entry.projection.team} size="sm" className="flex-1" />
                    <InjuryBadge injury={entry.projection.context.injury} />
                    <span className="text-right">
                      <ProjectionValue points={entry.projection.prediction.points} />
                      <span className="text-negative-text block text-[0.6875rem] font-medium">Ruled out — will not play</span>
                    </span>
                  </li>
                ))}
                {unprojected.map((r) => (
                  <li key={r.id} className="flex items-center gap-3 px-4 py-2.5">
                    {r.player ? (
                      <PlayerIdentity player={r.player} size="sm" className="flex-1" />
                    ) : (
                      <span className="text-ink-secondary flex-1 text-sm">{r.id}</span>
                    )}
                    <span className="text-ink-muted text-xs">No projection this week — usually a bye week or an inactive listing</span>
                    <button
                      type="button"
                      onClick={() => setIds(ids.filter((id) => id !== r.id))}
                      className="text-ink-muted hover:text-ink rounded-sm text-xs underline"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card className="mb-6 overflow-hidden">
            <CardHeader
              as="h2"
              title={
                customised
                  ? `Your lineup — ${formatPoints(total)} pts`
                  : `Highest-projected lineup — ${formatPoints(total)} pts`
              }
              description={
                customised
                  ? `${catalog.format.label}. You have changed this lineup. It projects ${formatPoints(Math.abs(bestTotal - total))} pts ${total <= bestTotal ? 'below' : 'above'} the highest-projected lineup (${formatPoints(bestTotal)} pts).`
                  : `${catalog.format.label}. Filled with your highest-projected players, slot by slot — a starting point, not the final word. Use Bench and Start to change it.`
              }
              action={
                <div className="flex items-center gap-2">
                  <ProvenanceBadge provenance="model" />
                  {customised && (
                    <Button size="sm" variant="ghost" onClick={() => setChoice(null)}>
                      <RotateCcw aria-hidden className="size-3.5" />
                      Reset
                    </Button>
                  )}
                  {lineup.some((r) => r.player) && (
                    <Link to={simulateHref} className="text-accent-text inline-flex items-center gap-1 text-sm hover:underline">
                      <Shuffle aria-hidden className="size-3.5" />
                      Simulate
                    </Link>
                  )}
                </div>
              }
            />
            <RosterTable
              rows={lineup.map((row, index) => {
                const entry = row.player ? byId.get(row.player.player_id) : undefined
                const fillers = entry ? [] : benchOptions(row.slot)
                return {
                  slot: row.slot,
                  entry,
                  emptyNote:
                    fillers.length > 0
                      ? 'Empty — choose a bench player to start here'
                      : 'Empty — no eligible player on your bench',
                  move: entry ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => benchSlot(index)}
                      aria-label={`Move ${entry.projection.player.name} to the bench`}
                    >
                      <ArrowDownToLine aria-hidden className="size-3.5" />
                      Bench
                    </Button>
                  ) : fillers.length > 0 ? (
                    <MoveSelect
                      label={`Start a player at ${row.slot}`}
                      placeholder="Start…"
                      options={fillers}
                      onChoose={(playerId) => startInSlot(index, playerId)}
                    />
                  ) : null,
                }
              })}
              scaleMax={scaleMax}
              onRemove={(id) => setIds(ids.filter((x) => x !== id))}
            />
            {openSlots > 0 && (
              <CardBody className="border-line text-caution-text border-t py-3 text-xs">
                {openSlots} {openSlots === 1 ? 'slot is' : 'slots are'} empty. An empty slot scores zero.
              </CardBody>
            )}
          </Card>

          {bench.length > 0 && (
            <Card className="overflow-hidden">
              <CardHeader
                as="h2"
                title="Bench"
                description={
                  customised
                    ? 'Not in your starting lineup. Use Start to move a player into a slot.'
                    : 'Projected lower than the starter in their slot. Use Start to move a player in anyway.'
                }
              />
              <RosterTable
                rows={bench.map((entry) => {
                  const options = slotOptions(entry)
                  return {
                    slot: 'BN',
                    entry,
                    move:
                      options.length > 0 ? (
                        <MoveSelect
                          label={`Start ${entry.projection.player.name}`}
                          placeholder="Start in…"
                          options={options}
                          onChoose={(value) => startInSlot(Number(value), entry.projection.player.player_id)}
                        />
                      ) : (
                        <span className="text-ink-muted text-xs">No eligible slot</span>
                      ),
                  }
                })}
                scaleMax={scaleMax}
                onRemove={(id) => setIds(ids.filter((x) => x !== id))}
              />
            </Card>
          )}
        </Refreshing>
      )}
    </>
  )
}

function RosterTable({
  rows,
  scaleMax,
  onRemove,
}: {
  rows: { slot: string; entry: RankedProjection | undefined; move?: ReactNode; emptyNote?: string }[]
  scaleMax: number
  onRemove: (playerId: string) => void
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Roster players with this week's projections</caption>
        <thead>
          <tr className="border-line text-ink-muted border-b text-xs font-medium tracking-wide uppercase">
            <th scope="col" className="w-14 px-3 py-2 text-left">Slot</th>
            <th scope="col" className="px-3 py-2 text-left">Player</th>
            <th scope="col" className="hidden px-3 py-2 text-left sm:table-cell">Matchup</th>
            <th scope="col" className="hidden w-48 px-3 py-2 text-left lg:table-cell">Range</th>
            <th scope="col" className="px-3 py-2 text-right">Projection</th>
            <th scope="col" className="w-32 px-2 py-2"><span className="sr-only">Move</span></th>
            <th scope="col" className="w-10 px-2 py-2"><span className="sr-only">Remove</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ slot, entry, move, emptyNote }, index) => (
            <tr key={entry?.projection.player.player_id ?? `${slot}-${index}`} className="border-line border-b last:border-b-0">
              <td className="px-3 py-2">
                <Badge tone={slot === 'BN' ? 'neutral' : 'accent'}>{slot}</Badge>
              </td>
              {entry ? (
                <>
                  <td className="px-3 py-2">
                    <PlayerIdentity
                      player={entry.projection.player}
                      team={entry.projection.team}
                      size="sm"
                      subtitle={
                        <span className="inline-flex items-center gap-1.5">
                          {entry.projection.player.position} · {entry.projection.team}{' '}
                          {entry.projection.is_home ? 'vs' : '@'} {entry.projection.opponent}
                          <InjuryBadge injury={entry.projection.context.injury} />
                        </span>
                      }
                    />
                  </td>
                  <td className="hidden px-3 py-2 sm:table-cell">
                    <MatchupGradeChip
                      grade={entry.projection.matchup?.grade}
                      opponent={entry.projection.opponent}
                      fpAllowed={entry.projection.matchup?.fp_allowed_vs_position_l4}
                    />
                  </td>
                  <td className="hidden px-3 py-2 lg:table-cell">
                    <OutcomeRange
                      floor={entry.projection.prediction.points.floor}
                      median={entry.projection.prediction.points.median}
                      ceiling={entry.projection.prediction.points.ceiling}
                      scaleMax={scaleMax}
                    />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <ProjectionValue points={entry.projection.prediction.points} actualPoints={entry.projection.actual_points} />
                  </td>
                  <td className="px-2 py-2 text-right">{move}</td>
                  <td className="px-2 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => onRemove(entry.projection.player.player_id)}
                      aria-label={`Remove ${entry.projection.player.name}`}
                      className="text-ink-muted hover:text-ink rounded-sm p-1"
                    >
                      <Trash2 aria-hidden className="size-3.5" />
                    </button>
                  </td>
                </>
              ) : (
                <>
                  <td colSpan={4} className="text-ink-muted px-3 py-2 text-xs">
                    {emptyNote ?? 'Empty — no eligible player on this roster'}
                  </td>
                  <td className="px-2 py-2 text-right">{move}</td>
                  <td />
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * A one-shot "move here" menu: choosing an option acts immediately and the
 * menu returns to its placeholder. A native select, so it works by keyboard and
 * on a phone without a custom popover.
 */
function MoveSelect({
  label,
  placeholder,
  options,
  onChoose,
}: {
  label: string
  placeholder: string
  options: { value: string; label: string }[]
  onChoose: (value: string) => void
}) {
  return (
    <Select
      label={label}
      hideLabel
      size="sm"
      value=""
      className="ml-auto w-32"
      options={[{ value: '', label: placeholder, disabled: true }, ...options]}
      onChange={(event) => {
        if (event.target.value) onChoose(event.target.value)
      }}
    />
  )
}

/**
 * The lineup the manager chose, or null when there is no usable choice.
 *
 * A stored choice is re-checked against this week every time: a player who
 * left the roster, has no projection, is ruled out or no longer fits the slot
 * leaves that slot empty rather than being silently replaced. A choice written
 * for a different lineup format (a different slot count) is ignored outright.
 */
function chosenLineup(
  rows: LineupRow[],
  choice: string[] | null,
  available: RankedProjection[],
  slots: LineupSlot[],
): LineupRow[] | null {
  if (!choice || choice.length !== rows.length) return null
  const players = new Map(available.map((entry) => [entry.projection.player.player_id, entry.projection.player]))
  const used = new Set<string>()
  return rows.map((row, index) => {
    const player = players.get(choice[index] ?? '')
    if (!player || used.has(player.player_id)) return row
    if (!player.position || !eligiblePositions(slots, row.slot).includes(player.position)) return row
    used.add(player.player_id)
    return { ...row, player }
  })
}

function lineupPoints(rows: LineupRow[], byId: Map<string, RankedProjection>): number {
  return rows.reduce((sum, row) => {
    const entry = row.player ? byId.get(row.player.player_id) : undefined
    return sum + (headlinePoints(entry?.projection.prediction.points).value ?? 0)
  }, 0)
}

function lineupIds(rows: LineupRow[]): string[] {
  return rows.map((row) => row.player?.player_id ?? '')
}

function sameIds(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((id, index) => id === b[index])
}

function sameLineup(a: LineupRow[], b: LineupRow[]): boolean {
  return sameIds(lineupIds(a), lineupIds(b))
}
