import type { HistoricalWeek } from '@/api/schemas'

/**
 * Which of a player's games the game log and the usage trend are showing.
 *
 * `recent` is the last 17 scored games, running across a season boundary. A
 * season is every scored game of that season, playoffs included.
 */
export type GameWindow = 'recent' | number

/**
 * Games in the `recent` window. 17 is a full regular season of games. It is
 * games played, not calendar weeks — a bye or a missed game leaves no row, so
 * counting weeks would give a different number of columns for every player and
 * would depend on how long each season's playoffs ran. A player with fewer
 * than 17 scored games shows what they have; nothing is padded.
 */
export const RECENT_GAMES = 17

/** How many games the page loads to begin with: the API's own default. */
export const DEFAULT_HISTORY = 24

/** The most the API will return in one profile (`MAX_HISTORY_WEEKS`). */
export const FULL_HISTORY = 120

/**
 * The scored games in a history, oldest first.
 *
 * A time axis reads oldest to newest. Sorted explicitly rather than trusting
 * the API's newest-first order and reversing it — a season boundary or a
 * duplicate (season, week) row from an upstream join would otherwise land out
 * of sequence with no defence on this side.
 */
export function scoredGames(history: readonly HistoricalWeek[]): HistoricalWeek[] {
  return [...history]
    .sort((a, b) => a.season - b.season || a.week - b.week)
    .filter((week) => week.actual_points !== null && week.actual_points !== undefined)
}

/**
 * The seasons a reader can choose, newest first.
 *
 * `truncated` says the history was cut off by the number of games asked for,
 * so its oldest season may be missing its first weeks. That season is left
 * out: "2024 season" over the last nine games of 2024 would be a wrong label
 * on a right chart.
 */
export function selectableSeasons(games: readonly HistoricalWeek[], truncated: boolean): number[] {
  const seasons = [...new Set(games.map((game) => game.season))].sort((a, b) => b - a)
  return truncated ? seasons.slice(0, -1) : seasons
}

/** The games of one window, oldest first. `games` must already be oldest first. */
export function gamesIn(games: readonly HistoricalWeek[], window: GameWindow): HistoricalWeek[] {
  return window === 'recent' ? games.slice(-RECENT_GAMES) : games.filter((game) => game.season === window)
}

/** What the window is called in a sentence: "last 17 games", "the 2025 season". */
export function describeWindow(games: readonly HistoricalWeek[], window: GameWindow): string {
  if (window !== 'recent') return `the ${window} season, ${games.length} ${games.length === 1 ? 'game' : 'games'}`
  const seasons = [...new Set(games.map((game) => game.season))]
  const span = seasons.length > 1 ? `across ${new Intl.ListFormat('en').format(seasons.map(String))}` : `of ${seasons[0] ?? ''}`
  return `last ${games.length} ${games.length === 1 ? 'game' : 'games'} ${span}`.trim()
}
