/** The ranked board, position rankings, and a single player's week. */

import { z } from 'zod'

import { request, type QueryValue } from './client'
import { projectionSchema, rankedProjectionSchema } from './schemas'

/** Season, week and scoring format — the arguments almost everything takes. */
export interface SlateParams {
  season?: number | null
  week?: number | null
  scoringProfile?: string | null
}

export function slateQuery(params: SlateParams): Record<string, QueryValue> {
  return {
    season: params.season,
    week: params.week,
    scoring_profile: params.scoringProfile,
  }
}

export interface BoardParams extends SlateParams {
  positions?: string[]
  teams?: string[]
  limit?: number
  offset?: number
  modelName?: string | null
}

/**
 * The ranked board.
 *
 * Returns the whole envelope rather than just `data`, because for this endpoint
 * the meta *is* half the answer: `meta.model === null` distinguishes "no run is
 * published for this week" from "this week has no players", and the two need
 * completely different screens.
 */
export function getBoard(params: BoardParams = {}, signal?: AbortSignal) {
  return request('/projections', z.array(rankedProjectionSchema), {
    signal,
    params: {
      ...slateQuery(params),
      positions: params.positions,
      teams: params.teams,
      limit: params.limit,
      offset: params.offset,
      model_name: params.modelName,
    },
  })
}

/** A single-position board. A recognised but unprojected position (K, DST) is a 422. */
export function getPositionRankings(
  position: string,
  params: SlateParams & { limit?: number } = {},
  signal?: AbortSignal,
) {
  return request(`/rankings/${encodeURIComponent(position)}`, z.array(rankedProjectionSchema), {
    signal,
    params: { ...slateQuery(params), limit: params.limit },
  })
}

export function getProjection(playerId: string, params: SlateParams = {}, signal?: AbortSignal) {
  return request(`/projections/${encodeURIComponent(playerId)}`, projectionSchema, {
    signal,
    params: slateQuery(params),
  })
}
