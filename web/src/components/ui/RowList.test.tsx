import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { ROW_LIST_BELOW } from '@/hooks/useRowList'

import { RowList, RowListGroup, RowListItem, RowListLine, RowListRows, RowListTitle } from './RowList'

const render = (node: React.ReactNode) => renderToStaticMarkup(<MemoryRouter>{node}</MemoryRouter>)

describe('RowList', () => {
  it('says once what the right-hand number of every row is', () => {
    const html = render(
      <RowList value="Projected points">
        <RowListRows />
      </RowList>,
    )
    expect(html).toMatch(/<p class="[^"]*justify-between[^"]*"><span>Player<\/span><span>Projected points<\/span><\/p>/)
  })

  it('is a query container, and hands its rows the width of their leading slot', () => {
    const html = render(
      <RowList value="Change" lead="3.25rem">
        <RowListRows />
      </RowList>,
    )
    expect(html).toMatch(/<div data-row-list="" class="@container" style="--row-lead:3.25rem">/)
  })

  it('prints the key to a mark only when it is given one', () => {
    const withKey = render(
      <RowList value="Change" note="The lighter bar is the average.">
        <RowListRows />
      </RowList>,
    )
    expect(withKey).toContain('The lighter bar is the average.')
    expect((withKey.match(/<p /g) ?? []).length).toBe(2)

    const without = render(
      <RowList value="Change">
        <RowListRows />
      </RowList>,
    )
    expect((without.match(/<p /g) ?? []).length).toBe(1)
  })
})

describe('RowListGroup', () => {
  const group = (as?: 'h2' | 'h3') =>
    render(
      <RowListGroup id="report-out" as={as} heading="Ruled out" note="18 players">
        <RowListRows />
      </RowListGroup>,
    )

  it('is a section named by its heading, so a screen reader hears whose rows these are', () => {
    const html = group()
    expect(html).toMatch(/^<section aria-labelledby="report-out"/)
    expect(html).toMatch(/<h3 id="report-out"[^>]*>Ruled out<span class="[^"]*font-normal[^"]*">18 players<\/span><\/h3>/)
  })

  it('takes the heading level the page needs', () => {
    expect(group('h2')).toContain('<h2 id="report-out"')
  })
})

describe('RowListItem', () => {
  const row = (props: { highlighted?: boolean } = {}) =>
    render(
      <RowListItem to="/players/00-0031234" {...props}>
        <span>1</span>
        <RowListTitle name="Jahmyr Gibbs" meta="RB · DET @ CAR">
          <b>Questionable</b>
        </RowListTitle>
        <span>19.4</span>
        <RowListLine>the rest</RowListLine>
      </RowListItem>,
    )

  it('is one link, and the whole row is inside it', () => {
    const html = row()
    expect((html.match(/<a /g) ?? []).length).toBe(1)
    expect(html).toMatch(/^<li class=""><a class="[^"]*grid[^"]*" href="\/players\/00-0031234"[^>]*>.*<\/a><\/li>$/)
  })

  it('lays its children on the lead, the title and the number, with further lines under the title', () => {
    const html = row()
    expect(html).toContain('grid-cols-[var(--row-lead,1.5rem)_minmax(0,1fr)_auto]')
    expect(html).toMatch(/<span class="col-span-2 col-start-2 flex items-center gap-2">the rest<\/span>/)
  })

  it('sets the name first, then the meta in one unbroken run, then the flags', () => {
    const html = row()
    const name = html.indexOf('Jahmyr Gibbs')
    const meta = html.indexOf('RB · DET @ CAR')
    const flag = html.indexOf('Questionable')
    expect(name).toBeGreaterThan(-1)
    expect(meta).toBeGreaterThan(name)
    expect(flag).toBeGreaterThan(meta)
    expect(html).toMatch(/<span class="[^"]*truncate[^"]*">Jahmyr Gibbs<\/span>/)
    expect(html).toMatch(/<span class="[^"]*whitespace-nowrap[^"]*">RB · DET @ CAR<\/span>/)
  })

  it('tints a row the reader marked, and publishes the tint for an animation to settle on', () => {
    expect(row()).not.toContain('--row-rest')
    expect(row({ highlighted: true })).toContain('[--row-rest:color-mix(')
  })
})

describe('the room a table needs', () => {
  it('is a frozen player column and two columns of numbers', () => {
    // A 412px phone has 378px for its table and gets the list; a 768px tablet
    // has 734px and keeps the table.
    expect(ROW_LIST_BELOW).toBeGreaterThan(412 - 34)
    expect(ROW_LIST_BELOW).toBeLessThan(768 - 34)
  })
})
