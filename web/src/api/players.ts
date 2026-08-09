/** The player index, name search, history and the assembled profile. */

import { z } from 'zod'

import { request } from './client'
import { historicalWeekSchema, playerProfileSchema, playerSchema } from './schemas'
import { slateQuery, type SlateParams } from './projections'

export interface PlayerListParams {
  positions?: string[]
  teams?: string[]
  activeOnly?: boolean
  limit?: number
  offset?: number
}

/**
 * Browse the index. Ordered by name, not by anything derived — a listing that
 * reorders itself between pages makes paging skip players.
 */
export function listPlayers(params: PlayerListParams = {}, signal?: AbortSignal) {
  return request('/players', z.array(playerSchema), {
    signal,
    params: {
      positions: params.positions,
      teams: params.teams,
      active_only: params.activeOnly,
      limit: params.limit,
      offset: params.offset,
    },
  })
}

/** Name search. The API requires a minimum length; callers should not fire below it. */
export async function searchPlayers(
  query: string,
  params: { limit?: number; positions?: string[]; activeOnly?: boolean } = {},
  signal?: AbortSignal,
) {
  const response = await request('/search', z.array(playerSchema), {
    signal,
    params: {
      q: query,
      limit: params.limit,
      positions: params.positions,
      active_only: params.activeOnly,
    },
  })
  return response.data
}

export async function getPlayer(playerId: string, signal?: AbortSignal) {
  return (await request(`/players/${encodeURIComponent(playerId)}`, playerSchema, { signal })).data
}

export function getPlayerHistory(
  playerId: string,
  params: { scoringProfile?: string | null; weeks?: number } = {},
  signal?: AbortSignal,
) {
  return request(`/players/${encodeURIComponent(playerId)}/history`, z.array(historicalWeekSchema), {
    signal,
    params: { scoring_profile: params.scoringProfile, weeks: params.weeks },
  })
}

/** Everything the player page needs, in one call. Only an unknown player 404s. */
export function getPlayerProfile(
  playerId: string,
  params: SlateParams & { weeks?: number } = {},
  signal?: AbortSignal,
) {
  return request(`/players/${encodeURIComponent(playerId)}/profile`, playerProfileSchema, {
    signal,
    params: { ...slateQuery(params), weeks: params.weeks },
  })
}
