import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { formatNumber, formatPercent, formatPoints } from '@/utils/format'
import type { Components, Points } from '@/api/schemas'

/**
 * The outcome distribution, and what the model thinks produces it.
 *
 * The percentile strip is the point of this panel. A projection is a
 * distribution and showing it as one is the honest form — the reader can see
 * that the gap between a bad week and a good week dwarfs the gap between two
 * players' projections, which is the single most useful thing a fantasy
 * analytics product can teach.
 */
export function ProjectionPanel({
  points,
  components,
}: {
  points: Points
  components: Components
}) {
  return (
    <Card>
      <CardHeader
        as="h2"
        title="Projection"
        description="The published model run's output for this week."
        action={<ProvenanceBadge provenance="model" />}
      />
      <CardBody className="space-y-6">
        <PercentileStrip points={points} />

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Figure
            label="Boom"
            value={formatPercent(points.boom_probability)}
            detail={`over ${formatPoints(points.boom_threshold)} pts`}
          />
          <Figure
            label="Bust"
            value={formatPercent(points.bust_probability)}
            detail={`under ${formatPoints(points.bust_threshold)} pts`}
          />
          <Figure label="Shape" value={points.shape === 'unknown' ? '—' : points.shape} detail="outcome pattern" />
          <Figure
            label="Sample"
            value={points.samples === null || points.samples === undefined ? '—' : String(points.samples)}
            detail="held-out residuals"
          />
        </div>

        <ComponentBreakdown components={components} />

        {points.extrapolated && (
          <p className="bg-caution-soft text-caution-text rounded-[var(--radius-control)] px-3 py-2 text-xs leading-relaxed">
            This projection is higher than anything seen while fitting the outcome distribution, so
            its range is an extrapolation rather than a measured interval.
          </p>
        )}
      </CardBody>
    </Card>
  )
}

/**
 * Floor, median and ceiling on one axis.
 *
 * A bar chart of three numbers would be three bars saying what one line says
 * better. The strip is the form: it shows the *span*, which is the quantity
 * that matters, and puts the median where it actually falls inside it.
 */
function PercentileStrip({ points }: { points: Points }) {
  const { floor, p25, median, p75, ceiling } = points
  if (floor === null || floor === undefined || ceiling === null || ceiling === undefined) {
    return <p className="text-ink-muted text-sm">No outcome range was stored for this projection.</p>
  }

  const span = Math.max(ceiling - floor, 0.001)
  const at = (value: number) => ((value - floor) / span) * 100
  const marks = [
    { label: 'P10', value: floor },
    p25 !== null && p25 !== undefined ? { label: 'P25', value: p25 } : null,
    median !== null && median !== undefined ? { label: 'P50', value: median } : null,
    p75 !== null && p75 !== undefined ? { label: 'P75', value: p75 } : null,
    { label: 'P90', value: ceiling },
  ].filter((mark): mark is { label: string; value: number } => mark !== null)

  return (
    <div>
      <div className="text-ink-muted mb-2 flex items-baseline justify-between text-xs">
        <span>Range of outcomes</span>
        <span>
          {formatPoints(floor)} – {formatPoints(ceiling)} pts
        </span>
      </div>

      <div
        className="relative h-10"
        role="img"
        aria-label={marks.map((mark) => `${mark.label} ${formatPoints(mark.value)} points`).join(', ')}
      >
        <div className="bg-chart-series/25 absolute inset-x-0 top-3 h-2 rounded-full" />
        {marks.map((mark) => (
          <div
            key={mark.label}
            className="absolute top-0 -translate-x-1/2"
            style={{ left: `${Math.min(Math.max(at(mark.value), 0), 100)}%` }}
          >
            <span
              className={
                mark.label === 'P50'
                  ? 'bg-chart-series ring-surface block h-8 w-1 rounded-full ring-2'
                  : 'bg-chart-series/70 mt-2 block h-4 w-0.5 rounded-full'
              }
            />
          </div>
        ))}
      </div>

      <dl className="text-ink-muted mt-1 flex justify-between text-[0.6875rem]">
        {marks.map((mark) => (
          <div key={mark.label} className="text-center">
            <dt className="font-medium">{mark.label}</dt>
            <dd className="tnum text-ink-secondary">{formatPoints(mark.value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** Projected opportunity and production, which is what the model actually predicts. */
function ComponentBreakdown({ components }: { components: Components }) {
  const rows: { label: string; value: number | null | undefined; digits?: number }[] = [
    { label: 'Pass yards', value: components.passing_yards },
    { label: 'Pass TDs', value: components.passing_tds, digits: 2 },
    { label: 'Interceptions', value: components.interceptions, digits: 2 },
    { label: 'Carries', value: components.carries },
    { label: 'Rush yards', value: components.rushing_yards },
    { label: 'Rush TDs', value: components.rushing_tds, digits: 2 },
    { label: 'Targets', value: components.targets },
    { label: 'Receptions', value: components.receptions },
    { label: 'Rec yards', value: components.receiving_yards },
    { label: 'Rec TDs', value: components.receiving_tds, digits: 2 },
  ].filter((row) => row.value !== null && row.value !== undefined && Math.abs(row.value) >= 0.05)

  if (rows.length === 0) return null

  return (
    <div>
      <h3 className="text-ink-muted mb-2 text-xs font-semibold tracking-wide uppercase">
        Projected production
      </h3>
      <p className="text-ink-muted mb-3 text-xs leading-relaxed">
        What the model predicts before scoring rules are applied. One set of components serves
        every league format — the points above are these numbers scored.
      </p>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3">
        {rows.map((row) => (
          <div key={row.label} className="border-line flex justify-between border-b py-1 text-sm">
            <dt className="text-ink-secondary">{row.label}</dt>
            <dd className="tnum text-ink font-medium">{formatNumber(row.value, row.digits ?? 1)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function Figure({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div>
      <dt className="text-ink-muted text-xs font-medium tracking-wide uppercase">{label}</dt>
      <dd className="tnum text-ink mt-0.5 text-lg font-semibold">{value}</dd>
      <p className="text-ink-muted text-[0.6875rem]">{detail}</p>
    </div>
  )
}
