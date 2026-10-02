import { describe, expect, it } from 'vitest'

import {
  ITERATIONS_PARAM,
  MODE_PARAM,
  SEED_PARAM,
  TEAM_A_PARAM,
  TEAM_B_PARAM,
  decodeLineup,
  encodeLineup,
  matchupParams,
} from './shareLink'

const lineup = [
  { slot: 'QB', player_id: '00-0034857' },
  { slot: 'RB', player_id: '00-0039139' },
  { slot: 'FLEX', player_id: '00-0038542' },
]

describe('encodeLineup and decodeLineup', () => {
  it('round-trips a lineup, in order', () => {
    // Order matters: the API's seed contract is about the submitted order.
    expect(encodeLineup(lineup)).toBe('QB:00-0034857,RB:00-0039139,FLEX:00-0038542')
    expect(decodeLineup(encodeLineup(lineup))).toEqual(lineup)
  })

  it('leaves empty slots out of the link', () => {
    expect(encodeLineup([{ slot: 'QB', player_id: '' }, lineup[1]!])).toBe('RB:00-0039139')
  })

  it('reads nothing from an absent or empty parameter', () => {
    expect(decodeLineup(null)).toEqual([])
    expect(decodeLineup('')).toEqual([])
  })

  it('drops malformed pairs and keeps the rest', () => {
    expect(decodeLineup('QB:00-1,garbage,:00-2,RB:,WR:00-3')).toEqual([
      { slot: 'QB', player_id: '00-1' },
      { slot: 'WR', player_id: '00-3' },
    ])
  })

  it('normalises a hand-edited slot', () => {
    expect(decodeLineup(' flex : 00-9 ')).toEqual([{ slot: 'FLEX', player_id: '00-9' }])
  })

  it('caps a hostile link', () => {
    const many = Array.from({ length: 200 }, (_, index) => `RB:00-${index}`).join(',')
    expect(decodeLineup(many)).toHaveLength(40)
  })
})

describe('matchupParams', () => {
  const input = { teamA: lineup, teamB: lineup.slice(0, 1), iterations: '10000', correlationMode: 'independent' }

  it('carries both lineups and the run settings', () => {
    const params = matchupParams({ ...input, seed: '7' })
    expect(params).toEqual({
      [TEAM_A_PARAM]: 'QB:00-0034857,RB:00-0039139,FLEX:00-0038542',
      [TEAM_B_PARAM]: 'QB:00-0034857',
      [ITERATIONS_PARAM]: '10000',
      [MODE_PARAM]: 'independent',
      [SEED_PARAM]: '7',
    })
  })

  it('omits the seed when none was named', () => {
    // No seed is a different request from seed=0: the API picks its own.
    expect(matchupParams({ ...input, seed: '' })).not.toHaveProperty(SEED_PARAM)
  })
})
