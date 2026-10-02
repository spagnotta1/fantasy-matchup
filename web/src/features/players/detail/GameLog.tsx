import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterChoice, FilterToolbar } from '@/components/ui/FilterToolbar'
import { Select } from '@/components/ui/Select'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { InfoTip } from '@/components/ui/Tooltip'
import { EmptyState } from '@/components/feedback/States'
import { formatPoints, formatSigned } from '@/utils/format'
import { GameLogChart, type GameLogDatum } from './GameLogChart'
import { describeWindow, FULL_HISTORY, type GameWindow } from './gameWindow'
import type { HistoricalWeek, Trend } from '@/api/schemas'

type Datum = GameLogDatum

/**
 * Completed weeks: a column chart of what actually happened, plus the table.
 *
 * Deliberate choices, in the order they were made.
 *
 * **Form.** Discrete games, one measure, ordered in time — that is a column
 * chart. Not a line: a line implies continuity between games, and week 12 does
 * not flow into week 13 through intermediate values.
 *
 * **One series, one hue.** The obvious idea is to colour boom weeks green and
 * bust weeks red. That pair fails colour-vision separation outright (measured
 * ΔE 3.8 under deuteranopia — effectively the same colour), so the two
 * categories a reader most needs to tell apart would be the two they cannot.
 * Magnitude is already carried by column height, and the boom and bust lines
 * mark the thresholds for everyone. The single hue is the validated chart
 * series token.
 *
 * **The projection is a tick, not a second series.** Each game that had a
 * stored projection carries a short ink rule across its column at the number
 * that was published before kickoff. It is told apart from the column by shape
 * and not by hue, so there is still one colour to read, and "how did the
 * projections hold up" is answered by how far each column ends from its tick.
 * A game with no stored projection has no tick; nothing is drawn in its place.
 *
 * **A table, not only a chart.** The table is a real view, toggled rather than
 * hidden in a tooltip, so every value is reachable without hovering — which is
 * also what makes the figures available to a screen reader.
 *
 * **Which games.** The last 17, or one season. The choice is the page's, not
 * this card's, because the usage trend under it draws the same games column
 * for column. Earlier seasons are loaded only when asked for: the full history
 * is several times the size of the response the page opens with.
 */
