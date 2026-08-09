/**
 * Comparison and start/sit.
 *
 * Two endpoints rather than one because they answer different questions.
 * `/compare` lays a set of players side by side and grades *consecutive* pairs
 * — the ordering it produced, checked one step at a time. `/start-sit` grades
 * an arbitrary pair, which is what a manager choosing between the first and the
 * fourth name on the list actually needs.
 */

import { useQuery } from '@tanstack/react-query'

import * as adviceApi from '@/api/advice'
import { keepPreviousSubject } from '@/api/keepPreviousSubject'
import { queryKeys } from '@/api/queryKeys'
import { useSlate } from '@/app/slate-context'

/** The API refuses fewer than two and more than six. */
export const MIN_COMPARISON_PLAYERS = 2
export const MAX_COMPARISON_PLAYERS = 6

export function useComparison(playerIds: string[]) {
  const slate = useSlate()
  const params = {
    season: slate.season,
    week: slate.week,
    scoringProfile: slate.scoringProfile,
  }
  const valid =
    playerIds.length >= MIN_COMPARISON_PLAYERS && playerIds.length <= MAX_COMPARISON_PLAYERS

  // The set of players is the subject. Re-grading the same names under a
  // different week or scoring format keeps the table on screen; adding or
  // swapping a player changes what is being compared and must not.
  const subject = [...playerIds].sort().join('+')

  return useQuery({
    queryKey: queryKeys.advice.compare(playerIds, params),
    queryFn: ({ signal }) => adviceApi.comparePlayers(playerIds, params, signal),
    enabled: valid && slate.resolved,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}

/** One head-to-head, for a pair the user picked rather than a consecutive one. */
export function useStartSit(playerA: string | null, playerB: string | null) {
  const slate = useSlate()
  const params = {
    season: slate.season,
    week: slate.week,
    scoringProfile: slate.scoringProfile,
  }
  const ready = Boolean(playerA) && Boolean(playerB) && playerA !== playerB

  // The pair is the subject, unordered — asking about B vs A is the same
  // question as A vs B.
  const subject = [playerA ?? '', playerB ?? ''].sort().join('+')

  return useQuery({
    queryKey: queryKeys.advice.startSit(playerA ?? '', playerB ?? '', params),
    queryFn: ({ signal }) => adviceApi.getStartSit(playerA as string, playerB as string, params, signal),
    enabled: ready && slate.resolved,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}
