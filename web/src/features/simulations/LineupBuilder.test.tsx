import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { injurySchema, type Projection } from '@/api/schemas'
import { makeProjection } from '@/test/factories'

import { LineupBuilder } from './LineupBuilder'
import type { BoardIndex } from './availability'
import type { LineupRow } from './lineupFormat'

const noop = () => {}

const QUESTIONABLE = injurySchema.parse({
  provenance: 'context',
  // As the API sends it: a designation is shown, and is not in the number.
  applied_to_projection: false,
  report_status: 'Questionable',
  will_not_play: false,
  is_questionable_or_worse: true,
})

/** Three starters; the second carries a designation. */
const PROJECTIONS: Projection[] = [
  makeProjection({ id: 'qb', name: 'Josh Allen', position: 'QB' }),
  {
    ...makeProjection({ id: 'rb', name: 'Jahmyr Gibbs', position: 'RB' }),
    context: { ...makeProjection().context, injury: QUESTIONABLE },
  },
  makeProjection({ id: 'wr', name: 'Puka Nacua', position: 'WR' }),
]

const ROWS: LineupRow[] = PROJECTIONS.map((projection) => ({
  key: projection.player.player_id,
  slot: projection.player.position ?? 'FLEX',
  player: projection.player,
}))

const BOARD: BoardIndex = {
  byPlayer: new Map(PROJECTIONS.map((projection) => [projection.player.player_id, projection])),
  complete: true,
  pending: false,
}

const render = (disclosure?: { open: boolean; onToggle: () => void }) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <LineupBuilder
        title="Your team"
        description="Your starting lineup — Standard skill lineup."
        rows={ROWS}
        slots={[]}
        board={BOARD}
        projectedPositions={new Set(['QB', 'RB', 'WR', 'TE'])}
        week={4}
        otherLineupIds={[]}
        onChange={noop}
        onAutofill={noop}
        disclosure={disclosure}
      />
    </MemoryRouter>,
  )

const words = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

/** The disclosure button's opening tag, and the id of what it controls. */
function disclosureOf(html: string) {
  const tag = /<button[^>]*aria-expanded="(true|false)"[^>]*>/.exec(html)
  return { tag: tag?.[0] ?? '', expanded: tag?.[1], controls: /aria-controls="([^"]+)"/.exec(tag?.[0] ?? '')?.[1] }
}

describe('LineupBuilder, before a run', () => {
  const html = render()

  it('is always open and offers no fold', () => {
    expect(html).not.toContain('aria-expanded')
    expect(words(html)).not.toContain('Edit lineup')
    expect(words(html)).toContain('Your starting lineup — Standard skill lineup.')
    expect(html).not.toMatch(/<div[^>]*hidden=""/)
  })

  it('heads the lineup and says how many slots are filled', () => {
    expect(html).toMatch(/<h2[^>]*>Your team<\/h2>/)
    expect(words(html)).toContain('3/3 slots filled')
  })
})

describe('LineupBuilder, folded after a run', () => {
  const html = render({ open: false, onToggle: noop })
  const header = html.slice(0, html.indexOf('hidden=""'))

  it('is one line that still says whose lineup it is, how full, and who is in it', () => {
    expect(header).toMatch(/<h2[^>]*>Your team<\/h2>/)
    expect(words(header)).toContain('3/3 slots filled')
    // In lineup order. The designated starter is named first, with the
    // designation, and is not named twice.
    expect(words(header)).toMatch(/Jahmyr Gibbs\s+Questionable\s+Josh Allen, Jahmyr Gibbs, Puka Nacua/)
  })

  it('keeps a designation in view: folding the rows does not fold the caveat', () => {
    expect(header).toContain('Questionable')
    // Named whole, in an element that does not shrink; the list of names is
    // what gives way.
    expect(header).toMatch(/<span class="[^"]*shrink-0[^"]*">Jahmyr Gibbs<span[^>]*>.*?Questionable/)
    expect(header).toMatch(/<span class="truncate">Josh Allen, Jahmyr Gibbs, Puka Nacua<\/span>/)
  })

  it('is opened by a real disclosure button that names what it opens', () => {
    const { tag, expanded, controls } = disclosureOf(html)
    expect(tag).toMatch(/^<button type="button"/)
    expect(expanded).toBe('false')
    expect(controls).toBeTruthy()
    // The body it controls is there, and hidden.
    expect(html).toMatch(new RegExp(`<div [^>]*id="${controls}" hidden=""`))
    // Two builders, two buttons: the name says whose.
    expect(words(html)).toContain('Edit lineup , Your team')
  })

  it('puts the lineup\'s own actions away with its rows', () => {
    expect(header).not.toContain('Clear Your team')
    expect(header).not.toContain('Autofill')
  })

})

describe('LineupBuilder, opened again', () => {
  const html = render({ open: true, onToggle: noop })

  it('says it is open, and shows every row with what the builder always did', () => {
    const { expanded, controls } = disclosureOf(html)
    expect(expanded).toBe('true')
    expect(html).toMatch(new RegExp(`<div [^>]*id="${controls}"`))
    expect(html).not.toMatch(new RegExp(`id="${controls}" hidden`))
    for (const name of ['Josh Allen', 'Jahmyr Gibbs', 'Puka Nacua']) {
      expect(html).toContain(`aria-label="Remove ${name} from`)
    }
    expect(words(html)).toContain('Clear Your team')
    // Open, the rows name the starters; the line says what the lineup is.
    expect(words(html)).toContain('Your starting lineup — Standard skill lineup.')
  })

  it('keeps the same button in the same place, so a press does not lose the focus', () => {
    const folded = render({ open: false, onToggle: noop })
    const strip = (markup: string) => disclosureOf(markup).tag.replace(/aria-expanded="[^"]+"/, '').replace(/aria-controls="[^"]+"/, '')
    expect(strip(html)).toBe(strip(folded))
  })
})
