import { createContext, useContext } from 'react'

/**
 * The season / week / scoring format the whole application is looking at.
 *
 * One selection, shared by every view, held in the URL so a link to "Week 18,
 * PPR" is a link someone can send. `resolved` is false until the catalog has
 * told us which weeks actually have a published board — views should show a
 * skeleton rather than firing a request against a week we are about to change.
 */
export interface SlateSelection {
  season: number | null
  week: number | null
  scoringProfile: string | null
  /** True once season/week have been resolved against published runs. */
  resolved: boolean
  /**
   * The capability endpoints behind the selectors could not be reached.
   *
   * Distinct from "still loading": a selector that says "Loading…" forever is
   * a lie, and the controls need to be able to tell the two apart.
   */
  catalogFailed: boolean
  /** Whether the current selection is known to have a published board. */
  hasPublishedBoard: boolean
  /** Published weeks for the selected season, newest last. */
  availableWeeks: number[]
  availableSeasons: number[]
  availableProfiles: string[]
  setSeason: (season: number) => void
  setWeek: (week: number) => void
  setScoringProfile: (profile: string) => void
}

export const SlateContext = createContext<SlateSelection | null>(null)

export function useSlate(): SlateSelection {
  const value = useContext(SlateContext)
  if (!value) throw new Error('useSlate must be used inside <SlateProvider>')
  return value
}
