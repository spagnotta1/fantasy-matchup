import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { perPlayerRangeBoard, sharedRangeBoard } from '@/test/factories'

import { CalibrationNotice } from './CalibrationNotice'

const render = (projections: Parameters<typeof CalibrationNotice>[0]['projections']) =>
  renderToStaticMarkup(<CalibrationNotice projections={projections} />)

const SHARED = /shared across groups of similar players/
const APPROXIMATE = /projections are approximate/

describe('CalibrationNotice', () => {
  // The regression. On run 146 every projection is calibrated and the ranges
  // are still shared — 2 distinct widths among 90 quarterbacks — but the
  // shared-range sentence sat behind the "uncalibrated" check and never showed.
  it('states that ranges are shared on a calibrated run', () => {
    const html = render(sharedRangeBoard(40, 3))
    expect(html).toMatch(SHARED)
    expect(html).not.toMatch(APPROXIMATE)
  })

  it('renders nothing on a calibrated run with per-player ranges', () => {
    expect(render(perPlayerRangeBoard(40))).toBe('')
  })

  it('states both on an uncalibrated run with shared ranges', () => {
    const html = render(sharedRangeBoard(40, 3, { expected: null }))
    expect(html).toMatch(APPROXIMATE)
    expect(html).toMatch(SHARED)
  })

  it('states only the calibration caveat on an uncalibrated run with per-player ranges', () => {
    const html = render(perPlayerRangeBoard(40, { expected: null }))
    expect(html).toMatch(APPROXIMATE)
    expect(html).not.toMatch(SHARED)
  })

  it('does not judge a handful of players as shared', () => {
    // Six players comparing on the Compare page are too few to call banded.
    expect(render(sharedRangeBoard(6, 1))).toBe('')
  })

  it('renders nothing with no projections', () => {
    expect(render(undefined)).toBe('')
    expect(render([])).toBe('')
  })
})