export function GameLog({
  games,
  window,
  seasons,
  onWindowChange,
  trend,
  boomThreshold,
  bustThreshold,
  current,
  loaded,
  canLoadEarlier,
  onLoadEarlier,
  loadingEarlier,
}: {
  /** The games of the chosen window, oldest first. */
  games: HistoricalWeek[]
  window: GameWindow
  /** Seasons that can be chosen, newest first. */
  seasons: number[]
  onWindowChange: (window: GameWindow) => void
  trend: Trend
  boomThreshold: number | null | undefined
  bustThreshold: number | null | undefined
  /** The week the page is on, marked in the table when it has been played. */
  current?: { season: number; week: number } | null
  /** How many scored games are loaded in all. */
  loaded: number
  /** There may be games older than the ones loaded. */
  canLoadEarlier: boolean
  onLoadEarlier: () => void
  loadingEarlier: boolean
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')

  const data = useMemo<Datum[]>(
    () =>
      games.map((week, index, all) => ({
        key: `${week.season}-${week.week}`,
        // "W1" alone is ambiguous once the window crosses a season, so the
        // first column of each season carries its year.
        label:
          all[index - 1]?.season !== week.season ? `'${String(week.season).slice(-2)} W${week.week}` : `W${week.week}`,
        season: week.season,
        week: week.week,
        points: week.actual_points as number,
        opponent: week.opponent ?? '—',
        isHome: week.is_home ?? false,
        projected: week.projected_points ?? null,
      })),
    [games],
  )

  if (loaded === 0) {
    return (
      <Card>
        <CardHeader as="h2" title="Game log" />
        <EmptyState title="No completed games" description="We have no past games on record for this player." />
      </Card>
    )
  }

  return (
    // `clip`, not `hidden`: see the note on cards around tables in `DataTable`.
    <Card className="overflow-clip">
      <CardHeader
        as="h2"
        title="Game log"
        description={`Fantasy points scored, ${describeWindow(games, window)}.`}
        action={
          <>
            <ProvenanceBadge provenance="actual" />
            <FilterToolbar label="Choose games and a view" className="mb-0">
              <Select
                label="Games shown"
                hideLabel
                size="sm"
                className="w-40 shrink-0"
                value={String(window)}
                onChange={(event) =>
                  onWindowChange(event.target.value === 'recent' ? 'recent' : Number(event.target.value))
                }
                options={[
                  { value: 'recent', label: 'Last 17 games' },
                  ...seasons.map((season) => ({ value: String(season), label: `${season} season` })),
                ]}
              />
              <FilterChoice<'chart' | 'table'>
                label="Game log view"
                value={view}
                onChange={setView}
                options={[
                  { value: 'chart', label: 'Chart' },
                  { value: 'table', label: 'Table' },
                ]}
              />
            </FilterToolbar>
          </>
        }
      />

      {view === 'chart' ? (
        <CardBody>
          <GameLogChart data={data} boomThreshold={boomThreshold ?? null} bustThreshold={bustThreshold ?? null} />
        </CardBody>
      ) : (
        <GameLogTable games={games} current={current} />
      )}

      <CardBody className="border-line flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t py-3">
        <p className="text-ink-muted text-detail" aria-live="polite">
          {canLoadEarlier
            ? `The last ${loaded} games are loaded.`
            : loaded >= FULL_HISTORY
              ? `The last ${loaded} games are loaded, which is as far back as this page goes.`
              : `All ${loaded} games on record are loaded.`}
        </p>
        {canLoadEarlier && (
          <Button size="sm" variant="secondary" onClick={onLoadEarlier} loading={loadingEarlier}>
            Load earlier seasons
          </Button>
        )}
      </CardBody>

      <CardBody className="border-line border-t">
        <TrendSummary trend={trend} />
      </CardBody>
    </Card>
  )
}

const percent = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`

/** Points scored minus the projection made for that game, or null where there was none. */
function difference(week: HistoricalWeek): number | null {
  if (week.actual_points == null || week.projected_points == null) return null
  return week.actual_points - week.projected_points
}

/**
 * The table's columns. The week comes first and is the row's header, so it is
 * what stays in view when a phone scrolls the rest sideways. A table is kept
 * at every width here, unlike the tables of players: these rows are compared
 * down their columns — points beside projection beside snaps, week over week —
 * and the frozen week is all the context a row needs.
 */
const COLUMNS: DataTableColumn<HistoricalWeek>[] = [
  {
    id: 'week',
    header: 'Week',
    rowHeader: true,
    className: 'text-ink-secondary whitespace-nowrap',
    cell: (week) => (
      <>
        {week.season} W{week.week}
      </>
    ),
  },
  {
    id: 'opponent',
    header: 'Opp',
    className: 'text-ink-secondary whitespace-nowrap',
    cell: (week) => (
      <>
        {week.is_home ? '' : '@'}
        {week.opponent ?? '—'}
      </>
    ),
  },
  { id: 'points', header: 'Points', numeric: true, className: 'font-semibold', cell: (week) => formatPoints(week.actual_points) },
  {
    id: 'projected',
    header: 'Projected',
    numeric: true,
    className: 'text-ink-secondary',
    tip: 'The projection that was published before the game, as stored at the time. A dash means none was stored for that week.',
    cell: (week) => formatPoints(week.projected_points),
  },
  {
    id: 'difference',
    header: 'Difference',
    numeric: true,
    tip: 'Points scored minus the projection. Positive means the player beat it.',
    cell: (week) => {
      const value = difference(week)
      if (value === null) return <span className="text-ink-muted">—</span>
      return (
        // The sign says the direction; the colour only repeats it.
        <span className={value >= 0 ? 'text-positive-text' : 'text-negative-text'}>{formatSigned(value)}</span>
      )
    },
  },
  { id: 'snaps', header: 'Snaps', numeric: true, className: 'text-ink-secondary', cell: (week) => percent(week.snap_pct) },
  { id: 'targets', header: 'Tgt', numeric: true, className: 'text-ink-secondary', cell: (week) => formatPoints(week.targets, 0) },
  { id: 'carries', header: 'Car', numeric: true, className: 'text-ink-secondary', cell: (week) => formatPoints(week.carries, 0) },
]

function GameLogTable({
  games,
  current,
}: {
  games: HistoricalWeek[]
  current?: { season: number; week: number } | null
}) {
  // Newest first: the game a reader came for is the last one played.
  const rows = useMemo(() => [...games].reverse(), [games])
  return (
    <DataTable
      caption="Completed games, newest first, with the projection made for each"
      columns={COLUMNS}
      rows={rows}
      rowKey={(week) => `${week.season}-${week.week}`}
      isSelected={(week) => current?.season === week.season && current.week === week.week}
      density="compact"
      minWidth="38rem"
      freezeFirstColumn
      // A season of rows in the middle of a long page: the page scrolls, and
      // the table is not a second scroller inside it.
      stickyHeader={false}
    />
  )
}

/**
 * Form and accuracy.
 *
 * `graded_games` is given prominence because it is the number that decides
 * whether the accuracy figures mean anything. A mean absolute error computed
 * over one stored projection is not a track record, and presenting it without
 * that count would imply it is.
 *
 * The figures are over every loaded game, not over the games the chart is
 * showing, and each says how many that is.
 */
function TrendSummary({ trend }: { trend: Trend }) {
  const accuracyIsThin = trend.graded_games < 4

  return (
    <>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <dt className="text-ink-muted text-caption font-medium tracking-wide uppercase">Average</dt>
          <dd className="tnum text-ink mt-0.5 text-lg font-semibold">{formatPoints(trend.mean_points)}</dd>
          <dd className="text-ink-muted text-chip">over {trend.games} games</dd>
        </div>
        <div>
          <dt className="text-ink-muted text-caption font-medium tracking-wide uppercase">Swing</dt>
          <dd className="tnum text-ink mt-0.5 text-lg font-semibold">{formatPoints(trend.standard_deviation)}</dd>
          <dd className="text-ink-muted text-chip">typical week-to-week swing</dd>
        </div>
        <div>
          <dt className="text-ink-muted flex items-center gap-1 text-caption font-medium tracking-wide uppercase">
            Avg error
            <InfoTip
              label="About average error"
              content="On average, how far our projection was from what the player actually scored. Only counts weeks where we had a projection."
            />
          </dt>
          <dd className="tnum text-ink mt-0.5 text-lg font-semibold">
            {trend.graded_games > 0 ? formatPoints(trend.mean_absolute_error) : '—'}
          </dd>
          <dd className="text-ink-muted text-chip">
            {trend.graded_games} graded {trend.graded_games === 1 ? 'week' : 'weeks'}
          </dd>
        </div>
        <div>
          <dt className="text-ink-muted text-caption font-medium tracking-wide uppercase">Lean</dt>
          <dd className="tnum text-ink mt-0.5 text-lg font-semibold">
            {trend.graded_games > 0 ? formatSigned(trend.bias) : '—'}
          </dd>
          <dd className="text-ink-muted text-chip">positive = we projected too high</dd>
        </div>
      </dl>

      {accuracyIsThin && trend.graded_games > 0 && (
        <p className="text-ink-muted mt-3 text-detail leading-relaxed">
          This is based on only {trend.graded_games} {trend.graded_games === 1 ? 'projection' : 'projections'} — too few
          to say how accurate we are for this player. Treat it as a rough hint, not a track record.
        </p>
      )}
    </>
  )
}
