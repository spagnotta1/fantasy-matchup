/**
 * Presentation helpers.
 *
 * Formatting only. Nothing here computes a projection, a probability or a
 * grade — those come from the API and are rendered as received. The one
 * judgement call in this file is `headlinePoints`, and it exists to *mirror* a
 * rule the backend already defines rather than to invent one.
 */

import type { Points } from '@/api/schemas'

/** Rendered wherever a number is genuinely absent, rather than zero. */
export const EM_DASH = '—'

/**
 * The projected-points number to display.
 *
 * The API documents `prediction.points.expected` as the headline and
 * `predicted` as lineage-only. But `expected` is null on any run written before
 * the distribution layer existed, and the backend handles that itself:
 * `PointDistribution.headline` in `nflfp/services/dto.py` is
 * `expected if expected is not None else predicted`, and the repository orders
 * boards by `COALESCE(pp.expected_points, pp.predicted_points)`.
 *
 * This applies the same rule so the frontend and the ranking it renders cannot
 * disagree, and reports which branch it took. `calibrated: false` means the
 * number is the raw model output — conditionally biased by construction — and
 * the UI is expected to say so rather than presenting it as a calibrated mean.
 */
export function headlinePoints(points: Points | null | undefined): {
  value: number | null
  calibrated: boolean
} {
  if (!points) return { value: null, calibrated: false }
  if (points.expected !== null && points.expected !== undefined) {
    return { value: points.expected, calibrated: true }
  }
  return { value: points.predicted, calibrated: false }
}

/** Whether a distribution carries the calibrated mean the API documents as the headline. */
export function isCalibrated(points: Points | null | undefined): boolean {
  return points?.expected !== null && points?.expected !== undefined
}

/** Fantasy points. One decimal is the convention every fantasy platform uses. */
export function formatPoints(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH
  return value.toFixed(digits)
}

/** A signed delta, where the sign carries the meaning. */
export function formatSigned(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH
  const formatted = Math.abs(value).toFixed(digits)
  if (value > 0) return `+${formatted}`
  if (value < 0) return `−${formatted}`
  return formatted
}

/** A 0-1 proportion as a percentage. */
export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH
  return `${(value * 100).toFixed(digits)}%`
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function formatInteger(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH
  return Math.round(value).toLocaleString()
}

/** `1` -> `1st`. Used for ranks, which read wrong as bare integers in prose. */
export function ordinal(value: number): string {
  const remainderTen = value % 10
  const remainderHundred = value % 100
  if (remainderTen === 1 && remainderHundred !== 11) return `${value}st`
  if (remainderTen === 2 && remainderHundred !== 12) return `${value}nd`
  if (remainderTen === 3 && remainderHundred !== 13) return `${value}rd`
  return `${value}th`
}

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
})

/** An ISO date from the API as a short, local, human date. */
export function formatGameDay(value: string | null | undefined): string {
  if (!value) return EM_DASH
  const parsed = new Date(value.length === 10 ? `${value}T00:00:00` : value)
  if (Number.isNaN(parsed.getTime())) return EM_DASH
  return DATE_FORMAT.format(parsed)
}

/** `half_ppr` -> `Half PPR`. The API's profile ids are snake_case identifiers. */
export function formatScoringProfile(profile: string | null | undefined): string {
  if (!profile) return EM_DASH
  return profile
    .split('_')
    .map((part) => (part === 'ppr' || part === 'te' ? part.toUpperCase() : part))
    .map((part) => (part === part.toUpperCase() ? part : part.charAt(0).toUpperCase() + part.slice(1)))
    .join(' ')
}

/** `very_low` -> `Very low`. Confidence labels arrive as identifiers. */
export function formatLabel(value: string | null | undefined): string {
  if (!value) return EM_DASH
  const spaced = value.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** A spread as a book would print it: `KC -3.5`. */
export function formatSpread(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH
  if (value === 0) return 'PK'
  // `team_spread` is points the team is favoured by, so a positive value is a
  // favourite and prints with a minus, the way a sportsbook shows it.
  return value > 0 ? `−${value.toFixed(1)}` : `+${Math.abs(value).toFixed(1)}`
}
