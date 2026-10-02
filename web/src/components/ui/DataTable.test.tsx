import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import {
  DataTable,
  GroupHeaderRow,
  RowLink,
  Table,
  TableBody,
  TableCell,
  TableRow,
  type DataTableColumn,
  type DataTableProps,
} from './DataTable'

interface Row {
  id: string
  name: string
  points: number | null
}

const ROWS: Row[] = [
  { id: 'a', name: 'Bijan Robinson', points: 16.5 },
  { id: 'b', name: 'Jahmyr Gibbs', points: 19.4 },
  { id: 'c', name: 'A rookie', points: null },
  { id: 'd', name: 'Derrick Henry', points: 17.1 },
]

const COLUMNS: DataTableColumn<Row>[] = [
  {
    id: 'name',
    header: 'Player',
    rowHeader: true,
    sortValue: (row) => row.name,
    cell: (row) => <RowLink to={`/players/${row.id}`}>{row.name}</RowLink>,
  },
  { id: 'team', header: 'Team', cell: () => 'DET' },
  {
    id: 'points',
    header: 'Projection',
    numeric: true,
    sortValue: (row) => row.points,
    cell: (row) => (row.points === null ? '—' : row.points.toFixed(1)),
  },
]

const table = (props: Partial<DataTableProps<Row>> = {}): ReactElement => (
  <DataTable caption="Running backs" columns={COLUMNS} rows={ROWS} rowKey={(row) => row.id} {...props} />
)
const render = (props?: Partial<DataTableProps<Row>>) => renderToStaticMarkup(<MemoryRouter>{table(props)}</MemoryRouter>)

/** The text of each body row's first cell, in order. */
const names = (html: string) => [...html.matchAll(/<th scope="row"[^>]*><a [^>]*>([^<]+)<\/a>/g)].map((match) => match[1])

describe('DataTable structure', () => {
  it('is a real table with a caption, column headers and row headers', () => {
    const html = render()
    expect(html).toMatch(/<table[^>]*><caption class="sr-only">Running backs<\/caption><thead><tr><th scope="col"/)
    expect(html.match(/<th scope="col"/g)).toHaveLength(3)
    expect(html.match(/<th scope="row"/g)).toHaveLength(4)
  })

  it('aligns numbers right in tabular figures, and text left', () => {
    const html = render()
    // Header and cell of the numeric column.
    expect(html).toMatch(/<th scope="col"[^>]*class="[^"]*text-right[^"]*"[^>]*>Projection<\/th>/)
    expect(html).toMatch(/<td class="[^"]*tnum[^"]*text-right[^"]*">16\.5<\/td>/)
    expect(html).toMatch(/<th scope="col"[^>]*class="[^"]*text-left[^"]*"[^>]*>Player<\/th>/)
    // A text cell carries neither.
    expect(html).toMatch(/<td class="(?![^"]*tnum)(?![^"]*text-right)[^"]*">DET<\/td>/)
  })

  it('sets the row height from the density', () => {
    expect(render()).toContain('--dt-row:var(--spacing-row)')
    expect(render({ density: 'compact' })).toContain('--dt-row:var(--spacing-row-compact)')
    expect(render({ density: 'comfortable' })).toContain('--dt-row:var(--spacing-row-comfortable)')
  })

  it('keeps one header style: one type token, no forced capitals', () => {
    const headers = [...render().matchAll(/<th scope="col"[^>]*class="([^"]*)"/g)].map((match) => match[1])
    for (const classes of headers) {
      expect(classes).toContain('text-caption')
      expect(classes).not.toContain('uppercase')
    }
  })
})

describe('DataTable sorting', () => {
  it('leaves rows in the order given when there is no sort', () => {
    expect(names(render())).toEqual(['Bijan Robinson', 'Jahmyr Gibbs', 'A rookie', 'Derrick Henry'])
  })

  it('sorts by the column, with a missing value last either way', () => {
    const noop = () => {}
    expect(names(render({ sort: { key: 'points', direction: 'desc' }, onSortChange: noop }))).toEqual([
      'Jahmyr Gibbs',
      'Derrick Henry',
      'Bijan Robinson',
      'A rookie',
    ])
    expect(names(render({ sort: { key: 'points', direction: 'asc' }, onSortChange: noop }))).toEqual([
      'Bijan Robinson',
      'Derrick Henry',
      'Jahmyr Gibbs',
      'A rookie',
    ])
  })

  it('marks only the sorted column with aria-sort, and says the sort in the caption', () => {
    const html = render({ sort: { key: 'points', direction: 'desc' }, onSortChange: () => {} })
    expect(html.match(/aria-sort=/g)).toHaveLength(1)
    expect(html).toMatch(/<th scope="col" aria-sort="descending"[^>]*><button/)
    expect(html).toContain('<caption class="sr-only">Running backs, sorted by projection, descending</caption>')
  })

  it('gives a sortable column a button and a plain column none', () => {
    const html = render({ sort: null, onSortChange: () => {} })
    expect(html.match(/<button type="button"/g)).toHaveLength(2)
    expect(html).toMatch(/<th scope="col"[^>]*>Team<\/th>/)
  })

  it('draws no sort buttons when nothing can change the sort', () => {
    expect(render({ sort: { key: 'points', direction: 'desc' } })).not.toContain('<button')
  })

  // A sorted column's arrow is part of the header; an unsorted column's is a
  // hint hung outside the label, so it reserves no width in six columns.
  it('reserves room for the arrow only in the sorted column', () => {
    const html = render({ sort: { key: 'points', direction: 'desc' }, onSortChange: () => {} })
    const icons = [...html.matchAll(/<svg[^>]*class="([^"]*)"/g)].map((match) => match[1] ?? '')
    expect(icons).toHaveLength(2)
    expect(icons.filter((classes) => classes.includes('absolute'))).toHaveLength(1)
    expect(icons.filter((classes) => classes.includes('opacity-0'))).toHaveLength(1)
  })
})

