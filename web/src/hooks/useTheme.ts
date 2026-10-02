import { useCallback, useEffect, useState } from 'react'

export type ThemePreference = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'nflfp.theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

function readPreference(): ThemePreference {
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

/** What a preference draws as, given what the device currently asks for. */
export function resolveTheme(preference: ThemePreference, deviceIsDark: boolean): 'light' | 'dark' {
  if (preference === 'system') return deviceIsDark ? 'dark' : 'light'
  return preference
}

/**
 * Theme preference, applied as `data-theme` on the document root.
 *
 * Three states rather than two. "System" is the default and follows the
 * device; an explicit choice overrides it in *both* directions. A two-state
 * toggle cannot express "follow my phone", which is what most people actually
 * want.
 *
 * The attribute is always stamped, with `light` or `dark`. "System" used to
 * stamp nothing and leave the choice to a `prefers-color-scheme` block in the
 * stylesheet, which meant the dark palette had to be written twice. Resolving
 * it here, and in the inline script in `index.html` before first paint, lets
 * the stylesheet define each palette once. The cost is the listener below:
 * the device changing its mind is now this hook's to notice.
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
    const device = window.matchMedia(DARK_QUERY)
    const apply = () => root.setAttribute('data-theme', resolveTheme(preference, device.matches))
    apply()

    try {
      if (preference === 'system') window.localStorage.removeItem(STORAGE_KEY)
      else window.localStorage.setItem(STORAGE_KEY, preference)
    } catch {
      // Storage is a convenience here, not a requirement.
    }

    if (preference !== 'system') return
    device.addEventListener('change', apply)
    return () => device.removeEventListener('change', apply)
  }, [preference])

  /** Cycles light -> dark -> system, so every state is reachable from the toggle. */
  const cycle = useCallback(() => {
    setPreference((current) =>
      current === 'light' ? 'dark' : current === 'dark' ? 'system' : 'light',
    )
  }, [])

  return { preference, setPreference, cycle }
}
