import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Target } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Select } from '@/components/ui/Select'
import { Skeleton, SkeletonTable } from '@/components/ui/Skeleton'
import { StatCard } from '@/components/ui/StatCard'
import { InfoTip } from '@/components/ui/Tooltip'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { useSlate } from '@/app/slate-context'
import { useTrackRecord } from '@/hooks/useInsights'
import { useUrlState } from '@/hooks/useUrlState'
import { cn } from '@/utils/cn'
import { formatPercent, formatPoints, formatScoringProfile, formatSigned } from '@/utils/format'
import type { Accuracy, Outcome, TrackRecord } from '@/api/schemas'

const DEFAULT_STATE = { season: '', week: '' }

/**
 * The model's record, in public.
 *
 * Every published run's stored projections, graded against what the player
 * actually scored. The headline is interval coverage — how often the outcome
 * landed inside the range the product showed — because the range is the claim
 * this product makes, and a range that is right 80% of the time when it says
 * 80% is the thing a manager can plan around. The point-estimate error is
 * shown beside it, not instead of it.
 *
 * Two numbers must never be confused here, and the page keeps them apart: the
 * *live* record, computed now from stored runs, and the *validation* record the
 * frozen model was promoted on. They are different measurements over different
 * sets; the second is printed beside the first as a reference, never
 * substituted for it.
 */
export default function TrackRecordPage() {
  const slate = useSlate()
  const [state, setState] = useUrlState(DEFAULT_STATE)
  const season = state.season ? Number(state.season) : null
  const week = state.week ? Number(state.week) : null
  const { data, isPending, isError, error, refetch, isPlaceholderData } = useTrackRecord(season, week)
  const record = data?.data

  return (
    <>
      <PageHeader
        title="Track record"
        question="When we said a score would land in a range 80% of the time, did it?"
      />

      {isPending ? (
        <div className="space-y-6">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className="h-28 rounded-[var(--radius-card)]" />
            ))}
          </div>
          <Card>
            <SkeletonTable rows={5} columns={6} />
          </Card>
        </div>
      ) : isError ? (
        <Card>
          <ErrorState error={error} onRetry={() => void refetch()} />
        </Card>
      ) : !record?.overall ? (
        <Card>
          <EmptyState
            icon={<Target aria-hidden className="size-5" />}
            title="Nothing graded yet"
            description="None of these projections has a final result yet. This fills in as games are played."
          />
        </Card>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-end gap-3">
            <Select
              label="Season"
              size="sm"
              value={state.season}
              onChange={(event) => setState({ season: event.target.value, week: '' })}
              className="w-40"
              options={[
                { value: '', label: 'All seasons' },
                ...[...record.seasons].reverse().map((s) => ({ value: String(s), label: String(s) })),
              ]}
            />
            <p className="text-ink-muted pb-1.5 text-xs">
              {formatScoringProfile(record.scoring_profile)} scoring (set at the top of the page).
              Actual points use the same scoring, so it is a fair comparison.
            </p>
          </div>

          <NoticeList notices={data.meta.notices} className="mb-6" />

          <Refreshing active={isPlaceholderData}>
            <Headline record={record} />
            <div className="mt-6 grid gap-6 xl:grid-cols-2">
              <PositionTable rows={record.by_position} />
              <BandTable rows={record.by_band} />
            </div>
            {season === null ? (
              <SeasonTable rows={record.by_season} className="mt-6" />
            ) : (
              <WeeklyStrip rows={record.weekly} season={season} className="mt-6" />
            )}
            <ScorecardCard
              record={record}
              onWeek={(s, w) => setState({ season: String(s), week: String(w) })}
              currentSlateWeek={slate.week}
            />
          </Refreshing>
        </>
      )}
    </>
  )
}

