import { describe, expect, it } from 'vitest'

import { groupNotices } from './notices'

const LABELS = { a: 'Your team', b: 'Opponent' }

describe('groupNotices', () => {
  it('sorts each notice into the lineup it names and strips the prefix', () => {
    const groups = groupNotices(
      [
        'Player outcomes were drawn independently.',
        'team_a: Kyle Pitts is listed Questionable.',
        'team_b: George Kittle, Brock Purdy share an offence (SF).',
        'team_a: Josh Allen, Quentin Johnston are in the same game (LAC at BUF).',
      ],
      LABELS,
    )
    expect(groups.map((group) => group.key)).toEqual(['a', 'b', 'run'])
    expect(groups[0]?.notices).toEqual([
      'Kyle Pitts is listed Questionable.',
      'Josh Allen, Quentin Johnston are in the same game (LAC at BUF).',
    ])
    expect(groups[1]?.notices).toEqual(['George Kittle, Brock Purdy share an offence (SF).'])
    expect(groups[2]?.notices).toEqual(['Player outcomes were drawn independently.'])
  })

  it('never drops a notice', () => {
    const notices = ['team_a: one', 'two', 'TEAM_B: three', 'team_c: four']
    const total = groupNotices(notices, LABELS).reduce((count, group) => count + group.notices.length, 0)
    expect(total).toBe(notices.length)
  })

  it('leaves an unlabelled or unrecognised notice with the run, untouched', () => {
    const [group] = groupNotices(['team_c: four', 'the team_a: prefix must lead'], LABELS)
    expect(group?.key).toBe('run')
    expect(group?.notices).toEqual(['team_c: four', 'the team_a: prefix must lead'])
  })

  it('omits a group with nothing in it', () => {
    expect(groupNotices(['team_b: only this'], LABELS).map((group) => group.key)).toEqual(['b'])
    expect(groupNotices([], LABELS)).toEqual([])
  })

  it('titles each side with its label', () => {
    const [a] = groupNotices(['team_a: x'], LABELS)
    expect(a?.title).toBe('Your team — what to know')
  })
})
