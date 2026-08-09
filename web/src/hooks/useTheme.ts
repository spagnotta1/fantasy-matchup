import { useCallback, useEffect, useState } from 'react'

export type ThemePreference = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'nflfp.theme'

function readPreference(): ThemePreference {
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

/**
 * Theme preference, applied as `data-theme` on the document root.
 *
 * Three states rather than two. "System" is the default and stamps no
 * attribute, which lets the stylesheet's `prefers-color-scheme` block decide;
 * an explicit choice stamps the attribute and overrides the OS in *both*
 * directions. A two-state toggle cannot express "follow my phone", which is
 * what most people actually want.
 */
export function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(() => {
    try {
      return readPreference()
    } catch {
      return 'system'
    }
  })

  useEffect(() => {
    const root = document.documentElement
    if (preference === 'system') {
      root.removeAttribute('data-theme')
    } else {
      root.setAttribute('data-theme', preference)
    }
    try {
      if (preference === 'system') window.localStorage.removeItem(STORAGE_KEY)
      else window.localStorage.setItem(STORAGE_KEY, preference)
    } catch {
      // Storage is a convenience here, not a requirement.
    }
  }, [preference])

  /** Cycles light -> dark -> system, so every state is reachable from the toggle. */
  const cycle = useCallback(() => {
    setPreference((current) =>
      current === 'light' ? 'dark' : current === 'dark' ? 'system' : 'light',
    )
  }, [])

  return { preference, setPreference, cycle }
}
