import { describe, expect, it } from 'vitest'

import type { LineupSlot, Player } from '@/api/schemas'
import { makeEntry } from '@/test/factories'

import {
  autofillLineup,
  eligiblePositions,
  emptyLineup,
  expandSlots,
  fillFromLineup,
  parseLineupFormats,
  resolveFormat,
  type LineupRow,
} from './lineupFormat'

// The notice exactly as `/meta/lineup-slots` writes it.
const NOTICE =
  'Standard skill lineup (QB/RB/RB/WR/WR/TE/FLEX) (standard_skill): 1xQB, 2xRB, 2xWR, 1xTE, 1xFLEX'

const slot = (name: string, eligible: string[], supported = true): LineupSlot => ({
  slot: name,
  label: name,
  eligible_positions: eligible,
  supported,
  unsupported_positions: [],
  description: '',
})

const SLOTS = [
  slot('QB', ['QB']),
  slot('RB', ['RB']),
  slot('WR', ['WR']),
  slot('TE', ['TE']),
  slot('FLEX', ['RB', 'WR', 'TE']),
  slot('K', ['K'], false),
]

const player = (id: string, position: string): Player => ({ player_id: id, name: id, position })
const row = (slotName: string, who: Player | null, index = 0): LineupRow => ({
  key: `${slotName}-${index}`,
  slot: slotName,
  player: who,
})
const filled = (rows: LineupRow[]) => rows.map((entry) => entry.player?.player_id ?? null)

describe('parseLineupFormats', () => {
  it('reads the composition out of the notice', () => {
    const [format] = parseLineupFormats([NOTICE])
    expect(format).toMatchObject({
      name: 'standard_skill',
      label: 'Standard skill lineup (QB/RB/RB/WR/WR/TE/FLEX)',
      size: 7,
    })
    expect(format?.requirements).toEqual([
      { slot: 'QB', count: 1 },
      { slot: 'RB', count: 2 },
      { slot: 'WR', count: 2 },
      { slot: 'TE', count: 1 },
      { slot: 'FLEX', count: 1 },
    ])
  })

  it('skips notices that are not a format, without throwing', () => {
    expect(parseLineupFormats(['Kickers are not projected.', '', 'Lineup (odd): none here'])).toEqual([])
  })

  it('reads several formats in order', () => {
    const formats = parseLineupFormats([NOTICE, 'Superflex (superflex): 2xQB, 2xRB'])
    expect(formats.map((format) => format.name)).toEqual(['standard_skill', 'superflex'])
    expect(formats[1]?.size).toBe(4)
  })
})

describe('resolveFormat', () => {
  it('uses the parsed format when there is one', () => {
    const formats = parseLineupFormats([NOTICE])
    expect(resolveFormat(formats, SLOTS).name).toBe('standard_skill')
  })

  it('falls back to one of every simulable slot, never an unsupported one', () => {
    const format = resolveFormat([], SLOTS)
    expect(format.name).toBe('unknown')
    expect(expandSlots(format)).toEqual(['QB', 'RB', 'WR', 'TE', 'FLEX'])
  })
})

describe('expandSlots and emptyLineup', () => {
  const [format] = parseLineupFormats([NOTICE])

  it('lists one row per starter in format order', () => {
    expect(expandSlots(format!)).toEqual(['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX'])
  })

  it('builds an empty lineup with stable, distinct keys', () => {
    const lineup = emptyLineup(format!)
    expect(lineup).toHaveLength(7)
    expect(new Set(lineup.map((entry) => entry.key)).size).toBe(7)
    expect(lineup.every((entry) => entry.player === null)).toBe(true)
  })
})

describe('eligiblePositions', () => {
  it('reads the catalog and gives an unknown slot nothing', () => {
    expect(eligiblePositions(SLOTS, 'FLEX')).toEqual(['RB', 'WR', 'TE'])
    expect(eligiblePositions(SLOTS, 'SUPERFLEX')).toEqual([])
  })
})

describe('autofillLineup', () => {
  const board = [
    makeEntry(1, { id: 'qb1', position: 'QB' }),
    makeEntry(2, { id: 'rb1', position: 'RB' }),
    makeEntry(3, { id: 'wr1', position: 'WR' }),
    makeEntry(4, { id: 'rb2', position: 'RB' }),
    makeEntry(5, { id: 'te1', position: 'TE' }),
    makeEntry(6, { id: 'wr2', position: 'WR' }),
  ]

  it('fills each empty slot with the highest-ranked eligible player', () => {
    const rows = [row('QB', null), row('RB', null), row('FLEX', null)]
    expect(filled(autofillLineup(rows, board, SLOTS, []))).toEqual(['qb1', 'rb1', 'wr1'])
  })

  it('never hands out a player the other lineup holds', () => {
    const rows = [row('RB', null), row('WR', null)]
    expect(filled(autofillLineup(rows, board, SLOTS, ['rb1', 'wr1']))).toEqual(['rb2', 'wr2'])
  })

  it('leaves a filled slot alone and does not reuse its player', () => {
    const rows = [row('RB', player('rb1', 'RB')), row('FLEX', null)]
    expect(filled(autofillLineup(rows, board, SLOTS, []))).toEqual(['rb1', 'wr1'])
  })

  it('leaves a slot empty when nobody eligible is left', () => {
    expect(filled(autofillLineup([row('QB', null), row('QB', null, 1)], board, SLOTS, []))).toEqual(['qb1', null])
  })
})

describe('fillFromLineup', () => {
  const source = [
    row('QB', player('qb', 'QB')),
    row('RB', player('rbA', 'RB')),
    row('RB', player('rbB', 'RB'), 1),
    row('FLEX', player('wrFlex', 'WR')),
  ]

  it('brings each player across in the slot My team starts them in', () => {
    const rows = [row('QB', null), row('RB', null), row('RB', null, 1), row('FLEX', null)]
    expect(filled(fillFromLineup(rows, source, SLOTS, []))).toEqual(['qb', 'rbA', 'rbB', 'wrFlex'])
  })

  it('places a leftover player in any slot their position fits', () => {
    // No FLEX row to take the receiver, but a WR row is open.
    const rows = [row('QB', null), row('WR', null)]
    expect(filled(fillFromLineup(rows, source, SLOTS, []))).toEqual(['qb', 'wrFlex'])
  })

  it('adds nobody from outside the source, and skips anyone already taken', () => {
    const rows = [row('QB', null), row('TE', null)]
    expect(filled(fillFromLineup(rows, source, SLOTS, ['qb']))).toEqual([null, null])
  })
})
