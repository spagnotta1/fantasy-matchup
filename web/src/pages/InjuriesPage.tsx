import { memo, useMemo } from 'react'
import { HeartPulse } from 'lucide-react'

import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Card, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { ProjectionValue } from '@/components/domain/ProjectionValue'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { TeamLink } from '@/components/domain/TeamLink'
import { useSlate } from '@/app/slate-context'
import { usePositions } from '@/hooks/useCatalog'
import { boardNotices, useBoard } from '@/hooks/useProjections'
import { useUrlState } from '@/hooks/useUrlState'
import { entryPoints } from '@/utils/board'
import type { RankedProjection } from '@/api/schemas'

type Status = 'out' | 'doubtful' | 'questionable' | 'practice'

const STATUS: Record<Status, { label: string; tone: BadgeTone; heading: string }> = {
  out: { label: 'Out', tone: 'negative', heading: 'Ruled out' },
  doubtful: { label: 'Doubtful', tone: 'negative', heading: 'Doubtful' },
  questionable: { label: 'Questionable', tone: 'caution', heading: 'Questionable' },
  practice: { label: 'Practice', tone: 'neutral', heading: 'On the practice report only' },
}

const ORDER: Status[] = ['out', 'doubtful', 'questionable', 'practice']

function statusOf(entry: RankedProjection): Status | null {
  const injury = entry.projection.context.injury
  if (!injury) return null
  const report = (injury.report_status ?? '').toLowerCase()
  if (report.startsWith('out') || injury.will_not_play) return 'out'
  if (report.startsWith('doubtful')) return 'doubtful'
  if (report.startsWith('questionable')) return 'questionable'
  // A practice line with no game designation: limited or absent in practice,
  // expected to play. Worth listing, not worth alarm.
  const practice = (injury.practice_status ?? '').toLowerCase()
  if (practice && !practice.startsWith('full')) return 'practice'
  return null
}

const DEFAULT_STATE = { position: '', status: 'all' }

/**
 * This week's injury report, beside each player's projection.
 *
 * The rule this page exists to keep: a designation is a hard caveat *above*
 * the statistical verdict, and it never changes the number. The projection is
 * shown exactly as published — for a player ruled out, the points he would be
 * projected for if he played — with "Ruled out" beside it, because silently
 * zeroing him would erase the difference between "projected for nothing" and
 * "not playing". The report is `context`: observed, and not applied.
 */
