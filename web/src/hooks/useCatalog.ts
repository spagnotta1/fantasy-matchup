/**
 * Capability data as hooks.
 *
 * These back the shell's selectors and every position filter in the product.
 * They are cached aggressively — the set of NFL positions does not change
 * during a session — so the shell can read them on every render without
 * thinking about cost.
 */

import { useQuery } from '@tanstack/react-query'

import * as meta from '@/api/meta'
import { queryKeys } from '@/api/queryKeys'

/** Capability data is effectively static for a session. */
const STATIC = { staleTime: 60 * 60 * 1000, gcTime: 24 * 60 * 60 * 1000 } as const

/**
 * The seasons this deployment has published a board for, newest first.
 *
 * Every entry carries its published weeks, which is why the shell can build the
 * season picker, the week picker and its opening slate from this one request.
 * The API filters to published seasons itself — the frontend never has to guess
 * which of the warehouse's twenty-eight seasons are real, and cannot get the
 * answer wrong.
 */
export function useSeasons() {
  return useQuery({
    queryKey: queryKeys.catalog.seasons(),
    queryFn: ({ signal }) => meta.getSeasons(signal),
    // Shorter than the rest of the catalog: this is the one capability that
    // changes during a session, when Thursday's job publishes a new week.
    staleTime: 5 * 60 * 1000,
    gcTime: STATIC.gcTime,
  })
}

export function useScoringProfiles() {
  return useQuery({
    queryKey: queryKeys.catalog.scoringProfiles(),
    queryFn: ({ signal }) => meta.getScoringProfiles(signal),
    ...STATIC,
  })
}

export function usePositions() {
  return useQuery({
    queryKey: queryKeys.catalog.positions(),
    queryFn: ({ signal }) => meta.getPositions(signal),
    ...STATIC,
  })
}

export function useLineupSlots() {
  return useQuery({
    queryKey: queryKeys.catalog.lineupSlots(),
    queryFn: ({ signal }) => meta.getLineupSlots(signal),
    ...STATIC,
  })
}

export function useTeams() {
  return useQuery({
    queryKey: queryKeys.catalog.teams(),
    queryFn: ({ signal }) => meta.getTeams(signal),
    ...STATIC,
  })
}

export function useProvenanceLegend() {
  return useQuery({
    queryKey: queryKeys.catalog.provenance(),
    queryFn: ({ signal }) => meta.getProvenanceLegend(signal),
    ...STATIC,
  })
}

export function useModelFoundation() {
  return useQuery({
    queryKey: queryKeys.catalog.model(),
    queryFn: ({ signal }) => meta.getModelFoundation(signal),
    ...STATIC,
  })
}

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.catalog.health(),
    queryFn: ({ signal }) => meta.getHealth(signal),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
    retry: false,
  })
}
