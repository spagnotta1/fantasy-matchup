import { useMemo, type ReactNode } from 'react'
import { ArrowDownRight, ArrowUpRight, TrendingUp } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterChoice, FilterToolbar } from '@/components/ui/FilterToolbar'
import { PageHeader } from '@/components/ui/PageHeader'
import { RowList, RowListItem, RowListLine, RowListRows, RowListTitle } from '@/components/ui/RowList'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { PlayerCell } from '@/components/domain/PlayerCell'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { ProjectionValue } from '@/components/domain/ProjectionValue'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { useSlate } from '@/app/slate-context'
import { boardNotices, useBoard } from '@/hooks/useProjections'
import { useRowList } from '@/hooks/useRowList'
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

const pct = (value: number) => `${Math.round(value * 100)}%`

/** The change, signed. The arrow and the sign say the direction; the colour only repeats it. */
function Change({ row }: { row: Movement }) {
  const up = row.change > 0
  return (
    <span
      className={cn('inline-flex items-center gap-0.5 font-semibold', up ? 'text-positive-text' : 'text-negative-text')}
    >
      {up ? <ArrowUpRight aria-hidden className="size-3.5" /> : <ArrowDownRight aria-hidden className="size-3.5" />}
      {up ? '+' : '−'}
      {Math.abs(Math.round(row.change * 100))}
      <span className="sr-only"> percentage points</span>
    </span>
  )
}

/** What the bar draws, in a sentence: the header's tip in the table, a line above the rows in the list. */
const BAR_KEY = 'The lighter bar is the four-game average; the darker mark is the most recent game.'

/** The four-game average as a bar and the last game as a mark on it, with both printed either side. */
function ShareBar({ row, className }: { row: Movement; className?: string }) {
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <span className="tnum text-ink-muted text-detail w-9 text-right">{pct(row.average)}</span>
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
      <span className="tnum text-ink text-detail w-9 font-medium">{pct(row.last)}</span>
    </div>
  )
}

/**
 * The table's columns.
 *
 * The player comes first and is the row's header, so on a phone — where the
 * table scrolls inside its own frame — it is the column that stays, and the
 * change is the first thing beside it. Nothing is dropped at narrow widths:
 * the average-to-last bar used to disappear below 768px.
 *
 * No column sorts. The order *is* the page: "Rising" and "Falling" in the
 * toolbar choose which end of the change column the 25 rows are taken from.
 *
 * On a phone the rows are a list instead (`Movers`): the change beside the
 * name, the bar on a line of its own and as wide as the row, the projection
 * under it. Scrolling sideways showed the change and nothing that explains it.
 */
