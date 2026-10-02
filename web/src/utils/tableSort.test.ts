import { describe, expect, it } from 'vitest'

import { compareSortValues, nextSort, parseSort, sortRows } from './tableSort'

describe('compareSortValues', () => {
  it('orders numbers by value, not as text', () => {
    expect(compareSortValues(9, 10, 'asc')).toBeLessThan(0)
    expect(compareSortValues(9, 10, 'desc')).toBeGreaterThan(0)
  })

  it('orders text without regard to case, and digits inside it as numbers', () => {
    expect(compareSortValues('adams', 'Brown', 'asc')).toBeLessThan(0)
    expect(compareSortValues('WR2', 'WR10', 'asc')).toBeLessThan(0)
  })

  it('puts a missing value last in both directions', () => {
    for (const direction of ['asc', 'desc'] as const) {
      expect(compareSortValues(null, 1, direction)).toBeGreaterThan(0)
      expect(compareSortValues(1, undefined, direction)).toBeLessThan(0)
      expect(compareSortValues(Number.NaN, 1, direction)).toBeGreaterThan(0)
      expect(compareSortValues(null, undefined, direction)).toBe(0)
    }
  })
})

describe('sortRows', () => {
  const rows = [
    { name: 'A', points: 12.5 },
    { name: 'B', points: null },
    { name: 'C', points: 19.4 },
    { name: 'D', points: 12.5 },
  ]

  it('returns a sorted copy and leaves the input alone', () => {
    const sorted = sortRows(rows, (row) => row.points, 'desc')
    expect(sorted.map((row) => row.name)).toEqual(['C', 'A', 'D', 'B'])
    expect(rows.map((row) => row.name)).toEqual(['A', 'B', 'C', 'D'])
  })

  it('keeps tied rows in the order they arrived, whichever way it runs', () => {
    expect(sortRows(rows, (row) => row.points, 'asc').map((row) => row.name)).toEqual(['A', 'D', 'C', 'B'])
  })
})

describe('nextSort', () => {
  it("opens a new column in that column's own first direction", () => {
    expect(nextSort({ key: 'name', direction: 'asc' }, 'points', 'desc')).toEqual({ key: 'points', direction: 'desc' })
    expect(nextSort(null, 'name', 'asc')).toEqual({ key: 'name', direction: 'asc' })
  })

  it('reverses the column that is already sorted', () => {
    expect(nextSort({ key: 'points', direction: 'desc' }, 'points', 'desc')).toEqual({ key: 'points', direction: 'asc' })
    expect(nextSort({ key: 'points', direction: 'asc' }, 'points', 'desc')).toEqual({ key: 'points', direction: 'desc' })
  })
})

describe('parseSort', () => {
  const fallback = { key: 'adp', direction: 'asc' } as const

  it('accepts a known column and direction', () => {
    expect(parseSort('value', 'desc', ['adp', 'value'], fallback)).toEqual({ key: 'value', direction: 'desc' })
  })

  it('falls back for a column the table does not sort on', () => {
    expect(parseSort('nonsense', 'desc', ['adp', 'value'], fallback)).toEqual(fallback)
    expect(parseSort('', '', ['adp', 'value'], fallback)).toEqual(fallback)
  })

  it('keeps the column and repairs a direction that is neither', () => {
    expect(parseSort('value', 'sideways', ['adp', 'value'], fallback)).toEqual({ key: 'value', direction: 'asc' })
  })
})
