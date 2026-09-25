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
    label: 'Standard',
    description:
      "Each player's score is simulated on its own. This is the default. In real games teammates' scores are linked (most of all a quarterback and their own receivers), but when tested on 2,878 past lineups the 80% range still held the real score 79.4% of the time, against a target of 80%.",
  },
  {
    value: 'game_environment',
    label: 'Linked (experimental)',
    description:
      'Simulates teammates and opponents as linked, based on how past games played out. Each player’s own range stays the same. Experimental: in tests on past matchups it has not beaten the standard mode.',
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
