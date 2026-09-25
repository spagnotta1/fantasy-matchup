import { memo, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Radio } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Card, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { Skeleton, SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { ShowMoreRows } from '@/components/domain/BoardBudget'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { TeamLink } from '@/components/domain/TeamLink'
import { useSlate } from '@/app/slate-context'
import { LIVE_REFRESH_MS, useLive } from '@/hooks/useInsights'
import { useRenderBudget } from '@/hooks/useRenderBudget'
import { useRememberedRoster } from '@/hooks/useRoster'
import { useUrlState } from '@/hooks/useUrlState'
import { cn } from '@/utils/cn'
import { formatPoints, formatSigned } from '@/utils/format'
import type { LiveGame, LivePlayer } from '@/api/schemas'

const DEFAULT_STATE = { position: '', who: 'all' }

/** A signed count, with a real minus sign for negative yardage. */
const n = (value: number | undefined) => {
  const v = value ?? 0
  return v < 0 ? `−${Math.abs(v)}` : String(v)
}

/** A compact, labelled stat line: "16 car, 52 yds · 6/8 rec, 61 yds, 1 TD". */
function statLine(c: Record<string, number>): string {
  const parts: string[] = []
  const td = (count: number | undefined) => (count ? `, ${count} TD` : '')
  if (c.passing_yards || c.passing_tds || c.passing_interceptions) {
    parts.push(`${n(c.passing_yards)} pass yds${td(c.passing_tds)}${c.passing_interceptions ? `, ${c.passing_interceptions} INT` : ''}`)
  }
  if (c.carries) parts.push(`${c.carries} car, ${n(c.rushing_yards)} yds${td(c.rushing_tds)}`)
  if (c.targets || c.receptions) {
    parts.push(`${c.receptions ?? 0}/${c.targets ?? 0} rec, ${n(c.receiving_yards)} yds${td(c.receiving_tds)}`)
  }
  if (c.special_teams_tds) parts.push(`${c.special_teams_tds} return TD`)
  if (c.fumbles_lost_total) parts.push(`${c.fumbles_lost_total} fum lost`)
  return parts.join(' · ') || 'No offensive stats yet'
}

/**
 * The week as it happens.
 *
 * Every started player's points so far, from ESPN's in-game box score scored
 * with this product's rules, beside the projection published before kickoff.
 * The two are kept apart on purpose: the projection is never updated by the
 * live number, and the difference between them is shown only once a game is
 * final — mid-game, "behind his projection" mostly measures how much of the
 * game is left.
 *
 * Unofficial, and labelled so: two-point conversions and stat corrections are
 * missing until the official line is loaded. Refreshes once a minute while a
 * game is in progress, and not at all otherwise.
 */
export default function LivePage() {
  const slate = useSlate()
  const live = useLive()
  const roster = useRememberedRoster()
  const [state, setState] = useUrlState(DEFAULT_STATE)
  const data = live.data?.data

  const games = useMemo(() => new Map((data?.games ?? []).map((g) => [g.event_id, g])), [data])
  const players = useMemo(
    () =>
      (data?.players ?? []).filter(
        (p) =>
          (!state.position || p.position === state.position) &&
          (state.who !== 'mine' || roster.has(p.player_id)),
      ),
    [data, state.position, state.who, roster],
  )
  const inProgress = (data?.games ?? []).some((g) => g.state === 'in')
  // A full Sunday is ~300 players; draw the top of it and reveal the rest on
  // request, like the boards (see `useRenderBudget`).
  const budget = useRenderBudget(players.length)
  const visible = players.slice(0, budget.shown)

  return (
    <>
      <PageHeader
        title="Live"
        question={`How is week ${slate.week ?? '—'} going, against what was projected?`}
        action={
          inProgress ? (
            <Badge tone="negative" icon={<Radio className="size-3" />}>
              Live · updates every {LIVE_REFRESH_MS / 1000}s
            </Badge>
          ) : undefined
        }
      />

      {live.data && <NoticeList notices={live.data.meta.notices} className="mb-4" />}

      {live.isPending ? (
        <div className="space-y-6">
          <Skeleton className="h-24 rounded-[var(--radius-card)]" />
          <Card>
            <SkeletonTable rows={10} columns={4} />
          </Card>
        </div>
      ) : live.isError ? (
        <Card>
          <ErrorState error={live.error} onRetry={() => void live.refetch()} />
        </Card>
      ) : (
        <Refreshing active={live.isPlaceholderData}>
          <div className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
            {(data?.games ?? []).map((game) => (
              <GameTile key={game.event_id} game={game} />
            ))}
          </div>

          <div className="mb-4 flex flex-wrap items-center gap-2">
            <SegmentedControl
              label="Position"
              value={state.position}
              onChange={(value) => setState({ position: value })}
              options={[{ value: '', label: 'All' }, ...['QB', 'RB', 'WR', 'TE'].map((p) => ({ value: p, label: p }))]}
            />
            <SegmentedControl
              label="Players"
              value={state.who}
              onChange={(value) => setState({ who: value })}
              options={[
                { value: 'all', label: 'Everyone' },
                { value: 'mine', label: `My team${roster.size ? ` (${roster.size})` : ''}` },
              ]}
            />
            {state.who === 'mine' && roster.size === 0 && (
              <Link to="/my-team" className="text-accent-text text-xs hover:underline">
                Add your roster first
              </Link>
            )}
          </div>

          <Card className="overflow-hidden">
            <CardHeader
              as="h2"
              title="Points so far"
              description="Unofficial points scored so far, highest first, next to each player's projection."
              action={
                <span className="flex items-center gap-1.5">
                  <ProvenanceBadge provenance="actual" />
                  <ProvenanceBadge provenance="model" />
                </span>
              }
            />
            {players.length === 0 ? (
              <EmptyState
                icon={<Radio aria-hidden className="size-5" />}
                title={data?.games.length ? 'No points yet' : 'No games found for this week'}
                description={
                  data?.games.length
                    ? 'Nobody matching these filters has scored yet. Points appear once games kick off.'
                    : 'We could not find any games for the selected week.'
                }
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <caption className="sr-only">Unofficial live fantasy points with published projections</caption>
                  <thead>
                    <tr className="border-line text-ink-muted border-b text-xs font-medium tracking-wide uppercase">
                      <th scope="col" className="px-3 py-2 text-left">Player</th>
                      <th scope="col" className="hidden px-3 py-2 text-left md:table-cell">Stat line</th>
                      <th scope="col" className="px-3 py-2 text-right">Live</th>
                      <th scope="col" className="px-3 py-2 text-right">Projected</th>
                      <th scope="col" className="hidden px-3 py-2 text-right sm:table-cell">Final vs proj.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((player) => (
                      <LiveRow key={player.player_id} player={player} game={games.get(player.event_id)} mine={roster.has(player.player_id)} />
                    ))}
                  </tbody>
                </table>
                <ShowMoreRows budget={budget} />
              </div>
            )}
          </Card>
        </Refreshing>
      )}
    </>
  )
}

