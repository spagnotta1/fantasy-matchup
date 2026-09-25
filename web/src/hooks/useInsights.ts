/**
 * The planning and accountability views: track record, strength of schedule,
 * a team's week and the ADP value board.
 */

import { useQuery } from '@tanstack/react-query'

import * as draftApi from '@/api/draft'
import * as insightsApi from '@/api/insights'
import { keepPreviousSubject } from '@/api/keepPreviousSubject'
import * as matchupsApi from '@/api/matchups'
import { queryKeys } from '@/api/queryKeys'
import { useSlate } from '@/app/slate-context'

/**
 * Stored projections graded against outcomes.
 *
 * Takes its own season rather than the slate's: the track record's natural
 * default is *every* season, and a reader looking at week 2 of 2026 still wants
 * eight seasons of record, not two weeks of it. Only the scoring format comes
 * from the slate, because actual points are scored in it.
 */
export function useTrackRecord(season: number | null, week: number | null) {
  const slate = useSlate()
  const params = { season, week, scoringProfile: slate.scoringProfile }
  // The season is the subject; a scorecard week change keeps the page up.
  const subject = season ?? 'all'

  return useQuery({
    queryKey: queryKeys.insights.trackRecord(params),
    queryFn: ({ signal }) => insightsApi.getTrackRecord(params, signal),
    enabled: slate.scoringProfile !== null,
    // A historical aggregate: it moves when a game completes, not while a
    // reader is looking at it.
    staleTime: 15 * 60 * 1000,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}

export function useScheduleStrength(position: string | null) {
  const slate = useSlate()
  const subject = position ?? ''

  return useQuery({
    queryKey: queryKeys.insights.scheduleStrength(position ?? '', slate.season, slate.week),
    queryFn: ({ signal }) =>
      insightsApi.getScheduleStrength(
        position as string,
        { season: slate.season, week: slate.week },
        signal,
      ),
    enabled: Boolean(position) && slate.resolved,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}

/** A team's week: the game, the market, and its projected players. */
export function useTeamOutlook(team: string | undefined) {
  const slate = useSlate()
  const params = { season: slate.season, week: slate.week, scoringProfile: slate.scoringProfile }
  const subject = team ?? ''

  return useQuery({
    queryKey: queryKeys.matchups.teamOutlook(team ?? '', params),
    queryFn: ({ signal }) => matchupsApi.getTeamOutlook(team as string, params, signal),
    enabled: Boolean(team) && slate.resolved,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}

/** The draft pool beside the market's ADP for one season. */
export function useValueBoard(season: number | null) {
  const slate = useSlate()
  const subject = season ?? ''

  return useQuery({
    queryKey: queryKeys.draft.valueBoard(season ?? 0, slate.scoringProfile),
    queryFn: ({ signal }) =>
      draftApi.getValueBoard(
        { season: season as number, scoringProfile: slate.scoringProfile },
        signal,
      ),
    enabled: season !== null && slate.scoringProfile !== null,
    staleTime: 15 * 60 * 1000,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}

/**
 * Every defence's form at every position, keyed by team.
 *
 * One request serves every team page: the unfiltered defence board is the same
 * answer whichever team is being read, so it is cached once rather than per team.
 */
export function useAllDefenseForm() {
  const slate = useSlate()
  return useQuery({
    queryKey: queryKeys.matchups.defense({ season: slate.season, week: slate.week, position: null }),
    queryFn: ({ signal }) =>
      matchupsApi.getDefenseRankings({ season: slate.season, week: slate.week }, signal),
    enabled: slate.resolved,
    meta: { subject: 'defense-all' },
    placeholderData: keepPreviousSubject('defense-all'),
  })
}
