import { describe, expect, it } from 'vitest'

import { makeEntry, makeProjection, perPlayerRangeBoard, sharedRangeBoard } from '@/test/factories'

import {
  boardCeiling,
  entryPoints,
  gameLine,
  groupByTier,
  hasBandedIntervals,
  matchesQuery,
  orderSignature,
  sortBoard,
} from './board'

const ids = (entries: { projection: { player: { player_id: string } } }[]) =>
  entries.map((entry) => entry.projection.player.player_id)

describe('sortBoard', () => {
  const board = [
    makeEntry(1, { name: 'Cee', predicted: 20, floor: 9, ceiling: 31, boom: 0.5, bust: 0.02, grade: 'C' }),
    makeEntry(2, { name: 'Bee', predicted: 18, floor: 4, ceiling: 34, boom: 0.4, bust: 0.1 }),
    makeEntry(3, { name: 'Ay', predicted: 12, floor: 6, ceiling: 22, boom: 0.1, bust: 0.05, grade: 'A' }),
  ]

  it('keeps the API rank order ascending and reverses it descending', () => {
    expect(ids(sortBoard(board, 'rank', 'asc'))).toEqual(['p1', 'p2', 'p3'])
    expect(ids(sortBoard(board, 'rank', 'desc'))).toEqual(['p3', 'p2', 'p1'])
  })

  it('sorts by each published number', () => {
    expect(ids(sortBoard(board, 'projection', 'desc'))).toEqual(['p1', 'p2', 'p3'])
    expect(ids(sortBoard(board, 'ceiling', 'desc'))).toEqual(['p2', 'p1', 'p3'])
    expect(ids(sortBoard(board, 'floor', 'desc'))).toEqual(['p1', 'p3', 'p2'])
    expect(ids(sortBoard(board, 'boom', 'desc'))).toEqual(['p1', 'p2', 'p3'])
    expect(ids(sortBoard(board, 'bust', 'asc'))).toEqual(['p1', 'p3', 'p2'])
  })

  it('sorts by name', () => {
    expect(ids(sortBoard(board, 'name', 'asc'))).toEqual(['p3', 'p2', 'p1'])
    expect(ids(sortBoard(board, 'name', 'desc'))).toEqual(['p1', 'p2', 'p3'])
  })

  it('puts a missing value last in both directions', () => {
    // An ungraded matchup is not an average one, and a missing ceiling is not a low one.
    expect(ids(sortBoard(board, 'matchup', 'desc')).at(-1)).toBe('p2')
    expect(ids(sortBoard(board, 'matchup', 'asc')).at(-1)).toBe('p2')
    const withGap = [makeEntry(1, { ceiling: null, median: null }), makeEntry(2, { ceiling: 30 })]
    expect(ids(sortBoard(withGap, 'ceiling', 'desc'))).toEqual(['p2', 'p1'])
    expect(ids(sortBoard(withGap, 'ceiling', 'asc'))).toEqual(['p2', 'p1'])
  })

  it('breaks ties on the API rank, so equal values never shuffle', () => {
    const tied = [makeEntry(3, { boom: 0.2 }), makeEntry(1, { boom: 0.2 }), makeEntry(2, { boom: 0.2 })]
    expect(ids(sortBoard(tied, 'boom', 'desc'))).toEqual(['p1', 'p2', 'p3'])
    expect(ids(sortBoard(tied, 'boom', 'asc'))).toEqual(['p1', 'p2', 'p3'])
  })

  it('does not mutate the list it was given', () => {
    const before = ids(board)
    sortBoard(board, 'name', 'asc')
    expect(ids(board)).toEqual(before)
  })
})

describe('entryPoints', () => {
  it('reads the calibrated mean, and the raw output only when there is none', () => {
    expect(entryPoints(makeEntry(1, { expected: 14.2, predicted: 13.1 }))).toBe(14.2)
    expect(entryPoints(makeEntry(1, { expected: null, predicted: 13.1 }))).toBe(13.1)
  })
})

describe('matchesQuery', () => {
  const entry = makeEntry(1, { name: 'Jahmyr Gibbs', team: 'DET' })

  it('matches on name or team, ignoring case and surrounding space', () => {
    expect(matchesQuery(entry, ' gibbs ')).toBe(true)
    expect(matchesQuery(entry, 'det')).toBe(true)
    expect(matchesQuery(entry, 'xyz')).toBe(false)
  })

  it('matches everything on an empty query', () => {
    expect(matchesQuery(entry, '   ')).toBe(true)
  })
})

describe('groupByTier', () => {
  it('splits a ranked list on tier boundaries, keeping order', () => {
    const groups = groupByTier([
      makeEntry(1, { tier: 1 }),
      makeEntry(2, { tier: 2 }),
      makeEntry(3, { tier: 2 }),
      makeEntry(4, { tier: 3 }),
    ])
    expect(groups.map((group) => [group.tier, ids(group.entries)])).toEqual([
      [1, ['p1']],
      [2, ['p2', 'p3']],
      [3, ['p4']],
    ])
  })

  it('groups only adjacent rows, which is why callers must pass rank order', () => {
    const groups = groupByTier([makeEntry(1, { tier: 1 }), makeEntry(2, { tier: 2 }), makeEntry(3, { tier: 1 })])
    expect(groups.map((group) => group.tier)).toEqual([1, 2, 1])
  })
})

describe('boardCeiling', () => {
  it('is the largest ceiling, ignoring missing ones', () => {
    expect(
      boardCeiling([makeEntry(1, { ceiling: 28 }), makeEntry(2, { ceiling: null, median: null }), makeEntry(3, { ceiling: 33.5 })]),
    ).toBe(33.5)
    expect(boardCeiling([])).toBe(0)
  })
})

describe('hasBandedIntervals', () => {
  it('detects ranges shared across groups of players', () => {
    expect(hasBandedIntervals(sharedRangeBoard(40, 3))).toBe(true)
  })

  it('stays quiet when every player has their own range', () => {
    expect(hasBandedIntervals(perPlayerRangeBoard(40))).toBe(false)
  })

  it('does not judge a position with fewer than ten players', () => {
    expect(hasBandedIntervals(sharedRangeBoard(9, 1))).toBe(false)
  })

  it('judges each position separately', () => {
    const mixed = [...perPlayerRangeBoard(20, { position: 'WR' }), ...sharedRangeBoard(20, 2, { position: 'QB' })]
    expect(hasBandedIntervals(mixed)).toBe(true)
  })

  it('ignores projections with no range', () => {
    const noRange = Array.from({ length: 20 }, (_, index) =>
      makeProjection({ id: `n${index}`, median: null, ceiling: null }),
    )
    expect(hasBandedIntervals(noRange)).toBe(false)
  })
})

describe('orderSignature', () => {
  it('changes when the drawn order changes', () => {
    const a = [makeEntry(1), makeEntry(2)]
    expect(orderSignature(a)).not.toBe(orderSignature([...a].reverse()))
  })
})

describe('gameLine', () => {
  const projection = makeProjection({ id: 'g1' })
  const away = { ...projection, team: 'DET', opponent: 'CAR', is_home: false }
  const home = { ...projection, team: 'BAL', opponent: 'TEN', is_home: true }

  it('says where the player is playing', () => {
    expect(gameLine(away, false)).toBe('DET @ CAR')
    expect(gameLine(home, false)).toBe('BAL vs TEN')
  })

  it('leads with the position on a board that mixes positions', () => {
    expect(gameLine(away, true)).toBe(`${away.player.position} · DET @ CAR`)
  })
})
