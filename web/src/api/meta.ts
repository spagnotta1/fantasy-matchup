/**
 * Capability endpoints.
 *
 * The API serves its own vocabulary — which positions are projected, which
 * scoring formats exist, which lineup slots can be simulated — precisely so a
 * client does not hard-code it. Every one of these is fetched rather than
 * declared as a constant, which is what makes shipping a kicker model a
 * server-side change with no frontend release.
 */

import { z } from 'zod'

import { request, requestBare } from './client'
import {
  cacheRuleSchema,
  healthSchema,
  lineupSlotSchema,
  positionSupportSchema,
  provenanceLegendSchema,
  seasonSchema,
  teamSchema,
} from './schemas'

export function getHealth(signal?: AbortSignal) {
  return requestBare('/health', healthSchema, { signal })
}

/**
 * Seasons with a published board, newest first, each with its weeks.
 *
 * Not every season in the warehouse — the API filters to what has actually been
 * projected, so this is safe to put straight into a picker.
 */
export async function getSeasons(signal?: AbortSignal) {
  return (await request('/seasons', z.array(seasonSchema), { signal })).data
}

/**
 * Weeks of one season that have a *published* run.
 *
 * The shell does not need this — `getSeasons` already carries every season's
 * weeks, and one request beats one per season on first paint. Kept because it
 * is the cheap answer for a view that cares about a single season and holds no
 * season list.
 */
export async function getPublishedWeeks(season: number, signal?: AbortSignal) {
  return (await request(`/seasons/${season}/weeks`, z.array(z.number()), { signal })).data
}

export async function getScoringProfiles(signal?: AbortSignal) {
  const response = await request('/meta/scoring-profiles', z.array(z.string()), { signal })
  return { profiles: response.data, defaultProfile: response.meta.scoring_profile ?? null }
}

export async function getPositions(signal?: AbortSignal) {
  return (await request('/meta/positions', z.array(positionSupportSchema), { signal })).data
}

export async function getLineupSlots(signal?: AbortSignal) {
  const response = await request('/meta/lineup-slots', z.array(lineupSlotSchema), { signal })
  return { slots: response.data, formats: response.meta.notices }
}

export async function getProvenanceLegend(signal?: AbortSignal) {
  return (await request('/meta/provenance', provenanceLegendSchema, { signal })).data
}

export async function getTeams(signal?: AbortSignal) {
  return (await request('/teams', z.array(teamSchema), { signal })).data
}

/** The frozen foundation and what it was measured to do. Free-form by design. */
export async function getModelFoundation(signal?: AbortSignal) {
  return (await request('/meta/model', z.record(z.string(), z.unknown()), { signal })).data
}

export async function getCachePolicy(signal?: AbortSignal) {
  return (await request('/meta/cache', z.array(cacheRuleSchema), { signal })).data
}
