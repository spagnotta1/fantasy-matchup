import { useMemo, type CSSProperties } from 'react'

import { useTeams } from '@/hooks/useCatalog'
import type { Team } from '@/api/schemas'

/**
 * Team colours and logos, as nflverse publishes them.
 *
 * Read from the cached `/teams` catalogue, which every page already holds
 * (the command palette lists teams), so a brand costs no request.
 *
 * Team colour is decoration in this product and nothing else: a stripe, a
 * ring, a wash behind a header. It never colours text, a mark on a chart or
 * anything a reader has to decode, because thirty-two brand palettes cannot be
 * made to clear contrast on both themes, and because colour already means
 * something here — the warm `--app-you` is "your side" in a head-to-head, and
 * CLE, CIN, DEN and MIA would collide with it. Keep it off the simulation.
 */
export function useTeamBrands(): Map<string, Team> {
  const { data } = useTeams()
  return useMemo(() => new Map((data ?? []).map((team) => [team.abbr, team])), [data])
}

export function useTeamBrand(abbr: string | null | undefined): Team | undefined {
  const brands = useTeamBrands()
  return abbr ? brands.get(abbr) : undefined
}

/**
 * The `--team` custom property for a container, or nothing.
 *
 * Components draw with `var(--team)` and fall back to the ink when a team is
 * unknown, so a free agent or a failed catalogue reads as unbranded rather
 * than broken.
 */
export function teamStyle(team: Team | undefined): CSSProperties {
  return team?.primary_color ? ({ '--team': team.primary_color } as CSSProperties) : {}
}

const ESPN_LOGO = /^https:\/\/a\.espncdn\.com(\/i\/teamlogos\/.+\.png)$/

/**
 * A logo URL resized by ESPN's image combiner to `px` square.
 *
 * The published URLs are the 500px originals, ~56 KB each; a 24px score-bug
 * logo resized on request is ~2 KB. Any URL in another shape passes through
 * untouched rather than being guessed at (the same rule as headshots).
 */
export function sizedLogo(url: string, px: number): string {
  const match = ESPN_LOGO.exec(url)
  return match ? `https://a.espncdn.com/combiner/i?img=${match[1]}&w=${px}&h=${px}` : url
}