function Headline({ record }: { record: TrackRecord }) {
  const overall = record.overall as Accuracy
  const v = record.validation
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard
        label="Inside the 80% range"
        value={formatPercent(overall.coverage_80, 1)}
        emphasis="primary"
        detail={`Target ${formatPercent(v.nominal_80)}. When the model was first tested: ${formatPercent(v.coverage_80, 1)}.`}
        badge={<ProvenanceBadge provenance="derived" />}
      />
      <StatCard
        label="Inside the 50% range"
        value={formatPercent(overall.coverage_50, 1)}
        detail={`Target ${formatPercent(v.nominal_50)}. When the model was first tested: ${formatPercent(v.coverage_50, 1)}.`}
      />
      <StatCard
        label="Average miss"
        value={formatPoints(overall.mean_absolute_error)}
        unit="pts"
        detail={`How far off a typical projection was, across ${overall.graded.toLocaleString()} player-games.`}
      />
      <StatCard
        label="Lean"
        value={formatSigned(overall.bias, 2)}
        unit="pts"
        detail="Projected minus actual. Positive means we projected too high on average."
      />
    </div>
  )
}

/** Coverage as a bar against its nominal rate, so "close to 80%" is visible. */
function CoverageBar({ value, nominal }: { value: number | null | undefined; nominal: number }) {
  if (value === null || value === undefined) return <span className="text-ink-muted">—</span>
  const off = Math.abs(value - nominal)
  return (
    <span className="inline-flex w-full items-center gap-2">
      <span
        className="bg-surface-sunken relative h-1.5 w-20 rounded-full"
        role="img"
        aria-label={`${formatPercent(value, 1)} against a nominal ${formatPercent(nominal)}`}
      >
        <span
          className={cn('absolute inset-y-0 left-0 rounded-full', off <= 0.02 ? 'bg-accent' : 'bg-caution')}
          style={{ width: `${Math.min(100, value * 100)}%` }}
        />
        <span className="bg-ink absolute -inset-y-0.5 w-px" style={{ left: `${nominal * 100}%` }} />
      </span>
      <span className="tnum text-ink text-xs">{formatPercent(value, 1)}</span>
    </span>
  )
}

function Rate({ predicted, observed }: { predicted: number | null | undefined; observed: number | null | undefined }) {
  return (
    <span className="tnum text-xs whitespace-nowrap">
      <span className="text-ink-secondary">{formatPercent(predicted, 1)}</span>
      <span className="text-ink-muted"> → </span>
      <span className="text-ink font-medium">{formatPercent(observed, 1)}</span>
    </span>
  )
}

