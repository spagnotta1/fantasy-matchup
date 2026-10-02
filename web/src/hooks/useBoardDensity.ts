import { useCallback, useState } from 'react'

import type { TableDensity } from '@/components/ui/DataTable'

/** The two row heights the board offers: 40px, and 48px for more room. */
export type BoardDensity = Extract<TableDensity, 'default' | 'comfortable'>

const STORAGE_KEY = 'nflfp.board.density'

function read(): BoardDensity {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'comfortable' ? 'comfortable' : 'default'
  } catch {
    return 'default'
  }
}

/**
 * How tall the board's rows are, remembered in this browser.
 *
 * A preference, not a filter, which is why it is kept beside the theme and the
 * roster rather than in the URL with the search and the sort: a link to "RBs
 * sorted by ceiling" should not also set the row height of whoever opens it.
 */
export function useBoardDensity(): [BoardDensity, (next: BoardDensity) => void] {
  const [density, setDensity] = useState<BoardDensity>(read)

  const set = useCallback((next: BoardDensity) => {
    setDensity(next)
    try {
      if (next === 'default') window.localStorage.removeItem(STORAGE_KEY)
      else window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Storage is a convenience here, not a requirement.
    }
  }, [])

  return [density, set]
}
