import { sizedLogo, useTeamBrand } from '@/hooks/useTeamBrand'
import { cn } from '@/utils/cn'

const PX = { xs: 16, sm: 24, md: 32, lg: 56 } as const
// The one place type is set off the scale, on purpose. These are initials
// inside a disc of fixed size, standing in for a logo that failed to load: the
// letters have to fit the disc, and at 16-32px the smallest type token does not.
const BOX = { xs: 'size-4 text-[0.5rem]', sm: 'size-6 text-[0.5625rem]', md: 'size-8 text-[0.625rem]', lg: 'size-14 text-detail' } as const

/**
 * A team's logo, or its abbreviation where there is none.
 *
 * Decorative: the abbreviation or name is always written beside it, so the
 * image carries `alt=""` and a missing logo loses nothing a reader needs.
 */
export function TeamLogo({
  team,
  size = 'sm',
  className,
}: {
  team: string | null | undefined
  size?: keyof typeof PX
  className?: string
}) {
  const brand = useTeamBrand(team)
  const px = PX[size]

  if (!brand?.logo_url) {
    return (
      <span
        aria-hidden
        className={cn(
          'bg-surface-sunken text-ink-muted flex shrink-0 items-center justify-center rounded-full font-semibold',
          BOX[size],
          className,
        )}
      >
        {team ?? '—'}
      </span>
    )
  }

  return (
    <img
      src={sizedLogo(brand.logo_url, px * 2)}
      srcSet={`${sizedLogo(brand.logo_url, px)} 1x, ${sizedLogo(brand.logo_url, px * 2)} 2x`}
      width={px}
      height={px}
      alt=""
      loading="lazy"
      decoding="async"
      className={cn('shrink-0 object-contain', BOX[size], className)}
    />
  )
}
