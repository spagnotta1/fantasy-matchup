import { useMemo } from 'react'
import { Link } from 'react-router-dom'

import { Card, CardHeader } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/feedback/States'
import { useTeams } from '@/hooks/useCatalog'
import { useGames } from '@/hooks/useMatchups'
import type { Game, Team } from '@/api/schemas'

/**
 * Every team, by division, with this week's opponent.
 *
 * A way in, not an analysis: it answers "where is my team's page" and, at a
 * glance, who everyone plays. The analysis is one click further, on the team's
 * own page.
 *
 * It is a view of Matchups. It used to be a page and a sidebar entry of its
 * own, but it is the same week's games read by team instead of by game, and
 * that is what the other Matchups views already are.
 */
export function TeamGrid() {
  const teams = useTeams()
  const games = useGames()

  const gameByTeam = useMemo(() => {
    const map = new Map<string, Game>()
    for (const game of games.data?.data ?? []) {
      map.set(game.home_team, game)
      map.set(game.away_team, game)
    }
    return map
  }, [games.data])

  const divisions = useMemo(() => {
    const grouped = new Map<string, Team[]>()
    for (const team of teams.data ?? []) {
      const key = team.division ?? 'Other'
      grouped.set(key, [...(grouped.get(key) ?? []), team])
    }
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [teams.data])

  if (teams.isPending) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 8 }, (_, index) => (
          <Skeleton key={index} className="h-48 rounded-[var(--radius-card)]" />
        ))}
      </div>
    )
  }

  if (teams.isError) {
    return (
      <Card>
        <ErrorState error={teams.error} onRetry={() => void teams.refetch()} />
      </Card>
    )
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {divisions.map(([division, members]) => (
        <Card key={division}>
          <CardHeader as="h2" title={division} />
          <ul className="divide-line divide-y">
            {members.map((team) => (
              <li key={team.abbr}>
                <TeamTile team={team} game={gameByTeam.get(team.abbr)} />
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  )
}

/** A team's logo from the catalogue, or its abbreviation in a disc where there is none. */
export function TeamCrest({ team, size = 'md' }: { team: Pick<Team, 'abbr' | 'logo_url'>; size?: 'md' | 'lg' }) {
  const box = size === 'lg' ? 'size-14' : 'size-8'
  return team.logo_url ? (
    <img src={team.logo_url} alt="" className={`${box} shrink-0 object-contain`} loading="lazy" />
  ) : (
    <span
      aria-hidden
      className={`${box} bg-surface-sunken text-ink-muted flex shrink-0 items-center justify-center rounded-full text-detail font-semibold`}
    >
      {team.abbr}
    </span>
  )
}

function TeamTile({ team, game }: { team: Team; game: Game | undefined }) {
  const isHome = game?.home_team === team.abbr
  const opponent = game ? (isHome ? game.away_team : game.home_team) : null
  return (
    <Link
      to={`/teams/${team.abbr}`}
      className="hover:bg-surface-hover flex items-center gap-3 px-4 py-2.5 transition-colors"
    >
      <TeamCrest team={team} />
      <span className="min-w-0 flex-1">
        <span className="text-ink block truncate text-sm font-medium">{team.name ?? team.abbr}</span>
        <span className="text-ink-muted block text-detail">
          {opponent ? `${isHome ? 'vs' : '@'} ${opponent}` : 'Bye this week'}
        </span>
      </span>
    </Link>
  )
}
