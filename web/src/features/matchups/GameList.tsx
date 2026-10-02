import { Link } from 'react-router-dom'
import { CalendarX, ChevronRight } from 'lucide-react'

import { Card } from '@/components/ui/Card'
import { MatchupColorBar, ScoreBugTeam } from '@/components/domain/ScoreBug'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, Refreshing } from '@/components/feedback/States'
import { useGames } from '@/hooks/useMatchups'
import { formatGameDay, formatPoints } from '@/utils/format'
import type { Game } from '@/api/schemas'

/**
 * The week's slate.
 *
 * The card leads with the two teams and the market's view of the game, because
 * those are the two facts that decide whether a matchup is worth opening: a
 * 51-point total with a three-point spread is a different environment from a
 * 37-point blowout, and neither is visible from a list of team names.
 *
 * The spread is printed against the team it favours rather than as the API's
 * signed `home_spread`, which reads backwards to anyone who has seen a
 * sportsbook.
 */
export function GameList({ selectedGameId }: { selectedGameId?: string }) {
  const { data, isPending, isError, error, refetch, isPlaceholderData } = useGames()

  if (isPending) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-28 rounded-[var(--radius-card)]" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refetch()} />
      </Card>
    )
  }

  if (data.data.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<CalendarX aria-hidden className="size-5" />}
          eyebrow="Bye week"
          title="No games scheduled"
          description="There are no games in the selected week. Pick another week at the top of the page."
        />
      </Card>
    )
  }

  return (
    <Refreshing active={isPlaceholderData}>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {data.data.map((game) => (
          <li key={game.game_id}>
            <GameCard game={game} selected={game.game_id === selectedGameId} />
          </li>
        ))}
      </ul>
    </Refreshing>
  )
}

function GameCard({ game, selected }: { game: Game; selected: boolean }) {
  const completed =
    game.home_score !== null &&
    game.home_score !== undefined &&
    game.away_score !== null &&
    game.away_score !== undefined
  const awayScore = game.away_score ?? 0
  const homeScore = game.home_score ?? 0

  // Market lines as one quiet line of text rather than a row of chips: on a
  // slate of sixteen identical cards, three pills each was the loudest thing
  // on the page. "Upcoming" is gone for the same reason — the kickoff date
  // under it already says so.
  const lines = [
    game.home_spread !== null && game.home_spread !== undefined ? describeSpread(game) : null,
    game.total_line !== null && game.total_line !== undefined ? `O/U ${formatPoints(game.total_line)}` : null,
  ].filter(Boolean)

  return (
    <Link
      to={`/matchups/${encodeURIComponent(game.game_id)}`}
      aria-current={selected ? 'true' : undefined}
      className={[
        'bg-surface hover:border-line-strong focus-visible:outline-focus group relative block h-full overflow-hidden rounded-[var(--radius-card)] border px-4 pt-5 pb-4 transition-[border-color,transform,box-shadow] hover:-translate-y-0.5 hover:shadow-raised',
        selected ? 'border-accent ring-accent/30 ring-2' : 'border-line',
      ].join(' ')}
    >
      <MatchupColorBar away={game.away_team} home={game.home_team} />
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1 space-y-2">
          <ScoreBugTeam
            team={game.away_team}
            score={completed ? game.away_score : undefined}
            trailing={completed && awayScore < homeScore}
          />
          <ScoreBugTeam
            team={game.home_team}
            score={completed ? game.home_score : undefined}
            trailing={completed && homeScore < awayScore}
          >
            <span className="text-ink-muted mr-1 font-normal">at</span>
            {game.home_team}
          </ScoreBugTeam>
        </div>
        <ChevronRight
          aria-hidden
          className="text-ink-muted group-hover:text-ink mt-0.5 size-4 shrink-0 transition-colors"
        />
      </div>

      <p className="text-ink-muted border-line mt-3 flex flex-wrap gap-x-2 border-t pt-2.5 text-detail">
        <span className={completed ? 'text-ink font-semibold' : undefined}>
          {completed ? 'Final' : formatGameDay(game.gameday)}
        </span>
        {lines.map((line) => (
          <span key={line} className="tnum">
            <span aria-hidden className="mr-2">·</span>
            {line}
          </span>
        ))}
      </p>
    </Link>
  )
}

/**
 * `home_spread` as a book would print it.
 *
 * The API's field is points the home team is favoured by, so a positive number
 * means the home team is the favourite and prints with a minus beside their
 * abbreviation. Getting this backwards would invert every game on the slate,
 * which is why it is one named function rather than an inline sign flip.
 */
function describeSpread(game: Game): string {
  const spread = game.home_spread as number
  if (spread === 0) return 'Pick’em'
  const favourite = spread > 0 ? game.home_team : game.away_team
  return `${favourite} −${Math.abs(spread).toFixed(1)}`
}
