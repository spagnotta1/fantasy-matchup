/**
 * Matchup simulation. The only endpoint that takes a body, and the only one
 * that is slow enough to need its own timeout.
 *
 * Nothing is persisted server-side: the result is computed and returned inline.
 * That is why "simulation history" is a client-side concern, and why a result
 * is reproducible from `{lineups, seed, iterations, model run}` alone.
 */

import { request, LONG_TIMEOUT_MS } from './client'
import { matchupSimulationSchema, type SimulationRequest } from './schemas'

/** The default the API applies when a request names no seed. Echoed back on every run. */
export const DEFAULT_SIMULATION_COUNT = 10_000

export function runSimulation(body: SimulationRequest, signal?: AbortSignal) {
  return request('/simulations', matchupSimulationSchema, {
    method: 'POST',
    body,
    signal,
    timeoutMs: LONG_TIMEOUT_MS,
  })
}
