import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { ResponseMeta } from '@/api/schemas'
import { makeSimulation } from '@/test/factories'

import { PositionalEdges } from './PositionalEdges'
import { ScoreDistribution } from './ScoreDistribution'
import { SimulationDetails, SimulationSummary } from './SimulationResults'

const A = 'Your team'
const B = 'Opponent'

const render = (node: React.ReactNode) => renderToStaticMarkup(<MemoryRouter>{node}</MemoryRouter>)

/** The words on the page, without the markup between them. */
const words = (html: string) =>
  html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')

const RESULT = makeSimulation()
const META = {
  notices: [
    'team_b: Chris Olave, Tyler Shough share an offence (NO).',
    'Player outcomes were drawn independently.',
  ],
} as unknown as ResponseMeta

describe('SimulationSummary', () => {
  const html = render(<SimulationSummary result={RESULT} labelA={A} labelB={B} />)
  const text = words(html)

  it('is one surface headed by what was asked: the week, the format, the draws and the mode', () => {
    expect((html.match(/<h2/g) ?? []).length).toBe(1)
    expect(html).toMatch(/<h2[^>]*>Result<\/h2>/)
    expect(text).toContain('Week 4 · Half PPR · 10,000 simulated weeks · Standard')
  })

  it('leads with the estimate, both sides of it, and what the figure is a share of', () => {
    expect(text).toContain('Your team — estimated win probability')
    // The real figures, for a reader of the markup; the drawn ones count up to them.
    expect(html).toContain('<span class="sr-only">59%</span>')
    expect(html).toContain('<span class="sr-only">41%</span>')
    expect(html).toContain('aria-label="Your team wins 59% of simulated weeks, Opponent wins 41%."')
    expect(text).toContain('Across 10,000 simulated weeks, Your team finished ahead in 59% of them.')
    expect(text).toContain('Both lineups tied in 0.01%.')
  })

  it('calls it an estimate and never a prediction, a confidence or a win', () => {
    expect(text).toContain('not a prediction of the result')
    expect(text).not.toMatch(/confidence/i)
    expect(text).not.toMatch(/will win|you win/i)
  })

  it('keeps the limits of the number in the same part of the summary as the number', () => {
    const estimate = html.slice(html.indexOf('aria-label="Estimated win probability"'), html.indexOf('id="simulation-scores"'))
    expect(words(estimate)).toContain(
      "It covers QB, RB, WR and TE only (no kickers or defences), simulates each player's score on its own and does not adjust for injury designations.",
    )
    expect(estimate).toContain('href="#simulation-assumptions"')
  })

  it('draws both score ranges, named, with the published quantiles and the average', () => {
    const scores = html.slice(html.indexOf('id="simulation-scores"'), html.indexOf('id="simulation-gaps"'))
    expect(scores).toContain(
      'aria-label="Your team: 10th percentile 88.9 points, 25th 101.0, median 115.3, 75th 130.0, 90th 145.5."',
    )
    expect(scores).toContain(
      'aria-label="Opponent: 10th percentile 83.0 points, 25th 95.0, median 108.1, 75th 122.0, 90th 137.6."',
    )
    const said = words(scores)
    expect(said).toContain('Your team 116.4 pts on average Low 88.9 · Middle 115.3 · High 145.5')
    expect(said).toContain('Opponent 109.3 pts on average Low 83.0 · Middle 108.1 · High 137.6')
    // Why the number above is a chance. "Above" is gone: the estimate is
    // beside this chart on a wide screen.
    expect(said).toContain('The overlap is why the result is a chance, not a certainty.')
  })

  it('shows the gap at each position, in position order, with what a gap is not', () => {
    const gaps = html.slice(html.indexOf('id="simulation-gaps"'))
    const order = ['QB', 'RB', 'WR', 'TE'].map((position) => gaps.indexOf(`aria-label="${position}:`))
    expect(order.every((at) => at > -1)).toBe(true)
    expect([...order].sort((a, b) => a - b)).toEqual(order)
    expect(gaps).toContain('aria-label="RB: Your team 52.5 points, Opponent 35.5. Your team ahead by 17.0."')
    expect(gaps).toContain('aria-label="WR: Your team 32.7 points, Opponent 44.8. Opponent ahead by 12.1."')
    expect(words(gaps)).toContain('Each gap is an average, not a guaranteed result')
  })

  it('names the two parts that are calculated, and holds the share actions', () => {
    expect((html.match(/<h3/g) ?? []).length).toBe(2)
    expect(html).toMatch(/<h3 id="simulation-scores"[^>]*>Where the scores land<\/h3>/)
    expect(html).toMatch(/<h3 id="simulation-gaps"[^>]*>Where the gap is<\/h3>/)
    expect(text).toContain('Share image')
    expect(text).toContain('Copy link')
  })

  it('names the mode the run used, from the response', () => {
    const linked = makeSimulation({ mode: 'game_environment' })
    expect(words(render(<SimulationSummary result={linked} labelA={A} labelB={B} />))).toContain(
      '10,000 simulated weeks · Linked (experimental)',
    )
  })

  it('says nothing about a tie when there was none', () => {
    const none = makeSimulation({ tie: 0 })
    expect(words(render(<SimulationSummary result={none} labelA={A} labelB={B} />))).not.toContain('tied')
  })
})

