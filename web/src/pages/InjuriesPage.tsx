import { memo, useMemo, type ReactNode } from 'react'
import { AlertTriangle, Ban, HeartPulse, HelpCircle, SearchX } from 'lucide-react'

import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardHeader } from '@/components/ui/Card'
import {
  ColumnHeader,
  GroupHeaderRow,
  RowHeaderCell,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from '@/components/ui/DataTable'
import { FilterChoice, FilterToolbar } from '@/components/ui/FilterToolbar'
import { PageHeader } from '@/components/ui/PageHeader'
import {
  RowList,
  RowListGroup,
  RowListItem,
  RowListLine,
  RowListRows,
  RowListTitle,
} from '@/components/ui/RowList'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { PlayerCell } from '@/components/domain/PlayerCell'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { ProjectionValue } from '@/components/domain/ProjectionValue'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { TeamLink } from '@/components/domain/TeamLink'
import { useSlate } from '@/app/slate-context'
import { usePositions } from '@/hooks/useCatalog'
import { boardNotices, useBoard } from '@/hooks/useProjections'
import { useRowList } from '@/hooks/useRowList'
import { useUrlState } from '@/hooks/useUrlState'
import { entryPoints } from '@/utils/board'
import type { RankedProjection } from '@/api/schemas'

type Status = 'out' | 'doubtful' | 'questionable' | 'practice'

/**
 * How each designation is drawn. Out and doubtful share a colour, so the glyph
 * is what tells them apart — and the badge always carries the report's own
 * word, so neither the colour nor the glyph is the only thing saying it.
 */
const STATUS: Record<Status, { label: string; tone: BadgeTone; heading: string; icon: ReactNode }> = {
  out: { label: 'Out', tone: 'negative', heading: 'Ruled out', icon: <Ban className="size-3" /> },
  doubtful: { label: 'Doubtful', tone: 'negative', heading: 'Doubtful', icon: <AlertTriangle className="size-3" /> },
  questionable: {
    label: 'Questionable',
    tone: 'caution',
    heading: 'Questionable',
    icon: <HelpCircle className="size-3" />,
  },
  practice: { label: 'Practice', tone: 'neutral', heading: 'On the practice report only', icon: null },
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
 *
 * One table, grouped by designation. It used to be a card and a table per
 * designation, each sizing its own columns, so "Practice" sat in a different
 * place in each of the four. A group heading is a row group's header, which is
 * what a screen reader announces it as.
 *
 * On a phone the same groups are a list (`ReportList`). Scrolling sideways
 * kept the designation beside the name and put the projection, and the words
 * "will not play" under it, two columns off screen: the one pairing this page
 * exists to show.
 */
export default function InjuriesPage() {
  const slate = useSlate()
  const positions = usePositions()
  const board = useBoard()
  const [state, setState] = useUrlState(DEFAULT_STATE)

  const { groups, reported } = useMemo(() => {
    const byStatus = new Map<Status, RankedProjection[]>()
    // Everyone on the report, before the position filter: it is what tells
    // "the report is empty" from "the filters match nobody".
    let reported = 0
    for (const entry of board.data?.data ?? []) {
      const status = statusOf(entry)
      if (!status) continue
      reported += 1
      if (state.position && entry.projection.player.position !== state.position) continue
      byStatus.set(status, [...(byStatus.get(status) ?? []), entry])
    }
    for (const list of byStatus.values()) {
      list.sort((a, b) => (entryPoints(b) ?? 0) - (entryPoints(a) ?? 0))
    }
    return { groups: byStatus, reported }
  }, [board.data, state.position])

  const shown = ORDER.filter((status) => {
    if ((groups.get(status)?.length ?? 0) === 0) return false
    if (state.status === 'all') return true
    if (state.status === 'serious') return status === 'out' || status === 'doubtful'
    return status === state.status
  })
  const reason = board.data?.data.find((e) => e.projection.context.injury)?.projection.context.injury
    ?.unapplied_reason
  const listed = shown.reduce((sum, status) => sum + (groups.get(status)?.length ?? 0), 0)

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
              'The projections do not account for injuries. Each player shows their normal projection, with their injury status beside it as the warning.',
          ]}
        />
        {board.data && <NoticeList notices={boardNotices(board.data.meta, { showsGrades: false })} />}
      </div>

      <FilterToolbar
        label="Filter the report"
        summary={ORDER.map((s) => `${groups.get(s)?.length ?? 0} ${STATUS[s].label.toLowerCase()}`).join(' · ')}
      >
        <FilterChoice
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
        <FilterChoice
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
      </FilterToolbar>

      {/* `clip`, not `hidden`: a hidden overflow would make the card a scroll
          container and the column header would stick to it. */}
      <Card className="overflow-clip">
        <CardHeader
          as="h2"
          title="On the report"
          description="Grouped by designation, highest projection first."
          action={<ProvenanceBadge provenance="context" />}
        />
        {board.isPending ? (
          <SkeletonTable rows={10} columns={4} />
        ) : board.isError ? (
          <ErrorState error={board.error} onRetry={() => void board.refetch()} />
        ) : reported === 0 ? (
          <EmptyState
            icon={<HeartPulse aria-hidden className="size-5" />}
            title="No one on the report"
            description="No projected player is on the injury or practice report this week — or the report is not out yet. Reports usually come out Wednesday to Friday."
          />
        ) : listed === 0 ? (
          <EmptyState
            icon={<SearchX aria-hidden className="size-5" />}
            title="No players match these filters"
            description={`${reported} ${reported === 1 ? 'player is' : 'players are'} on this week's report, none with this position and designation.`}
            action={
              <Button size="sm" variant="secondary" onClick={() => setState({ position: '', status: 'all' })}>
                Clear filters
              </Button>
            }
          />
        ) : (
          <Refreshing active={board.isPlaceholderData}>
            <Report
              caption={`Injury report for week ${slate.week ?? ''}, grouped by designation`}
              groups={shown.map((status) => ({ status, entries: groups.get(status) ?? [] }))}
            />
          </Refreshing>
        )}
      </Card>
    </>
  )
}

