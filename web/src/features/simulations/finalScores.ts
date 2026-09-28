import type { LiveSlate, Projection } from '@/api/schemas'

/** What a starter scored in a game that is over. Provenance `actual`. */
export interface KnownFinal {
  points: number
  /** False: ESPN's box score, until the official line is loaded. */
  official: boolean
}

/**
 * Unofficial final scores from the live feed, for games that are over.
 *
 * Only `post` games. A game in progress has a partial score, which is not a
 * result — the simulation keeps sampling that player's projection, and the
 * builder keeps showing it, so the two never disagree about who is settled.
 */
export function liveFinals(live: LiveSlate | undefined): Map<string, KnownFinal> {
  const finals = new Map<string, KnownFinal>()
  if (!live) return finals
  const over = new Set(live.games.filter((game) => game.state === 'post').map((game) => game.event_id))
  for (const player of live.players) {
    if (over.has(player.event_id)) {
      finals.set(player.player_id, { points: player.live_points, official: false })
    }
  }
  return finals
}

/**
 * The score a lineup row should show in place of its projection, if any.
 *
 * The same order of authority the simulation uses: the official line when the
 * week is loaded, the live feed's final box score before that.
 */
export function knownFinal(
  playerId: string,
  projection: Projection | undefined,
  live: Map<string, KnownFinal>,
): KnownFinal | null {
  if (projection?.actual_points !== null && projection?.actual_points !== undefined) {
    return { points: projection.actual_points, official: true }
  }
  return live.get(playerId) ?? null
}
