/**
 * A matchup as a URL.
 *
 * The product's rule everywhere else is that what you are looking at lives in
 * the address bar — the slate does, the rankings position does, the matchup does
 * — because a link is the thing people actually send each other. The simulation
 * was the exception: two lineups took fourteen searches to assemble, lived in
 * component state, and did not survive a refresh, let alone a text message.
 *
 * The encoding is deliberately readable and deliberately thin: slot and player
 * id, in lineup order, which is exactly what `POST /simulations` takes. Order is
 * preserved because the API's seed contract is a statement about the submitted
 * order, so a shared link that reordered the lineup would reproduce different
 * numbers from the same seed.
 *
 *     ?a=QB:00-0036971,RB:00-0038542,…&b=…&sim=10000&mode=independent&seed=7
 *
 * Nothing here resolves a player. The ids are looked up through the same cached
 * player queries the builder already uses, so a link opens on the real dimension
 * rather than on names baked into a URL that could go stale.
 */

import type { LineupEntry } from '@/api/schemas'

export const TEAM_A_PARAM = 'a'
export const TEAM_B_PARAM = 'b'
export const ITERATIONS_PARAM = 'sim'
export const MODE_PARAM = 'mode'
export const SEED_PARAM = 'seed'

/** Bounds a pasted link so a hostile or broken one cannot fill the builder. */
const MAX_ENTRIES = 40

export function encodeLineup(entries: LineupEntry[]): string {
  return entries
    .filter((entry) => entry.player_id)
    .map((entry) => `${entry.slot}:${entry.player_id}`)
    .join(',')
}

/**
 * Read a lineup out of a query parameter.
 *
 * Anything malformed is dropped rather than defended against downstream — a
 * hand-edited URL is not a contract, and the builder shows whatever survived
 * with the remaining slots empty, which is a state the user can see and fix.
 */
export function decodeLineup(value: string | null): LineupEntry[] {
  if (!value) return []
  const entries: LineupEntry[] = []

  for (const pair of value.split(',').slice(0, MAX_ENTRIES)) {
    const [slot, playerId] = pair.split(':')
    if (!slot || !playerId) continue
    entries.push({ slot: slot.trim().toUpperCase(), player_id: playerId.trim() })
  }

  return entries
}

/** The search params that carry a matchup, for merging into the existing ones. */
export function matchupParams(input: {
  teamA: LineupEntry[]
  teamB: LineupEntry[]
  iterations: string
  correlationMode: string
  seed: string
}): Record<string, string> {
  const params: Record<string, string> = {
    [TEAM_A_PARAM]: encodeLineup(input.teamA),
    [TEAM_B_PARAM]: encodeLineup(input.teamB),
    [ITERATIONS_PARAM]: input.iterations,
    [MODE_PARAM]: input.correlationMode,
  }
  // An omitted seed is not the same request as `seed=0`: the API applies its own
  // default when none is named, and echoes what it used.
  if (input.seed) params[SEED_PARAM] = input.seed
  return params
}
