import { Link } from 'react-router-dom'

import { cn } from '@/utils/cn'
import type { Player } from '@/api/schemas'

/**
 * A player's headshot, initials fallback and name block.
 *
 * One component because it appears in five places and drifting versions of
 * "name, position, team" is how an interface stops looking like one product.
 */
export function PlayerAvatar({
  player,
  size = 'md',
}: {
  player: Pick<Player, 'name' | 'headshot_url'>
  size?: 'sm' | 'md' | 'lg'
}) {
  const sizes = { sm: 'size-8 text-[0.625rem]', md: 'size-10 text-xs', lg: 'size-16 text-lg' } as const
  const initials = player.name
    .split(' ')
    .slice(0, 2)
    .map((part) => part.charAt(0))
    .join('')

  return (
    <span
      className={cn(
        'bg-surface-sunken text-ink-muted relative flex shrink-0 items-center justify-center overflow-hidden rounded-full font-semibold',
        sizes[size],
      )}
    >
      {/* Initials sit underneath rather than in a fallback branch: the headshot
          host is external, and an image that 404s should reveal them without a
          load-error handler and a re-render. */}
      <span aria-hidden>{initials}</span>
      {player.headshot_url && (
        <img
          src={player.headshot_url}
          alt=""
          loading="lazy"
          decoding="async"
          className="absolute inset-0 size-full object-cover"
        />
      )}
    </span>
  )
}

interface PlayerIdentityProps {
  player: Player
  /** Overrides `player.team`, which is the dimension record rather than the week's team. */
  team?: string | null
  /** Wraps the name in a link to the detail page. */
  link?: boolean
  size?: 'sm' | 'md' | 'lg'
  /** Rendered under the name instead of the default "POS · TEAM" line. */
  subtitle?: React.ReactNode
  className?: string
}

export function PlayerIdentity({
  player,
  team,
  link = true,
  size = 'md',
  subtitle,
  className,
}: PlayerIdentityProps) {
  const meta = [player.position, team ?? player.team].filter(Boolean).join(' · ')

  const name = (
    <span
      className={cn(
        'text-ink truncate font-medium',
        size === 'lg' ? 'text-lg' : size === 'sm' ? 'text-sm' : 'text-sm',
      )}
    >
      {player.name}
    </span>
  )

  return (
    <span className={cn('flex min-w-0 items-center gap-3', className)}>
      <PlayerAvatar player={player} size={size} />
      <span className="flex min-w-0 flex-col">
        {link ? (
          <Link
            to={`/players/${encodeURIComponent(player.player_id)}`}
            className="hover:text-accent-text min-w-0 rounded-sm transition-colors"
          >
            {name}
          </Link>
        ) : (
          name
        )}
        <span className="text-ink-muted truncate text-xs">{subtitle ?? meta}</span>
      </span>
    </span>
  )
}
