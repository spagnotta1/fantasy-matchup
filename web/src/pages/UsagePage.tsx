import { memo, useMemo } from 'react'
import { ArrowDownRight, ArrowUpRight, TrendingUp } from 'lucide-react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { InfoTip } from '@/components/ui/Tooltip'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { ProjectionValue } from '@/components/domain/ProjectionValue'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { useSlate } from '@/app/slate-context'
import { boardNotices, useBoard } from '@/hooks/useProjections'
import { useUrlState } from '@/hooks/useUrlState'
import { cn } from '@/utils/cn'
import type { RankedProjection } from '@/api/schemas'

type Metric = 'snap' | 'target'
type Direction = 'up' | 'down'

/** Rows shown per list. Enough to scan a week's movement; the rest is noise. */
const SHOWN = 25

/** Below this 4-game share a "change" is a backup's garbage-time snaps. */
const MIN_SHARE: Record<Metric, number> = { snap: 0.2, target: 0.05 }

interface Movement {
  entry: RankedProjection
  average: number
  last: number
  change: number
}

/**
 * Last game against the four-game window, for one share.
 *
 * The API's `*_trend` is the four-game average **minus** the most recent game
 * (see `features/usage.py`), so a positive trend is a *shrinking* role. It is
 * negated here, once, so that everything on this page reads the natural way
 * round: a positive change means the last game ran above the average.
 */
function movement(entry: RankedProjection, metric: Metric): Movement | null {
  const usage = entry.projection.usage
  const average = metric === 'snap' ? usage.snap_pct_l4 : usage.target_share_l4
  const trend = metric === 'snap' ? usage.snap_pct_trend : usage.target_share_trend
  if (average === null || average === undefined || trend === null || trend === undefined) return null
  if (average < MIN_SHARE[metric]) return null
  if ((usage.games_in_window ?? 0) < 2) return null
  const change = -trend
  return { entry, average, last: average + change, change }
}

const DEFAULT_STATE = { metric: 'snap', direction: 'up', position: '' }

/**
 * Whose role is moving.
 *
 * The in-season equivalent of a "trending" list, built from the one thing that
 * moves before the points do: share of snaps and of targets. It compares a
 * player's most recent game with his four-game average — the same window the
 * projection is built from — so a riser here is a role the window has only
 * partly caught up with, not a claim that the projection is wrong.
 *
 * One game is a small sample: a blowout, an injury mid-game or a bye-week
 * return all move it. The page says so rather than ranking noise with
 * confidence.
 */
