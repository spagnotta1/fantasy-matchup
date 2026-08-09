import { CalendarDays, CheckCircle2, CircleDot, Database } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/feedback/States'
import { useWeek } from '@/hooks/useProjections'
import { formatGameDay, formatSpread } from '@/utils/format'

/**
 * The week at a glance, and — more importantly — whether there is a board.
 *
 * `/weeks/{week}` exists to disambiguate an empty projections list: a bye-heavy
 * week, an unbuilt warehouse and a projection job that has not run all return
 * the same empty array. This card is where that distinction surfaces, so no
 * other view has to guess.
 */
export function WeekOverview() {
  const { data, isPending, isError, error, refetch } = useWeek()

  if (isPending) {
    return (
      <Card>
        <CardHeader title="This week" as="h2" />
        <CardBody className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-40 w-full" />
        </CardBody>
      </Card>
    )
  }

  if (isError) {
    return (
      <Card>
        <CardHeader title="This week" as="h2" />
        <ErrorState error={error} onRetry={() => void refetch()} compact />
      </Card>
    )
  }

  const week = data.data
  const upcoming = week.games.filter((game) => game.is_upcoming)
  const finished = week.games.filter((game) => !game.is_upcoming)

  return (
    <Card>
      <CardHeader
        as="h2"
        title={`Week ${week.week} · ${week.season}`}
        description={`${week.game_count} games — ${week.completed_games} completed, ${week.upcoming_games} still to play.`}
        action={
          week.projections_published ? (
            <Badge tone="positive" icon={<CheckCircle2 className="size-3" />}>
              {week.projection_count} projections
            </Badge>
          ) : (
            <Badge tone="caution" icon={<CircleDot className="size-3" />}>
              No board yet
            </Badge>
          )
        }
      />

      <CardBody className="space-y-4">
        {!week.projections_published && (
          <p className="bg-caution-soft text-caution-text rounded-[var(--radius-control)] px-3 py-2 text-xs leading-relaxed">
            The schedule for this week is final, but the projection job has not published a run
            for it. Nothing below will show players until it does.
          </p>
        )}

        {week.projections_published && week.projection_count === 0 && (
          <p className="bg-caution-soft text-caution-text rounded-[var(--radius-control)] px-3 py-2 text-xs leading-relaxed">
            A run is published for this week but holds no projections. That is a real state, not
            a loading failure.
          </p>
        )}

        {week.model && (
          <p className="text-ink-muted flex items-center gap-1.5 text-xs">
            <Database aria-hidden className="size-3.5" />
            {week.model.model_name} v{week.model.model_version} · run {week.model.run_id}
          </p>
        )}

        {week.games.length === 0 ? (
          <p className="text-ink-muted text-sm">No games are scheduled for this week.</p>
        ) : (
          <div>
            <h3 className="text-ink-muted mb-2 flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase">
              <CalendarDays aria-hidden className="size-3.5" />
              {upcoming.length > 0 ? 'Schedule' : 'Results'}
            </h3>
            <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
              {[...upcoming, ...finished].map((game) => (
                <li
                  key={game.game_id}
                  className="border-line flex items-center justify-between gap-3 border-b py-1.5 text-sm last:border-b-0"
                >
                  <span className="tnum text-ink font-medium">
                    {game.away_team} <span className="text-ink-muted font-normal">at</span>{' '}
                    {game.home_team}
                  </span>
                  <span className="text-ink-muted tnum flex items-center gap-2 text-xs">
                    {game.is_upcoming ? (
                      <>
                        <span>{formatGameDay(game.gameday)}</span>
                        {game.home_spread !== null && game.home_spread !== undefined && (
                          // `home_spread` is points the *home* team is favoured
                          // by, so a negative value means the road team is. The
                          // favourite is named either way, the way a book prints it.
                          <span title="Betting line">
                            {game.home_spread >= 0 ? game.home_team : game.away_team}{' '}
                            {formatSpread(Math.abs(game.home_spread))}
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="text-ink-secondary font-medium">
                        {game.away_score}–{game.home_score}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
