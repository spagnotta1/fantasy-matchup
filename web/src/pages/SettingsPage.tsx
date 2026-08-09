import { CheckCircle2, CircleDashed } from 'lucide-react'

import { useSlate } from '@/app/slate-context'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Select } from '@/components/ui/Select'
import { SkeletonText } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/feedback/States'
import {
  useHealth,
  useModelFoundation,
  usePositions,
  useProvenanceLegend,
  useSeasons,
} from '@/hooks/useCatalog'
import { formatLabel, formatScoringProfile } from '@/utils/format'

/**
 * Settings, and the product's disclosure surface.
 *
 * This page is real in Phase 1 rather than a placeholder, for two reasons. It
 * exercises the whole stack end to end — client, validation, query cache,
 * loading and error states — against live endpoints. And the disclosure it
 * carries is not optional for a statistical product: what the model is, what it
 * was measured to do, what the provenance labels mean, and which positions it
 * cannot project.
 */
export default function SettingsPage() {
  const slate = useSlate()

  return (
    <>
      <PageHeader
        title="Settings"
        question="How is this configured, and what is behind the numbers?"
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <ScoringCard
          value={slate.scoringProfile}
          options={slate.availableProfiles}
          failed={slate.catalogFailed}
          onChange={slate.setScoringProfile}
        />
        <ServiceCard />
        <CoverageCard />
        <ProvenanceCard />
        <PositionsCard />
        <ModelCard />
      </div>
    </>
  )
}

function ScoringCard({
  value,
  options,
  failed,
  onChange,
}: {
  value: string | null
  options: string[]
  failed: boolean
  onChange: (profile: string) => void
}) {
  return (
    <Card>
      <CardHeader
        title="Scoring format"
        description="Applies everywhere. Projections are published for each format separately, so switching does not rescale a number — it reads a different one."
      />
      <CardBody>
        <Select
          label="League format"
          value={value ?? ''}
          disabled={options.length === 0}
          options={
            options.length > 0
              ? options.map((profile) => ({ value: profile, label: formatScoringProfile(profile) }))
              : [{ value: '', label: failed ? 'Unavailable' : 'Loading…' }]
          }
          hint={
            failed
              ? 'The list of league formats could not be loaded. Your current selection still applies.'
              : undefined
          }
          onChange={(event) => onChange(event.target.value)}
          className="max-w-xs"
        />
      </CardBody>
    </Card>
  )
}

function ServiceCard() {
  const { data, isPending, isError, error, refetch } = useHealth()

  return (
    <Card>
      <CardHeader title="Service" description="Live status of the projections API." />
      <CardBody>
        {isPending ? (
          <SkeletonText lines={3} />
        ) : isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} compact />
        ) : (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <Row label="Status">
              <Badge tone={data.status === 'ok' ? 'positive' : 'caution'}>
                {formatLabel(data.status)}
              </Badge>
            </Row>
            <Row label="Environment">{data.environment}</Row>
            <Row label="Version">{data.version}</Row>
            <Row label="Database">
              <Badge tone={data.database ? 'positive' : 'negative'}>
                {data.database ? 'Reachable' : 'Unreachable'}
              </Badge>
            </Row>
            <Row label="Cache">{formatLabel(data.cache)}</Row>
          </dl>
        )}
      </CardBody>
    </Card>
  )
}

/**
 * Which slates exist, stated rather than left to be discovered.
 *
 * The season and week selectors already offer exactly what is published, but a
 * dropdown answers "what can I pick" and not "what does this deployment have".
 * Those read the same when the answer is one week and very differently when it
 * is eight seasons, and a user who has only ever seen the newest week has no
 * way to tell which they are looking at. The gap is the useful part: seasons
 * the warehouse holds but no run covers are absent here for a reason, and
 * saying so beats leaving someone to conclude the data is missing.
 */
