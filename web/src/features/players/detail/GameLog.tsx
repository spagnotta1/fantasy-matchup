import { useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { InfoTip } from '@/components/ui/Tooltip'
import { EmptyState } from '@/components/feedback/States'
import { formatPoints, formatSigned } from '@/utils/format'
import type { HistoricalWeek, Trend } from '@/api/schemas'

/** Games in the chart. Beyond this the columns are too thin to read on a laptop. */
const CHART_GAMES = 16

interface Datum {
  key: string
  label: string
  season: number
  week: number
  points: number
  opponent: string
  isHome: boolean
  projected: number | null
}

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
 * **A table, not only a chart.** The table is a real view, toggled rather than
 * hidden in a tooltip, so every value is reachable without hovering — which is
 * also what makes the figures available to a screen reader.
 */
export function GameLog({
  history,
  trend,
  boomThreshold,
  bustThreshold,
}: {
  history: HistoricalWeek[]
  trend: Trend
  boomThreshold: number | null | undefined
  bustThreshold: number | null | undefined
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')

  // A time axis reads oldest to newest. Sorted explicitly rather than trusting
  // the API's newest-first order and reversing it — a season boundary or a
  // duplicate (season, week) row from an upstream join would otherwise land
  // out of sequence with no defense on this side.
  const chronological = useMemo(
    () => [...history].sort((a, b) => a.season - b.season || a.week - b.week),
    [history],
  )

  const data = useMemo<Datum[]>(
    () =>
      chronological
        .filter((week) => week.actual_points !== null && week.actual_points !== undefined)
        .slice(-CHART_GAMES)
        .map((week) => ({
          key: `${week.season}-${week.week}`,
          label: `W${week.week}`,
          season: week.season,
          week: week.week,
          points: week.actual_points as number,
          opponent: week.opponent ?? '—',
          isHome: week.is_home ?? false,
          projected: week.projected_points ?? null,
        })),
    [chronological],
  )

  const seasons = useMemo(() => [...new Set(data.map((d) => d.season))].sort(), [data])

  if (history.length === 0) {
    return (
      <Card>
        <CardHeader as="h2" title="Game log" />
        <EmptyState
          title="No completed games"
          description="This player has no recorded weeks in the seasons covered by the warehouse."
        />
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader
        as="h2"
        title="Game log"
        description={
          seasons.length > 1
            ? `Fantasy points scored, last ${data.length} games across ${seasons.join(' and ')}.`
            : `Fantasy points scored, last ${data.length} games of ${seasons[0] ?? ''}.`
        }
        action={
          <div className="flex items-center gap-2">
            <ProvenanceBadge provenance="actual" />
            <SegmentedControl<'chart' | 'table'>
              label="Game log view"
              size="sm"
              value={view}
              onChange={setView}
              options={[
                { value: 'chart', label: 'Chart' },
                { value: 'table', label: 'Table' },
              ]}
            />
          </div>
        }
      />

      <CardBody>
        {view === 'chart' ? (
          <GameLogChart
            data={data}
            boomThreshold={boomThreshold ?? null}
            bustThreshold={bustThreshold ?? null}
          />
        ) : (
          <GameLogTable history={history} />
        )}

        <TrendSummary trend={trend} />
      </CardBody>
    </Card>
  )
}

function GameLogChart({
  data,
  boomThreshold,
  bustThreshold,
}: {
  data: Datum[]
  boomThreshold: number | null
  bustThreshold: number | null
}) {
  if (data.length === 0) {
    return <p className="text-ink-muted text-sm">No scored games to chart.</p>
  }

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid
            vertical={false}
            stroke="var(--color-chart-grid)"
            strokeWidth={1}
          />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={{ stroke: 'var(--color-chart-axis)' }}
            tick={{ fill: 'var(--color-ink-muted)', fontSize: 11 }}
            interval="preserveStartEnd"
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={44}
            tick={{ fill: 'var(--color-ink-muted)', fontSize: 11 }}
          />

          {/* Thresholds the API supplied, so "boom" and "bust" mean the same
              thing here as they do in the probabilities above. */}
          {boomThreshold !== null && (
            <ReferenceLine
              y={boomThreshold}
              stroke="var(--color-chart-reference)"
              strokeDasharray="4 4"
              label={{
                value: `Boom ${formatPoints(boomThreshold)}`,
                position: 'insideTopRight',
                fill: 'var(--color-ink-muted)',
                fontSize: 10,
              }}
            />
          )}
          {bustThreshold !== null && (
            <ReferenceLine
              y={bustThreshold}
              stroke="var(--color-chart-reference)"
              strokeDasharray="4 4"
              label={{
                value: `Bust ${formatPoints(bustThreshold)}`,
                position: 'insideBottomRight',
                fill: 'var(--color-ink-muted)',
                fontSize: 10,
              }}
            />
          )}
          {/* No reference line for the player's average. It lands within a
              point of the boom threshold for most startable players, and two
              near-coincident horizontal rules read as one mislabelled line.
              The average is stated numerically directly beneath the chart. */}

          <RechartsTooltip
            cursor={{ fill: 'var(--color-surface-hover)' }}
            content={<ChartTooltip />}
          />

          <Bar dataKey="points" maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {data.map((datum) => (
              <Cell key={datum.key} fill="var(--color-chart-series)" />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: Datum }[] }) {
  const datum = payload?.[0]?.payload
  if (!active || !datum) return null

  return (
    <div className="bg-surface-raised border-line rounded-[var(--radius-control)] border px-3 py-2 shadow-overlay">
      <p className="text-ink text-xs font-semibold">
        {datum.season} Week {datum.week}
      </p>
      <p className="text-ink-muted text-xs">
        {datum.isHome ? 'vs' : 'at'} {datum.opponent}
      </p>
      <p className="text-ink tnum mt-1 text-sm font-medium">{formatPoints(datum.points)} pts</p>
      {datum.projected !== null && (
        <p className="text-ink-muted tnum text-xs">
          Projected {formatPoints(datum.projected)} · {formatSigned(datum.points - datum.projected)}
        </p>
      )}
    </div>
  )
}

function GameLogTable({ history }: { history: HistoricalWeek[] }) {
  return (
    <div className="max-h-80 overflow-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">Completed games, newest first</caption>
        <thead className="bg-surface sticky top-0">
          <tr className="border-line border-b">
            {['Week', 'Opp', 'Points', 'Projected', 'Snaps', 'Tgt', 'Car'].map((label, index) => (
              <th
                key={label}
                scope="col"
                className={`text-ink-muted px-2 py-2 text-xs font-medium tracking-wide uppercase ${index < 2 ? 'text-left' : 'text-right'}`}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {history.map((week) => (
            <tr key={`${week.season}-${week.week}`} className="border-line border-b last:border-b-0">
              <td className="text-ink-secondary px-2 py-1.5 text-xs">
                {week.season} W{week.week}
              </td>
              <td className="text-ink-secondary px-2 py-1.5 text-xs">
                {week.is_home ? '' : '@'}
                {week.opponent ?? '—'}
              </td>
              <td className="tnum text-ink px-2 py-1.5 text-right font-medium">
                {formatPoints(week.actual_points)}
              </td>
              <td className="tnum text-ink-muted px-2 py-1.5 text-right">
                {formatPoints(week.projected_points)}
              </td>
              <td className="tnum text-ink-muted px-2 py-1.5 text-right">
                {week.snap_pct === null || week.snap_pct === undefined
                  ? '—'
                  : `${Math.round(week.snap_pct * 100)}%`}
              </td>
              <td className="tnum text-ink-muted px-2 py-1.5 text-right">
                {formatPoints(week.targets, 0)}
              </td>
              <td className="tnum text-ink-muted px-2 py-1.5 text-right">
                {formatPoints(week.carries, 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Form and accuracy.
 *
 * `graded_games` is given prominence because it is the number that decides
 * whether the accuracy figures mean anything. A mean absolute error computed
 * over one stored projection is not a track record, and presenting it without
 * that count would imply it is.
 */
function TrendSummary({ trend }: { trend: Trend }) {
  const accuracyIsThin = trend.graded_games < 4

  return (
    <div className="border-line mt-5 border-t pt-4">
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <dt className="text-ink-muted text-xs font-medium tracking-wide uppercase">Average</dt>
          <dd className="tnum text-ink mt-0.5 text-lg font-semibold">
            {formatPoints(trend.mean_points)}
          </dd>
          <p className="text-ink-muted text-[0.6875rem]">over {trend.games} games</p>
        </div>
        <div>
          <dt className="text-ink-muted text-xs font-medium tracking-wide uppercase">Volatility</dt>
          <dd className="tnum text-ink mt-0.5 text-lg font-semibold">
            {formatPoints(trend.standard_deviation)}
          </dd>
          <p className="text-ink-muted text-[0.6875rem]">standard deviation</p>
        </div>
        <div>
          <dt className="text-ink-muted flex items-center gap-1 text-xs font-medium tracking-wide uppercase">
            Avg error
            <InfoTip
              label="About average error"
              content="Mean absolute error between the projection stored at the time and what the player actually scored. Only weeks that carried a stored projection are counted."
            />
          </dt>
          <dd className="tnum text-ink mt-0.5 text-lg font-semibold">
            {trend.graded_games > 0 ? formatPoints(trend.mean_absolute_error) : '—'}
          </dd>
          <p className="text-ink-muted text-[0.6875rem]">
            {trend.graded_games} graded {trend.graded_games === 1 ? 'week' : 'weeks'}
          </p>
        </div>
        <div>
          <dt className="text-ink-muted text-xs font-medium tracking-wide uppercase">Bias</dt>
          <dd className="tnum text-ink mt-0.5 text-lg font-semibold">
            {trend.graded_games > 0 ? formatSigned(trend.bias) : '—'}
          </dd>
          <p className="text-ink-muted text-[0.6875rem]">projected minus actual</p>
        </div>
      </dl>

      {accuracyIsThin && trend.graded_games > 0 && (
        <p className="text-ink-muted mt-3 text-xs leading-relaxed">
          Accuracy is measured over {trend.graded_games} stored{' '}
          {trend.graded_games === 1 ? 'projection' : 'projections'}, which is far too few to
          describe how the model performs for this player. Read it as an anecdote, not a track
          record.
        </p>
      )}
    </div>
  )
}
