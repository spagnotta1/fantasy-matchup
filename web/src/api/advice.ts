/**
 * Start/sit and comparison — the only endpoints that recommend.
 *
 * Two response properties are contractual and the UI must not soften either:
 * `recommended` is null for a toss-up, and `caveats` carries the availability
 * and correlation warnings. Dropping them presents a more confident
 * recommendation than the API made.
 */

import { request } from './client'
import { comparisonSchema, startSitSchema } from './schemas'
import { slateQuery, type SlateParams } from './projections'

export function getStartSit(
  playerA: string,
  playerB: string,
  params: SlateParams = {},
  signal?: AbortSignal,
) {
  return request('/start-sit', startSitSchema, {
    signal,
    params: { ...slateQuery(params), player_a: playerA, player_b: playerB },
  })
}

/** Up to six players. Entries are ordered by expectation; pairs are consecutive. */
export function comparePlayers(playerIds: string[], params: SlateParams = {}, signal?: AbortSignal) {
  return request('/compare', comparisonSchema, {
    signal,
    params: { ...slateQuery(params), player_ids: playerIds },
  })
}
