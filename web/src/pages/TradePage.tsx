import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowLeftRight, X } from 'lucide-react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { InfoTip } from '@/components/ui/Tooltip'
import { EmptyState, NoticeList, Refreshing } from '@/components/feedback/States'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { PlayerSearchField } from '@/components/domain/PlayerSearchField'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { useSlate } from '@/app/slate-context'
import { useScheduleStrength } from '@/hooks/useInsights'
import { useBoard, usePlayers } from '@/hooks/useProjections'
import { cn } from '@/utils/cn'
import { formatPoints, formatSigned, headlinePoints } from '@/utils/format'
import { toneForScore } from '@/utils/grades'
import type { Player, RankedProjection, TeamSchedule } from '@/api/schemas'

const SIDE_LIMIT = 5
const FANTASY_POSITIONS = ['QB', 'RB', 'WR', 'TE'] as const

type Side = 'give' | 'get'

interface Valued {
  id: string
  player: Player | undefined
  entry: RankedProjection | undefined
  weekly: number | null
  games: number | null
  restOfSeason: number | null
  schedule: number | null
}

function parseIds(value: string | null): string[] {
  return value ? [...new Set(value.split(',').filter(Boolean))].slice(0, SIDE_LIMIT) : []
}

/**
 * Trade helper: two sides, set against each other on numbers this product can
 * stand behind.
 *
 * There is no rest-of-season projection in this system, and this page does not
 * invent one. What it can say is arithmetic on published numbers:
 *
 * - **This week** — each player's published projection (`model`).
 * - **At this week's rate** — that projection times the games his team has left
 *   (`derived`). The same construction the draft pool uses, stated as what it
 *   is: it assumes he plays every remaining game in the role he has now. No
 *   injury, no role change, no regression is in it.
 * - **Schedule** — the mean current-form grade of his remaining opponents at
 *   his position (`derived`), carried forward, not forecast.
 *
 * It sets the two sides side by side and states the difference. It does not
 * declare a winner: roster fit, depth and league settings decide trades, and
 * none of them are in the data.
 */
export default function TradePage() {
  const slate = useSlate()
  const [params, setParams] = useSearchParams()
  const give = parseIds(params.get('give'))
  const get = parseIds(params.get('get'))
  const board = useBoard()
  const identities = usePlayers([...give, ...get])

  // One schedule read per position — cached, and shared with the Matchups grid.
  const schedules = {
    QB: useScheduleStrength('QB'),
    RB: useScheduleStrength('RB'),
    WR: useScheduleStrength('WR'),
    TE: useScheduleStrength('TE'),
  }

  const byId = useMemo(() => {
    const map = new Map<string, RankedProjection>()
    for (const entry of board.data?.data ?? []) map.set(entry.projection.player.player_id, entry)
    return map
  }, [board.data])

  const setSide = (side: Side, ids: string[]) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        if (ids.length) next.set(side, ids.join(','))
        else next.delete(side)
        return next
      },
      { replace: true },
    )

  const value = (id: string, index: number): Valued => {
    const entry = byId.get(id)
    const player = entry?.projection.player ?? identities[index]?.data
    const position = (player?.position ?? '') as (typeof FANTASY_POSITIONS)[number]
    const team = entry?.projection.team ?? player?.team ?? null
    const row: TeamSchedule | undefined = schedules[position]?.data?.data.teams.find((t) => t.team === team)
    const weekly = headlinePoints(entry?.projection.prediction.points).value
    const games = row ? row.cells.filter((c) => c.opponent).length : null
    return {
      id,
      player,
      entry,
      weekly,
      games,
      restOfSeason: weekly !== null && games !== null ? weekly * games : null,
      schedule: row?.mean_score ?? null,
    }
  }

  const giveRows = give.map((id, i) => value(id, i))
  const getRows = get.map((id, i) => value(id, give.length + i))
  const sum = (rows: Valued[], key: 'weekly' | 'restOfSeason') =>
    rows.reduce((total, row) => total + (row[key] ?? 0), 0)

  const weeklyGap = sum(getRows, 'weekly') - sum(giveRows, 'weekly')
  const seasonGap = sum(getRows, 'restOfSeason') - sum(giveRows, 'restOfSeason')
  const missing = [...giveRows, ...getRows].filter((r) => r.weekly === null)
  const ready = give.length > 0 && get.length > 0

  return (
    <>
      <PageHeader
        title="Trade helper"
        question="What does this trade change — this week and for the rest of the season?"
      />

      <NoticeList
        className="mb-6"
        notices={[
          '“At this week’s rate” is each player’s projection this week multiplied by the games their team has left. It assumes they play every game in their current role — no injuries, no role change — so read it as a rate, not a forecast.',
          'The schedule grade shows how each remaining opponent is defending the position right now. It is not a forecast of how those defences will play later.',
        ]}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <SideCard
          title="You give"
          side="give"
          rows={giveRows}
          allIds={[...give, ...get]}
          onChange={(ids) => setSide('give', ids)}
          ids={give}
        />
        <SideCard
          title="You get"
          side="get"
          rows={getRows}
          allIds={[...give, ...get]}
          onChange={(ids) => setSide('get', ids)}
          ids={get}
        />
      </div>

      <Card className="mt-6">
        <CardHeader
          as="h2"
          title="The difference"
          description={`What you get minus what you give, from week ${slate.week ?? '—'}.`}
          action={<ProvenanceBadge provenance="derived" />}
        />
        {!ready ? (
          <EmptyState
            icon={<ArrowLeftRight aria-hidden className="size-5" />}
            title="Add a player to each side"
            description="Search for the players on both sides of the trade to compare them."
          />
        ) : (
          <Refreshing active={board.isPlaceholderData}>
            <CardBody className="grid gap-4 sm:grid-cols-2">
              <Gap label="This week" value={weeklyGap} unit="projected points" />
              <Gap label="At this week’s rate, rest of season" value={seasonGap} unit="points" />
            </CardBody>
            {missing.length > 0 && (
              <CardBody className="border-line text-caution-text border-t py-3 text-xs">
                {missing.map((r) => r.player?.name ?? r.id).join(', ')} {missing.length === 1 ? 'has' : 'have'} no
                projection this week (usually a bye week or an inactive listing), so{' '}
                {missing.length === 1 ? 'counts' : 'count'} as zero above.
              </CardBody>
            )}
          </Refreshing>
        )}
      </Card>
    </>
  )
}

