import { memo, useMemo } from 'react'
import { CalendarRange } from 'lucide-react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { InfoTip } from '@/components/ui/Tooltip'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { TeamLink } from '@/components/domain/TeamLink'
import { usePositions } from '@/hooks/useCatalog'
import { useScheduleStrength } from '@/hooks/useInsights'
import { useUrlState } from '@/hooks/useUrlState'
import { cn } from '@/utils/cn'
import { toneForLetter, toneForScore } from '@/utils/grades'
import type { ScheduleCell, TeamSchedule } from '@/api/schemas'

type SosSort = 'rest' | 'next' | 'playoffs' | 'team'

const DEFAULT_STATE = { position: '', sos: 'rest' as SosSort }

/** Tone classes by badge tone, matching `Badge` so the grid reads as the chips do. */
const CELL_TONES = {
  positive: 'bg-positive-soft text-positive-text',
  info: 'bg-info-soft text-info-text',
  neutral: 'bg-surface-sunken text-ink-secondary',
  caution: 'bg-caution-soft text-caution-text',
  negative: 'bg-negative-soft text-negative-text',
  accent: 'bg-accent-soft text-accent-text',
} as const

const SORTS: Record<SosSort, (t: TeamSchedule) => number | null> = {
  rest: (t) => t.mean_score ?? null,
  next: (t) => t.next_score ?? null,
  playoffs: (t) => t.playoff_score ?? null,
  team: () => null,
}

/**
 * Strength of schedule: every team's remaining opponents at one position.
 *
 * The question it answers is "who has the soft run-in?" — for a trade, a
 * waiver claim, or a playoff push. Each cell is the opponent's grade against
 * this position on **current form**, carried forward; the page says that above
 * the grid because it is the whole method, and a grade ten weeks out is not a
 * forecast of that defence.
 *
 * Early in a season almost every cell is ungraded, which is correct: below
 * three completed games a defence has no rank worth drawing.
 */