describe('DataTable column explanations', () => {
  const withTip = (sortable: boolean): DataTableColumn<Row>[] => [
    {
      id: 'name',
      header: 'Player',
      rowHeader: true,
      cell: (row) => row.name,
    },
    {
      id: 'points',
      header: 'Projection',
      numeric: true,
      tip: 'Expected fantasy points this week.',
      sortValue: sortable ? (row) => row.points : undefined,
      cell: (row) => String(row.points),
    },
  ]

  it('marks an explained header and draws no icon for it', () => {
    const html = render({ columns: withTip(false) })
    expect(html).toMatch(/<span class="[^"]*decoration-dotted[^"]*">Projection<\/span>/)
    expect(html).not.toContain('<svg')
    // Not sortable, so the label itself is the tab stop that opens the tip.
    expect(html).toMatch(/<span tabindex="0"[^>]*><span class="[^"]*decoration-dotted/)
  })

  it('describes a sort button by its explanation without adding a tab stop', () => {
    const html = render({ columns: withTip(true), sort: null, onSortChange: () => {} })
    const described = html.match(/<button type="button" aria-describedby="([^"]+)"/)
    expect(described).not.toBeNull()
    // The description is in the document, hidden, so it is read as the
    // button's description and not as part of the column's name.
    expect(html).toContain(`<span id="${described?.[1]}" hidden="">Expected fantasy points this week.</span>`)
    expect(html).not.toContain('tabindex="0"')
  })
})

describe('DataTable layout', () => {
  it('sizes columns from the header alone when asked to', () => {
    expect(render({ layout: 'fixed' })).toMatch(/<table[^>]*class="[^"]*table-fixed/)
    expect(render()).not.toContain('table-fixed')
  })

  it('tells the header where to stop', () => {
    expect(render()).toContain('--dt-sticky-top:calc(var(--spacing-shell-bar) + 1px)')
    expect(render({ stickyTop: '7rem' })).toContain('--dt-sticky-top:7rem')
  })
})

describe('DataTable rows', () => {
  it('marks the row link so the row can extend its target', () => {
    expect(render()).toContain('<a data-row-link="" class="')
    expect(render()).toContain('href="/players/b"')
  })

  it('marks a selected row for assistive technology as well as visually', () => {
    const html = render({ isSelected: (row) => row.id === 'b' })
    expect(html.match(/aria-current="true"/g)).toHaveLength(1)
    expect(html).toMatch(/<tr data-selected="true" aria-current="true" class="[^"]*bg-accent-soft/)
  })
})

describe('Table parts', () => {
  const parts = (row: ReactElement) =>
    renderToStaticMarkup(
      <MemoryRouter>
        <Table caption="Roster">
          <TableBody>{row}</TableBody>
        </Table>
      </MemoryRouter>,
    )

  it('tints a highlighted row opaquely, without claiming it is the current one', () => {
    const html = parts(
      <TableRow highlighted>
        <TableCell>RB</TableCell>
      </TableRow>,
    )
    expect(html).toContain('data-highlighted="true"')
    expect(html).not.toContain('aria-current')
    // Mixed with the surface, not translucent: a frozen cell inherits it.
    expect(html).toContain('color-mix(in_oklch,var(--color-accent-soft)_40%,var(--color-surface))')
    expect(html).not.toMatch(/bg-accent-soft\/\d/)
  })

  it('heads a row group with a rowgroup header whose words stay at the left edge', () => {
    const html = parts(<GroupHeaderRow colSpan={4}>Ruled out</GroupHeaderRow>)
    expect(html).toMatch(/<th scope="rowgroup" colSpan="4"[^>]*><span class="[^"]*sticky[^"]*left-2\.5[^"]*">Ruled out<\/span><\/th>/)
  })

  it('positions visually hidden cell text against its own frame', () => {
    expect(parts(<TableRow />)).toMatch(/^<div[^>]*class="relative /)
  })
})

describe('DataTable states', () => {
  it('draws placeholder rows under the real header while loading, and says so', () => {
    const html = render({ rows: [], loading: true, loadingRows: 3 })
    expect(html).toContain('aria-busy="true"')
    expect(html.match(/<th scope="col"/g)).toHaveLength(3)
    expect(html.match(/<tr class=/g)).toHaveLength(3)
    expect(html).toContain('<span class="sr-only">Loading</span>')
  })

  it('keeps the header and explains an empty table', () => {
    const html = render({ rows: [], empty: <p>No players match this position.</p> })
    expect(html.match(/<th scope="col"/g)).toHaveLength(3)
    expect(html).toContain('<td colSpan="3"><p>No players match this position.</p></td>')
  })
})
