/**
 * Simulation history, in the browser.
 *
 * The API stores nothing: `POST /simulations` computes a result and returns it
 * inline, with no roster, no run record and no principal. History is therefore
 * a client concern by design rather than by omission, and this module is honest
 * about what that means — clearing site data clears it, and it does not follow
 * the user to another device.
 *
 * What makes it worth keeping at all is that a run is *reproducible*: the same
 * lineups against the same published model run with the same seed produce
 * identical numbers, and the seed is echoed on every response. So an entry
 * stores the exact request rather than only the result, and re-running it is a
 * real re-run instead of a cached picture of one.
 */

import type { LineupEntry, MatchupSimulation, SimulationRequest } from '@/api/schemas'

const STORAGE_KEY = 'nflfp.simulations'

/** Enough to cover a week's tinkering; small enough to stay inside the quota. */
const MAX_ENTRIES = 25

/** A lineup slot with the name resolved, so history renders without refetching. */
export interface HistoryPlayer extends LineupEntry {
  name: string
  position: string | null
  team: string | null
}

export interface HistoryEntry {
  id: string
  /** ISO timestamp of the run, in the user's own clock. */
  ranAt: string
  season: number
  week: number
  scoringProfile: string
  correlationMode: string
  iterations: number
  seed: number
  /** The exact request, so the run can be repeated rather than approximated. */
  request: SimulationRequest
  teamA: HistoryPlayer[]
  teamB: HistoryPlayer[]
  /** Headline results, kept so the list renders without re-running anything. */
  winProbabilityA: number
  expectedScoreA: number
  expectedScoreB: number
  /** The published run the numbers came from. A later run makes them stale. */
  modelRunId: number | null
}

function read(): HistoryEntry[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    // Anything that is not the shape we wrote is discarded rather than
    // defended against downstream: this is our own storage, and a corrupt
    // entry is not worth a migration path.
    return Array.isArray(parsed) ? (parsed as HistoryEntry[]).filter(isEntry) : []
  } catch {
    return []
  }
}

function isEntry(value: unknown): value is HistoryEntry {
  if (typeof value !== 'object' || value === null) return false
  const entry = value as Partial<HistoryEntry>
  return (
    typeof entry.id === 'string' &&
    typeof entry.ranAt === 'string' &&
    Array.isArray(entry.teamA) &&
    Array.isArray(entry.teamB) &&
    typeof entry.winProbabilityA === 'number' &&
    typeof entry.request === 'object'
  )
}

function write(entries: HistoryEntry[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)))
  } catch {
    // A private-mode browser with no quota is not a reason to fail a simulation
    // that has already been computed and rendered.
  }
}

export function listHistory(): HistoryEntry[] {
  return read()
}

/**
 * Record a completed run.
 *
 * Identical re-runs replace rather than accumulate: the same lineups, seed and
 * model run produce the same answer, so twelve copies of it is a list nobody
 * can read. "Identical" is decided by the request and the model run, which is
 * exactly what determines the numbers.
 */
export function recordRun(
  result: MatchupSimulation,
  request: SimulationRequest,
  players: { teamA: HistoryPlayer[]; teamB: HistoryPlayer[] },
): HistoryEntry {
  const modelRunId = result.simulation.model?.run_id ?? null
  const entry: HistoryEntry = {
    id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    ranAt: new Date().toISOString(),
    season: result.season,
    week: result.week,
    scoringProfile: result.scoring_profile,
    correlationMode: result.simulation.correlation_mode,
    iterations: result.simulation.iterations,
    seed: result.simulation.seed,
    request,
    teamA: players.teamA,
    teamB: players.teamB,
    winProbabilityA: result.team_a.win_probability,
    expectedScoreA: result.team_a.expected_score,
    expectedScoreB: result.team_b.expected_score,
    modelRunId,
  }

  const fingerprint = signature(request, modelRunId)
  const kept = read().filter((existing) => signature(existing.request, existing.modelRunId) !== fingerprint)
  const next = [entry, ...kept]
  write(next)
  return entry
}

export function removeRun(id: string): HistoryEntry[] {
  const next = read().filter((entry) => entry.id !== id)
  write(next)
  return next
}

export function clearHistory(): HistoryEntry[] {
  write([])
  return []
}

/** Everything that determines the result, in a stable string. */
function signature(request: SimulationRequest, modelRunId: number | null): string {
  const lineup = (entries: LineupEntry[]) =>
    entries
      .map((entry) => `${entry.slot}:${entry.player_id}`)
      .sort()
      .join(',')

  return [
    request.season,
    request.week,
    request.scoring_profile,
    request.simulation_count,
    request.seed,
    request.correlation_mode,
    modelRunId,
    lineup(request.team_a),
    lineup(request.team_b),
  ].join('|')
}