export default function InjuriesPage() {
  const slate = useSlate()
  const positions = usePositions()
  const board = useBoard()
  const [state, setState] = useUrlState(DEFAULT_STATE)

  const groups = useMemo(() => {
    const byStatus = new Map<Status, RankedProjection[]>()
    for (const entry of board.data?.data ?? []) {
      const status = statusOf(entry)
      if (!status) continue
      if (state.position && entry.projection.player.position !== state.position) continue
      byStatus.set(status, [...(byStatus.get(status) ?? []), entry])
    }
    for (const list of byStatus.values()) {
      list.sort((a, b) => (entryPoints(b) ?? 0) - (entryPoints(a) ?? 0))
    }
    return byStatus
  }, [board.data, state.position])

  const shown = ORDER.filter((status) => {
    if (state.status === 'all') return true
    if (state.status === 'serious') return status === 'out' || status === 'doubtful'
    return status === state.status
  })
  const reason = board.data?.data.find((e) => e.projection.context.injury)?.projection.context.injury
    ?.unapplied_reason
  const total = ORDER.reduce((sum, s) => sum + (groups.get(s)?.length ?? 0), 0)

  return (
    <>
      <PageHeader
        title="Injury report"
        question={`Who is hurt in week ${slate.week ?? '—'}, and what were they projected for?`}
      />

      <div className="mb-4 space-y-3">
        <NoticeList
          title="Not included in the projection"
          showTitle
          notices={[
            reason ??
              'The frozen model does not read the injury report. Each projection is shown as published; the designation beside it is the caveat.',
          ]}
        />
        {board.data && <NoticeList notices={boardNotices(board.data.meta)} />}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SegmentedControl
          label="Position"
          value={state.position}
          onChange={(value) => setState({ position: value })}
          options={[
            { value: '', label: 'All' },
            ...(positions.data ?? [])
              .filter((p) => p.projected)
              .map((p) => ({ value: p.position, label: p.position })),
          ]}
        />
        <SegmentedControl
          label="Designation"
          value={state.status}
          onChange={(value) => setState({ status: value })}
          options={[
            { value: 'all', label: 'All' },
            { value: 'serious', label: 'Out & doubtful' },
            { value: 'questionable', label: 'Questionable' },
            { value: 'practice', label: 'Practice only' },
          ]}
        />
        <p className="text-ink-muted ml-auto text-xs" aria-live="polite">
          {ORDER.map((s) => `${groups.get(s)?.length ?? 0} ${STATUS[s].label.toLowerCase()}`).join(' · ')}
        </p>
      </div>

      {board.isPending ? (
        <Card>
          <SkeletonTable rows={10} columns={5} />
        </Card>
      ) : board.isError ? (
        <Card>
          <ErrorState error={board.error} onRetry={() => void board.refetch()} />
        </Card>
      ) : total === 0 ? (
        <Card>
          <EmptyState
            icon={<HeartPulse aria-hidden className="size-5" />}
            title="No one on the report"
            description="No projected player carries an injury designation or a limited practice line this week — or the report has not been published yet. Reports usually arrive Wednesday to Friday."
          />
        </Card>
      ) : (
        <Refreshing active={board.isPlaceholderData}>
          <div className="space-y-6">
            {shown.map((status) => {
              const entries = groups.get(status) ?? []
              if (entries.length === 0) return null
              return (
                <Card key={status} className="overflow-hidden">
                  <CardHeader
                    as="h2"
                    title={`${STATUS[status].heading} (${entries.length})`}
                    action={<ProvenanceBadge provenance="context" />}
                  />
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-sm">
                      <caption className="sr-only">{STATUS[status].heading} players this week</caption>
                      <thead>
                        <tr className="border-line text-ink-muted border-b text-xs font-medium tracking-wide uppercase">
                          <th scope="col" className="px-3 py-2 text-left">Player</th>
                          <th scope="col" className="px-3 py-2 text-left">Injury</th>
                          <th scope="col" className="hidden px-3 py-2 text-left md:table-cell">Practice</th>
                          <th scope="col" className="px-3 py-2 text-right">Projection</th>
                        </tr>
                      </thead>
                      <tbody>
                        {entries.map((entry) => (
                          <InjuryRow key={entry.projection.player.player_id} entry={entry} status={status} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              )
            })}
          </div>
        </Refreshing>
      )}
    </>
  )
}

const InjuryRow = memo(function InjuryRow({ entry, status }: { entry: RankedProjection; status: Status }) {
  const { projection } = entry
  const injury = projection.context.injury
  return (
    <tr className="border-line border-b last:border-b-0">
      <td className="px-3 py-2">
        <PlayerIdentity
          player={projection.player}
          team={projection.team}
          size="sm"
          subtitle={
            <>
              {projection.player.position} · <TeamLink team={projection.team} />{' '}
              {projection.is_home ? 'vs' : '@'} <TeamLink team={projection.opponent} />
            </>
          }
        />
      </td>
      <td className="px-3 py-2">
        <span className="inline-flex flex-wrap items-center gap-1.5">
          <Badge tone={STATUS[status].tone}>{injury?.report_status ?? 'No designation'}</Badge>
          {injury?.detail && <span className="text-ink-secondary text-xs">{injury.detail}</span>}
        </span>
      </td>
      <td className="text-ink-secondary hidden px-3 py-2 text-xs md:table-cell">
        {injury?.practice_status ?? '—'}
      </td>
      <td className="px-3 py-2 text-right">
        <span className="inline-flex flex-col items-end">
          <ProjectionValue points={projection.prediction.points} actualPoints={projection.actual_points} />
          {status === 'out' && (
            // Beside the number it qualifies, not in a footnote: the value is
            // what he would be projected for if he played, and he will not.
            <span className="text-negative-text text-[0.6875rem] font-medium">Ruled out — will not play</span>
          )}
          {status === 'doubtful' && (
            <span className="text-negative-text text-[0.6875rem] font-medium">Unlikely to play</span>
          )}
        </span>
      </td>
    </tr>
  )
})
