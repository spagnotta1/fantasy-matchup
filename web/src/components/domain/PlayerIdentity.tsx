import { Link } from 'react-router-dom'

import { cn } from '@/utils/cn'
import type { Player } from '@/api/schemas'

/** Rendered diameter of each avatar size, in CSS pixels. Matches `size-8/10/16`. */
const AVATAR_PX = { sm: 32, md: 40, lg: 64 } as const

/** The transform segment nflverse's headshot URLs carry: format and quality only. */
const HEADSHOT_TRANSFORM = /\/image\/(upload|private)\/f_auto,q_auto\//

/**
 * A headshot URL resized by the image host to `px` square, cropped on the face.
 *
 * The URLs arrive asking for the original photograph — 3400×2450, ~760 KB
 * each — and the board draws them 32 pixels wide. A hundred rows downloaded
 * ~76 MB, and decoding them starved the raster threads badly enough that
 * scrolling the board showed blank tiles. The host resizes on request
 * (`w_,h_,c_fill,g_face`), which brings one avatar to ~1.5 KB with the same
 * framing `object-cover` drew. A URL in any other shape is passed through
 * untouched rather than guessed at.
 */
function sizedHeadshot(url: string, px: number): string {
  return url.replace(
    HEADSHOT_TRANSFORM,
    (_, access: string) => `/image/${access}/f_auto,q_auto,w_${px},h_${px},c_fill,g_face/`,
  )
}

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
  const px = AVATAR_PX[size]
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
          src={sizedHeadshot(player.headshot_url, px * 2)}
          srcSet={`${sizedHeadshot(player.headshot_url, px)} 1x, ${sizedHeadshot(player.headshot_url, px * 2)} 2x, ${sizedHeadshot(player.headshot_url, px * 3)} 3x`}
          width={px}
          height={px}
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
