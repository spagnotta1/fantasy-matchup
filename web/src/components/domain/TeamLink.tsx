import { Link } from 'react-router-dom'

import { cn } from '@/utils/cn'

/**
 * A team abbreviation that goes to the team's page.
 *
 * Every place a team is named is a way into its week — the game, the market,
 * its projected players and its run of opponents — so the abbreviation is a
 * link wherever it appears rather than on one dedicated screen.
 */
export function TeamLink({
  team,
  className,
  children,
}: {
  team: string | null | undefined
  className?: string
  children?: React.ReactNode
}) {
  if (!team) return <span className={className}>{children ?? '—'}</span>
  return (
    <Link
      to={`/teams/${encodeURIComponent(team)}`}
      className={cn('hover:text-accent-text rounded-sm underline-offset-2 hover:underline', className)}
    >
      {children ?? team}
    </Link>
  )
}
