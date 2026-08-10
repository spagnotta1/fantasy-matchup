/**
 * The mock draft calls, and the league configuration behind them.
 *
 * Queries rather than mutations, which is the opposite of the matchup
 * simulation and deliberate. A matchup simulation is something a user *runs* at
 * a moment they choose; a draft analysis is something a user *looks at* for a
 * configuration they are editing, and they will come back to it — flipping
 * between seats, changing the roster and changing it back. Modelling it as a
 * query means the second look is instant instead of another minute of
 * simulation, because a request and its answer are a stable pair: the seed
 * travels in the request, so the same settings really do have the same answer.
 *
 * The request is only sent once the user commits it. Editing a form field must
 * not fire a thousand simulated drafts, so the hook takes a *committed*
 * configuration and `enabled` follows it.
 */

import { useQuery } from '@tanstack/react-query'

import * as draftApi from '@/api/draft'
import { keepPreviousSubject } from '@/api/keepPreviousSubject'
import { queryKeys } from '@/api/queryKeys'
import type { DraftAnalysisRequest, DraftRequest, RosterSlot } from '@/api/schemas'

/**
 * Configuration bounds and the seasons that can be drafted.
 *
 * Cached hard: it changes only when a projection run publishes, and every form
 * control on the page is built from it rather than from constants duplicated
 * on the client.
 */
export function useDraftConfig() {
  return useQuery({
    queryKey: queryKeys.draft.config(),
    queryFn: ({ signal }) => draftApi.getDraftConfig(signal),
    staleTime: 30 * 60 * 1000,
  })
}

/**
 * The subject a retained result describes.
 *
 * The season alone. Changing the league size, the roster or the seat re-runs
 * the simulation over the *same board*, and holding the previous answer on
 * screen under a busy state while that happens is honest and much less
 * disruptive than wiping a page of numbers. Changing the season changes the
 * board itself, and last season's rosters under this season's heading would be
 * a lie, so that one blanks.
 */
function subjectOf(request: { season: number } | null) {
  return request ? `season:${request.season}` : null
}

export function useDraftAnalysis(request: DraftAnalysisRequest | null) {
  const subject = subjectOf(request)
  return useQuery({
    queryKey: queryKeys.draft.analyze(request ?? ({} as DraftAnalysisRequest)),
    queryFn: ({ signal }) => draftApi.analyzeDraftPosition(request!, signal),
    enabled: request !== null,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
    // A draft is deterministic in its request, so a cached answer is not stale
    // in any sense that matters — it is the identical computation.
    staleTime: Infinity,
    retry: false,
  })
}

export function useDraftComparison(request: DraftRequest | null) {
  const subject = subjectOf(request)
  return useQuery({
    queryKey: queryKeys.draft.compare(request ?? ({} as DraftRequest)),
    queryFn: ({ signal }) => draftApi.compareDraftPositions(request!, signal),
    enabled: request !== null,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
    staleTime: Infinity,
    retry: false,
  })
}

/** Slot codes a league may start, in the order a roster form should list them. */
export const ROSTER_SLOT_ORDER = ['QB', 'RB', 'WR', 'TE', 'FLEX'] as const
export type RosterSlotCode = (typeof ROSTER_SLOT_ORDER)[number]

export const SLOT_LABELS: Record<string, string> = {
  QB: 'Quarterback',
  RB: 'Running back',
  WR: 'Wide receiver',
  TE: 'Tight end',
  FLEX: 'Flex (RB/WR/TE)',
}

/** Turn the editable roster map back into the API's list form, dropping zeros. */
export function toRosterList(counts: Record<string, number>): RosterSlot[] {
  return ROSTER_SLOT_ORDER.filter((slot) => (counts[slot] ?? 0) > 0).map((slot) => ({
    slot: slot as string,
    count: counts[slot] ?? 0,
  }))
}

export function fromRosterList(roster: RosterSlot[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const slot of ROSTER_SLOT_ORDER) counts[slot] = 0
  for (const entry of roster) counts[entry.slot] = entry.count
  return counts
}

export function starterCount(counts: Record<string, number>): number {
  return ROSTER_SLOT_ORDER.reduce((total, slot) => total + (counts[slot] ?? 0), 0)
}
