import { useCallback, useState } from 'react'

const STORAGE_KEY = 'nflfp.sidebar'

function read(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'rail'
  } catch {
    return false
  }
}

/**
 * Whether the desktop sidebar is drawn as a rail of icons, remembered in this
 * browser.
 *
 * A preference, kept beside the theme and the row height and not in the URL: a
 * link someone sends should not fold the sidebar of whoever opens it. The rail
 * gives a table 184px more, which in a 1,100px window is the difference
 * between the board's table and its two-line list.
 */
export function useSidebarRail(): [boolean, (next: boolean) => void] {
  const [rail, setRail] = useState(read)

  const set = useCallback((next: boolean) => {
    setRail(next)
    try {
      if (next) window.localStorage.setItem(STORAGE_KEY, 'rail')
      else window.localStorage.removeItem(STORAGE_KEY)
    } catch {
      // Storage is a convenience here, not a requirement.
    }
  }, [])

  return [rail, set]
}