export default function UsagePage() {
  const slate = useSlate()
  const board = useBoard()
  const [state, setState] = useUrlState(DEFAULT_STATE)
  const metric = state.metric as Metric
  const direction = state.direction as Direction

  const rows = useMemo(() => {
    const list: Movement[] = []
    for (const entry of board.data?.data ?? []) {
      if (state.position && entry.projection.player.position !== state.position) continue
      if (metric === 'target' && entry.projection.player.position === 'QB') continue
      const move = movement(entry, metric)
      if (move && (direction === 'up' ? move.change > 0 : move.change < 0)) list.push(move)
    }
    list.sort((a, b) => (direction === 'up' ? b.change - a.change : a.change - b.change))
    return list.slice(0, SHOWN)
  }, [board.data, metric, direction, state.position])

  const metricLabel = metric === 'snap' ? 'Snap share' : 'Target share'

  return (
    <>
      <PageHeader
        title="Usage trends"
        question={`Whose role grew or shrank going into week ${slate.week ?? '—'}?`}
      />

      <div className="mb-4 space-y-3">
        <NoticeList
          notices={[
            'Each row compares a player’s most recent game with their four-game average, which is what the projection is built from. One game can be misleading: a blowout, an in-game injury or a return from a bye can all skew it.',
          ]}
        />
        {board.data && <NoticeList notices={boardNotices(board.data.meta)} />}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SegmentedControl
          label="Share"
          value={metric}
          onChange={(value) => setState({ metric: value })}
          options={[
            { value: 'snap', label: 'Snap share' },
            { value: 'target', label: 'Target share' },
          ]}
        />
        <SegmentedControl
          label="Direction"
          value={direction}
          onChange={(value) => setState({ direction: value })}
          options={[
            { value: 'up', label: 'Rising', icon: <ArrowUpRight className="size-3.5" /> },
            { value: 'down', label: 'Falling', icon: <ArrowDownRight className="size-3.5" /> },
          ]}
        />
        <SegmentedControl
          label="Position"
          value={state.position}
          onChange={(value) => setState({ position: value })}
          options={[
            { value: '', label: 'All' },
            ...(metric === 'target' ? ['RB', 'WR', 'TE'] : ['QB', 'RB', 'WR', 'TE']).map((p) => ({
              value: p,
              label: p,
            })),
          ]}
        />
      </div>

      <Card className="overflow-hidden">
        <CardHeader
          as="h2"
          title={`${metricLabel}: ${direction === 'up' ? 'rising' : 'falling'}`}
          description={`Last game compared with the four-game average, in percentage points. Players averaging under ${Math.round(MIN_SHARE[metric] * 100)}% are left out.`}
          action={<ProvenanceBadge provenance="derived" />}
        />
        {board.isPending ? (
          <SkeletonTable rows={10} columns={5} />
        ) : board.isError ? (
          <ErrorState error={board.error} onRetry={() => void board.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<TrendingUp aria-hidden className="size-5" />}
            title="No movement to show"
            description="No player has enough recent games to compare yet. This is normal early in the season, or before this week's data is in."
          />
        ) : (
          <Refreshing active={board.isPlaceholderData}>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <caption className="sr-only">
                  {metricLabel} {direction === 'up' ? 'risers' : 'fallers'}, last game against four-game
                  average
                </caption>
                <thead>
                  <tr className="border-line text-ink-muted border-b text-xs font-medium tracking-wide uppercase">
                    <th scope="col" className="w-10 px-3 py-2 text-left">#</th>
                    <th scope="col" className="px-3 py-2 text-left">Player</th>
                    <th scope="col" className="hidden w-56 px-3 py-2 text-left md:table-cell">
                      <span className="inline-flex items-center gap-1">
                        Avg → last
                        <InfoTip
                          label="About the bar"
                          content="The lighter bar is the four-game average; the darker mark is the most recent game."
                        />
                      </span>
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">Change, pct. pts</th>
                    <th scope="col" className="px-3 py-2 text-right">Projection</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <MovementRow key={row.entry.projection.player.player_id} row={row} rank={index + 1} />
                  ))}
                </tbody>
              </table>
            </div>
            <CardBody className="border-line text-ink-muted border-t py-3 text-xs">
              These are the same recent games the projection is built from. The change shown here is
              for your information and does not adjust any projection.
            </CardBody>
          </Refreshing>
        )}
      </Card>
    </>
  )
}

const pct = (value: number) => `${Math.round(value * 100)}%`

const MovementRow = memo(function MovementRow({ row, rank }: { row: Movement; rank: number }) {
  const { projection } = row.entry
  const up = row.change > 0
  return (
    <tr className="border-line border-b last:border-b-0">
      <td className="text-ink-muted tnum px-3 py-2 text-xs">{rank}</td>
      <td className="px-3 py-2">
        <PlayerIdentity
          player={projection.player}
          team={projection.team}
          size="sm"
          subtitle={
            <span className="inline-flex items-center gap-1.5">
              {projection.player.position} · {projection.team}
              <InjuryBadge injury={projection.context.injury} />
            </span>
          }
        />
      </td>
      <td className="hidden px-3 py-2 md:table-cell">
        <div className="flex items-center gap-2">
          <span className="tnum text-ink-muted w-9 text-right text-xs">{pct(row.average)}</span>
          <div
            className="bg-surface-sunken relative h-2 flex-1 rounded-full"
            role="img"
            aria-label={`Four-game average ${pct(row.average)}, last game ${pct(row.last)}`}
          >
            <div
              className="bg-accent/35 absolute inset-y-0 left-0 rounded-full"
              style={{ width: `${Math.min(100, row.average * 100)}%` }}
            />
            <div
              className="bg-accent absolute inset-y-[-2px] w-1 rounded-full"
              style={{ left: `calc(${Math.min(100, Math.max(0, row.last * 100))}% - 2px)` }}
            />
          </div>
          <span className="tnum text-ink w-9 text-xs font-medium">{pct(row.last)}</span>
        </div>
      </td>
      <td className={cn('tnum px-3 py-2 text-right font-semibold', up ? 'text-positive-text' : 'text-negative-text')}>
        <span className="inline-flex items-center gap-0.5">
          {up ? <ArrowUpRight aria-hidden className="size-3.5" /> : <ArrowDownRight aria-hidden className="size-3.5" />}
          {up ? '+' : '−'}
          {Math.abs(Math.round(row.change * 100))}
          <span className="sr-only"> percentage points</span>
        </span>
      </td>
      <td className="px-3 py-2 text-right">
        <ProjectionValue points={projection.prediction.points} actualPoints={projection.actual_points} />
      </td>
    </tr>
  )
})
