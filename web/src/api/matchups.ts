/** Schedule, per-game analysis, defensive form and team outlook. */

import { z } from 'zod'

import { request } from './client'
import {
  gameSchema,
  matchupAnalysisSchema,
  positionMatchupSchema,
  teamOutlookSchema,
  weekSchema,
} from './schemas'
import { slateQuery, type SlateParams } from './projections'

export function getGames(params: Pick<SlateParams, 'season' | 'week'> = {}, signal?: AbortSignal) {
  return request('/games', z.array(gameSchema), {
    signal,
    params: { season: params.season, week: params.week },
  })
}

/**
 * A week: the schedule plus whether a board exists for it.
 *
 * This is the landing call. It answers the question an empty projections list
 * cannot — is there nothing here, or has the projection job simply not run?
 */
export function getWeek(week: number, season?: number | null, signal?: AbortSignal) {
  return request(`/weeks/${week}`, weekSchema, { signal, params: { season } })
}

export function getMatchup(gameId: string, params: SlateParams = {}, signal?: AbortSignal) {
  return request(`/matchups/${encodeURIComponent(gameId)}`, matchupAnalysisSchema, {
    signal,
    params: slateQuery(params),
  })
}

/** Every defence's form as of a week, keyed by team. Rank 1 is the toughest. */
export function getDefenseRankings(
  params: Pick<SlateParams, 'season' | 'week'> & { position?: string | null } = {},
  signal?: AbortSignal,
) {
  return request('/defense-rankings', z.record(z.string(), z.array(positionMatchupSchema)), {
    signal,
    params: { season: params.season, week: params.week, position: params.position },
  })
}

export function getTeamOutlook(team: string, params: SlateParams = {}, signal?: AbortSignal) {
  return request(`/teams/${encodeURIComponent(team)}/outlook`, teamOutlookSchema, {
    signal,
    params: slateQuery(params),
  })
}
