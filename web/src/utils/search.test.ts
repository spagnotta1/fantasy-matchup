import { describe, expect, it } from 'vitest'

import { MATCH_EXACT, MATCH_INSIDE, MATCH_NONE, MATCH_WORD_START, matchKind, rankPlayerSearch } from './search'

const player = (player_id: string, name: string) => ({ player_id, name })
const names = (players: { name: string }[]) => players.map((entry) => entry.name)

describe('matchKind', () => {
  it('recognises the whole name', () => {
    expect(matchKind('Josh Allen', 'josh allen')).toBe(MATCH_EXACT)
    expect(matchKind('Josh Allen', '  Josh Allen ')).toBe(MATCH_EXACT)
  })

  it('treats the start of a first name and of a surname alike', () => {
    expect(matchKind('Gibran Hamdan', 'gib')).toBe(MATCH_WORD_START)
    expect(matchKind('Jahmyr Gibbs', 'gib')).toBe(MATCH_WORD_START)
  })

  it('treats a hyphen and an apostrophe as the start of a word', () => {
    expect(matchKind('Jaxon Smith-Njigba', 'njig')).toBe(MATCH_WORD_START)
    expect(matchKind("Aidan O'Connell", 'conn')).toBe(MATCH_WORD_START)
    expect(matchKind('Amon-Ra St. Brown', 'brown')).toBe(MATCH_WORD_START)
  })

  it('ranks a match buried inside a word below a word start', () => {
    expect(matchKind('Lamar Jackson', 'mar')).toBe(MATCH_INSIDE)
    // Found at a word start on a later occurrence, not only the first one.
    expect(matchKind('Damar Marlowe', 'mar')).toBe(MATCH_WORD_START)
  })

  it('reports no match', () => {
    expect(matchKind('Josh Allen', 'xyz')).toBe(MATCH_NONE)
    expect(matchKind('Josh Allen', '')).toBe(MATCH_NONE)
  })
})

describe('rankPlayerSearch', () => {
  // The reported case, in the order the API used to return it.
  const gib = [
    player('hamdan', 'Gibran Hamdan'),
    player('gibbs', 'Jahmyr Gibbs'),
    player('gibler', 'Andy Gibler'),
    player('gibson', 'Antonio Gibson'),
  ]

  it('puts a player projected this week ahead of one who is not', () => {
    const projected = new Map([['gibbs', 19.4]])
    expect(names(rankPlayerSearch(gib, 'gib', projected))[0]).toBe('Jahmyr Gibbs')
  })

  it('keeps every result, however old', () => {
    const projected = new Map([['gibbs', 19.4]])
    expect(names(rankPlayerSearch(gib, 'gib', projected)).sort()).toEqual(names(gib).sort())
  })

  it('orders projected players by their projection', () => {
    const allens = [player('k', 'Keenan Allen'), player('j', 'Josh Allen'), player('z', 'Zach Allen')]
    const projected = new Map<string, number | null>([
      ['k', 9.1],
      ['j', 20.5],
    ])
    expect(names(rankPlayerSearch(allens, 'allen', projected))).toEqual([
      'Josh Allen',
      'Keenan Allen',
      'Zach Allen',
    ])
  })

  it('leaves unprojected players in the order the API gave them', () => {
    const smiths = [player('a', 'Recent Smith'), player('b', 'Older Smith'), player('c', 'Oldest Smith')]
    expect(names(rankPlayerSearch(smiths, 'smith', new Map()))).toEqual(names(smiths))
  })

  it('does not let a projection outrank a better match', () => {
    // An exact name is what was typed; a projected player who merely contains
    // the term does not jump ahead of it.
    const results = [player('inside', 'Sam Howellington'), player('exact', 'Sam Howell')]
    const projected = new Map([['inside', 14.2]])
    expect(names(rankPlayerSearch(results, 'sam howell', projected))).toEqual([
      'Sam Howell',
      'Sam Howellington',
    ])
  })

  it('ranks a word-start match above a projected player matched inside a word', () => {
    const results = [player('lamar', 'Lamar Jackson'), player('marvin', 'Marvin Retired')]
    const projected = new Map([['lamar', 17.5]])
    expect(names(rankPlayerSearch(results, 'mar', projected))).toEqual([
      'Marvin Retired',
      'Lamar Jackson',
    ])
  })

  it('returns the API order untouched when no board is available', () => {
    expect(names(rankPlayerSearch(gib, 'gib'))).toEqual(names(gib))
  })

  it('treats a board entry with no points as projected, after those with points', () => {
    const results = [player('none', 'Tom Gibson'), player('null', 'Ray Gibson'), player('pts', 'Al Gibson')]
    const projected = new Map<string, number | null>([
      ['null', null],
      ['pts', 3.2],
    ])
    expect(names(rankPlayerSearch(results, 'gibson', projected))).toEqual([
      'Al Gibson',
      'Ray Gibson',
      'Tom Gibson',
    ])
  })
})
