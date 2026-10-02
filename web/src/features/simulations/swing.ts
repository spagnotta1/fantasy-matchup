import type { SimulatedPlayer } from '@/api/schemas'
import { formatPoints } from '@/utils/format'

export interface Swing {
  player: SimulatedPlayer
  side: string
  floor: number
  ceiling: number
  spread: number
}

/**
 * Players whose range is the same width, to the precision the screen prints.
 *
 * A group of one is an ordinary row. A group of several is a tie: its members
 * are listed in lineup order and are not ranked against each other.
 */
export interface SwingGroup {
  /** The width as printed, e.g. `"22.8"`. Equality is decided on this. */
  width: string
  members: Swing[]
  /** How many players share this width, including any not listed. */
  size: number
  /** Members left out because the list is full. Only ever on the last group. */
  hidden: number
}

/** A player with a published range who has not finished their game. */
export function collectSwings(players: SimulatedPlayer[], side: string): Swing[] {
  const swings: Swing[] = []
  for (const player of players) {
    if (player.final) continue
    const { floor, ceiling } = player
    if (floor === null || floor === undefined || ceiling === null || ceiling === undefined) continue
    swings.push({ player, side, floor, ceiling, spread: ceiling - floor })
  }
  return swings
}

/**
 * Order players by how wide their range is, without inventing an order
 * between players whose ranges are the same width.
 *
 * The widths are not continuous. Ranges are shared across groups of players
 * with similar projections, so on a published run five of a lineup's six widest
 * ranges can be identical — and a list sorted by width then printed in sequence
 * presents a five-way tie as first to fifth, in whatever order the array held
 * them. So equal widths are returned as one group, in the order the players
 * were given (their lineup order), and the caller says they are tied.
 *
 * "Equal" means equal as printed. Two rows that both read "22.8 wide" are a tie
 * to the reader whatever the fourth decimal says, and the stored quantiles are
 * not precise enough for that decimal to mean anything.
 *
 * The list is capped at `limit` players. When the cap falls inside a tie the
 * group is cut in lineup order and reports how many it left out, so the cut is
 * never mistaken for a ranking either.
 */
export function groupSwingsByWidth(swings: Swing[], limit: number): SwingGroup[] {
  const byWidth = new Map<string, Swing[]>()
  for (const swing of swings) {
    const width = formatPoints(swing.spread)
    const members = byWidth.get(width)
    if (members) members.push(swing)
    else byWidth.set(width, [swing])
  }

  const ordered = [...byWidth.entries()].sort(
    ([left], [right]) => Number(right) - Number(left),
  )

  const groups: SwingGroup[] = []
  let room = Math.max(0, limit)
  for (const [width, members] of ordered) {
    if (room === 0) break
    const shown = members.slice(0, room)
    groups.push({ width, members: shown, size: members.length, hidden: members.length - shown.length })
    room -= shown.length
  }
  return groups
}
