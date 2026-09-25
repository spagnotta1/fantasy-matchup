import { useParams } from 'react-router-dom'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Skeleton, SkeletonText } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList } from '@/components/feedback/States'
import { ContextPanel, MatchupPanel, UsagePanel } from '@/features/players/detail/ContextPanels'
import { GameLog } from '@/features/players/detail/GameLog'
import { PlayerHero } from '@/features/players/detail/PlayerHero'
import { ProjectionPanel } from '@/features/players/detail/ProjectionPanel'
import { UsageTrends } from '@/features/players/detail/UsageTrends'
import { useDocumentTitle } from '@/app/page-title'
import { usePlayerProfile } from '@/hooks/useProjections'

/**
 * Everything known about one player for one week.
 *
 * A single `/players/{id}/profile` call backs the whole page, which is why it
 * loads as one unit rather than six panels racing each other.
 *
 * The page reads top to bottom as one story, provenance nearest the model
 * first: the projection itself, then the game log that shows how this
 * player's projections have actually tracked (the same boom/bust thresholds
 * as the panel above it, so the chart sits next to the number it explains
 * instead of at the bottom of the page); then usage, the model's own inputs
 * restated for a reader; then matchup and context, both derived *above* the
 * model or merely observed, and correspondingly last. A layout that
 * interleaved those would quietly imply the projection accounts for the wind.
 */
export default function PlayerDetailPage() {
  const { playerId } = useParams<{ playerId: string }>()
  const { data, isPending, isError, error, refetch } = usePlayerProfile(playerId)

  // This page's heading is the player's own name — `PlayerHero` draws it, so
  // the title is set here instead. Before the profile resolves there is no name
  // to use, and the hook leaves the previous title alone rather than flashing
  // the bare product name between two real ones.
  useDocumentTitle(data?.data.player.name)

  if (isPending) return <ProfileSkeleton />

  if (isError) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refetch()} />
      </Card>
    )
  }

  const profile = data.data
  const current = profile.current

  return (
    <>
      <PlayerHero
        player={profile.player}
        projection={current}
        scoringProfile={profile.scoring_profile}
      />

      <NoticeList notices={data.meta.notices} className="mb-6" />

      {current ? (
        <div className="space-y-6">
          <ProjectionPanel
            points={current.prediction.points}
            components={current.prediction.components}
          />

          <GameLog
            history={profile.history}
            trend={profile.trend}
            boomThreshold={current.prediction.points.boom_threshold}
            bustThreshold={current.prediction.points.bust_threshold}
          />

          <UsageTrends history={profile.history} />

          <div className="grid gap-6 xl:grid-cols-2">
            <UsagePanel usage={current.usage} />
            <MatchupPanel
              matchup={current.matchup}
              opponent={current.opponent}
              isHome={current.is_home}
            />
          </div>

          <ContextPanel context={current.context} />
        </div>
      ) : (
        <div className="space-y-6">
          <Card>
            <EmptyState
              title="No projection for this week"
              description="This player has no projection for the selected week — usually a bye week or an inactive listing. Their past games are below."
            />
          </Card>
          <GameLog
            history={profile.history}
            trend={profile.trend}
            boomThreshold={null}
            bustThreshold={null}
          />
          <UsageTrends history={profile.history} />
        </div>
      )}
    </>
  )
}

/** Mirrors the real layout, so nothing jumps when the data lands. */
function ProfileSkeleton() {
  return (
    <div className="animate-fade-in">
      <div className="mb-6 flex items-start gap-4">
        <Skeleton className="size-16 rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-4 w-40" />
        </div>
      </div>
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-28 rounded-[var(--radius-card)]" />
        ))}
      </div>
      <div className="space-y-6">
        <Card>
          <CardHeader as="h2" title={<Skeleton className="h-4 w-28" />} />
          <CardBody>
            <SkeletonText lines={6} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader as="h2" title={<Skeleton className="h-4 w-28" />} />
          <CardBody>
            <Skeleton className="h-40 rounded-[var(--radius-card)]" />
          </CardBody>
        </Card>
        <div className="grid gap-6 xl:grid-cols-2">
          {Array.from({ length: 2 }, (_, index) => (
            <Card key={index}>
              <CardHeader as="h2" title={<Skeleton className="h-4 w-28" />} />
              <CardBody>
                <SkeletonText lines={6} />
              </CardBody>
            </Card>
          ))}
        </div>
        <Card>
          <CardHeader as="h2" title={<Skeleton className="h-4 w-28" />} />
          <CardBody>
            <SkeletonText lines={6} />
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
