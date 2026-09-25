/** The track record and strength of schedule — planning and accountability reads. */

import { request } from './client'
import { liveSlateSchema, scheduleStrengthSchema, trackRecordSchema } from './schemas'
import { slateQuery, type SlateParams } from './projections'

export interface TrackRecordParams {
  /** Restrict every aggregate to one season. Omit for all seasons. */
  season?: number | null
  /** The scorecard's week within `season`. */
  week?: number | null
  scoringProfile?: string | null
}

export function getTrackRecord(params: TrackRecordParams = {}, signal?: AbortSignal) {
  return request('/track-record', trackRecordSchema, {
    signal,
    params: {
      season: params.season,
      week: params.week,
      scoring_profile: params.scoringProfile,
    },
  })
}

/** Every team's remaining schedule for one position, graded on current form. */
export function getScheduleStrength(
  position: string,
  params: Pick<SlateParams, 'season' | 'week'> = {},
  signal?: AbortSignal,
) {
  return request('/schedule-strength', scheduleStrengthSchema, {
    signal,
    params: { season: params.season, week: params.week, position },
  })
}

/** Games in progress and every started player's unofficial points so far. */
export function getLive(params: SlateParams = {}, signal?: AbortSignal) {
  return request('/live', liveSlateSchema, { signal, params: slateQuery(params) })
}
