import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { comparisonEntrySchema, type ComparisonEntry } from '@/api/schemas'
import { makeProjection, type ProjectionOptions } from '@/test/factories'

import { ComparisonGrid } from './ComparisonGrid'

function entry(options: ProjectionOptions): ComparisonEntry {
  const projection = makeProjection(options)
  const { points } = projection.prediction
  return comparisonEntrySchema.parse({
    projection,
    expected: points.expected,
    floor: points.floor,
    ceiling: points.ceiling,
  })
}

const render = (entries: ComparisonEntry[]) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <ComparisonGrid entries={entries} />
    </MemoryRouter>,
  )

/** The body rows of the table, keyed by the metric each one is about. */
function rows(html: string): Map<string, string> {
  const body = html.slice(html.indexOf('<tbody'), html.indexOf('</tbody>'))
  return new Map(
    body
      .split('<tr')
      .slice(1)
      .map((row) => [/<span>([^<]+)<\/span>/.exec(row)?.[1] ?? '', row] as const),
  )
}

const marks = (row: string | undefined) => (row?.match(/data-best-mark/g) ?? []).length

// One player ahead on every projection row: the case that used to print BEST
// seven times down a column.
const LEADER = entry({ id: 'a', name: 'Leader', predicted: 18, boom: 0.4, bust: 0.03 })
const SECOND = entry({ id: 'b', name: 'Second', predicted: 15, boom: 0.3, bust: 0.06 })
const THIRD = entry({ id: 'c', name: 'Third', predicted: 12, boom: 0.2, bust: 0.09 })

describe('ComparisonGrid', () => {
  it('is one table with a column per player, at every width', () => {
    const html = render([LEADER, SECOND, THIRD])
    expect((html.match(/<table/g) ?? []).length).toBe(1)
    expect((html.match(/<th scope="col"/g) ?? []).length).toBe(4)
    // Nothing is drawn a second time for a phone: the old layout rendered
    // every number twice and hid one copy.
    expect((html.match(/>Leader</g) ?? []).length).toBe(1)
  })

  it('marks the best number once per row, and never with the word', () => {
    const table = rows(render([LEADER, SECOND, THIRD]))
    for (const metric of ['Projected', 'Floor', 'Ceiling', 'Boom chance', 'Bust risk']) {
      expect(marks(table.get(metric)), metric).toBe(1)
    }
    const html = render([LEADER, SECOND, THIRD])
    expect(html).not.toMatch(/>\s*Best\s*</i)
    expect(html).not.toContain('uppercase')
  })

  it('says the mark in words to a reader who cannot see it', () => {
    const projected = rows(render([LEADER, SECOND])).get('Projected')!
    expect(projected).toMatch(/font-semibold[^"]*">18\.0<\/span>/)
    expect(projected).toContain('<span class="sr-only">best in this row</span>')
    // The other player's number carries neither.
    expect(projected).toMatch(/<span class="tnum text-ink">15\.0<\/span>/)
  })

  it('reads bust risk the other way: the lowest is the best', () => {
    const bust = rows(render([LEADER, SECOND])).get('Bust risk')!
    const [first, second] = bust.split('<td').slice(1)
    expect(first).toContain('3%')
    expect(marks(first)).toBe(1)
    expect(marks(second)).toBe(0)
  })

  it('marks nobody on a tie', () => {
    const twin = entry({ id: 'd', name: 'Twin', predicted: 18, boom: 0.4, bust: 0.03 })
    const table = rows(render([LEADER, twin]))
    expect(marks(table.get('Projected'))).toBe(0)
    expect(marks(table.get('Bust risk'))).toBe(0)
  })

  it('marks nobody on a row that has no winner or no numbers', () => {
    const table = rows(render([entry({ id: 'a', grade: 'A' }), entry({ id: 'b', predicted: 9, grade: 'D' })]))
    expect(marks(table.get('Matchup'))).toBe(0)
    expect(marks(table.get('Opponent'))).toBe(0)
    expect(marks(table.get('Based on'))).toBe(0)
    // Neither has played, and neither fixture carries usage.
    expect(marks(table.get('Actual'))).toBe(0)
    expect(marks(table.get('Snap share'))).toBe(0)
  })

  it('leaves the ranges to the ruler, which can put them on one axis', () => {
    const html = render([LEADER, SECOND])
    expect(html).not.toContain('role="img"')
    expect(rows(html).has('Range')).toBe(false)
  })

  it('needs room for every player before it stops scrolling in its own frame', () => {
    expect(render([LEADER, SECOND])).toContain('min-width:23.5rem')
    expect(render([LEADER, SECOND, THIRD])).toContain('min-width:32rem')
  })

  it('explains the mark where it is used, without calling it a recommendation', () => {
    const html = render([LEADER, SECOND])
    expect(html).toContain('The dot marks the best number in that row, not a recommendation.')
  })
})
