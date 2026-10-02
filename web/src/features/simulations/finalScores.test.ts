import { describe, expect, it } from 'vitest'

import type { LiveSlate } from '@/api/schemas'
import { makeProjection } from '@/test/factories'

import { knownFinal, liveFinals } from './finalScores'

const livePlayer = (id: string, eventId: string, points: number): LiveSlate['players'][number] => ({
  provenance: 'actual',
  official: false,
  player_id: id,
  name: id,
  position: 'RB',
  team: 'DET',
  event_id: eventId,
  live_points: points,
  components: {},
})

const slate: LiveSlate = {
  season: 2026,
  week: 4,
  scoring_profile: 'half_ppr',
  games: [
    { event_id: 'over', home: 'CLE', away: 'PIT', state: 'post' },
    { event_id: 'live', home: 'BUF', away: 'NE', state: 'in' },
    { event_id: 'later', home: 'SF', away: 'DEN', state: 'pre' },
  ],
  players: [livePlayer('done', 'over', 18.4), livePlayer('playing', 'live', 6.2), livePlayer('waiting', 'later', 0)],
}

describe('liveFinals', () => {
  it('takes scores only from games that are over', () => {
    const finals = liveFinals(slate)
    expect([...finals.keys()]).toEqual(['done'])
    // A box score, not the official line.
    expect(finals.get('done')).toEqual({ points: 18.4, official: false })
  })

  it('is empty with no live feed', () => {
    expect(liveFinals(undefined).size).toBe(0)
  })
})

describe('knownFinal', () => {
  const live = liveFinals(slate)

  it('prefers the official line once the week is loaded', () => {
    const projection = { ...makeProjection({ id: 'done' }), actual_points: 19.1 }
    expect(knownFinal('done', projection, live)).toEqual({ points: 19.1, official: true })
  })

  it('uses the box score before that', () => {
    expect(knownFinal('done', makeProjection({ id: 'done' }), live)).toEqual({ points: 18.4, official: false })
  })

  it('counts an official zero as a score', () => {
    const projection = { ...makeProjection({ id: 'done' }), actual_points: 0 }
    expect(knownFinal('done', projection, live)).toEqual({ points: 0, official: true })
  })

  it('has nothing for a player whose game is not over', () => {
    expect(knownFinal('playing', makeProjection({ id: 'playing' }), live)).toBeNull()
    expect(knownFinal('nobody', undefined, live)).toBeNull()
  })
})