describe('SimulationDetails', () => {
  const html = render(<SimulationDetails result={RESULT} meta={META} labelA={A} labelB={B} onAdjust={() => {}} />)
  const text = words(html)

  it('opens with what the engine flagged about each lineup, in its own words', () => {
    expect(text.indexOf('About these lineups')).toBeGreaterThan(-1)
    expect(text.indexOf('About these lineups')).toBeLessThan(text.indexOf('Expected margin'))
    expect(text).toContain('Chris Olave, Tyler Shough share an offence (NO).')
    // The side is the heading, so it is not repeated on the line.
    expect(text).not.toContain('team_b:')
  })

  it('shows every notice once: the run-wide ones are in the assumptions panel only', () => {
    expect((text.match(/Player outcomes were drawn independently\./g) ?? []).length).toBe(1)
    expect(text.indexOf('Player outcomes were drawn independently.')).toBeGreaterThan(
      text.indexOf('What this simulation assumes'),
    )
  })

  it('keeps the margin and the added-up projections, and does not repeat the two averages', () => {
    expect(text).toContain('Expected margin 7.1 pts Your team ahead on average. Typical margin 7.2.')
    expect(text).toMatch(/Projections added up .*114\.7 pts/)
    expect(text).toContain('Opponent 107.8.')
    // Each lineup's average is in the summary, beside its range.
    expect(text).not.toContain('— simulated')
  })

  it('still has the swing players, the assumptions and the way back to the controls', () => {
    expect(text).toContain('Most unpredictable players')
    expect(html).toContain('id="simulation-assumptions"')
    expect(text).toContain('Adjust and run again')
    expect(text).toContain('Running this exact setup again would give the same result.')
  })

  it('is headed for the outline: sections are h2, under the page title', () => {
    expect(html).toMatch(/<h2[^>]*>About these lineups<\/h2>/)
    expect(html).toMatch(/<h2[^>]*>Most unpredictable players<\/h2>/)
    expect(html).not.toContain('<h1')
  })
})

describe('PositionalEdges', () => {
  const html = render(
    <PositionalEdges labelA={A} labelB={B} playersA={RESULT.team_a.players} playersB={RESULT.team_b.players} />,
  )

  it('prints each side\'s points beside the bar, not inside it', () => {
    const [, ...bars] = html.split('role="img"')
    expect(bars).toHaveLength(4)
    for (const bar of bars) {
      // Up to the end of the bar: nothing printed in it.
      expect(bar.slice(0, bar.indexOf('</div>'))).not.toMatch(/>\d+\.\d</)
    }
    expect(words(html)).toContain('RB 35.5 52.5 +17.0')
    expect(words(html)).toContain('WR 44.8 32.7 −12.1')
  })

  it('says once per column whose number is on which side', () => {
    expect((html.match(/aria-hidden="true"[^>]*>(?:<span><\/span>)?<span class="col-span-3/g) ?? []).length).toBe(2)
    expect(words(html)).toContain('Opponent Your team Gap')
  })

  it('calls a gap of nothing level, in words', () => {
    const same = RESULT.team_a.players
    expect(words(render(<PositionalEdges labelA={A} labelB={B} playersA={same} playersB={same} />))).toContain('Level')
  })
})

describe('ScoreDistribution', () => {
  it('lets a side\'s line wrap, so three figures and a label fit a narrow phone', () => {
    const html = render(<ScoreDistribution labelA={A} teamA={RESULT.team_a} labelB={B} teamB={RESULT.team_b} />)
    expect((html.match(/class="mb-1 flex flex-wrap /g) ?? []).length).toBe(2)
    expect((html.match(/role="img"/g) ?? []).length).toBe(2)
  })
})
