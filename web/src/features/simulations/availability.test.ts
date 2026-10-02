import { describe, expect, it } from 'vitest'

import type { Player, PositionSupport } from '@/api/schemas'
import { makeEntry } from '@/test/factories'

import { indexBoard, lineupReadiness, projectedPositions, slotStatus } from './availability'
import type { LineupRow } from './lineupFormat'

const board = [makeEntry(1, { id: 'qb', position: 'QB' }), makeEntry(2, { id: 'rb', position: 'RB' })]
const player = (id: string, position: string): Player => ({ player_id: id, name: id.toUpperCase(), position })
const row = (slot: string, who: Player | null): LineupRow => ({ key: slot, slot, player: who })

const SUPPORT: PositionSupport[] = [
  { position: 'QB', label: 'Quarterback', status: 'projected', projected: true, blocked_on: [] },
  { position: 'RB', label: 'Running back', status: 'projected', projected: true, blocked_on: [] },
  { position: 'K', label: 'Kicker', status: 'planned', projected: false, blocked_on: [] },
]
const projected = projectedPositions(SUPPORT)

describe('indexBoard', () => {
  it('is complete when the whole slate arrived', () => {
    const index = indexBoard(board, { total: 2, limit: 1000, offset: 0, returned: 2 }, false)
    expect(index.complete).toBe(true)
    expect(index.byPlayer.has('qb')).toBe(true)
  })

  it('is not complete while pending, when truncated, or when empty', () => {
    expect(indexBoard(board, null, true).complete).toBe(false)
    expect(indexBoard(board, { total: 600, limit: 2, offset: 0, returned: 2 }, false).complete).toBe(false)
    expect(indexBoard([], null, false).complete).toBe(false)
  })
})

describe('projectedPositions', () => {
  it('lists only positions the engine projects', () => {
    expect([...(projected ?? [])]).toEqual(['QB', 'RB'])
  })

  it('makes no claim before the catalog arrives', () => {
    expect(projectedPositions(undefined)).toBeNull()
    expect(projectedPositions([])).toBeNull()
  })
})

describe('slotStatus', () => {
  const complete = indexBoard(board, null, false)

  it('reports an empty slot', () => {
    expect(slotStatus(row('QB', null), complete, projected, 4).kind).toBe('empty')
  })

  it('is ready for a player on the board', () => {
    const status = slotStatus(row('QB', player('qb', 'QB')), complete, projected, 4)
    expect(status.kind).toBe('ready')
  })

  it('names a missing projection, with the week', () => {
    const status = slotStatus(row('RB', player('bye', 'RB')), complete, projected, 4)
    expect(status).toMatchObject({ kind: 'unavailable', reason: 'no_projection' })
    expect(status.kind === 'unavailable' && status.detail).toContain('week 4')
  })

  it('separates a position the engine does not project', () => {
    const status = slotStatus(row('K', player('kicker', 'K')), complete, projected, 4)
    expect(status).toMatchObject({ kind: 'unavailable', reason: 'unprojected_position' })
  })

  it('makes no claim when the board cannot be trusted as complete', () => {
    // A false "no projection" on a projected player is worse than the 422.
    const truncated = indexBoard(board, { total: 600, limit: 2, offset: 0, returned: 2 }, false)
    expect(slotStatus(row('RB', player('bye', 'RB')), truncated, projected, 4).kind).toBe('unknown')
  })
})

describe('lineupReadiness', () => {
  const complete = indexBoard(board, null, false)

  it('is runnable only when every slot is filled with a sampleable player', () => {
    const ready = lineupReadiness([row('QB', player('qb', 'QB')), row('RB', player('rb', 'RB'))], complete, projected, 4)
    expect(ready).toEqual({ empty: 0, problems: [], runnable: true })
  })

  it('counts empty slots and names each problem by slot and player', () => {
    const result = lineupReadiness(
      [row('QB', null), row('RB', player('bye', 'RB')), row('K', player('kicker', 'K'))],
      complete,
      projected,
      4,
    )
    expect(result.empty).toBe(1)
    expect(result.runnable).toBe(false)
    expect(result.problems.map((problem) => [problem.slot, problem.name, problem.reason])).toEqual([
      ['RB', 'BYE', 'no_projection'],
      ['K', 'KICKER', 'unprojected_position'],
    ])
  })

  it('does not block on a board it cannot see', () => {
    const pending = indexBoard([], null, true)
    const result = lineupReadiness([row('RB', player('rb', 'RB'))], pending, projected, 4)
    expect(result.problems).toEqual([])
    expect(result.runnable).toBe(true)
  })

  it('is never runnable with no slots at all', () => {
    expect(lineupReadiness([], complete, projected, 4).runnable).toBe(false)
  })
})
