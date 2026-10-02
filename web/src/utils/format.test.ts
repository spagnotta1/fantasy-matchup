import { describe, expect, it } from 'vitest'

import { makeProjection } from '@/test/factories'

import {
  EM_DASH,
  formatGameDay,
  formatInteger,
  formatLabel,
  formatPercent,
  formatPoints,
  formatScoringProfile,
  formatSigned,
  formatSpread,
  formatThreshold,
  headlinePoints,
  isCalibrated,
  ordinal,
} from './format'

describe('formatPercent', () => {
  // The rain chance arrives as a 0–1 fraction. It used to arrive as 0–100 and
  // was printed as "6200%"; these are the values that regression was seen at.
  it.each([
    [0, '0%'],
    [0.01, '1%'],
    [0.02, '2%'],
    [0.05, '5%'],
    [0.62, '62%'],
    [1, '100%'],
  ])('renders the fraction %s as %s', (fraction, text) => {
    expect(formatPercent(fraction)).toBe(text)
  })

  it('takes a number of decimals', () => {
    expect(formatPercent(0.7432, 1)).toBe('74.3%')
  })

  it('renders a missing value as a dash, not as zero', () => {
    expect(formatPercent(null)).toBe(EM_DASH)
    expect(formatPercent(undefined)).toBe(EM_DASH)
    expect(formatPercent(Number.NaN)).toBe(EM_DASH)
  })
})

describe('headlinePoints', () => {
  it('prefers the calibrated mean and says so', () => {
    const { points } = makeProjection({ expected: 14.2, predicted: 13.1 }).prediction
    expect(headlinePoints(points)).toEqual({ value: 14.2, calibrated: true })
    expect(isCalibrated(points)).toBe(true)
  })

  it('falls back to the raw output and flags it uncalibrated', () => {
    const { points } = makeProjection({ expected: null, predicted: 13.1 }).prediction
    expect(headlinePoints(points)).toEqual({ value: 13.1, calibrated: false })
    expect(isCalibrated(points)).toBe(false)
  })

  it('has nothing to show without a distribution', () => {
    expect(headlinePoints(null)).toEqual({ value: null, calibrated: false })
    expect(headlinePoints(undefined)).toEqual({ value: null, calibrated: false })
  })
})

describe('points and signs', () => {
  it('prints points to one decimal', () => {
    expect(formatPoints(19.44)).toBe('19.4')
    expect(formatPoints(20)).toBe('20.0')
    expect(formatPoints(null)).toBe(EM_DASH)
  })

  it('carries the sign on a difference, with a true minus', () => {
    expect(formatSigned(2.34)).toBe('+2.3')
    expect(formatSigned(-5.93)).toBe('−5.9')
    expect(formatSigned(0)).toBe('0.0')
    expect(formatSigned(undefined)).toBe(EM_DASH)
  })

  it('prints a threshold the way it is said', () => {
    expect(formatThreshold(20)).toBe('20')
    expect(formatThreshold(17.5)).toBe('17.5')
    expect(formatThreshold(null)).toBe(EM_DASH)
  })

  it('rounds and groups an integer', () => {
    expect(formatInteger(2877.6)).toBe((2878).toLocaleString())
    expect(formatInteger(null)).toBe(EM_DASH)
  })
})

describe('ordinal', () => {
  it.each([
    [1, '1st'],
    [2, '2nd'],
    [3, '3rd'],
    [4, '4th'],
    [11, '11th'],
    [12, '12th'],
    [13, '13th'],
    [21, '21st'],
    [22, '22nd'],
    [103, '103rd'],
    [111, '111th'],
  ])('%s is %s', (value, text) => {
    expect(ordinal(value)).toBe(text)
  })
})

describe('labels', () => {
  it('names a scoring profile', () => {
    expect(formatScoringProfile('half_ppr')).toBe('Half PPR')
    expect(formatScoringProfile('ppr')).toBe('PPR')
    expect(formatScoringProfile('standard')).toBe('Standard')
    expect(formatScoringProfile('ppr_te_premium')).toBe('PPR TE Premium')
    expect(formatScoringProfile(null)).toBe(EM_DASH)
  })

  it('turns an identifier into a label', () => {
    expect(formatLabel('boom_or_bust')).toBe('Boom or bust')
    expect(formatLabel('')).toBe(EM_DASH)
  })

  it('prints a spread as a book does', () => {
    // `team_spread` is points the team is favoured by.
    expect(formatSpread(3.5)).toBe('−3.5')
    expect(formatSpread(-7)).toBe('+7.0')
    expect(formatSpread(0)).toBe('PK')
    expect(formatSpread(null)).toBe(EM_DASH)
  })

  it('reads an API date as a local calendar day, not a UTC instant', () => {
    // "2026-10-04" must not slide to the 3rd in a timezone behind UTC.
    expect(formatGameDay('2026-10-04')).toMatch(/4/)
    expect(formatGameDay('2026-10-04')).toMatch(/Oct/)
    expect(formatGameDay('not a date')).toBe(EM_DASH)
    expect(formatGameDay(null)).toBe(EM_DASH)
  })
})
