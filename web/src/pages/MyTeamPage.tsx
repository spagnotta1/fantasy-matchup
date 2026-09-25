import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Copy, Shuffle, Trash2, UserRound } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { PlayerSearchField } from '@/components/domain/PlayerSearchField'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { useSlate } from '@/app/slate-context'
import { autofillLineup, emptyLineup } from '@/features/simulations/lineupFormat'
import { encodeLineup, TEAM_A_PARAM } from '@/features/simulations/shareLink'
import { useBoard, usePlayers } from '@/hooks/useProjections'
import { useRoster } from '@/hooks/useRoster'
import { useLineupCatalog } from '@/hooks/useSimulation'
import { boardCeiling } from '@/utils/board'
import { formatPoints, headlinePoints } from '@/utils/format'
import type { Player, RankedProjection } from '@/api/schemas'

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
 * Two kinds of player are kept out of the lineup, and both are named rather
 * than dropped: anyone ruled out (the designation is a hard caveat; he keeps
 * his projection, he just does not play) and anyone with no projection this
 * week (a bye, an inactive listing, or a run that does not cover him).
 */
export default function MyTeamPage() {
  const slate = useSlate()
  const [ids, setIds] = useRoster()
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

  const lineup = useMemo(
    () =>
      catalog.isPending ? [] : autofillLineup(emptyLineup(catalog.format), available, catalog.slots, []),
    [catalog.isPending, catalog.format, catalog.slots, available],
  )
  const starters = new Set(lineup.map((row) => row.player?.player_id).filter(Boolean))
  const bench = available.filter((e) => !starters.has(e.projection.player.player_id))
  const total = lineup.reduce((sum, row) => {
    const entry = row.player ? byId.get(row.player.player_id) : undefined
    return sum + (headlinePoints(entry?.projection.prediction.points).value ?? 0)
  }, 0)
  const openSlots = lineup.filter((row) => !row.player).length
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
              <Button size="sm" variant="ghost" onClick={() => setIds([])}>
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
            description="Search for your players above. This page projects them for the week, fills the highest-projected lineup and flags anyone ruled out or not playing."
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
                    <span className="text-ink-muted text-xs">No projection this week — a bye, an inactive listing, or not covered by the run</span>
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
              title={`Highest-projected lineup — ${formatPoints(total)} pts`}
              description={`${catalog.format.label}. Filled slot by slot in the board's projected order — a starting point, not an optimiser. Inside a tier the order is close to noise.`}
              action={
                <div className="flex items-center gap-2">
                  <ProvenanceBadge provenance="model" />
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
              rows={lineup.map((row) => ({ slot: row.slot, entry: row.player ? byId.get(row.player.player_id) : undefined }))}
              scaleMax={scaleMax}
              onRemove={(id) => setIds(ids.filter((x) => x !== id))}
            />
            {openSlots > 0 && (
              <CardBody className="border-line text-caution-text border-t py-3 text-xs">
                {openSlots} {openSlots === 1 ? 'slot has' : 'slots have'} no eligible projected player on this roster.
              </CardBody>
            )}
          </Card>

          {bench.length > 0 && (
            <Card className="overflow-hidden">
              <CardHeader as="h2" title="Bench" description="Projected, and outscored at their slot by a starter above." />
              <RosterTable
                rows={bench.map((entry) => ({ slot: 'BN', entry }))}
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
  rows: { slot: string; entry: RankedProjection | undefined }[]
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
            <th scope="col" className="w-10 px-2 py-2"><span className="sr-only">Remove</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ slot, entry }, index) => (
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
                <td colSpan={5} className="text-ink-muted px-3 py-2 text-xs">
                  Empty — no eligible player on this roster
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