const COLUMNS: DataTableColumn<Movement>[] = [
  {
    id: 'player',
    header: 'Player',
    rowHeader: true,
    className: 'max-sm:max-w-44',
    cell: ({ entry: { projection } }, index) => (
      <span className="flex items-center gap-2">
        {/* The place in this list, not a rank anyone publishes. */}
        <span className="text-ink-muted tnum text-detail w-5 shrink-0">{index + 1}</span>
        <PlayerCell
          player={projection.player}
          meta={
            <>
              {projection.player.position} · {projection.team}
            </>
          }
        >
          <InjuryBadge injury={projection.context.injury} />
        </PlayerCell>
      </span>
    ),
  },
  {
    id: 'change',
    header: 'Change, pct. pts',
    numeric: true,
    cell: (row) => <Change row={row} />,
  },
  {
    id: 'bar',
    header: 'Avg → last',
    tip: BAR_KEY,
    // The bar takes the table's slack: a longer bar is an easier one to read.
    className: 'w-[38%]',
    cell: (row) => <ShareBar row={row} className="min-w-52" />,
  },
  {
    id: 'projection',
    header: 'Projection',
    numeric: true,
    className: 'whitespace-nowrap',
    cell: ({ entry: { projection } }) => (
      <ProjectionValue points={projection.prediction.points} actualPoints={projection.actual_points} />
    ),
  },
]

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

  const { rows, measurable } = useMemo(() => {
    const list: Movement[] = []
    // Whether anyone has a share to compare at all, whatever the filters say:
    // it is what tells "no data yet" from "nothing matches".
    let measurable = 0
    for (const entry of board.data?.data ?? []) {
      const move = movement(entry, metric)
      if (move) measurable += 1
      if (state.position && entry.projection.player.position !== state.position) continue
      if (metric === 'target' && entry.projection.player.position === 'QB') continue
      // A quarterback's snap share is all or nothing: 35% to 100% means a new
      // starter, not a growing role. Measured on the 2026 week 3 board, nine of
      // the top 25 "rising" rows were backups who started one game, crowding
      // out the RB/WR/TE role changes this list exists to find. They stay one
      // tap away on the QB tab, where a change of starter is the question.
      if (metric === 'snap' && !state.position && entry.projection.player.position === 'QB') continue
      if (move && (direction === 'up' ? move.change > 0 : move.change < 0)) list.push(move)
    }
    list.sort((a, b) => (direction === 'up' ? b.change - a.change : a.change - b.change))
    return { rows: list.slice(0, SHOWN), measurable }
  }, [board.data, metric, direction, state.position])

  const metricLabel = metric === 'snap' ? 'Snap share' : 'Target share'
  const moving = direction === 'up' ? 'rising' : 'falling'

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
        {board.data && <NoticeList notices={boardNotices(board.data.meta, { showsGrades: false })} />}
      </div>

      <FilterToolbar label="Choose a share, a direction and a position">
        <FilterChoice
          label="Share"
          value={metric}
          onChange={(value) => setState({ metric: value })}
          options={[
            { value: 'snap', label: 'Snap share' },
            { value: 'target', label: 'Target share' },
          ]}
        />
        <FilterChoice
          label="Direction"
          value={direction}
          onChange={(value) => setState({ direction: value })}
          options={[
            { value: 'up', label: 'Rising', icon: <ArrowUpRight className="size-3.5" /> },
            { value: 'down', label: 'Falling', icon: <ArrowDownRight className="size-3.5" /> },
          ]}
        />
        <FilterChoice
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
      </FilterToolbar>

      {/* `clip`, not `hidden`: a hidden overflow would make the card a scroll
          container and the column header would stick to it. */}
      <Card className="overflow-clip">
        <CardHeader
          as="h2"
          title={`${metricLabel}: ${moving}`}
          description={`Last game compared with the four-game average, in percentage points. Players averaging under ${Math.round(MIN_SHARE[metric] * 100)}% are left out.${
            metric === 'snap' && !state.position
              ? ' Quarterbacks are listed under QB: their snap share jumps only when the starter changes.'
              : ''
          }`}
          action={<ProvenanceBadge provenance="derived" />}
        />
        {board.isError ? (
          <ErrorState error={board.error} onRetry={() => void board.refetch()} />
        ) : (
          <Refreshing active={board.isPlaceholderData}>
            <Movers
              caption={`${metricLabel} ${direction === 'up' ? 'risers' : 'fallers'}, last game against four-game average, largest change first`}
              rows={rows}
              loading={board.isPending}
              empty={
                measurable === 0 ? (
                  <EmptyState
                    icon={<TrendingUp aria-hidden className="size-5" />}
                    title="No movement to show"
                    description="No player has enough recent games to compare yet. This is normal early in the season, or before this week's data is in."
                  />
                ) : (
                  <EmptyState
                    icon={<TrendingUp aria-hidden className="size-5" />}
                    title={`No ${state.position || 'player'}'s ${metricLabel.toLowerCase()} is ${moving}`}
                    description={
                      state.position
                        ? 'Nobody at this position moved that way in their last game. Try the other direction, or every position.'
                        : 'Nobody moved that way in their last game. Try the other direction.'
                    }
                    action={
                      state.position ? (
                        <Button size="sm" variant="secondary" onClick={() => setState({ position: '' })}>
                          Show every position
                        </Button>
                      ) : undefined
                    }
                  />
                )
              }
            />
            {rows.length > 0 && (
              <CardBody className="border-line text-ink-muted border-t py-3 text-detail">
                These are the same recent games the projection is built from. The change shown here is
                for your information and does not adjust any projection.
              </CardBody>
            )}
          </Refreshing>
        )}
      </Card>
    </>
  )
}

/**
 * The rows: a table where there is room for its columns, a list where there is
 * not. Loading and the empty states are the table's at every width — a header
 * over placeholder rows, or over the reason there are none.
 */
function Movers({
  caption,
  rows,
  loading,
  empty,
}: {
  caption: string
  rows: Movement[]
  loading: boolean
  empty: ReactNode
}) {
  const [frameRef, asList] = useRowList<HTMLDivElement>()

  return (
    <div ref={frameRef}>
      {asList && !loading && rows.length > 0 ? (
        // The leading slot holds the place in the list and the headshot.
        <RowList value="Change, pct. pts" note={BAR_KEY} lead="3.25rem">
          <RowListRows aria-label={caption}>
            {rows.map((row, index) => {
              const { projection } = row.entry
              return (
                <RowListItem
                  key={projection.player.player_id}
                  to={`/players/${encodeURIComponent(projection.player.player_id)}`}
                >
                  <span className="flex items-center gap-2">
                    {/* The place in this list, not a rank anyone publishes. */}
                    <span className="text-ink-muted tnum text-detail w-5 shrink-0">{index + 1}</span>
                    <PlayerAvatar player={projection.player} size="xs" />
                  </span>
                  <RowListTitle
                    name={projection.player.name}
                    meta={
                      <>
                        {projection.player.position} · {projection.team}
                      </>
                    }
                  >
                    <InjuryBadge injury={projection.context.injury} />
                  </RowListTitle>
                  <span className="justify-self-end">
                    <Change row={row} />
                  </span>
                  <RowListLine>
                    <ShareBar row={row} className="min-w-0 flex-1" />
                  </RowListLine>
                  <RowListLine>
                    <span className="text-ink-muted text-chip">Projection</span>
                    <ProjectionValue
                      size="sm"
                      points={projection.prediction.points}
                      actualPoints={projection.actual_points}
                    />
                  </RowListLine>
                </RowListItem>
              )
            })}
          </RowListRows>
        </RowList>
      ) : (
        <DataTable
          caption={caption}
          columns={COLUMNS}
          rows={rows}
          rowKey={(row) => row.entry.projection.player.player_id}
          loading={loading}
          loadingRows={10}
          minWidth="44rem"
          freezeFirstColumn
          empty={empty}
        />
      )}
    </div>
  )
}
