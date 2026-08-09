import { useCallback, useEffect, useMemo, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useScoringProfiles, useSeasons } from '@/hooks/useCatalog'

import { SlateContext, type SlateSelection } from './slate-context'

const SEASON_PARAM = 'season'
const WEEK_PARAM = 'week'
const PROFILE_PARAM = 'scoring'
const STORAGE_KEY = 'nflfp.slate'

interface StoredSlate {
  season?: number
  week?: number
  scoringProfile?: string
}

function readStored(): StoredSlate {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as StoredSlate) : {}
  } catch {
    return {}
  }
}

function writeStored(value: StoredSlate): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    // A private-mode browser with no storage quota is not a reason to fail.
  }
}

function parseIntParam(value: string | null): number | null {
  if (!value) return null
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) ? parsed : null
}

/**
 * Resolves and owns the global slate selection.
 *
 * The defaulting deserves an explanation, because it deviates from simply
 * letting the API decide. The API's own default is "the upcoming week", which
 * is correct for a live season: in August 2026 that resolves to 2026 week 1,
 * for which no run is published, so every screen in the product would open
 * empty. This provider instead defaults to *the newest week that actually has a
 * published board*, which is the only default that shows a working product on
 * first load.
 *
 * This is a presentation choice about which slate to request. It computes
 * nothing and infers nothing: `GET /seasons` returns the seasons that have a
 * published board, each with its published weeks, and both selectors and the
 * opening slate are read straight out of that one response. An explicit
 * `?season=&week=` in the URL always wins.
 */
export function SlateProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams()

  const seasonsQuery = useSeasons()
  const profilesQuery = useScoringProfiles()

  const stored = useMemo(readStored, [])

  const urlSeason = parseIntParam(searchParams.get(SEASON_PARAM))
  const urlWeek = parseIntParam(searchParams.get(WEEK_PARAM))
  const urlProfile = searchParams.get(PROFILE_PARAM)

  const seasons = useMemo(() => seasonsQuery.data ?? [], [seasonsQuery.data])
  const availableSeasons = useMemo(() => seasons.map((entry) => entry.season), [seasons])
  const availableProfiles = useMemo(() => profilesQuery.data?.profiles ?? [], [profilesQuery.data])

  // A remembered season that is no longer published is dropped rather than
  // restored. It happens on a redeploy against a different warehouse, and
  // restoring it would open the product on an empty screen the user did not ask
  // for — the one failure the stored selection exists to avoid.
  const storedSeason =
    stored.season !== undefined && availableSeasons.includes(stored.season)
      ? stored.season
      : null

  // The URL, then the last season used, then the newest with a published board.
  const season = urlSeason ?? storedSeason ?? seasons[0]?.season ?? null
  const selected = useMemo(
    () => seasons.find((entry) => entry.season === season) ?? null,
    [seasons, season],
  )
  const availableWeeks = useMemo(() => selected?.published_weeks ?? [], [selected])

  const catalogReady = seasonsQuery.isSuccess && profilesQuery.isSuccess

  const week = useMemo(() => {
    if (urlWeek !== null) return urlWeek
    if (!seasonsQuery.isSuccess) return stored.week ?? null
    // Newest published week for this season. Falls back to the stored choice so
    // a season with nothing published does not silently reset the selector.
    return selected?.latest_published_week ?? stored.week ?? null
  }, [urlWeek, seasonsQuery.isSuccess, selected, stored.week])

  const scoringProfile =
    urlProfile ?? stored.scoringProfile ?? profilesQuery.data?.defaultProfile ?? null

  // Persist so the next visit opens where the last one left off. Only ever
  // writes a fully resolved selection: storing a half-resolved one would make
  // the next cold start default to something the user never picked.
  useEffect(() => {
    if (!catalogReady || season === null || week === null || !scoringProfile) return
    writeStored({ season, week, scoringProfile })
  }, [catalogReady, season, week, scoringProfile])

  const update = useCallback(
    (next: Partial<Record<'season' | 'week' | 'scoring', string>>) => {
      setSearchParams(
        (current) => {
          const params = new URLSearchParams(current)
          for (const [key, value] of Object.entries(next)) {
            if (value === undefined) continue
            params.set(key, value)
          }
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const setSeason = useCallback(
    (value: number) => {
      // Changing season invalidates the week: week 18 of one season is not week
      // 18 of another, and carrying it over lands on an unpublished week. It is
      // cleared so the resolver picks that season's newest published week.
      setSearchParams(
        (current) => {
          const params = new URLSearchParams(current)
          params.set(SEASON_PARAM, String(value))
          params.delete(WEEK_PARAM)
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const setWeek = useCallback((value: number) => update({ week: String(value) }), [update])
  const setScoringProfile = useCallback(
    (value: string) => update({ scoring: value }),
    [update],
  )

  const value = useMemo<SlateSelection>(
    () => ({
      season,
      week,
      scoringProfile,
      resolved: catalogReady && season !== null && week !== null,
      catalogFailed: seasonsQuery.isError || profilesQuery.isError,
      hasPublishedBoard: week !== null && availableWeeks.includes(week),
      availableWeeks,
      availableSeasons,
      availableProfiles,
      setSeason,
      setWeek,
      setScoringProfile,
    }),
    [
      season,
      week,
      scoringProfile,
      catalogReady,
      seasonsQuery.isError,
      profilesQuery.isError,
      availableWeeks,
      availableSeasons,
      availableProfiles,
      setSeason,
      setWeek,
      setScoringProfile,
    ],
  )

  return <SlateContext.Provider value={value}>{children}</SlateContext.Provider>
}
