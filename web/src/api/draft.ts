/**
 * Mock draft. Two POSTs and one GET.
 *
 * The analysis calls are slow by nature — they run hundreds or thousands of
 * *complete drafts* server-side, measured at about 8 ms each — so they take a
 * longer budget than the matchup simulation, which sums curves rather than
 * drafting. The configuration call is a normal
 * GET and is cached hard: it is the same answer for everyone until a projection
 * run publishes.
 *
 * Nothing is persisted server-side. A result is reproducible from
 * `{settings, model run, historical panel, seed}` alone, all four of which come
 * back in the response, which is why there is no "saved draft" endpoint to wrap
 * here.
 */

import { request, DRAFT_TIMEOUT_MS } from './client'
import {
  draftAnalysisSchema,
  draftComparisonSchema,
  draftConfigSchema,
  type DraftAnalysisRequest,
  type DraftRequest,
} from './schemas'

export function getDraftConfig(signal?: AbortSignal) {
  return request('/mock-draft/config', draftConfigSchema, { signal })
}

export function analyzeDraftPosition(body: DraftAnalysisRequest, signal?: AbortSignal) {
  return request('/mock-draft/analyze', draftAnalysisSchema, {
    method: 'POST',
    body,
    signal,
    timeoutMs: DRAFT_TIMEOUT_MS,
  })
}

export function compareDraftPositions(body: DraftRequest, signal?: AbortSignal) {
  return request('/mock-draft/compare', draftComparisonSchema, {
    method: 'POST',
    body,
    signal,
    timeoutMs: DRAFT_TIMEOUT_MS,
  })
}