function PositionTable({ rows }: { rows: Accuracy[] }) {
  return (
    <Card className="min-w-0 overflow-hidden">
      <CardHeader
        as="h2"
        title="By position"
        description="How often scores landed inside the range (the tick is the target), and whether boom and bust chances matched how often they happened."
      />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">Accuracy by position</caption>
          <thead>
            <tr className="border-line text-ink-muted border-b text-xs font-medium tracking-wide uppercase">
              <th scope="col" className="px-3 py-2 text-left">Pos</th>
              <th scope="col" className="px-3 py-2 text-left">80% range</th>
              <th scope="col" className="hidden px-3 py-2 text-left sm:table-cell">50% range</th>
              <th scope="col" className="px-3 py-2 text-right">Miss</th>
              <th scope="col" className="hidden px-3 py-2 text-right md:table-cell">
                <span className="inline-flex items-center gap-1">
                  Boom
                  <InfoTip
                    label="About boom calibration"
                    content="The average predicted chance of a boom week, then how often it actually happened. If the two are close, the boom chances can be trusted."
                  />
                </span>
              </th>
              <th scope="col" className="hidden px-3 py-2 text-right md:table-cell">Bust</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.position} className="border-line border-b last:border-b-0">
                <th scope="row" className="text-ink px-3 py-2 text-left font-semibold">
                  {row.position}
                  <span className="text-ink-muted ml-1.5 text-xs font-normal">{row.graded.toLocaleString()}</span>
                </th>
                <td className="px-3 py-2">
                  <CoverageBar value={row.coverage_80} nominal={0.8} />
                </td>
                <td className="hidden px-3 py-2 sm:table-cell">
                  <CoverageBar value={row.coverage_50} nominal={0.5} />
                </td>
                <td className="tnum text-ink px-3 py-2 text-right">{formatPoints(row.mean_absolute_error)}</td>
                <td className="hidden px-3 py-2 text-right md:table-cell">
                  <Rate predicted={row.boom_predicted} observed={row.boom_observed} />
                </td>
                <td className="hidden px-3 py-2 text-right md:table-cell">
                  <Rate predicted={row.bust_predicted} observed={row.bust_observed} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/**
 * Bias by projection band — where "conditionally biased" would show.
 *
 * A diverging bar around zero: right of centre, projections in that band ran
 * high; left, low. The frozen model's own worst band is printed as the scale's
 * reference so a reader can tell drift from noise.
 */
function BandTable({ rows }: { rows: Accuracy[] }) {
  const span = Math.max(1, ...rows.map((r) => Math.abs(r.bias ?? 0)))
  return (
    <Card className="min-w-0 overflow-hidden">
      <CardHeader
        as="h2"
        title="Too high or too low?"
        description="Projected minus actual, grouped by how many points we projected. Right of centre means we projected too high; left, too low."
      />
      <ul className="divide-line divide-y">
        {rows.map((row) => {
          const bias = row.bias ?? 0
          const width = (Math.abs(bias) / span) * 50
          const label =
            row.band_high === null || row.band_high === undefined
              ? `${formatPoints(row.band_low, 0)}+`
              : `${formatPoints(row.band_low, 0)}–${formatPoints(row.band_high, 0)}`
          return (
            <li key={label} className="flex items-center gap-3 px-4 py-2.5">
              <span className="tnum text-ink w-14 text-xs font-medium">{label} pts</span>
              <span
                className="bg-surface-sunken relative h-2 flex-1 rounded-full"
                role="img"
                aria-label={`Bias ${formatSigned(bias, 2)} points over ${row.graded} player-weeks`}
              >
                <span className="bg-line-strong absolute -inset-y-0.5 left-1/2 w-px" />
                <span
                  className={cn('absolute inset-y-0 rounded-full', bias >= 0 ? 'bg-caution' : 'bg-info')}
                  style={bias >= 0 ? { left: '50%', width: `${width}%` } : { right: '50%', width: `${width}%` }}
                />
              </span>
              <span className="tnum text-ink w-12 text-right text-xs">{formatSigned(bias, 2)}</span>
              <span className="text-ink-muted hidden w-16 text-right text-[0.6875rem] sm:inline">
                {row.thin ? 'thin' : `${row.graded.toLocaleString()}`}
              </span>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

function SeasonTable({ rows, className }: { rows: Accuracy[]; className?: string }) {
  return (
    <Card className={cn('overflow-hidden', className)}>
      <CardHeader as="h2" title="Season by season" description="Pick a season above to see it week by week." />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">Accuracy by season</caption>
          <thead>
            <tr className="border-line text-ink-muted border-b text-xs font-medium tracking-wide uppercase">
              <th scope="col" className="px-3 py-2 text-left">Season</th>
              <th scope="col" className="px-3 py-2 text-left">80% range</th>
              <th scope="col" className="hidden px-3 py-2 text-left sm:table-cell">50% range</th>
              <th scope="col" className="px-3 py-2 text-right">Miss</th>
              <th scope="col" className="px-3 py-2 text-right">Bias</th>
              <th scope="col" className="hidden px-3 py-2 text-right md:table-cell">Graded</th>
            </tr>
          </thead>
          <tbody>
            {[...rows].reverse().map((row) => (
              <tr key={row.season} className="border-line border-b last:border-b-0">
                <th scope="row" className="text-ink px-3 py-2 text-left font-semibold">
                  {row.season}
                  {row.thin && (
                    <Badge tone="caution" className="ml-2">
                      Thin
                    </Badge>
                  )}
                </th>
                <td className="px-3 py-2">
                  <CoverageBar value={row.coverage_80} nominal={0.8} />
                </td>
                <td className="hidden px-3 py-2 sm:table-cell">
                  <CoverageBar value={row.coverage_50} nominal={0.5} />
                </td>
                <td className="tnum text-ink px-3 py-2 text-right">{formatPoints(row.mean_absolute_error)}</td>
                <td className="tnum text-ink px-3 py-2 text-right">{formatSigned(row.bias, 2)}</td>
                <td className="tnum text-ink-muted hidden px-3 py-2 text-right md:table-cell">
                  {row.graded.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/**
 * One season's weekly coverage as a dot strip against the nominal 80%.
 *
 * A dot per week rather than a line: week 7 does not flow into week 8. A single
 * week holds ~350 player-weeks, so scatter of a few points around 80% is
 * sampling noise; the reference line is what to read against. The values are
 * repeated in a visually hidden table for screen readers.
 */
function WeeklyStrip({ rows, season, className }: { rows: Accuracy[]; season: number; className?: string }) {
  const weeks = rows.filter((r) => r.season === season && r.coverage_80 != null)
  const width = 640
  const height = 160
  const pad = { top: 12, right: 12, bottom: 24, left: 36 }
  const lo = 0.6
  const hi = 1.0
  const x = (i: number) => pad.left + ((width - pad.left - pad.right) * (i + 0.5)) / Math.max(weeks.length, 1)
  const y = (v: number) => pad.top + ((hi - Math.max(lo, Math.min(hi, v))) / (hi - lo)) * (height - pad.top - pad.bottom)

  return (
    <Card className={cn('overflow-hidden', className)}>
      <CardHeader
        as="h2"
        title={`${season}, week by week`}
        description="How often scores landed inside the 80% range each week. The line marks the 80% target."
        action={<ProvenanceBadge provenance="derived" />}
      />
      <CardBody>
        {weeks.length === 0 ? (
          <p className="text-ink-muted text-sm">No graded weeks in this season yet.</p>
        ) : (
          <>
            <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" aria-hidden>
              {[0.6, 0.7, 0.8, 0.9, 1].map((tick) => (
                <g key={tick}>
                  <line
                    x1={pad.left}
                    x2={width - pad.right}
                    y1={y(tick)}
                    y2={y(tick)}
                    stroke={tick === 0.8 ? 'var(--color-chart-reference)' : 'var(--color-chart-grid)'}
                    strokeDasharray={tick === 0.8 ? '4 4' : undefined}
                  />
                  <text x={pad.left - 6} y={y(tick)} textAnchor="end" dominantBaseline="middle" fontSize={10} fill="var(--color-ink-muted)">
                    {Math.round(tick * 100)}%
                  </text>
                </g>
              ))}
              {weeks.map((row, i) => (
                <g key={row.week}>
                  <circle cx={x(i)} cy={y(row.coverage_80 as number)} r={4.5} fill="var(--color-chart-series)" stroke="var(--color-surface)" strokeWidth={2}>
                    <title>{`Week ${row.week}: ${formatPercent(row.coverage_80, 1)} of ${row.graded}`}</title>
                  </circle>
                  <text x={x(i)} y={height - 6} textAnchor="middle" fontSize={10} fill="var(--color-ink-muted)">
                    {row.week}
                  </text>
                </g>
              ))}
            </svg>
            <table className="sr-only">
              <caption>{season} weekly coverage of the 80% range</caption>
              <tbody>
                {weeks.map((row) => (
                  <tr key={row.week}>
                    <th scope="row">Week {row.week}</th>
                    <td>{formatPercent(row.coverage_80, 1)}</td>
                    <td>{row.graded} graded</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </CardBody>
    </Card>
  )
}

function ScorecardCard({
  record,
  onWeek,
  currentSlateWeek,
}: {
  record: TrackRecord
  onWeek: (season: number, week: number) => void
  currentSlateWeek: number | null
}) {
  const card = record.scorecard
  const weekOptions = useMemo(
    () =>
      [...record.weekly]
        .filter((w) => w.season != null && w.week != null && w.graded > 0)
        .reverse()
        .slice(0, 40)
        .map((w) => ({ value: `${w.season}-${w.week}`, label: `${w.season} week ${w.week}` })),
    [record.weekly],
  )
  if (!card) return null

  return (
    <Card className="mt-6 overflow-hidden">
      <CardHeader
        as="h2"
        title={`Scorecard: ${card.season} week ${card.week}`}
        description={`The week's biggest surprises among players projected for ${formatPoints(card.min_projection, 0)}+ points: what we projected at the time against what they actually scored.`}
        action={
          <Select
            label="Scorecard week"
            hideLabel
            size="sm"
            value={`${card.season}-${card.week}`}
            onChange={(event) => {
              const [s, w] = event.target.value.split('-').map(Number)
              if (s && w) onWeek(s, w)
            }}
            className="w-44"
            options={weekOptions}
          />
        }
      />
      {card.summary && (
        <CardBody className="border-line flex flex-wrap gap-x-6 gap-y-1 border-b py-3 text-xs">
          <span className="text-ink-secondary">
            80% range held for <span className="text-ink font-semibold">{formatPercent(card.summary.coverage_80, 1)}</span>
          </span>
          <span className="text-ink-secondary">
            Average miss <span className="text-ink font-semibold">{formatPoints(card.summary.mean_absolute_error)} pts</span>
          </span>
          <span className="text-ink-secondary">{card.summary.graded} graded player-weeks</span>
          {currentSlateWeek !== null && (
            <Link to="/rankings" className="text-accent-text ml-auto hover:underline">
              This week's board
            </Link>
          )}
        </CardBody>
      )}
      <div className="grid md:grid-cols-2">
        <OutcomeList title="Beat the projection" outcomes={card.beats} />
        <OutcomeList title="Fell short" outcomes={card.misses} className="md:border-line md:border-l" />
      </div>
    </Card>
  )
}

function OutcomeList({ title, outcomes, className }: { title: string; outcomes: Outcome[]; className?: string }) {
  return (
    <section className={className} aria-label={title}>
      <h3 className="text-ink-secondary px-4 pt-4 pb-2 text-xs font-semibold tracking-wide uppercase">{title}</h3>
      {outcomes.length === 0 ? (
        <p className="text-ink-muted px-4 pb-4 text-sm">None this week.</p>
      ) : (
        <ol>
          {outcomes.map((o) => (
            <li key={o.player_id} className="border-line flex items-center gap-3 border-t px-4 py-2">
              <PlayerAvatar player={{ name: o.name, headshot_url: o.headshot_url }} size="sm" />
              <span className="min-w-0 flex-1">
                <Link
                  to={`/players/${encodeURIComponent(o.player_id)}`}
                  className="text-ink hover:text-accent-text block truncate text-sm font-medium"
                >
                  {o.name}
                </Link>
                <span className="text-ink-muted block text-xs">
                  {o.position} · {o.team} {o.is_home ? 'vs' : '@'} {o.opponent}
                  {o.inside_range === false && ' · outside the 80% range'}
                </span>
              </span>
              <span className="text-right">
                <span className="tnum text-ink block text-sm font-semibold">
                  {formatPoints(o.actual)}
                  <span className="text-ink-muted ml-1 text-xs font-normal">actual</span>
                </span>
                <span className="tnum text-ink-muted block text-xs">
                  projected {formatPoints(o.projected)} · {formatSigned(o.difference)}
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
