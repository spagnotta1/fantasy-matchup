import { useCallback, useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

const PARAM = 'roster'
const STORAGE_KEY = 'nflfp.roster'
/** A fantasy roster, bench included, with room to spare. */
const MAX_PLAYERS = 30

function readStored(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : []
  } catch {
    return []
  }
}

function writeStored(ids: string[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids))
  } catch {
    // A private-mode browser with no storage quota is not a reason to fail.
  }
}

function parse(value: string | null): string[] {
  if (!value) return []
  return [...new Set(value.split(',').map((id) => id.trim()).filter(Boolean))].slice(0, MAX_PLAYERS)
}

/**
 * "My team": a list of player ids, held in the URL and remembered locally.
 *
 * Deliberately not an account or a saved league — this product has no storage
 * and no auth, by design. The roster is a query parameter, so a link *is* the
 * roster: it can be bookmarked, shared or opened on another device, the same
 * way a simulation matchup travels. The browser also remembers the last one,
 * as a per-viewer convenience exactly like the slate selection
 * (`SlateProvider`); nothing ever leaves the device except in a URL the user
 * chose to send.
 *
 * The URL wins over the remembered copy, so opening a shared roster never
 * silently shows your own instead.
 */
export function useRoster(): [string[], (ids: string[]) => void] {
  const [searchParams, setSearchParams] = useSearchParams()
  const fromUrl = searchParams.get(PARAM)
  const ids = useMemo(() => (fromUrl !== null ? parse(fromUrl) : readStored()), [fromUrl])

  // Keep the remembered copy in step with whatever is on screen.
  useEffect(() => {
    if (fromUrl !== null) writeStored(ids)
  }, [fromUrl, ids])

  const setIds = useCallback(
    (next: string[]) => {
      const clean = [...new Set(next)].slice(0, MAX_PLAYERS)
      writeStored(clean)
      setSearchParams(
        (current) => {
          const params = new URLSearchParams(current)
          if (clean.length) params.set(PARAM, clean.join(','))
          else params.delete(PARAM)
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  return [ids, setIds]
}

const LINEUP_PARAM = 'lineup'
const LINEUP_STORAGE_KEY = 'nflfp.lineup'

function readStoredLineup(): string[] | null {
  try {
    const raw = window.localStorage.getItem(LINEUP_STORAGE_KEY)
    const parsed = raw ? (JSON.parse(raw) as unknown) : null
    return Array.isArray(parsed) ? parsed.map((id) => (typeof id === 'string' ? id : '')) : null
  } catch {
    return null
  }
}

function writeStoredLineup(ids: string[] | null): void {
  try {
    if (ids) window.localStorage.setItem(LINEUP_STORAGE_KEY, JSON.stringify(ids))
    else window.localStorage.removeItem(LINEUP_STORAGE_KEY)
  } catch {
    // As above: no storage is not a failure.
  }
}

/**
 * The starting lineup a manager chose by hand, or null for the default.
 *
 * One player id per lineup slot, in slot order, with an empty string for a slot
 * left empty — `"a,,c"`. Null means "no choice made", and the page falls back to
 * the highest-projected lineup; that is a different state from a lineup whose
 * every slot was deliberately emptied.
 *
 * It travels with the roster and follows the same rule: the URL wins, and the
 * remembered copy is used only when the roster itself came from memory. A
 * shared roster link with no lineup must not pick up this browser's lineup for
 * someone else's players.
 */
export function useLineupChoice(): [string[] | null, (ids: string[] | null) => void] {
  const [searchParams, setSearchParams] = useSearchParams()
  const rosterInUrl = searchParams.get(PARAM) !== null
  const fromUrl = searchParams.get(LINEUP_PARAM)
  const choice = useMemo(() => {
    if (fromUrl !== null) return fromUrl.split(',').map((id) => id.trim())
    return rosterInUrl ? null : readStoredLineup()
  }, [fromUrl, rosterInUrl])

  const setChoice = useCallback(
    (next: string[] | null) => {
      writeStoredLineup(next)
      setSearchParams(
        (current) => {
          const params = new URLSearchParams(current)
          if (next) params.set(LINEUP_PARAM, next.join(','))
          else params.delete(LINEUP_PARAM)
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  return [choice, setChoice]
}

/** The remembered roster, for views that highlight it without owning it. */
export function useRememberedRoster(): Set<string> {
  const [ids] = useRoster()
  return useMemo(() => new Set(ids), [ids])
}
