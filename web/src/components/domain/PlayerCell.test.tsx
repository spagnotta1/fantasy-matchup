import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { PlayerCell } from './PlayerCell'

const PLAYER = { player_id: '00-0031234', name: 'Jahmyr Gibbs', headshot_url: null }

const render = (props: Partial<Parameters<typeof PlayerCell>[0]> = {}) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <PlayerCell player={PLAYER} {...props} />
    </MemoryRouter>,
  )

describe('PlayerCell', () => {
  it('names the player with the row link to their page', () => {
    const html = render()
    expect(html).toMatch(/<a data-row-link="" class="[^"]*font-medium[^"]*" href="\/players\/00-0031234"[^>]*>Jahmyr Gibbs<\/a>/)
  })

  it('draws an ordinary link, not the row link, in a row with actions of its own', () => {
    const html = render({ rowLink: false })
    expect(html).toContain('href="/players/00-0031234"')
    expect(html).not.toContain('data-row-link')
  })

  it('sets the meta after the name in one unbroken run, then the flags', () => {
    const html = render({ meta: 'RB · DET @ CAR', children: <b>Questionable</b> })
    const name = html.indexOf('Jahmyr Gibbs')
    const meta = html.indexOf('RB · DET @ CAR')
    const flag = html.indexOf('Questionable')
    expect(name).toBeGreaterThan(-1)
    expect(meta).toBeGreaterThan(name)
    expect(flag).toBeGreaterThan(meta)
    expect(html).toMatch(/<span class="[^"]*whitespace-nowrap[^"]*">RB · DET @ CAR<\/span>/)
  })

  it('draws no meta element when there is none', () => {
    expect(render()).not.toContain('whitespace-nowrap')
  })
})
