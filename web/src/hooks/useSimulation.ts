/**
 * The simulation call and the lineup vocabulary behind it.
 *
 * A mutation rather than a query, and not because it is a POST: a simulation is
 * something the user *runs*, at a moment they choose, and re-running it is the
 * point rather than a cache miss. Modelling it as a query would either fire on
 * every lineup edit or need `enabled` gymnastics to stop it.
 */

import { useMemo } from 'react'
import { useMutation } from '@tanstack/react-query'

import * as simulationsApi from '@/api/simulations'
import { useLineupSlots } from '@/hooks/useCatalog'
import {
  parseLineupFormats,
  resolveFormat,
  type LineupFormat,
} from '@/features/simulations/lineupFormat'
import type { LineupSlot, SimulationRequest } from '@/api/schemas'

export { DEFAULT_SIMULATION_COUNT } from '@/api/simulations'

/** Correlation modes the API accepts, with what choosing one actually means. */
export const CORRELATION_MODES = [
  {
    value: 'independent',
    label: 'Independent',
    description:
      "Every player drawn from their own distribution. The API's default. Teammates share an offence and opponents share game script, so the intervals come out too narrow and the win probability sits further from 50% than the evidence supports.",
  },
  {
    value: 'game_environment',
    label: 'Correlated (experimental)',
    description:
      'Applies a correlation structure fitted on held-out historical outcomes, leaving every player’s own distribution unchanged. Experimental: it has not been shown to beat the independent baseline on held-out matchups.',
  },
] as const

export interface LineupCatalog {
  slots: LineupSlot[]
  format: LineupFormat
  /** True when the composition was read from the API rather than fallen back to. */
  formatKnown: boolean
  isPending: boolean
  isError: boolean
}

/** The slot vocabulary and the composition a lineup must satisfy. */
export function useLineupCatalog(): LineupCatalog {
  const query = useLineupSlots()

  return useMemo(() => {
    const slots = query.data?.slots ?? []
    const formats = parseLineupFormats(query.data?.formats ?? [])
    return {
      slots,
      format: resolveFormat(formats, slots),
      formatKnown: formats.length > 0,
      isPending: query.isPending,
      isError: query.isError,
    }
  }, [query.data, query.isPending, query.isError])
}

/**
 * Run a simulation.
 *
 * No retry. The failures this endpoint produces are refusals — a kicker slot, a
 * lineup of the wrong shape, a player with no projection — and repeating an
 * invalid request three times only delays telling the user what is wrong. A
 * genuine timeout is offered a retry button instead, which is a decision the
 * user makes rather than one made for them.
 */
export function useSimulationRun() {
  return useMutation({
    mutationFn: (request: SimulationRequest) => simulationsApi.runSimulation(request),
    retry: false,
  })
}
