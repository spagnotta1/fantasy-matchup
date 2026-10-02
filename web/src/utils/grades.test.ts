import { describe, expect, it } from 'vitest'

import { toneForLetter, toneForScore } from './grades'

describe('toneForLetter', () => {
  it('reads the head of the letter, so A+ and A- agree', () => {
    expect(toneForLetter('A+')).toBe('positive')
    expect(toneForLetter('a-')).toBe('positive')
    expect(toneForLetter('B')).toBe('info')
    expect(toneForLetter('C+')).toBe('neutral')
    expect(toneForLetter('D-')).toBe('caution')
    expect(toneForLetter('F')).toBe('negative')
  })
})

describe('toneForScore', () => {
  const band = 100 / 13

  it('uses the same thirteen-step ladder the API draws letters from', () => {
    expect(toneForScore(100)).toBe('positive')
    expect(toneForScore(10 * band)).toBe('positive')
    expect(toneForScore(10 * band - 0.01)).toBe('info')
    expect(toneForScore(7 * band)).toBe('info')
    expect(toneForScore(7 * band - 0.01)).toBe('neutral')
    expect(toneForScore(4 * band)).toBe('neutral')
    expect(toneForScore(4 * band - 0.01)).toBe('caution')
    expect(toneForScore(band)).toBe('caution')
    expect(toneForScore(band - 0.01)).toBe('negative')
    expect(toneForScore(0)).toBe('negative')
  })

  it('is neutral, not average, when there is no score', () => {
    expect(toneForScore(null)).toBe('neutral')
    expect(toneForScore(undefined)).toBe('neutral')
  })
})
