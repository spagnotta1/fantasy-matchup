import { describe, expect, it } from 'vitest'

import { MAX_COMPARISON_PLAYERS } from './useCompare'
import { compareHref, compareSearch, parsePlayerIds, togglePlayerId } from './useCompareSelection'

const SIX = ['a', 'b', 'c', 'd', 'e', 'f']

describe('parsePlayerIds', () => {
  it('reads a comma-separated list in the order it was written', () => {
    expect(parsePlayerIds('00-0032764,00-0038134')).toEqual(['00-0032764', '00-0038134'])
  })

  it('is empty for a missing or blank parameter', () => {
    expect(parsePlayerIds(null)).toEqual([])
    expect(parsePlayerIds('')).toEqual([])
    expect(parsePlayerIds(' , ,')).toEqual([])
  })

  it('drops repeats and stray spaces, so a hand-edited link still opens', () => {
    expect(parsePlayerIds('a, b,a,,b ,c')).toEqual(['a', 'b', 'c'])
  })

  it('keeps the first six of an over-long list: what the comparison accepts', () => {
    expect(MAX_COMPARISON_PLAYERS).toBe(6)
    expect(parsePlayerIds([...SIX, 'g', 'h'].join(','))).toEqual(SIX)
  })
})

describe('togglePlayerId', () => {
  it('ticks a player at the end, so the order is the order they were chosen in', () => {
    expect(togglePlayerId(['a'], 'b')).toEqual(['a', 'b'])
  })

  it('unticks a player who is ticked', () => {
    expect(togglePlayerId(['a', 'b', 'c'], 'b')).toEqual(['a', 'c'])
  })

  it('takes no seventh player, and still unticks one of the six', () => {
    expect(togglePlayerId(SIX, 'g')).toEqual(SIX)
    expect(togglePlayerId(SIX, 'a')).toEqual(['b', 'c', 'd', 'e', 'f'])
  })
})

describe('where a selection goes', () => {
  it('links to the comparison of the ticked players', () => {
    expect(compareHref(['00-0032764', '00-0038134'])).toBe('/compare?players=00-0032764,00-0038134')
  })

  it('rides on a link as a query string, and as nothing when nobody is ticked', () => {
    expect(compareSearch(['a', 'b'])).toBe('?compare=a,b')
    expect(compareSearch([])).toBe('')
  })

  it('round-trips through the parameter it writes', () => {
    const search = new URLSearchParams(compareSearch(['00-0032764', '00-0038134']))
    expect(parsePlayerIds(search.get('compare'))).toEqual(['00-0032764', '00-0038134'])
  })
})
