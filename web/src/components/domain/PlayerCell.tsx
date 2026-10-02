import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { RowLink } from '@/components/ui/DataTable'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import type { Player } from '@/api/schemas'

/**
 * Who a table row is about: a 24px headshot, the name, then what places the
 * player this week in grey, then anything that qualifies the row's numbers.
 *
 * One line where there is room for one, which is what keeps a row at 40px, and
 * wrapping where there is not: in a frozen first column on a phone the name
 * takes a line and the rest goes under it. Every table of players draws its
 * first cell with this, so the name is the strongest thing in each of them and
 * a designation sits in the same place on all of them.
 *
 * It goes inside the row's `RowHeaderCell`.
 */
export function PlayerCell({
  player,
  meta,
  rowLink = true,
  children,
}: {
  player: Pick<Player, 'player_id' | 'name' | 'headshot_url'>
  /** Position, team, opponent: one unbroken grey run after the name. */
  meta?: ReactNode
  /**
   * The name is the row's link, and a click anywhere on the row follows it.
   * Turn it off in a row that holds actions of its own, where a press that
   * just misses "Remove" must not leave the page: the name is then an
   * ordinary link and the rest of the row is inert.
   */
  rowLink?: boolean
  /** Caveats and marks after the meta: an injury designation, "My team". */
  children?: ReactNode
}) {
  const to = `/players/${encodeURIComponent(player.player_id)}`
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
      <span className="flex min-w-0 items-center gap-2">
        <PlayerAvatar player={player} size="xs" />
        {rowLink ? (
          <RowLink to={to}>{player.name}</RowLink>
        ) : (
          <Link to={to} className="text-ink hover:text-accent-text rounded-sm font-medium transition-colors">
            {player.name}
          </Link>
        )}
      </span>
      {meta && <span className="text-ink-muted text-detail whitespace-nowrap">{meta}</span>}
      {children}
    </span>
  )
}