/** What is printed under a projection whose player is not expected to play. */
const CAVEAT: Partial<Record<Status, string>> = {
  // The value is what he would be projected for if he played, and he will not.
  out: 'Ruled out — will not play',
  doubtful: 'Unlikely to play',
}

const countOf = (entries: RankedProjection[]) => `${entries.length} ${entries.length === 1 ? 'player' : 'players'}`

/** The report's rows: a table where there is room for its columns, a list where there is not. */
function Report({ caption, groups }: { caption: string; groups: { status: Status; entries: RankedProjection[] }[] }) {
  const [frameRef, asList] = useRowList<HTMLDivElement>()

  return (
    <div ref={frameRef}>
      {asList ? (
        <RowList value="Projection">
          {groups.map(({ status, entries }) => (
            <RowListGroup key={status} id={`report-${status}`} heading={STATUS[status].heading} note={countOf(entries)}>
              <RowListRows>
                {entries.map((entry) => (
                  <ReportListRow key={entry.projection.player.player_id} entry={entry} status={status} />
                ))}
              </RowListRows>
            </RowListGroup>
          ))}
        </RowList>
      ) : (
        <Table caption={caption} minWidth="44rem" freezeFirstColumn>
          <TableHead>
            <ColumnHeader className="max-sm:max-w-44">Player</ColumnHeader>
            <ColumnHeader>Injury</ColumnHeader>
            <ColumnHeader>Practice</ColumnHeader>
            <ColumnHeader numeric>Projection</ColumnHeader>
          </TableHead>
          {groups.map(({ status, entries }) => (
            <TableBody key={status}>
              <GroupHeaderRow colSpan={4}>
                {STATUS[status].heading}
                <span className="text-ink-muted ml-2 font-normal">{countOf(entries)}</span>
              </GroupHeaderRow>
              {entries.map((entry) => (
                <InjuryRow key={entry.projection.player.player_id} entry={entry} status={status} />
              ))}
            </TableBody>
          ))}
        </Table>
      )}
    </div>
  )
}

/**
 * One player on the list. The projection is on the first line, and where he is
 * not expected to play the caveat is the first thing under it, at the same
 * edge. The designation and the injury are on that line too, and the practice
 * line under them.
 */
const ReportListRow = memo(function ReportListRow({ entry, status }: { entry: RankedProjection; status: Status }) {
  const { projection } = entry
  const injury = projection.context.injury
  return (
    <RowListItem to={`/players/${encodeURIComponent(projection.player.player_id)}`}>
      <PlayerAvatar player={projection.player} size="xs" />
      <RowListTitle
        name={projection.player.name}
        meta={
          <>
            {projection.player.position} · {projection.team} {projection.is_home ? 'vs' : '@'} {projection.opponent}
          </>
        }
      />
      <ProjectionValue
        points={projection.prediction.points}
        actualPoints={projection.actual_points}
        className="justify-self-end"
      />
      <RowListLine className="flex-wrap gap-y-1">
        <Badge tone={STATUS[status].tone} icon={STATUS[status].icon}>
          {injury?.report_status ?? 'No designation'}
        </Badge>
        {injury?.detail && <span className="text-ink-secondary text-detail">{injury.detail}</span>}
        {CAVEAT[status] && (
          <span className="text-negative-text text-chip ml-auto font-medium whitespace-nowrap">{CAVEAT[status]}</span>
        )}
      </RowListLine>
      {injury?.practice_status && (
        <RowListLine className="text-ink-secondary text-chip">{injury.practice_status}</RowListLine>
      )}
    </RowListItem>
  )
})

const InjuryRow = memo(function InjuryRow({ entry, status }: { entry: RankedProjection; status: Status }) {
  const { projection } = entry
  const injury = projection.context.injury
  return (
    <TableRow>
      <RowHeaderCell className="max-sm:max-w-44">
        <PlayerCell
          player={projection.player}
          meta={
            <>
              {projection.player.position} · <TeamLink team={projection.team} />{' '}
              {projection.is_home ? 'vs' : '@'} <TeamLink team={projection.opponent} />
            </>
          }
        />
      </RowHeaderCell>
      <TableCell>
        <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <Badge tone={STATUS[status].tone} icon={STATUS[status].icon}>
            {injury?.report_status ?? 'No designation'}
          </Badge>
          {injury?.detail && <span className="text-ink-secondary text-detail">{injury.detail}</span>}
        </span>
      </TableCell>
      <TableCell className="text-ink-secondary text-detail">{injury?.practice_status ?? '—'}</TableCell>
      <TableCell numeric>
        <span className="inline-flex flex-col items-end">
          <ProjectionValue points={projection.prediction.points} actualPoints={projection.actual_points} />
          {CAVEAT[status] && (
            // Beside the number it qualifies, not in a footnote.
            <span className="text-negative-text text-chip font-medium whitespace-nowrap">{CAVEAT[status]}</span>
          )}
        </span>
      </TableCell>
    </TableRow>
  )
})
