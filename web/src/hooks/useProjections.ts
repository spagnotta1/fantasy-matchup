/**
 * Board and profile data.
 *
 * Every hook here takes the slate from `useSlate()` rather than accepting it as
 * an argument, so a view cannot accidentally render week 18's players under a
 * week 14 header. The one thing a caller passes is what makes its request
 * different from another view's.
 */

import { useQueries, useQuery } from '@tanstack/react-query'

import { keepPreviousSubject } from '@/api/keepPreviousSubject'
import * as matchupsApi from '@/api/matchups'
import * as playersApi from '@/api/players'
import * as projectionsApi from '@/api/projections'
import { queryKeys } from '@/api/queryKeys'
import { useSlate } from '@/app/slate-context'

/**
 * A whole slate in one request.
 *
 * The API's page ceiling is 500 and a full slate is roughly 400 projected
 * players, so the board is fetched entire and filtered in the browser. That is
 * a deliberate trade: sorting or filtering a *paginated* board client-side
 * would silently sort one page and present it as the ranking, which is worse
 * than either doing it server-side or not offering it.
 */
export const FULL_SLATE_LIMIT = 500

/** The ranked board for the current slate. Returns the envelope — meta matters here. */
export function useBoard(options: { positions?: string[]; teams?: string[]; enabled?: boolean } = {}) {
  const slate = useSlate()
  const params = {
    season: slate.season,
    week: slate.week,
    scoringProfile: slate.scoringProfile,
    positions: options.positions,
    teams: options.teams,
    limit: FULL_SLATE_LIMIT,
  }

  // Every board is the same subject: "the slate". A position or team filter
  // narrows the same list rather than replacing it with a different one, so
  // holding the wider set on screen for a moment under a busy state shows the
  // reader their filter narrowing rather than the page restarting.
  const subject = 'board'

  return useQuery({
    queryKey: queryKeys.projections.board(params),
    queryFn: ({ signal }) => projectionsApi.getBoard(params, signal),
    // Firing before the slate resolves would request the API's default week,
    // then immediately re-request the real one — two round trips and a flash of
    // the wrong week's data.
    enabled: slate.resolved && (options.enabled ?? true),
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}

/**
 * A single position's board.
 *
 * Separate from `useBoard` with a position filter, and not a convenience
 * wrapper over it: `/rankings/{position}` re-ranks within the position, so
 * `rank` and `positional_rank` agree and the tiers are drawn against that
 * position's own distribution. Filtering the mixed board would keep the
 * cross-position tiers, which group a quarterback with a wide receiver.
 *
 * Callers must not enable this for a position the catalog reports as
 * unprojected — the API answers those with a 422 by design, and a request we
 * know will be refused is not a request.
 */
export function usePositionRankings(position: string | null | undefined, enabled = true) {
  const slate = useSlate()
  const params = {
    season: slate.season,
    week: slate.week,
    scoringProfile: slate.scoringProfile,
    limit: FULL_SLATE_LIMIT,
  }

  // The position *is* the subject here. A week change keeps the rows; a tab
  // change does not, because those are different players under a heading that
  // has already updated.
  const subject = position ?? ''

  return useQuery({
    queryKey: queryKeys.projections.rankings(position ?? '', params),
    queryFn: ({ signal }) => projectionsApi.getPositionRankings(position as string, params, signal),
    enabled: Boolean(position) && slate.resolved && enabled,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}

/** The week's schedule plus whether a board exists for it. */
export function useWeek() {
  const slate = useSlate()
  // Always the same subject — "the selected week's schedule" — so it holds
  // through a slate change and the dashboard fades as one unit instead of each
  // panel collapsing to a skeleton on its own schedule.
  const subject = 'week'

  return useQuery({
    queryKey: queryKeys.matchups.week(slate.week ?? 0, slate.season),
    queryFn: ({ signal }) => matchupsApi.getWeek(slate.week as number, slate.season, signal),
    enabled: slate.resolved && slate.week !== null,
    meta: { subject },
    placeholderData: keepPreviousSubject(subject),
  })
}

/** Everything the player page needs, in one call. */
export function usePlayerProfile(playerId: string | undefined) {
  const slate = useSlate()
  const params = {
    season: slate.season,
    week: slate.week,
    scoringProfile: slate.scoringProfile,
  }

  return useQuery({
    queryKey: queryKeys.players.profile(playerId ?? '', params),
    queryFn: ({ signal }) => playersApi.getPlayerProfile(playerId as string, params, signal),
    enabled: Boolean(playerId) && slate.resolved,
  })
}

/**
 * Identity for a set of player ids.
 *
 * One cached query per player rather than a batch call: the ids on the compare
 * screen change one at a time, and a batch key would refetch every player each
 * time one is added. It also means a player already seen anywhere else in the
 * session — a detail page, a previous comparison — resolves from cache with no
 * request at all.
 */
export function usePlayers(playerIds: string[]) {
  return useQueries({
    queries: playerIds.map((playerId) => ({
      queryKey: queryKeys.players.detail(playerId),
      queryFn: ({ signal }: { signal: AbortSignal }) => playersApi.getPlayer(playerId, signal),
      // Identity does not change within a session.
      staleTime: 60 * 60 * 1000,
    })),
  })
}

/**
 * Name search.
 *
 * Disabled below the API's own minimum term length rather than firing and
 * catching the 422 — a request we know will be refused is not a request.
 */
export const MIN_SEARCH_LENGTH = 2

export function usePlayerSearch(
  query: string,
  options: { limit?: number; positions?: string[] } = {},
) {
  const term = query.trim()
  const limit = options.limit ?? 10
  // Sorted so that ['RB','WR'] and ['WR','RB'] are one cache entry rather than
  // two identical results under different keys.
  const positions = options.positions ? [...options.positions].sort() : undefined

  return useQuery({
    queryKey: queryKeys.players.search(`${term}:${limit}:${positions?.join('+') ?? 'all'}`),
    queryFn: ({ signal }) => playersApi.searchPlayers(term, { limit, positions }, signal),
    enabled: term.length >= MIN_SEARCH_LENGTH,
    staleTime: 60 * 1000,
  })
}
