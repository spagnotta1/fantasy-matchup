import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { FilterChip, FilterChoice, FilterSearch, FilterToolbar } from './FilterToolbar'

const noop = () => {}

const OPTIONS = [
  { value: '', label: 'All' },
  { value: 'QB', label: 'QB' },
  { value: 'RB', label: 'RB' },
]

describe('FilterToolbar', () => {
  it('is a named group, so a screen reader hears what the controls are for', () => {
    const html = renderToStaticMarkup(
      <FilterToolbar label="Filter players">
        <span>control</span>
      </FilterToolbar>,
    )
    expect(html).toMatch(/^<div role="group" aria-label="Filter players"/)
  })

  it('announces the count it is given, and draws none when there is none', () => {
    const withCount = renderToStaticMarkup(
      <FilterToolbar label="Filter players" summary="12 of 214 players">
        <span>control</span>
      </FilterToolbar>,
    )
    expect(withCount).toMatch(/<p class="[^"]*" aria-live="polite">12 of 214 players<\/p>/)

    const without = renderToStaticMarkup(
      <FilterToolbar label="Filter players">
        <span>control</span>
      </FilterToolbar>,
    )
    expect(without).not.toContain('aria-live')
  })

  it('wraps between controls and gives a search box and a select the touch height', () => {
    const html = renderToStaticMarkup(
      <FilterToolbar label="Filter players">
        <span>control</span>
      </FilterToolbar>,
    )
    expect(html).toContain('flex-wrap')
    expect(html).toContain('pointer-coarse:[&amp;_input[type=search]]:h-touch')
    expect(html).toContain('pointer-coarse:[&amp;_select]:h-touch')
  })
})

describe('FilterSearch', () => {
  const render = (value: string) =>
    renderToStaticMarkup(<FilterSearch label="Search players" value={value} onChange={noop} placeholder="Search…" />)

  it('is a labelled search box at the toolbar height', () => {
    const html = render('')
    expect(html).toMatch(/<label for="([^"]+)" class="[^"]*sr-only[^"]*">Search players<\/label>/)
    expect(html).toMatch(/<input[^>]*type="search"[^>]*class="[^"]*h-control-sm/)
  })

  it('offers a named way to clear it only while there is something to clear', () => {
    expect(render('')).not.toContain('Clear search')
    expect(render('gibbs')).toContain('<button type="button" aria-label="Clear search"')
  })
})

describe('FilterChoice', () => {
  it('is a radio group named for what it chooses, with the value checked', () => {
    const html = renderToStaticMarkup(<FilterChoice label="Position" value="RB" options={OPTIONS} onChange={noop} />)
    expect(html).toContain('role="radiogroup" aria-label="Position"')
    expect(html.match(/type="radio"/g)).toHaveLength(3)
    const checked = (html.match(/<input [^>]*>/g) ?? []).filter((input) => input.includes('checked=""'))
    expect(checked).toHaveLength(1)
    expect(checked[0]).toContain('value="RB"')
  })

  it('does not let a flex row squeeze it, so its options never wrap inside it', () => {
    const html = renderToStaticMarkup(<FilterChoice label="Position" value="" options={OPTIONS} onChange={noop} />)
    expect(html).toMatch(/^<div class="[^"]*shrink-0/)
  })
})

describe('FilterChip', () => {
  it('names its remove button by what removing does', () => {
    const html = renderToStaticMarkup(
      <FilterChip removeLabel="Show every game" onRemove={noop}>
        DET @ CAR
      </FilterChip>,
    )
    expect(html).toContain('DET @ CAR')
    expect(html).toContain('<button type="button" aria-label="Show every game" title="Show every game"')
    // A control, not a status: squared, where a pill is reserved for a label.
    expect(html).toContain('rounded-control')
    expect(html).not.toMatch(/^<span class="[^"]*rounded-full/)
  })
})
