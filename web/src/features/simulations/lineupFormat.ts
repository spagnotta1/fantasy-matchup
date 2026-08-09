/**
 * The lineup a simulation must be filled to.
 *
 * The API serves the slot *vocabulary* as structured data (`/meta/lineup-slots`
 * returns each slot's eligible positions and whether it can be simulated) but
 * serves the *composition* — how many of each slot a format starts — only as
 * prose in `meta.notices`:
 *
 *     Standard skill lineup (QB/RB/RB/WR/WR/TE/FLEX) (standard_skill): 1xQB, 2xRB, 2xWR, 1xTE, 1xFLEX
 *
 * That string is generated from the format's own requirements
 * (`f"{r['count']}x{r['slot']}"` in the meta router), and the identical shape
 * appears in the 422 the endpoint raises for a wrong lineup, so it is stable
 * enough to read. It is still prose, and this is the one place in the client
 * that parses any: a structured `lineup_formats` block in the response would
 * retire this file, and that is the single API gap worth closing for this view.
 *
 * The parser is written to fail into a usable state rather than a broken one.
 * If the notice ever stops matching, `parseLineupFormats` returns nothing, the
 * builder falls back to one row per simulable slot, and the API's own
 * validation — which is the authority either way — corrects the user.
 */

import type { LineupSlot, Player, RankedProjection } from '@/api/schemas'

export interface SlotRequirement {
  slot: string
  count: number
}

export interface LineupFormat {
  /** The machine name, e.g. `standard_skill`. */
  name: string
  /** The human label, e.g. `Standard skill lineup (QB/RB/RB/WR/WR/TE/FLEX)`. */
  label: string
  requirements: SlotRequirement[]
  /** Total starters. Both lineups must hold exactly this many. */
  size: number
}

/** `<label> (<name>): 1xQB, 2xRB, …` */
const FORMAT_PATTERN = /^(.+?)\s+\(([a-z0-9_]+)\):\s*(.+)$/
const REQUIREMENT_PATTERN = /(\d+)\s*x\s*([A-Z]+)/g

export function parseLineupFormats(notices: string[]): LineupFormat[] {
  const formats: LineupFormat[] = []

  for (const notice of notices) {
    const match = FORMAT_PATTERN.exec(notice)
    const label = match?.[1]
    const name = match?.[2]
    const tail = match?.[3]
    if (!label || !name || !tail) continue

    const requirements: SlotRequirement[] = []
    for (const requirement of tail.matchAll(REQUIREMENT_PATTERN)) {
      const slot = requirement[2]
      const count = Number.parseInt(requirement[1] ?? '', 10)
      if (slot && Number.isFinite(count) && count > 0) requirements.push({ slot, count })
    }
    if (requirements.length === 0) continue

    formats.push({
      name,
      label,
      requirements,
      size: requirements.reduce((total, requirement) => total + requirement.count, 0),
    })
  }

  return formats
}

/**
 * The format to build against, or a fallback.
 *
 * The fallback is one of every simulable slot. It will not match any real
 * league, and it is not meant to — it exists so the screen still functions if
 * the notice format changes, with the API rejecting the lineup and saying what
 * it wanted.
 */
export function resolveFormat(formats: LineupFormat[], slots: LineupSlot[]): LineupFormat {
  const first = formats[0]
  if (first) return first

  const requirements = slots
    .filter((slot) => slot.supported)
    .map((slot) => ({ slot: slot.slot, count: 1 }))

  return {
    name: 'unknown',
    label: 'Lineup',
    requirements,
    size: requirements.length,
  }
}

/** One row per starter: `['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX']`. */
export function expandSlots(format: LineupFormat): string[] {
  return format.requirements.flatMap((requirement) =>
    Array.from({ length: requirement.count }, () => requirement.slot),
  )
}

/** Positions a slot accepts, from the catalog. Unknown slots accept nothing. */
export function eligiblePositions(slots: LineupSlot[], slot: string): string[] {
  return slots.find((entry) => entry.slot === slot)?.eligible_positions ?? []
}

/** A filled or empty starting spot. `key` is stable across edits for React. */
export interface LineupRow {
  key: string
  slot: string
  player: Player | null
}

/** The empty lineup a format requires, one row per starter. */
export function emptyLineup(format: LineupFormat): LineupRow[] {
  return expandSlots(format).map((slot, index) => ({
    key: `${slot}-${index}`,
    slot,
    player: null,
  }))
}

/**
 * Fill empty slots with the highest-projected eligible players.
 *
 * Walks the API's board in the order the API ranked it and takes the first
 * eligible player not already spoken for. That is **not** an optimal lineup:
 * filling slots greedily in order can leave a better total on the table, and no
 * optimiser exists in this product to claim otherwise. It is a starting point.
 *
 * `taken` must include the *opposing* lineup as well as this one. Autofilling
 * both sides from one board otherwise hands each of them the same seven players
 * and returns a 50/50 — arithmetically correct, useless as a starting point,
 * and not a matchup that can exist, since two managers in a league cannot start
 * the same player.
 *
 * Pure, so the caller can run it inside a functional state update and never see
 * a stale view of the other lineup.
 */
export function autofillLineup(
  rows: LineupRow[],
  board: RankedProjection[],
  slots: LineupSlot[],
  taken: Iterable<string>,
): LineupRow[] {
  const used = new Set(taken)
  for (const row of rows) {
    if (row.player) used.add(row.player.player_id)
  }

  return rows.map((row) => {
    if (row.player) return row
    const eligible = eligiblePositions(slots, row.slot)
    const pick = board.find((entry) => {
      const { player } = entry.projection
      if (used.has(player.player_id)) return false
      return player.position ? eligible.includes(player.position) : false
    })
    if (!pick) return row
    used.add(pick.projection.player.player_id)
    return { ...row, player: pick.projection.player }
  })
}
