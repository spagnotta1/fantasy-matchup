import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

// A self-referential constraint ("every property of T is a string"), not
// `Record<string, string>`: the latter requires an explicit index signature,
// which a plain `interface`/`type` of named string fields does not have, even
// though it satisfies this shape.
type AllStringValues<T> = { [K in keyof T]: string }

/**
 * URL-search-param-backed replacement for `useState` on a flat object of
 * string filters — the same pattern `SlateProvider` (`app/SlateProvider.tsx`)
 * already uses for season/week/scoring, generalised for page-level toolbars
 * (search, position, team, sort, view, …).
 *
 * Plain `useState` loses its value the moment the owning route unmounts —
 * which React Router does on every navigation away, including the browser
 * Back button. Deriving state from the URL on every render survives both,
 * because the URL these toolbars write is exactly the URL Back restores.
 *
 * A value equal to its default is omitted from the URL so an untouched
 * toolbar doesn't clutter the address bar with `?query=&team=`.
 */
export function useUrlState<T extends AllStringValues<T>>(
  defaults: T,
): [T, (patch: Partial<T>) => void] {
  const [searchParams, setSearchParams] = useSearchParams()

  const state = useMemo(() => {
    const next = { ...defaults }
    for (const key of Object.keys(defaults)) {
      const raw = searchParams.get(key)
      if (raw !== null) next[key as keyof T] = raw as T[keyof T]
    }
    return next
  }, [searchParams, defaults])

  const setState = useCallback(
    (patch: Partial<T>) => {
      setSearchParams(
        (current) => {
          const params = new URLSearchParams(current)
          for (const key of Object.keys(patch)) {
            const value = patch[key as keyof T]
            if (value === undefined || value === defaults[key as keyof T]) {
              params.delete(key)
            } else {
              params.set(key, value as string)
            }
          }
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams, defaults],
  )

  return [state, setState]
}