export function ScheduleGrid() {
  const positions = usePositions()
  const projected = useMemo(
    () => (positions.data ?? []).filter((entry) => entry.projected),
    [positions.data],
  )
  const [state, setState] = useUrlState(DEFAULT_STATE)
  const position = state.position || projected.find((p) => p.position === 'WR')?.position || projected[0]?.position || null
  const sort = state.sos as SosSort

  const { data, isPending, isError, error, refetch, isPlaceholderData } = useScheduleStrength(position)

  const teams = useMemo(() => {
    const list = [...(data?.data.teams ?? [])]
    if (sort === 'team') return list.sort((a, b) => a.team.localeCompare(b.team))
    const key = SORTS[sort]
    return list.sort((a, b) => {
      const left = key(a)
      const right = key(b)
      if (left === null && right === null) return a.team.localeCompare(b.team)
      if (left === null) return 1
      if (right === null) return -1
      return right - left || a.team.localeCompare(b.team)
    })
  }, [data, sort])

  return (
    <Card className="overflow-hidden">
      <CardHeader
        as="h2"
        title="Strength of schedule"
        description="Every remaining opponent, graded on its current form against this position. A is the softest draw."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <ProvenanceBadge provenance="derived" />
            {projected.length > 0 && (
              <SegmentedControl
                label="Position"
                size="sm"
                value={position ?? ''}
                onChange={(value) => setState({ position: value })}
                options={projected.map((entry) => ({ value: entry.position, label: entry.position }))}
              />
            )}
          </div>
        }
      />

      {data && (
        <div className="px-4 pt-4">
          <NoticeList notices={data.meta.notices} />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 px-4 pt-4">
        <SegmentedControl<SosSort>
          label="Order teams by"
          size="sm"
          value={sort}
          onChange={(value) => setState({ sos: value })}
          options={[
            { value: 'rest', label: 'Rest of season' },
            { value: 'next', label: 'Next 4' },
            { value: 'playoffs', label: 'Weeks 15–17' },
            { value: 'team', label: 'Team' },
          ]}
        />
      </div>

      {isPending ? (
        <SkeletonTable rows={12} columns={8} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : teams.length === 0 ? (
        <EmptyState
          icon={<CalendarRange aria-hidden className="size-5" />}
          title="No remaining schedule"
          description="The selected week is past the end of the regular season."
        />
      ) : (
        <Refreshing active={isPlaceholderData}>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <caption className="sr-only">
                Remaining schedule strength for {position}, from week {data?.data.from_week}. Scores run
                0 to 100, where 100 is the softest schedule.
              </caption>
              <thead>
                <tr className="border-line text-ink-muted border-b font-medium tracking-wide uppercase">
                  <th scope="col" className="bg-surface sticky left-0 z-10 px-3 py-2 text-left">
                    Team
                  </th>
                  <th scope="col" className="px-2 py-2 text-center">
                    <span className="inline-flex items-center gap-1">
                      Rest
                      <InfoTip
                        label="About the schedule score"
                        content="The mean of every graded remaining opponent's 0–100 matchup score. 100 is the softest schedule. Ungraded opponents and byes are left out, not averaged in as middling."
                      />
                    </span>
                  </th>
                  <th scope="col" className="hidden px-2 py-2 text-center sm:table-cell">Next 4</th>
                  <th scope="col" className="hidden px-2 py-2 text-center sm:table-cell">Wk 15–17</th>
                  {data?.data.weeks.map((week) => (
                    <th key={week} scope="col" className="px-1 py-2 text-center">
                      {week}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {teams.map((team) => (
                  <ScheduleRow key={team.team} team={team} />
                ))}
              </tbody>
            </table>
          </div>
          <CardBody className="border-line text-ink-muted border-t py-3 text-xs leading-relaxed">
            Cells show the opponent (@ for away) and its current grade against {position}. A dash is an
            opponent without three completed games of history; BYE is a bye. Scores are percentiles
            across the league this week, not a verdict on a defence in absolute terms.
          </CardBody>
        </Refreshing>
      )}
    </Card>
  )
}

function ScoreCell({ score, className }: { score: number | null | undefined; className?: string }) {
  if (score === null || score === undefined) {
    return <td className={cn('text-ink-muted px-2 py-1.5 text-center', className)}>—</td>
  }
  return (
    <td className={cn('px-2 py-1.5 text-center', className)}>
      <span
        className={cn(
          'tnum inline-block min-w-8 rounded px-1.5 py-0.5 font-semibold',
          CELL_TONES[toneForScore(score)],
        )}
      >
        {Math.round(score)}
      </span>
    </td>
  )
}

export const ScheduleRow = memo(function ScheduleRow({ team }: { team: TeamSchedule }) {
  return (
    <tr className="border-line hover:bg-surface-hover border-b last:border-b-0">
      <th scope="row" className="bg-surface sticky left-0 z-10 px-3 py-1.5 text-left">
        <TeamLink team={team.team} className="text-ink text-sm font-semibold" />
      </th>
      <ScoreCell score={team.mean_score} />
      <ScoreCell score={team.next_score} className="hidden sm:table-cell" />
      <ScoreCell score={team.playoff_score} className="hidden sm:table-cell" />
      {team.cells.map((cell) => (
        <GridCell key={cell.week} cell={cell} />
      ))}
    </tr>
  )
})

function GridCell({ cell }: { cell: ScheduleCell }) {
  if (!cell.opponent) {
    return (
      <td className="text-ink-muted px-1 py-1.5 text-center text-[0.625rem] font-medium">BYE</td>
    )
  }
  const grade = cell.grade
  const graded = grade?.graded && grade.letter
  return (
    <td className="px-1 py-1.5 text-center">
      <span
        className={cn(
          'inline-flex min-w-11 flex-col items-center rounded px-1 py-0.5 leading-tight',
          graded ? CELL_TONES[toneForLetter(grade.letter as string)] : 'text-ink-muted',
        )}
      >
        <span className="text-[0.625rem]">
          {cell.is_home ? '' : '@'}
          {cell.opponent}
        </span>
        <span className="font-semibold">{graded ? grade.letter : '—'}</span>
        <span className="sr-only">
          {graded
            ? `, grade ${grade.letter}, defence ranked ${grade.defense_rank} of 32`
            : `, not graded: ${grade?.reason ?? 'no defensive history'}`}
        </span>
      </span>
    </td>
  )
}
