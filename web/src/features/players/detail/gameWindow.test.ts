import { describe, expect, it } from 'vitest'

import { historicalWeekSchema, type HistoricalWeek } from '@/api/schemas'

import { RECENT_GAMES, describeWindow, gamesIn, scoredGames, selectableSeasons } from './gameWindow'

/** A completed week, through the real contract. `points: null` is a week with no score. */
function week(season: number, number: number, points: number | null = 10): HistoricalWeek {
  return historicalWeekSchema.parse({ provenance: 'actual', season, week: number, actual_points: points })
}

/** Newest first, as the API sends it: all of 2025 (18 weeks), then three weeks of 2026. */
const HISTORY = [
  ...[3, 2, 1].map((number) => week(2026, number)),
  ...Array.from({ length: 18 }, (_, index) => week(2025, 18 - index)),
]

describe('scoredGames', () => {
  it('reads oldest to newest, whatever order the history arrives in', () => {
    const games = scoredGames([week(2026, 1), week(2025, 17), week(2026, 3), week(2025, 18)])
    expect(games.map((game) => `${game.season}-${game.week}`)).toEqual(['2025-17', '2025-18', '2026-1', '2026-3'])
  })

  it('leaves out a week with no score, and pads nothing in its place', () => {
    const games = scoredGames([week(2026, 2), week(2026, 1, null)])
    expect(games).toHaveLength(1)
  })

  it('does not reorder the history it was given', () => {
    const history = [week(2026, 2), week(2026, 1)]
    scoredGames(history)
    expect(history.map((game) => game.week)).toEqual([2, 1])
  })
})

describe('gamesIn', () => {
  const games = scoredGames(HISTORY)

  it('takes the last seventeen games for the recent window, across the season boundary', () => {
    const recent = gamesIn(games, 'recent')
    expect(recent).toHaveLength(RECENT_GAMES)
    expect(recent.at(-1)).toMatchObject({ season: 2026, week: 3 })
    expect(recent[0]).toMatchObject({ season: 2025, week: 5 })
  })

  it('shows what there is when there are fewer than seventeen', () => {
    expect(gamesIn(scoredGames([week(2026, 2), week(2026, 1)]), 'recent')).toHaveLength(2)
  })

  it('takes every game of a season, however many that is', () => {
    expect(gamesIn(games, 2025)).toHaveLength(18)
    expect(gamesIn(games, 2026).map((game) => game.week)).toEqual([1, 2, 3])
    expect(gamesIn(games, 2019)).toEqual([])
  })
})

describe('selectableSeasons', () => {
  const games = scoredGames(HISTORY)

  it('lists the seasons newest first', () => {
    expect(selectableSeasons(games, false)).toEqual([2026, 2025])
  })

  it('leaves out the oldest season of a history that was cut off, since its first weeks may be missing', () => {
    expect(selectableSeasons(games, true)).toEqual([2026])
  })
})

describe('describeWindow', () => {
  const games = scoredGames(HISTORY)

  it('names both seasons when the recent games cross a boundary', () => {
    expect(describeWindow(gamesIn(games, 'recent'), 'recent')).toBe('last 17 games across 2025 and 2026')
  })

  it('names the one season when they do not', () => {
    expect(describeWindow(gamesIn(scoredGames([week(2026, 1)]), 'recent'), 'recent')).toBe('last 1 game of 2026')
  })

  it('names a season and counts its games', () => {
    expect(describeWindow(gamesIn(games, 2025), 2025)).toBe('the 2025 season, 18 games')
  })
})
