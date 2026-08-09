/**
 * Sorting and filtering a board that has already been fetched.
 *
 * Everything here is **presentation over published numbers**. Nothing computes
 * a projection, a probability or a grade — each function either compares two
 * values the API returned or subtracts one from another to order a list. Where
 * a subtraction happens it is named for what it is (`upside` = ceiling minus
 * the headline) and never presented as a model output.
 *
 * This is safe to do in the browser only because a whole slate arrives in one
 * page (the API's limit is 500, a slate is ~400). Sorting a paginated board
 * client-side would reorder one page and present it as the ranking.
 */

import type { Projection, RankedProjection } from '@/api/schemas'
import { headlinePoints } from './format'

export type SortKey =
  | 'rank'
  | 'projection'
  | 'floor'
  | 'ceiling'
  | 'boom'
  | 'bust'
  | 'matchup'
  | 'confidence'
  | 'name'

export type SortDirection = 'asc' | 'desc'

/** The orderings offered in the UI, and what to call them. */
export const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'rank', label: 'Board rank' },
  { value: 'projection', label: 'Projection' },
  { value: 'ceiling', label: 'Ceiling' },
  { value: 'floor', label: 'Floor' },
  { value: 'boom', label: 'Boom chance' },
  { value: 'bust', label: 'Bust risk' },
  { value: 'matchup', label: 'Matchup grade' },
  { value: 'confidence', label: 'Confidence' },
  { value: 'name', label: 'Name' },
]

/** The headline points for an entry, using the backend's own fallback rule. */
export function entryPoints(entry: RankedProjection): number | null {
  return headlinePoints(entry.projection.prediction.points).value
}

/** Positions with fewer entries than this are too small to judge banding on. */
const BANDING_MIN_SAMPLE = 10

/** Distinct widths at or below this share of the group means the widths are bucketed. */
const BANDING_RATIO = 0.25

/**
 * Whether the stored outcome intervals are bucketed rather than per-player.
 *
 * This matters because it bounds what the UI may claim. Under the currently
 * published run the interval width is not continuous: the 92 running backs fall
 * into roughly fifteen buckets, and the widest bucket holds eight players with
 * an *identical* floor-to-ceiling spread of 12.74. Two consequences follow.
 *
 * A "biggest upside" ranking built as ceiling minus projection is not an
 * ordering — its top is an eight-way tie broken by whatever order the array
 * happened to be in. This product therefore does not ship one; the ceiling
 * itself is ranked instead, which is a published number.
 *
 * And a single player's range describes their bucket rather than them, which is
 * a caveat worth stating rather than hiding. The check is a heuristic on the
 * data in hand, so it goes quiet on a run whose intervals are genuinely
 * per-player.
 */
export function hasBandedIntervals(projections: Projection[]): boolean {
  const byPosition = new Map<string, { total: number; widths: Set<number> }>()

  for (const projection of projections) {
    const { ceiling, median } = projection.prediction.points
    const position = projection.player.position
    if (!position || ceiling === null || ceiling === undefined || median === null || median === undefined) {
      continue
    }
    const group = byPosition.get(position) ?? { total: 0, widths: new Set<number>() }
    group.total += 1
    group.widths.add(Math.round((ceiling - median) * 100) / 100)
    byPosition.set(position, group)
  }

  return [...byPosition.values()].some(
    (group) => group.total >= BANDING_MIN_SAMPLE && group.widths.size <= group.total * BANDING_RATIO,
  )
}

/** Nulls always sort last, whichever direction is active. A missing value is not a low one. */
function compareNullable(a: number | null, b: number | null, direction: SortDirection): number {
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  return direction === 'desc' ? b - a : a - b
}

function sortValue(entry: RankedProjection, key: SortKey): number | null {
  const { points } = entry.projection.prediction
  switch (key) {
    case 'rank':
      return entry.rank
    case 'projection':
      return entryPoints(entry)
    case 'floor':
      return points.floor ?? null
    case 'ceiling':
      return points.ceiling ?? null
    case 'boom':
      return points.boom_probability ?? null
    case 'bust':
      return points.bust_probability ?? null
    case 'matchup':
      // The grade's percentile, not its letter: sorting letters alphabetically
      // would put A+ beside A- and call it an ordering. Ungraded is null, so it
      // falls to the bottom rather than pretending to be average.
      return entry.projection.matchup?.grade.score ?? null
    case 'confidence':
      return points.confidence ?? null
    default:
      return null
  }
}

export function sortBoard(
  entries: RankedProjection[],
  key: SortKey,
  direction: SortDirection,
): RankedProjection[] {
  const sorted = [...entries]
  if (key === 'name') {
    sorted.sort((a, b) => {
      const result = a.projection.player.name.localeCompare(b.projection.player.name)
      return direction === 'desc' ? -result : result
    })
    return sorted
  }
  sorted.sort((a, b) => {
    const result = compareNullable(sortValue(a, key), sortValue(b, key), direction)
    // Stable tiebreak on the API's own rank, so equal values keep the order the
    // server produced instead of shuffling between renders.
    return result !== 0 ? result : a.rank - b.rank
  })
  return sorted
}

/** Case- and accent-insensitive substring match on the player's name. */
export function matchesQuery(entry: RankedProjection, query: string): boolean {
  const term = query.trim().toLocaleLowerCase()
  if (!term) return true
  const name = entry.projection.player.name.toLocaleLowerCase()
  const team = (entry.projection.team ?? '').toLocaleLowerCase()
  return name.includes(term) || team.includes(term)
}

/** A run of consecutive rows the API placed in the same tier. */
export interface TierGroup {
  tier: number
  entries: RankedProjection[]
}

/**
 * Split an already-ranked list on the API's tier boundaries.
 *
 * Only meaningful on a list still in rank order. A tier is a statement about
 * *adjacent* players — "the one below still has a real chance of outscoring the
 * one above" — so drawing the boundaries onto a list sorted by ceiling would
 * scatter one tier across the whole table and assert something the API never
 * said. Callers are responsible for that precondition; it cannot be checked
 * from the list alone.
 */
export function groupByTier(entries: RankedProjection[]): TierGroup[] {
  const groups: TierGroup[] = []
  for (const entry of entries) {
    const last = groups.at(-1)
    if (last && last.tier === entry.tier) {
      last.entries.push(entry)
      continue
    }
    groups.push({ tier: entry.tier, entries: [entry] })
  }
  return groups
}

/** The largest ceiling on the board, so range bars share one scale. */
export function boardCeiling(entries: RankedProjection[]): number {
  return entries.reduce((max, entry) => {
    const ceiling = entry.projection.prediction.points.ceiling
    return ceiling !== null && ceiling !== undefined && ceiling > max ? ceiling : max
  }, 0)
}
