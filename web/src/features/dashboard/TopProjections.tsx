import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'

import { Card, CardBody, CardFooter, CardHeader } from '@/components/ui/Card'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState } from '@/components/feedback/States'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { ProjectionValue } from '@/components/domain/ProjectionValue'
import { useBoard } from '@/hooks/useProjections'
import type { RankedProjection } from '@/api/schemas'

/**
 * The highest projected players on the slate.
 *
 * No sorting happens here. The API returns the board already ranked by
 * calibrated expectation, and this takes the first N — which is the point of
 * a ranked endpoint.
 */
export function TopProjections({ count = 8 }: { count?: number }) {
  const { data, isPending, isError, error, refetch } = useBoard()

  return (
    <Card>
      <CardHeader
        as="h2"
        title="Top projections"
        description="Ranked by the published model run, with the matchup derived beside it."
      />

      {isPending ? (
        <SkeletonTable rows={count} columns={4} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} compact />
      ) : data.data.length === 0 ? (
        <EmptyState
          title="No projections for this week"
          description={
            data.meta.model === null
              ? 'No model run has been published for this week yet. The board appears once the weekly job runs.'
              : 'The published run holds no players for this week.'
          }
        />
      ) : (
        <>
          <CardBody className="p-0">
            <ol className="divide-line divide-y">
              {data.data.slice(0, count).map((entry) => (
                <TopRow key={entry.projection.player.player_id} entry={entry} />
              ))}
            </ol>
          </CardBody>
          <CardFooter>
            <Link
              to="/players"
              className="text-accent-text inline-flex items-center gap-1 font-medium hover:underline"
            >
              All {data.meta.page?.total ?? data.data.length} projected players
              <ArrowRight aria-hidden className="size-3.5" />
            </Link>
          </CardFooter>
        </>
      )}
    </Card>
  )
}

function TopRow({ entry }: { entry: RankedProjection }) {
  const { projection } = entry
  const { points } = projection.prediction

  return (
    <li className="hover:bg-surface-hover flex items-center gap-3 px-5 py-2.5 transition-colors">
      <span className="text-ink-muted tnum w-5 shrink-0 text-xs font-medium">{entry.rank}</span>

      <PlayerIdentity
        player={projection.player}
        team={projection.team}
        size="sm"
        className="flex-1"
        subtitle={
          <>
            {projection.player.position} · {projection.team}
            <span className="text-ink-muted"> {projection.is_home ? 'vs' : '@'} </span>
            {projection.opponent}
          </>
        }
      />

      <span className="hidden shrink-0 sm:block">
        <MatchupGradeChip
          grade={projection.matchup?.grade}
          align="end"
          opponent={projection.opponent}
          fpAllowed={projection.matchup?.fp_allowed_vs_position_l4}
        />
      </span>

      <span className="w-14 shrink-0 text-right">
        <ProjectionValue points={points} actualPoints={projection.actual_points} />
      </span>
    </li>
  )
}