function GameTile({ game }: { game: LiveGame }) {
  const live = game.state === 'in'
  return (
    <div
      className={cn(
        'bg-surface rounded-[var(--radius-control)] border px-3 py-2 text-xs',
        live ? 'border-negative/40' : 'border-line',
      )}
    >
      {[
        { team: game.away, score: game.away_score },
        { team: game.home, score: game.home_score },
      ].map(({ team, score }) => (
        <div key={team} className="flex items-center justify-between">
          <TeamLink team={team} className="text-ink font-semibold" />
          <span className="tnum text-ink font-semibold">{game.state === 'pre' ? '' : (score ?? '—')}</span>
        </div>
      ))}
      <p className={cn('mt-0.5 truncate', live ? 'text-negative-text font-medium' : 'text-ink-muted')}>
        {game.detail ?? game.state}
      </p>
    </div>
  )
}

const LiveRow = memo(function LiveRow({
  player,
  game,
  mine,
}: {
  player: LivePlayer
  game: LiveGame | undefined
  mine: boolean
}) {
  const final = game?.state === 'post'
  const difference = final && player.projected != null ? player.live_points - player.projected : null
  return (
    <tr className={cn('border-line border-b last:border-b-0', mine && 'bg-accent-soft/40')}>
      <td className="px-3 py-2">
        <span className="flex items-center gap-3">
          <PlayerAvatar player={{ name: player.name, headshot_url: player.headshot_url }} size="sm" />
          <span className="min-w-0">
            <Link to={`/players/${encodeURIComponent(player.player_id)}`} className="text-ink hover:text-accent-text block truncate font-medium">
              {player.name}
            </Link>
            <span className="text-ink-muted block text-xs">
              {player.position} · {player.team}
              {game ? ` · ${game.state === 'in' ? game.detail : final ? 'Final' : 'Not started'}` : ''}
              {mine && ' · My team'}
            </span>
          </span>
        </span>
      </td>
      <td className="text-ink-secondary hidden px-3 py-2 text-xs md:table-cell">{statLine(player.components)}</td>
      <td className="tnum text-ink px-3 py-2 text-right text-base font-semibold">{formatPoints(player.live_points)}</td>
      <td className="tnum text-ink-secondary px-3 py-2 text-right">
        {formatPoints(player.projected)}
        {player.floor != null && player.ceiling != null && (
          <span className="text-ink-muted block text-[0.6875rem]">
            {formatPoints(player.floor)}–{formatPoints(player.ceiling)}
          </span>
        )}
      </td>
      <td
        className={cn(
          'tnum hidden px-3 py-2 text-right sm:table-cell',
          difference == null ? 'text-ink-muted' : difference >= 0 ? 'text-positive-text' : 'text-negative-text',
        )}
      >
        {difference == null ? '—' : formatSigned(difference)}
      </td>
    </tr>
  )
})
