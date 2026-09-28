import type { ReactNode } from 'react'

import { TeamLogo } from '@/components/domain/TeamLogo'
import { useTeamBrand } from '@/hooks/useTeamBrand'
import { cn } from '@/utils/cn'

/**
 * One team's line in a broadcast score bug: colour tab, logo, name, score.
 *
 * Shared by the Matchups slate and the Live ticker so a game looks like the
 * same object on both. The colour tab is decoration (see `useTeamBrand`); the
 * abbreviation beside it is what identifies the team. On a final, the losing
 * side drops to the secondary ink rather than to an opacity, which keeps it
 * inside the palette's measured contrast.
 */
export function ScoreBugTeam({
  team,
  score,
  trailing = false,
  children,
  className,
}: {
  team: string
  /** Omitted before kickoff: a 0–0 that has not happened is not a score. */
  score?: number | null
  trailing?: boolean
  /** Rendered after the abbreviation, e.g. a link wrapper's content. */
  children?: ReactNode
  className?: string
}) {
  const brand = useTeamBrand(team)
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <span
        aria-hidden
        className="h-5 w-1 shrink-0 rounded-full"
        style={{ background: brand?.primary_color ?? 'var(--color-line-strong)' }}
      />
      <TeamLogo team={team} size="sm" />
      <span
        className={cn(
          'min-w-0 flex-1 truncate text-sm font-semibold tracking-tight',
          trailing ? 'text-ink-secondary' : 'text-ink',
        )}
      >
        {children ?? team}
      </span>
      {score !== undefined && (
        <span className={cn('tnum text-lg leading-none font-bold', trailing ? 'text-ink-secondary' : 'text-ink')}>
          {score ?? '—'}
        </span>
      )}
    </div>
  )
}

/** The two teams' colours side by side, as a thin bar along a tile's top edge. */
export function MatchupColorBar({ away, home }: { away: string; home: string }) {
  const awayBrand = useTeamBrand(away)
  const homeBrand = useTeamBrand(home)
  return (
    <span aria-hidden className="absolute inset-x-0 top-0 flex h-1">
      <span className="flex-1" style={{ background: awayBrand?.primary_color ?? 'var(--color-line)' }} />
      <span className="flex-1" style={{ background: homeBrand?.primary_color ?? 'var(--color-line)' }} />
    </span>
  )
}
