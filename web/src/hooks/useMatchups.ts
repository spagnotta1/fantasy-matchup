/**
 * Schedule, per-game analysis and defensive form.
 *
 * As with the board hooks, the slate is read from context rather than passed
 * in, so a game card and the analysis it opens can never describe different
 * weeks.
 */

import { useQuery } from '@tanstack/react-query'

import { keepPreviousSubject } from '@/api/keepPreviousSubject'
import * as matchupsApi from '@/api/matchups'
import { queryKeys } from '@/api/queryKeys'
import { useSlate } from '@/app/slate-context'

/** The week's schedule. Available for weeks with no published board. */
export function useGames() {
  const slate = useSlate()
  const params = { season: slate.season, week: slate.week }

  // Always the same subject — "the selected week's schedule" — so the game list
  // dims and refreshes on a week change instead of collapsing to a skeleton.
  const subject = 'games'

  return useQuery({
    queryKey: queryKeys.matchups.games(slate.season, slate.week),
    queryFn: ({ signal }) => matchupsApi.getGames(params, signal),
    enabled: slate.resolved,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}

/** Both defences, both offences and the game's context, for one game. */
export function useMatchupAnalysis(gameId: string | undefined) {
  const slate = useSlate()
  const params = {
    season: slate.season,
    week: slate.week,
    scoringProfile: slate.scoringProfile,
  }

  // The game is the subject. A scoring change re-grades the same fixture and
  // keeps it on screen; opening a different fixture does not.
  const subject = gameId ?? ''

  return useQuery({
    queryKey: queryKeys.matchups.game(gameId ?? '', params),
    queryFn: ({ signal }) => matchupsApi.getMatchup(gameId as string, params, signal),
    enabled: Boolean(gameId) && slate.resolved,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}

/**
 * Every defence's form for one position, keyed by team.
 *
 * Takes no scoring profile, because it is not a scoring question — the points
 * allowed are computed in the API's own reference format. That is why this
 * hook does not include the profile in its key: doing so would fragment one
 * cached answer into three identical copies.
 */
export function useDefenseRankings(position: string | null | undefined) {
  const slate = useSlate()
  const params = { season: slate.season, week: slate.week, position }

  // The position is the subject: a week change keeps the board, switching the
  // position it is about does not.
  const subject = position ?? ''

  return useQuery({
    queryKey: queryKeys.matchups.defense({ season: slate.season, week: slate.week, position }),
    queryFn: ({ signal }) => matchupsApi.getDefenseRankings(params, signal),
    enabled: Boolean(position) && slate.resolved,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}
