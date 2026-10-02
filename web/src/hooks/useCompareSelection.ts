import { useCallback, useLayoutEffect, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

import { MAX_COMPARISON_PLAYERS } from '@/hooks/useCompare'

/** The query parameter a list keeps its ticked players in. */
export const COMPARE_PARAM = 'compare'

/**
 * A comma-separated list of player ids, as it arrives in a URL.
 *
 * De-duplicated and capped here rather than at the request: an over-long or
 * hand-edited URL should open a working screen, not a 422.
 */
export function parsePlayerIds(raw: string | null): string[] {
  if (!raw) return []
  return [...new Set(raw.split(',').map((id) => id.trim()).filter(Boolean))].slice(0, MAX_COMPARISON_PLAYERS)
}

/** The selection with one player ticked or unticked. A full selection takes no more. */
export function togglePlayerId(ids: string[], playerId: string): string[] {
  if (ids.includes(playerId)) return ids.filter((id) => id !== playerId)
  return ids.length >= MAX_COMPARISON_PLAYERS ? ids : [...ids, playerId]
}

/** The comparison of these players, in the order they were ticked. */
export function compareHref(ids: string[]): string {
  return `/compare?players=${ids.map(encodeURIComponent).join(',')}`
}

/** A query string holding only the selection, for a link that should carry it. */
export function compareSearch(ids: string[]): string {
  return ids.length === 0 ? '' : `?${COMPARE_PARAM}=${ids.map(encodeURIComponent).join(',')}`
}

export interface CompareSelection {
  /** In the order they were ticked. */
  ids: string[]
  /** Six are ticked: the rest of the boxes are disabled, not refused on arrival. */
  full: boolean
  has: (playerId: string) => boolean
  toggle: (playerId: string) => void
  clear: () => void
}

/**
 * The players ticked on a list, to be compared.
 *
 * Start/sit is a question about specific players, and the list is where the
 * candidates are: Compare used to start from an empty search box. The ticks
 * live in the page's own URL (`?compare=`), like every other piece of list
 * state here, so they survive what a reader does between ticking the first
 * and the second — Back from the comparison, a reload, a change of position
 * tab (`PositionTabs` carries the parameter) — and a link to a board with two
 * players ticked is a thing that can be sent.
 *
 * Written like a filter: in place, and without throwing the page to its top.
 */
export function useCompareSelection(): CompareSelection {
  const [searchParams, setSearchParams] = useSearchParams()
  const raw = searchParams.get(COMPARE_PARAM)
  const ids = useMemo(() => parsePlayerIds(raw), [raw])

  // The router rebuilds `setSearchParams` on every change of address, and a
  // `toggle` rebuilt with it would re-render every row of a board each time one
  // box is ticked. The rows are handed one function for the life of the page,
  // which reaches the current setter through this.
  const setter = useRef(setSearchParams)
  useLayoutEffect(() => {
    setter.current = setSearchParams
  })

  const write = useCallback(
    (next: (current: string[]) => string[]) => {
      setter.current(
        (current) => {
          const params = new URLSearchParams(current)
          const ids = next(parsePlayerIds(params.get(COMPARE_PARAM)))
          if (ids.length === 0) params.delete(COMPARE_PARAM)
          else params.set(COMPARE_PARAM, ids.join(','))
          return params
        },
        { replace: true, preventScrollReset: true },
      )
    },
    [],
  )

  const toggle = useCallback((playerId: string) => write((current) => togglePlayerId(current, playerId)), [write])
  const clear = useCallback(() => write(() => []), [write])

  return useMemo(
    () => ({
      ids,
      full: ids.length >= MAX_COMPARISON_PLAYERS,
      has: (playerId: string) => ids.includes(playerId),
      toggle,
      clear,
    }),
    [ids, toggle, clear],
  )
}
