import { describe, expect, it } from 'vitest'

import type { SimulatedPlayer } from '@/api/schemas'

import { collectSwings, groupSwingsByWidth, type Swing } from './swing'

function simulated(name: string, floor: number | null, ceiling: number | null, final = false): SimulatedPlayer {
  return {
    provenance: 'model',
    player_id: name,
    name,
    slot: 'RB',
    position: 'RB',
    team: 'DET',
    game_id: null,
    expected_points: floor === null || ceiling === null ? null : (floor + ceiling) / 2,
    floor,
    ceiling,
    simulated_mean: 10,
    final: final ? { provenance: 'actual', points: 12, official: true, source: 'nflverse' } : null,
  }
}

function swings(...ranges: [name: string, floor: number, ceiling: number][]): Swing[] {
  return collectSwings(
    ranges.map(([name, floor, ceiling]) => simulated(name, floor, ceiling)),
    'Your team',
  )
}

const names = (groups: ReturnType<typeof groupSwingsByWidth>) =>
  groups.map((group) => group.members.map((swing) => swing.player.name))

describe('groupSwingsByWidth', () => {
  it('orders unequal widths widest first, each alone', () => {
    const groups = groupSwingsByWidth(
      swings(['narrow', 5, 15], ['widest', 2, 30], ['middle', 4, 22]),
      6,
    )
    expect(names(groups)).toEqual([['widest'], ['middle'], ['narrow']])
    expect(groups.map((group) => group.width)).toEqual(['28.0', '18.0', '10.0'])
    expect(groups.every((group) => group.size === 1 && group.hidden === 0)).toBe(true)
  })

  it('returns equal widths as one tied group, in the order given', () => {
    // Week 4 of 2026, run 146: five running backs with the same 22.8 width.
    const groups = groupSwingsByWidth(
      swings(
        ['Bijan Robinson', 6.7, 29.5],
        ['Jahmyr Gibbs', 9.7, 32.5],
        ['Kenneth Walker III', 8.1, 30.9],
        ['Josh Allen', 9.4, 30.1],
        ['Jonathan Taylor', 4.7, 27.5],
      ),
      6,
    )
    expect(groups).toHaveLength(2)
    expect(groups[0]).toMatchObject({ width: '22.8', size: 4, hidden: 0 })
    // Lineup order, not an order invented by the sort.
    expect(names(groups)[0]).toEqual([
      'Bijan Robinson',
      'Jahmyr Gibbs',
      'Kenneth Walker III',
      'Jonathan Taylor',
    ])
    expect(names(groups)[1]).toEqual(['Josh Allen'])
  })

  it('does not reorder a tie when the input order changes its sort position', () => {
    const forward = groupSwingsByWidth(swings(['a', 0, 10], ['b', 5, 15], ['c', 2, 12]), 6)
    const reversed = groupSwingsByWidth(swings(['c', 2, 12], ['b', 5, 15], ['a', 0, 10]), 6)
    expect(names(forward)).toEqual([['a', 'b', 'c']])
    expect(names(reversed)).toEqual([['c', 'b', 'a']])
  })

  it('treats widths that print the same as tied', () => {
    // 22.83 and 22.79 both read "22.8 wide" on screen.
    const groups = groupSwingsByWidth(swings(['x', 1, 23.83], ['y', 1, 23.79], ['z', 1, 23.9]), 6)
    expect(names(groups)).toEqual([['z'], ['x', 'y']])
  })

  it('reports what a cap leaves out of a tie instead of cutting it silently', () => {
    const groups = groupSwingsByWidth(
      swings(['wide', 0, 30], ['t1', 0, 20], ['t2', 1, 21], ['t3', 2, 22], ['t4', 3, 23]),
      3,
    )
    expect(names(groups)).toEqual([['wide'], ['t1', 't2']])
    expect(groups[1]).toMatchObject({ width: '20.0', size: 4, hidden: 2 })
  })

  it('never starts a group it has no room for', () => {
    const groups = groupSwingsByWidth(swings(['a', 0, 30], ['b', 0, 20], ['c', 0, 10]), 2)
    expect(names(groups)).toEqual([['a'], ['b']])
  })

  it('returns nothing for an empty list', () => {
    expect(groupSwingsByWidth([], 6)).toEqual([])
  })
})

describe('collectSwings', () => {
  it('leaves out players with no range and players whose game is over', () => {
    const collected = collectSwings(
      [simulated('ranged', 3, 20), simulated('no range', null, null), simulated('done', 3, 20, true)],
      'Opponent',
    )
    expect(collected.map((swing) => swing.player.name)).toEqual(['ranged'])
    expect(collected[0]).toMatchObject({ side: 'Opponent', spread: 17 })
  })
})