function Gap({ label, value, unit }: { label: string; value: number; unit: string }) {
  return (
    <div>
      <p className="text-ink-muted text-xs font-medium tracking-wide uppercase">{label}</p>
      <p
        className={cn(
          'tnum mt-1 text-2xl font-semibold tracking-tight',
          value > 0 ? 'text-positive-text' : value < 0 ? 'text-negative-text' : 'text-ink',
        )}
      >
        {formatSigned(value)}
      </p>
      <p className="text-ink-muted text-xs">{unit}, for the side you get</p>
    </div>
  )
}

const SCORE_CLASSES = {
  positive: 'bg-positive-soft text-positive-text',
  info: 'bg-info-soft text-info-text',
  neutral: 'bg-surface-sunken text-ink-secondary',
  caution: 'bg-caution-soft text-caution-text',
  negative: 'bg-negative-soft text-negative-text',
  accent: 'bg-accent-soft text-accent-text',
} as const

function SideCard({
  title,
  side,
  rows,
  ids,
  allIds,
  onChange,
}: {
  title: string
  side: Side
  rows: Valued[]
  ids: string[]
  allIds: string[]
  onChange: (ids: string[]) => void
}) {
  return (
    <Card className="overflow-hidden">
      <CardHeader as="h2" title={title} />
      <CardBody className="border-line border-b">
        <PlayerSearchField
          label={`Add a player you ${side}`}
          size="sm"
          positions={[...FANTASY_POSITIONS]}
          excludeIds={allIds}
          disabled={ids.length >= SIDE_LIMIT}
          hint={ids.length >= SIDE_LIMIT ? `Up to ${SIDE_LIMIT} players a side.` : undefined}
          onSelect={(player) => onChange([...ids, player.player_id])}
        />
      </CardBody>
      {rows.length === 0 ? (
        <p className="text-ink-muted px-4 py-6 text-center text-sm">No players yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">{title}</caption>
            <thead>
              <tr className="border-line text-ink-muted border-b text-xs font-medium tracking-wide uppercase">
                <th scope="col" className="px-3 py-2 text-left">Player</th>
                <th scope="col" className="px-3 py-2 text-right">Week</th>
                <th scope="col" className="px-3 py-2 text-right">
                  <span className="inline-flex items-center gap-1">
                    Rate × games
                    <InfoTip
                      label="About rate times games"
                      content="This week's projection times the games their team has left. Assumes they play every game in their current role."
                    />
                  </span>
                </th>
                <th scope="col" className="hidden px-3 py-2 text-center sm:table-cell">Schedule</th>
                <th scope="col" className="w-8 px-2 py-2"><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-line border-b last:border-b-0">
                  <td className="px-3 py-2">
                    {row.player ? (
                      <PlayerIdentity
                        player={row.player}
                        team={row.entry?.projection.team}
                        size="sm"
                        subtitle={
                          <span className="inline-flex items-center gap-1.5">
                            {row.player.position} · {row.entry?.projection.team ?? row.player.team ?? '—'}
                            <InjuryBadge injury={row.entry?.projection.context.injury} />
                          </span>
                        }
                      />
                    ) : (
                      <span className="text-ink-muted text-sm">Loading…</span>
                    )}
                  </td>
                  <td className="tnum text-ink px-3 py-2 text-right font-medium">{formatPoints(row.weekly)}</td>
                  <td className="tnum text-ink-secondary px-3 py-2 text-right">
                    {formatPoints(row.restOfSeason, 0)}
                    {row.games !== null && <span className="text-ink-muted block text-[0.6875rem]">{row.games} games</span>}
                  </td>
                  <td className="hidden px-3 py-2 text-center sm:table-cell">
                    {row.schedule === null ? (
                      <span className="text-ink-muted text-xs">—</span>
                    ) : (
                      <span className={cn('tnum inline-block min-w-8 rounded px-1.5 py-0.5 text-xs font-semibold', SCORE_CLASSES[toneForScore(row.schedule)])}>
                        {Math.round(row.schedule)}
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => onChange(ids.filter((id) => id !== row.id))}
                      aria-label={`Remove ${row.player?.name ?? 'player'}`}
                      className="text-ink-muted hover:text-ink rounded-sm p-1"
                    >
                      <X aria-hidden className="size-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
