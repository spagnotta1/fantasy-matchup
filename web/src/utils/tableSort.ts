/**
 * Sorting for `DataTable`.
 *
 * Pure, so it can be tested without a table and reused where a page needs the
 * sorted list for something else (a count, a chart beside the table). The state
 * itself is two short strings, which is what lets a page keep it in the URL
 * with the rest of its filters.
 */

export type SortDirection = 'asc' | 'desc'

export interface SortState {
  /** The id of the column the rows are ordered by. */
  key: string
  direction: SortDirection
}

/** What a column sorts on. `null` and `undefined` are "no value". */
export type SortValue = number | string | null | undefined

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

function isMissing(value: SortValue): value is null | undefined {
  return value === null || value === undefined || (typeof value === 'number' && Number.isNaN(value))
}

/**
 * Orders two values, with missing ones last **in both directions**.
 *
 * A missing value is not a small one. Reversing a column should bring the
 * largest numbers to the top, not a block of em dashes, so absence sorts after
 * everything whichever way the column runs.
 */
export function compareSortValues(a: SortValue, b: SortValue, direction: SortDirection): number {
  const aMissing = isMissing(a)
  const bMissing = isMissing(b)
  if (aMissing || bMissing) return aMissing === bMissing ? 0 : aMissing ? 1 : -1

  const order =
    typeof a === 'number' && typeof b === 'number' ? a - b : collator.compare(String(a), String(b))
  return direction === 'asc' ? order : -order
}

/** A sorted copy. Stable: rows that tie keep the order they arrived in. */
export function sortRows<T>(
  rows: readonly T[],
  value: (row: T) => SortValue,
  direction: SortDirection,
): T[] {
  return rows
    .map((row, index) => ({ row, index, value: value(row) }))
    .sort((a, b) => compareSortValues(a.value, b.value, direction) || a.index - b.index)
    .map((entry) => entry.row)
}

/**
 * The state after a header is pressed: the pressed column's own first
 * direction if it was not the sorted one, the opposite direction if it was.
 *
 * The first direction belongs to the column. Numbers open largest-first,
 * because the top of a points column is what was asked for; names open A to Z.
 */
export function nextSort(
  current: SortState | null | undefined,
  key: string,
  firstDirection: SortDirection,
): SortState {
  if (current?.key !== key) return { key, direction: firstDirection }
  return { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
}

/**
 * Reads a sort out of two URL strings, falling back for anything a hand-edited
 * address might hold: an unknown column, a direction that is neither.
 */
export function parseSort(
  key: string | null | undefined,
  direction: string | null | undefined,
  sortable: readonly string[],
  fallback: SortState,
): SortState {
  if (!key || !sortable.includes(key)) return fallback
  return { key, direction: direction === 'asc' || direction === 'desc' ? direction : fallback.direction }
}
