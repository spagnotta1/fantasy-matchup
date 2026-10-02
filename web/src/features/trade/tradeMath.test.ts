import { describe, expect, it } from 'vitest'

import type { TradeValue } from '@/api/schemas'

import { EVEN_SHARE, bestLineup, evenOut, fromRoster, tradeBalance } from './tradeMath'

let rank = 0
const value = (id: string, tradeValue: number, position = 'RB', rate = tradeValue / 10): TradeValue => ({
  player: { player_id: id, name: id },
  position,
  rate,
  rate_week: 4,
  on_bye: false,
  games_left: 14,
  availability: 0.9,
  availability_basis: 'player_history',
  expected_games: 12.6,
  rest_of_season: tradeValue + 40,
  value_over_replacement: tradeValue,
  trade_value: tradeValue,
  overall_rank: (rank += 1),
  position_rank: rank,
})

describe('tradeBalance', () => {
  it('sums each side and takes the gap as what you get minus what you give', () => {
    const balance = tradeBalance([value('a', 100)], [value('b', 80), value('c', 60)])
    expect(balance).toMatchObject({ give: 100, get: 140, gap: 40, lean: 'you' })
    expect(balance.share).toBeCloseTo(40 / 140)
  })

  it('leans to the other side when you give more', () => {
    expect(tradeBalance([value('a', 150)], [value('b', 100)]).lean).toBe('them')
  })

  it('calls a gap under a tenth of the larger side even', () => {
    expect(tradeBalance([value('a', 100)], [value('b', 109)]).lean).toBe('even')
    // 12 of 112 is 10.7%: just outside the band.
    expect(tradeBalance([value('a', 100)], [value('b', 112)]).lean).toBe('you')
    expect(EVEN_SHARE).toBe(0.1)
  })

  it('is even, not undefined, when both sides are empty', () => {
    expect(tradeBalance([], [])).toMatchObject({ give: 0, get: 0, gap: 0, share: 0, lean: 'even' })
  })
})

describe('evenOut', () => {
  const pool = [value('p10', 10), value('p25', 25), value('p40', 40), value('p55', 55), value('p90', 90)]

  it('has nothing to suggest for an even trade', () => {
    expect(evenOut(tradeBalance([value('a', 100)], [value('b', 105)]), pool, new Set())).toBeNull()
  })

  it('names the lighter side and a value range that closes the gap', () => {
    const balance = tradeBalance([value('a', 100)], [value('b', 150)])
    const result = evenOut(balance, pool, new Set())
    expect(result?.side).toBe('give')
    expect(result?.low).toBeCloseTo(35)
    expect(result?.high).toBeCloseTo(150 / 0.9 - 100)
    expect(result?.candidates.map((candidate) => candidate.player.player_id)).toEqual(['p55', 'p40'])
  })

  it('never disagrees with the verdict: adding any candidate makes the trade even', () => {
    for (const [give, get] of [
      [100, 150],
      [220, 90],
      [35, 180],
    ] as const) {
      const giveSide = [value('g', give)]
      const getSide = [value('t', get)]
      const result = evenOut(tradeBalance(giveSide, getSide), pool, new Set())
      for (const candidate of result?.candidates ?? []) {
        const after =
          result?.side === 'give'
            ? tradeBalance([...giveSide, candidate], getSide)
            : tradeBalance(giveSide, [...getSide, candidate])
        expect(after.lean, `${give} for ${get}, adding ${candidate.trade_value}`).toBe('even')
      }
    }
  })

  it('skips players already in the trade', () => {
    const balance = tradeBalance([value('a', 100)], [value('b', 150)])
    const result = evenOut(balance, pool, new Set(['p55']))
    expect(result?.candidates.map((candidate) => candidate.player.player_id)).toEqual(['p40'])
  })

  it("offers the manager's own players first when they are the one adding", () => {
    const balance = tradeBalance([value('a', 100)], [value('b', 150)])
    const result = evenOut(balance, pool, new Set(), new Set(['p40']))
    expect(result?.candidates.map((candidate) => candidate.player.player_id)).toEqual(['p40'])
    expect(fromRoster(result!, new Set(['p40']))).toBe(true)
    expect(fromRoster(evenOut(balance, pool, new Set())!, new Set(['zzz']))).toBe(false)
  })
})

describe('bestLineup', () => {
  const eligible = (slot: string) => (slot === 'FLEX' ? ['RB', 'WR', 'TE'] : [slot])

  it('fills each slot with the best unused player it accepts', () => {
    const players = [
      value('rb1', 0, 'RB', 18),
      value('rb2', 0, 'RB', 14),
      value('rb3', 0, 'RB', 12),
      value('wr1', 0, 'WR', 16),
      value('qb1', 0, 'QB', 21),
    ]
    const result = bestLineup(players, ['QB', 'RB', 'WR', 'FLEX'], eligible)
    expect(result.starters.map((starter) => starter.player.player_id)).toEqual(['qb1', 'rb1', 'wr1', 'rb2'])
    expect(result.total).toBe(21 + 18 + 16 + 14)
  })

  it('leaves a slot out when nobody can fill it', () => {
    const result = bestLineup([value('rb1', 0, 'RB', 18)], ['QB', 'RB'], eligible)
    expect(result.starters).toHaveLength(1)
    expect(result.total).toBe(18)
  })
})