function CoverageCard() {
  const { data, isPending, isError, error, refetch } = useSeasons()

  const totalWeeks = data?.reduce((sum, entry) => sum + entry.published_weeks.length, 0) ?? 0

  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title="Data coverage"
        description="Every season and week with a published board. These are exactly the slates the season and week selectors offer."
      />
      <CardBody>
        {isPending ? (
          <SkeletonText lines={4} />
        ) : isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} compact />
        ) : data.length === 0 ? (
          <p className="text-ink-secondary text-sm leading-relaxed">
            No projection run has been published yet, so there is no board to show. The
            weekly job publishes the upcoming week;{' '}
            <code className="text-ink-primary text-xs">
              python -m nflfp.jobs run backfill_projections
            </code>{' '}
            publishes every week the feature layer supports.
          </p>
        ) : (
          <>
            <dl className="grid gap-2 sm:grid-cols-[6rem_1fr] sm:gap-x-4">
              {data.map((entry) => (
                <div key={entry.season} className="contents">
                  <dt className="text-ink-primary text-sm font-medium tabular-nums">
                    {entry.season}
                  </dt>
                  <dd className="text-ink-secondary mb-2 text-sm sm:mb-0">
                    {describeWeeks(entry.published_weeks)}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="text-ink-muted mt-4 text-xs leading-relaxed">
              {data.length} season{data.length === 1 ? '' : 's'}, {totalWeeks} published
              week{totalWeeks === 1 ? '' : 's'}. Weeks 19–22 are the NFL playoffs, which
              the feature layer does not cover; a season the warehouse holds but no run
              covers is not listed, because it has no board to show.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}

/**
 * "1–18", or "1–9, 11–18" when a week is genuinely missing.
 *
 * Collapsing to a range would hide a hole, and a hole is the one thing worth
 * seeing here — it is the difference between a complete season and one whose
 * projection job failed on a Tuesday.
 */
function describeWeeks(weeks: number[]): string {
  if (weeks.length === 0) return 'none'

  const runs: Array<[number, number]> = []
  for (const week of weeks) {
    const last = runs[runs.length - 1]
    if (last && week === last[1] + 1) last[1] = week
    else runs.push([week, week])
  }

  const label = runs
    .map(([start, end]) => (start === end ? `Week ${start}` : `Weeks ${start}–${end}`))
    .join(', ')
  return runs.length === 1 ? label : `${label} (${weeks.length} total)`
}

function ProvenanceCard() {
  const { data, isPending, isError, error, refetch } = useProvenanceLegend()

  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title="What the labels mean"
        description="Every number in this product carries one of these. They are not interchangeable, and the interface keeps them apart on purpose."
      />
      <CardBody>
        {isPending ? (
          <SkeletonText lines={6} />
        ) : isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} compact />
        ) : (
          <dl className="space-y-4">
            {Object.entries(data).map(([label, explanation]) => (
              <div key={label} className="grid gap-1 sm:grid-cols-[7rem_1fr] sm:gap-4">
                <dt>
                  <Badge tone={label === 'model' ? 'accent' : label === 'derived' ? 'info' : 'neutral'}>
                    {formatLabel(label)}
                  </Badge>
                </dt>
                <dd className="text-ink-secondary text-sm leading-relaxed">{explanation}</dd>
              </div>
            ))}
          </dl>
        )}
      </CardBody>
    </Card>
  )
}

function PositionsCard() {
  const { data, isPending, isError, error, refetch } = usePositions()

  return (
    <Card>
      <CardHeader
        title="Positions"
        description="Which positions are projected, and what the others are waiting on. Filters throughout the product are built from this list rather than a hard-coded one."
      />
      <CardBody>
        {isPending ? (
          <SkeletonText lines={5} />
        ) : isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} compact />
        ) : (
          <ul className="space-y-4">
            {data.map((position) => (
              <li key={position.position}>
                <div className="flex items-center gap-2">
                  {position.projected ? (
                    <CheckCircle2 aria-hidden className="text-positive size-4" />
                  ) : (
                    <CircleDashed aria-hidden className="text-ink-muted size-4" />
                  )}
                  <span className="text-ink text-sm font-medium">{position.label}</span>
                  <Badge tone={position.projected ? 'positive' : 'neutral'}>
                    {formatLabel(position.status)}
                  </Badge>
                </div>
                {position.reason && (
                  <p className="text-ink-muted mt-1.5 pl-6 text-xs leading-relaxed">
                    {position.reason}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  )
}

function ModelCard() {
  const { data, isPending, isError, error, refetch } = useModelFoundation()

  // `/meta/model` is a free-form audit document by design — it carries whatever
  // the frozen foundation measured. Rather than pin a schema to it and break on
  // the next freeze, the scalar entries are surfaced and the nested detail is
  // left to the phase that designs a proper model-card view.
  const scalars = Object.entries(data ?? {}).filter(
    ([, value]) => typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean',
  )

  return (
    <Card>
      <CardHeader
        title="Model"
        description="The frozen prediction foundation behind every model-provenance number."
      />
      <CardBody>
        {isPending ? (
          <SkeletonText lines={5} />
        ) : isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} compact />
        ) : scalars.length === 0 ? (
          <p className="text-ink-muted text-sm">No summary fields were returned.</p>
        ) : (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            {scalars.map(([key, value]) => (
              <Row key={key} label={formatLabel(key)}>
                {String(value)}
              </Row>
            ))}
          </dl>
        )}
      </CardBody>
    </Card>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-ink-muted text-xs font-medium tracking-wide uppercase">{label}</dt>
      <dd className="text-ink text-sm">{children}</dd>
    </>
  )
}
