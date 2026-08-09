import { Link } from 'react-router-dom'
import { CalendarX, ChevronRight } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
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
          title="No games scheduled"
          description="The schedule holds no games for the selected week. Pick another week from the header."
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

  return (
    <Link
      to={`/matchups/${encodeURIComponent(game.game_id)}`}
      aria-current={selected ? 'true' : undefined}
      className={[
        'bg-surface hover:border-line-strong focus-visible:outline-focus group block h-full rounded-[var(--radius-card)] border p-4 shadow-card transition-colors',
        selected ? 'border-accent ring-accent/30 ring-2' : 'border-line',
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-ink text-sm font-semibold tracking-tight">
          {game.away_team} <span className="text-ink-muted font-normal">at</span> {game.home_team}
        </p>
        <ChevronRight
          aria-hidden
          className="text-ink-muted group-hover:text-ink size-4 shrink-0 transition-colors"
        />
      </div>

      <p className="text-ink-muted mt-0.5 text-xs">{formatGameDay(game.gameday)}</p>

      {completed && (
        <p className="text-ink-secondary tnum mt-2 text-sm">
          Final {game.away_team} {game.away_score} — {game.home_team} {game.home_score}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {game.home_spread !== null && game.home_spread !== undefined && (
          <Badge tone="neutral">{describeSpread(game)}</Badge>
        )}
        {game.total_line !== null && game.total_line !== undefined && (
          <Badge tone="neutral">O/U {formatPoints(game.total_line)}</Badge>
        )}
        {!completed && game.is_upcoming && <Badge tone="info">Upcoming</Badge>}
      </div>
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
