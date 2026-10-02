import type { Player } from '@/api/schemas'

/**
 * How a search term matched a name. Lower is better.
 *
 * The same three kinds the API ranks by (`repository.search_players`), so a
 * re-rank in the browser refines the server's order instead of undoing it.
 */
export type MatchKind = 0 | 1 | 2 | 3

export const MATCH_EXACT: MatchKind = 0
export const MATCH_WORD_START: MatchKind = 1
export const MATCH_INSIDE: MatchKind = 2
export const MATCH_NONE: MatchKind = 3

/** A space, a hyphen or an apostrophe starts a word: "St. Brown", "Smith-Njigba", "O'Connell". */
const WORD_BREAK = /[\s\-']/

export function matchKind(name: string, term: string): MatchKind {
  const haystack = name.trim().toLowerCase()
  const needle = term.trim().toLowerCase()
  if (!needle) return MATCH_NONE
  if (haystack === needle) return MATCH_EXACT

  let from = haystack.indexOf(needle)
  if (from === -1) return MATCH_NONE
  while (from !== -1) {
    if (from === 0 || WORD_BREAK.test(haystack[from - 1]!)) return MATCH_WORD_START
    from = haystack.indexOf(needle, from + 1)
  }
  return MATCH_INSIDE
}

/**
 * Order search results by how useful they are this week.
 *
 * The API already ranks by how the name matched and then by how recently the
 * player was active. What it cannot know is the slate on screen. So, within
 * each kind of match, players with a projection for the selected week come
 * first, highest projection first, and everyone else keeps the order the API
 * gave them. "gib" finds this week's Gibbs before a Gibson on injured reserve,
 * and both before a quarterback who retired in 2009.
 *
 * Nothing is dropped. A retired player, or one on a bye, is still in the list;
 * he is further down it.
 *
 * `projected` maps player id to this week's headline points. Without it (the
 * board has not loaded, or failed) the API's order is returned untouched.
 */
export function rankPlayerSearch<T extends Pick<Player, 'player_id' | 'name'>>(
  players: readonly T[],
  query: string,
  projected?: ReadonlyMap<string, number | null>,
): T[] {
  return players
    .map((player, index) => ({
      player,
      index,
      kind: matchKind(player.name, query),
      onBoard: projected?.has(player.player_id) ?? false,
      points: projected?.get(player.player_id) ?? null,
    }))
    .sort(
      (a, b) =>
        a.kind - b.kind ||
        Number(b.onBoard) - Number(a.onBoard) ||
        (b.points ?? -Infinity) - (a.points ?? -Infinity) ||
        a.index - b.index,
    )
    .map((entry) => entry.player)
}
