/**
 * Whether a lineup can actually be simulated, decided before the run.
 *
 * The engine refuses a whole matchup if any one starter has no published
 * projection — correctly, because a team total is a sum and a missing starter
 * removes their entire contribution rather than making the answer slightly less
 * complete. The refusal arrives as a 422 whose message names the player in a
 * paragraph, after the user has filled fourteen slots and pressed Run.
 *
 * Everything needed to see that coming is already on screen: the week's board is
 * fetched for autofill and the per-row projection, and a player who is not on it
 * has no projection this week. So the condition is surfaced on the row that
 * causes it, while it can still be fixed in one click.
 *
 * Two things this is careful about.
 *
 * **The server stays the authority.** This pre-empts a refusal, it does not
 * replace one. Nothing here decides a lineup is *valid* — the composition, the
 * slot eligibility and the final word on every player all remain the API's, and
 * a lineup that passes these checks is still submitted and can still be refused.
 *
 * **It does not guess when it cannot see.** The board is one page, and if it is
 * ever truncated a player's absence from it stops meaning anything. In that
 * state every row is reported `unknown` and nothing is blocked, because a false
 * "this player has no projection" on a player who has one is a worse failure
 * than the 422 this exists to avoid.
 */

import type { Page, PositionSupport, RankedProjection } from '@/api/schemas'
import type { LineupRow } from './lineupFormat'

/** Why a filled slot cannot be simulated. Mirrors the API's own reason codes. */
export type UnavailableReason = 'no_projection' | 'unprojected_position'

export type SlotStatus =
  | { kind: 'empty' }
  | { kind: 'ready'; projection: RankedProjection['projection'] }
  /** No claim either way — the board is not fully in hand. */
  | { kind: 'unknown' }
  | { kind: 'unavailable'; reason: UnavailableReason; detail: string }

/**
 * The week's board, indexed by player, or `null` when it cannot be trusted as a
 * complete list of who is projected.
 */
export interface BoardIndex {
  byPlayer: Map<string, RankedProjection['projection']>
  /** False when the board was truncated, or has not arrived yet. */
  complete: boolean
  /** Still in flight. Distinct from `complete`: a *truncated* board has arrived. */
  pending: boolean
}

export function indexBoard(
  entries: RankedProjection[],
  page: Page | null | undefined,
  pending: boolean,
): BoardIndex {
  const byPlayer = new Map<string, RankedProjection['projection']>()
  for (const entry of entries) {
    byPlayer.set(entry.projection.player.player_id, entry.projection)
  }
  // `total` is the count before paging. Holding fewer rows than that means the
  // board on screen is a page of the slate rather than the slate.
  const truncated = page ? page.total > entries.length : false
  return { byPlayer, complete: !pending && entries.length > 0 && !truncated, pending }
}

/** Positions the engine projects, from `/meta/positions`. */
export function projectedPositions(support: PositionSupport[] | undefined): Set<string> | null {
  if (!support || support.length === 0) return null
  return new Set(support.filter((entry) => entry.projected).map((entry) => entry.position))
}

/**
 * What one slot is, right now.
 *
 * The two unavailable reasons are worth separating for the same reason the API
 * separates them: a kicker will never have a projection and the lineup has to be
 * built around it, while a receiver on bye has one next week. The copy differs
 * because the action does.
 */
export function slotStatus(
  row: LineupRow,
  board: BoardIndex,
  projected: Set<string> | null,
  week: number | null,
): SlotStatus {
  if (!row.player) return { kind: 'empty' }

  const projection = board.byPlayer.get(row.player.player_id)
  if (projection) return { kind: 'ready', projection }
  if (!board.complete) return { kind: 'unknown' }

  const position = row.player.position
  if (position && projected && !projected.has(position)) {
    return {
      kind: 'unavailable',
      reason: 'unprojected_position',
      detail: `${position} is not a position this engine projects, so this slot cannot be simulated.`,
    }
  }

  return {
    kind: 'unavailable',
    reason: 'no_projection',
    detail: `No projection published for week ${week ?? '—'} — a bye, an inactive designation, or a run that has not covered them.`,
  }
}

export interface LineupProblem {
  slot: string
  name: string
  detail: string
  reason: UnavailableReason
}

export interface LineupReadiness {
  /** Slots with nobody in them. */
  empty: number
  /** Filled slots the engine will refuse. */
  problems: LineupProblem[]
  /** Every slot is filled with somebody the engine can sample. */
  runnable: boolean
}

export function lineupReadiness(
  rows: LineupRow[],
  board: BoardIndex,
  projected: Set<string> | null,
  week: number | null,
): LineupReadiness {
  let empty = 0
  const problems: LineupProblem[] = []

  for (const row of rows) {
    const status = slotStatus(row, board, projected, week)
    if (status.kind === 'empty') empty += 1
    else if (status.kind === 'unavailable') {
      problems.push({
        slot: row.slot,
        name: row.player?.name ?? row.slot,
        detail: status.detail,
        reason: status.reason,
      })
    }
  }

  return { empty, problems, runnable: rows.length > 0 && empty === 0 && problems.length === 0 }
}
