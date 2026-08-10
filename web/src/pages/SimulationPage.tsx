import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, Play, Settings2, ShieldAlert } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { Card, CardBody } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { Select } from '@/components/ui/Select'
import { Input } from '@/components/ui/Input'
import { EmptyState, ErrorState } from '@/components/feedback/States'
import { LineupBuilder, LineupSkeleton } from '@/features/simulations/LineupBuilder'
import { SimulationHistory } from '@/features/simulations/SimulationHistory'
import { SimulationResults } from '@/features/simulations/SimulationResults'
import { PreRunExplainer } from '@/features/simulations/PreRunExplainer'
import {
  indexBoard,
  lineupReadiness,
  projectedPositions,
  type LineupReadiness,
} from '@/features/simulations/availability'
import {
  decodeLineup,
  matchupParams,
  TEAM_A_PARAM,
  TEAM_B_PARAM,
  ITERATIONS_PARAM,
  MODE_PARAM,
  SEED_PARAM,
} from '@/features/simulations/shareLink'
import {
  autofillLineup,
  emptyLineup,
  expandSlots,
  type LineupRow,
} from '@/features/simulations/lineupFormat'
import {
  clearHistory,
  listHistory,
  recordRun,
  removeRun,
  type HistoryEntry,
  type HistoryPlayer,
} from '@/features/simulations/history'
import { CORRELATION_MODES, useLineupCatalog, useSimulationRun } from '@/hooks/useSimulation'
import { usePositions } from '@/hooks/useCatalog'
import { useBoard, usePlayers } from '@/hooks/useProjections'
import { useSlate } from '@/app/slate-context'
import { formatScoringProfile } from '@/utils/format'
import { scrollBehavior } from '@/utils/motion'
import type { LineupEntry, Player, SimulationRequest } from '@/api/schemas'

const LABEL_A = 'Your team'
const LABEL_B = 'Opponent'

/** Offered draw counts. The API's own bounds are 100 to 50,000. */
const ITERATION_OPTIONS = [
  { value: '2000', label: '2,000 — fast' },
  { value: '10000', label: '10,000 — default' },
  { value: '25000', label: '25,000' },
  { value: '50000', label: '50,000 — slowest' },
]

/**
 * Simulate a head-to-head fantasy week.
 *
 * Build two lineups, run a Monte Carlo over the published outcome
 * distributions, read the result. The screen computes nothing: the lineup shape
 * comes from the API's format, every draw is taken server-side from a stored
 * distribution, and the win probability is returned rather than derived.
 *
 * Four structural choices.
 *
 * The run is a *mutation*, so nothing fires while a lineup is being edited and
 * re-running is an action rather than a cache miss.
 *
 * The matchup lives in the URL. Fourteen searches is too much work to lose to a
 * refresh, and a matchup is the most sendable thing in the product — so the two
 * lineups are mirrored into the query string as they are built, and a link
 * rebuilds them. The URL is read once, at mount; after that this page owns the
 * state and writes to it, which is what keeps an edit from fighting a hydration.
 *
 * A lineup is checked before it is submitted. Not to second-guess the engine —
 * it stays the authority on every refusal — but because it refuses a starter
 * with no projection for the whole matchup, and finding that out from a
 * paragraph after filling fourteen slots is the difference between a tool and a
 * form. See `availability.ts`.
 *
 * And history is local, because the endpoint stores nothing by design — what
 * makes that useful rather than a consolation is that a run is reproducible
 * from its lineups, its seed and the model run it was made against, all three
 * of which are kept.
 */
export default function SimulationPage() {
  const slate = useSlate()
  const catalog = useLineupCatalog()
  const board = useBoard()
  const positions = usePositions()
  const run = useSimulationRun()
  const [searchParams, setSearchParams] = useSearchParams()

  // Both lineups in one state object, not two.
  //
  // Autofill for one side has to know who the other side already holds, and
  // with two separate states a handler reads whatever the last render gave it —
  // so autofilling both in quick succession hands the second one a view of the
  // first that is still empty, and produces two identical teams. One object
  // means a functional update always sees both sides as they actually are.
  const [lineups, setLineups] = useState<{ a: LineupRow[]; b: LineupRow[] }>({ a: [], b: [] })
  const { a: teamA, b: teamB } = lineups
  const setTeamA = (rows: LineupRow[]) => setLineups((current) => ({ ...current, a: rows }))
  const setTeamB = (rows: LineupRow[]) => setLineups((current) => ({ ...current, b: rows }))
  // The URL is the source of truth for exactly one render — the first. Reading
  // it on every render would mean an edit and a hydration taking turns
  // overwriting each other for as long as the two disagreed.
  const shared = useMemo(
    () => ({
      a: decodeLineup(searchParams.get(TEAM_A_PARAM)),
      b: decodeLineup(searchParams.get(TEAM_B_PARAM)),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount only, by design
    [],
  )

  const [correlationMode, setCorrelationMode] = useState<string>(
    () => searchParams.get(MODE_PARAM) ?? 'independent',
  )
  const [iterations, setIterations] = useState(
    () => searchParams.get(ITERATIONS_PARAM) ?? '10000',
  )
  const [seed, setSeed] = useState(() => searchParams.get(SEED_PARAM) ?? '')
  const [history, setHistory] = useState<HistoryEntry[]>(() => listHistory())
  const [pendingLoad, setPendingLoad] = useState<{ a: LineupEntry[]; b: LineupEntry[] } | null>(
    () => (shared.a.length > 0 || shared.b.length > 0 ? shared : null),
  )

  const resultsRef = useRef<HTMLDivElement>(null)
  const controlsRef = useRef<HTMLDivElement>(null)
  const slotSignature = expandSlots(catalog.format).join(',')

  /**
   * Back to the run controls from the bottom of a result.
   *
   * Focus moves as well as the scroll position, for the same reason the route
   * change does it: a keyboard or screen-reader user who activates this needs
   * their next Tab to land in the controls, not back at the top of the results
   * they just left.
   */
  const onAdjust = useCallback(() => {
    controlsRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'center' })
    controlsRef.current?.focus({ preventScroll: true })
  }, [])

  // Build the empty lineups once the format arrives. `catalog.format` is
  // memoised by the hook, so this settles after one pass rather than rebuilding
  // — and clearing a lineup the user has filled would be the bug to avoid here.
  useEffect(() => {
    if (catalog.isPending || slotSignature === '') return
    setLineups((current) =>
      current.a.length > 0
        ? current
        : { a: emptyLineup(catalog.format), b: emptyLineup(catalog.format) },
    )
  }, [slotSignature, catalog.isPending, catalog.format])

  const boardEntries = useMemo(() => board.data?.data ?? [], [board.data])
  const boardIndex = useMemo(
    () => indexBoard(boardEntries, board.data?.meta.page, board.isPending),
    [boardEntries, board.data?.meta.page, board.isPending],
  )
  const projected = useMemo(() => projectedPositions(positions.data), [positions.data])

  const readinessA = lineupReadiness(teamA, boardIndex, projected, slate.week)
  const readinessB = lineupReadiness(teamB, boardIndex, projected, slate.week)
  const ready = readinessA.runnable && readinessB.runnable && slate.resolved

  const request = useMemo<SimulationRequest | null>(() => {
    if (!ready) return null
    const parsedSeed = Number.parseInt(seed, 10)
    return {
      season: slate.season,
      week: slate.week,
      scoring_profile: slate.scoringProfile,
      simulation_count: Number.parseInt(iterations, 10),
      seed: Number.isFinite(parsedSeed) && parsedSeed >= 0 ? parsedSeed : null,
      correlation_mode: correlationMode,
      // `ready` guarantees every slot is filled, so this is the whole lineup in
      // submission order — which is what the seed contract is a statement about.
      team_a: rowsToEntries(teamA),
      team_b: rowsToEntries(teamB),
    }
  }, [ready, teamA, teamB, slate.season, slate.week, slate.scoringProfile, iterations, seed, correlationMode])

  // Mirror the matchup into the address bar as it is built, replacing rather
  // than pushing: a lineup is edited a slot at a time, and pushing would bury
  // the page the user arrived from under fourteen history entries.
  //
  // Written through a ref rather than driven by the effect's dependencies
  // alone. `setSearchParams` is not contractually stable across renders, and an
  // effect that both depends on it and calls it would loop forever if it ever
  // stopped being. Comparing against what was last written makes the effect
  // idempotent, so the identity of the setter stops mattering.
  const written = useRef<string | null>(null)
  const desiredParams = useMemo(
    () =>
      matchupParams({
        teamA: rowsToEntries(teamA),
        teamB: rowsToEntries(teamB),
        iterations,
        correlationMode,
        seed,
      }),
    [teamA, teamB, iterations, correlationMode, seed],
  )

  useEffect(() => {
    // Hydration in flight: the builder does not yet hold what the URL says, and
    // writing now would overwrite the link with the empty lineup it is loading.
    if (pendingLoad) return
    if (!desiredParams[TEAM_A_PARAM] && !desiredParams[TEAM_B_PARAM]) return

    const next = new URLSearchParams(desiredParams).toString()
    if (written.current === next) return
    written.current = next

    setSearchParams(
      (current) => {
        const params = new URLSearchParams(current)
        for (const [key, value] of Object.entries(desiredParams)) params.set(key, value)
        if (!desiredParams[SEED_PARAM]) params.delete(SEED_PARAM)
        return params
      },
      { replace: true },
    )
  }, [desiredParams, pendingLoad, setSearchParams])

  const onRun = () => {
    if (!request) return
    run.mutate(request, {
      onSuccess: (response) => {
        recordRun(response.data, request, {
          teamA: toHistoryPlayers(teamA),
          teamB: toHistoryPlayers(teamB),
        })
        setHistory(listHistory())
        // Move focus to the result rather than leaving the user at the button
        // wondering whether anything happened below the fold.
        window.requestAnimationFrame(() => {
          resultsRef.current?.focus({ preventScroll: true })
          // Explicitly asked rather than hard-coded to 'smooth': an explicit
          // behaviour overrides the stylesheet's reduced-motion rule, so this
          // is the one scroll in the product that has to check the setting.
          resultsRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' })
        })
      },
    })
  }

  const onLineupsResolved = useCallback((rowsA: LineupRow[], rowsB: LineupRow[]) => {
    setLineups((current) => ({
      // A link may name fewer starters than the format requires, or none for one
      // side. The rest of the format is kept so the builder still shows the
      // shape the engine expects rather than a short lineup.
      a: rowsA.length > 0 ? rowsA : current.a,
      b: rowsB.length > 0 ? rowsB : current.b,
    }))
    setPendingLoad(null)
  }, [])

  /** Fill one side, treating the other side's players as unavailable. */
  const onAutofill = (side: 'a' | 'b') => {
    setLineups((current) => ({
      ...current,
      [side]: autofillLineup(
        current[side],
        boardEntries,
        catalog.slots,
        idsOf(side === 'a' ? current.b : current.a),
      ),
    }))
  }

  const onLoadHistory = (entry: HistoryEntry) => {
    setCorrelationMode(entry.correlationMode)
    setIterations(String(entry.iterations))
    setSeed(String(entry.seed))
    setPendingLoad({ a: entry.teamA, b: entry.teamB })
    run.reset()
  }

  return (
    <>
      <PageHeader
        title="Matchup simulation"
        question="How likely is this lineup to beat that one, and what would decide it?"
      />

      {!slate.hasPublishedBoard && slate.resolved && (
        <aside
          className="bg-caution-soft mb-6 flex gap-2.5 rounded-[var(--radius-card)] px-4 py-3"
          aria-label="No published board"
        >
          <ShieldAlert aria-hidden className="text-caution-text mt-0.5 size-4 shrink-0" />
          <p className="text-caution-text text-xs leading-relaxed">
            No model run is published for week {slate.week ?? '—'}, so players will have no
            projections to simulate. Pick a week with a published board from the header.
          </p>
        </aside>
      )}

      {catalog.isError ? (
        <Card>
          <EmptyState
            title="Lineup format unavailable"
            description="The lineup slots this engine accepts could not be loaded, so the builder cannot be shown. This is usually temporary."
          />
        </Card>
      ) : catalog.isPending || teamA.length === 0 ? (
        <div className="grid gap-6 xl:grid-cols-2">
          <LineupSkeleton />
          <LineupSkeleton />
        </div>
      ) : (
        <>
          {pendingLoad && (
            <LineupResolver entries={pendingLoad} onResolved={onLineupsResolved} />
          )}

          <div className="grid gap-6 xl:grid-cols-2">
            <LineupBuilder
              title={LABEL_A}
              description={`Your starting lineup — ${catalog.format.label}.`}
              rows={teamA}
              slots={catalog.slots}
              board={boardIndex}
              projectedPositions={projected}
              week={slate.week}
              otherLineupIds={idsOf(teamB)}
              onChange={setTeamA}
              onAutofill={() => onAutofill('a')}
              disabled={run.isPending}
            />
            <LineupBuilder
              title={LABEL_B}
              description="The lineup you are playing against this week."
              rows={teamB}
              slots={catalog.slots}
              board={boardIndex}
              projectedPositions={projected}
              week={slate.week}
              otherLineupIds={idsOf(teamA)}
              onChange={setTeamB}
              onAutofill={() => onAutofill('b')}
              disabled={run.isPending}
            />
          </div>

          {!catalog.formatKnown && (
            <p className="text-ink-muted mt-3 text-xs leading-relaxed">
              The lineup composition could not be read from the API, so one row per simulable slot
              is shown. The engine validates the lineup either way and will say what it expects.
            </p>
          )}

          <div ref={controlsRef} tabIndex={-1} className="scroll-mt-24 outline-none">
          <RunControls
            correlationMode={correlationMode}
            onCorrelationModeChange={setCorrelationMode}
            iterations={iterations}
            onIterationsChange={setIterations}
            seed={seed}
            onSeedChange={setSeed}
            ready={ready}
            running={run.isPending}
            onRun={onRun}
            scoringProfile={slate.scoringProfile}
            week={slate.week}
            readiness={[
              { label: LABEL_A, ...readinessA },
              { label: LABEL_B, ...readinessB },
            ]}
          />
          </div>
        </>
      )}

      <div ref={resultsRef} tabIndex={-1} className="mt-6 scroll-mt-24 outline-none">
        {run.isPending ? (
          <RunningState iterations={Number.parseInt(iterations, 10)} />
        ) : run.isError ? (
          <Card>
            <ErrorState error={run.error} onRetry={onRun} />
          </Card>
        ) : run.isSuccess ? (
          <SimulationResults
            result={run.data.data}
            meta={run.data.meta}
            labelA={LABEL_A}
            labelB={LABEL_B}
            onAdjust={onAdjust}
          />
        ) : (
          <PreRunExplainer />
        )}
      </div>

      <div className="mt-6">
        <SimulationHistory
          entries={history}
          currentModelRunId={board.data?.meta.model?.run_id ?? null}
          onLoad={onLoadHistory}
          onRemove={(id) => setHistory(removeRun(id))}
          onClear={() => setHistory(clearHistory())}
        />
      </div>
    </>
  )
}

/**
 * Run settings, and the run itself.
 *
 * Correlation mode is here rather than behind an "advanced" disclosure because
 * it changes what the result means: the default draws players independently and
 * the response says so in its assumptions, and a user should be able to see the
 * alternative without hunting for it.
 */
function RunControls({
  correlationMode,
  onCorrelationModeChange,
  iterations,
  onIterationsChange,
  seed,
  onSeedChange,
  ready,
  running,
  onRun,
  scoringProfile,
  week,
  readiness,
}: {
  correlationMode: string
  onCorrelationModeChange: (value: string) => void
  iterations: string
  onIterationsChange: (value: string) => void
  seed: string
  onSeedChange: (value: string) => void
  ready: boolean
  running: boolean
  onRun: () => void
  scoringProfile: string | null
  week: number | null
  readiness: (LineupReadiness & { label: string })[]
}) {
  const [showAdvanced, setShowAdvanced] = useState(false)
  const mode = CORRELATION_MODES.find((entry) => entry.value === correlationMode)
  const blocked = readiness.filter((side) => side.problems.length > 0)
  const emptySlots = readiness.reduce((total, side) => total + side.empty, 0)

  return (
    <Card className="mt-6">
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <p className="text-ink-secondary mb-1.5 text-xs font-medium">Player outcomes</p>
            <SegmentedControl
              label="Correlation mode"
              value={correlationMode}
              onChange={onCorrelationModeChange}
              options={CORRELATION_MODES.map((entry) => ({
                value: entry.value,
                label: entry.label,
              }))}
            />
          </div>

          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={() => setShowAdvanced((current) => !current)}>
              <Settings2 aria-hidden className="size-3.5" />
              {showAdvanced ? 'Hide settings' : 'Settings'}
            </Button>
            <Button
              size="lg"
              variant="primary"
              onClick={onRun}
              disabled={!ready}
              loading={running}
            >
              {!running && <Play aria-hidden className="size-4" />}
              {running ? 'Simulating…' : 'Run simulation'}
            </Button>
          </div>
        </div>

        {mode && <p className="text-ink-muted text-xs leading-relaxed">{mode.description}</p>}

        {showAdvanced && (
          <div className="border-line grid gap-3 border-t pt-4 sm:grid-cols-2">
            <Select
              label="Iterations"
              value={iterations}
              onChange={(event) => onIterationsChange(event.target.value)}
              options={ITERATION_OPTIONS}
              hint="More draws tighten the estimate, not the underlying uncertainty."
            />
            <Input
              label="Seed"
              value={seed}
              onChange={(event) => onSeedChange(event.target.value.replace(/[^0-9]/g, ''))}
              placeholder="Leave blank for the API default"
              inputMode="numeric"
              hint="The same lineups and seed reproduce the same numbers exactly."
            />
          </div>
        )}

        {/*
          The engine refuses the whole matchup if one starter has no projection,
          and its message is a paragraph naming the player. Naming the slot here
          instead turns "read this and work out which of fourteen rows to change"
          into "look at the row that is already highlighted". The API is still
          the authority: this only pre-empts a refusal it would issue anyway.
        */}
        {blocked.length > 0 ? (
          <div
            className="bg-caution-soft flex gap-2.5 rounded-[var(--radius-control)] px-3 py-2.5"
            aria-label="Lineup cannot be simulated"
          >
            <AlertTriangle aria-hidden className="text-caution-text mt-0.5 size-4 shrink-0" />
            <div className="text-caution-text min-w-0 text-xs leading-relaxed">
              <p className="font-semibold">
                {blocked.reduce((total, side) => total + side.problems.length, 0)} starter(s) cannot
                be simulated, so the engine would refuse this matchup.
              </p>
              <ul className="mt-1 space-y-0.5">
                {blocked.flatMap((side) =>
                  side.problems.map((problem) => (
                    <li key={`${side.label}-${problem.slot}-${problem.name}`}>
                      <span className="font-medium">
                        {side.label} {problem.slot} — {problem.name}:
                      </span>{' '}
                      {problem.detail}
                    </li>
                  )),
                )}
              </ul>
            </div>
          </div>
        ) : (
          <p className="text-ink-muted text-xs">
            {ready
              ? `Ready — week ${week ?? '—'}, ${formatScoringProfile(scoringProfile)}.`
              : `Fill every slot on both lineups to run a simulation. ${emptySlots} still empty.`}
          </p>
        )}
      </CardBody>
    </Card>
  )
}

/**
 * The waiting state.
 *
 * An indeterminate bar rather than a percentage. The endpoint reports no
 * progress — it holds a worker for the whole run and answers once — so a
 * counting progress bar would be an animation pretending to be telemetry.
 */
function RunningState({ iterations }: { iterations: number }) {
  return (
    <Card>
      <CardBody className="py-10 text-center" aria-live="polite">
        <p className="text-ink text-sm font-medium">
          Simulating {Number.isFinite(iterations) ? iterations.toLocaleString() : ''} weeks…
        </p>
        <p className="text-ink-muted mx-auto mt-1 max-w-md text-xs leading-relaxed">
          Drawing each player from their published outcome distribution and summing both lineups,
          one week at a time.
        </p>
        <div className="bg-surface-sunken relative mx-auto mt-4 h-1.5 w-56 overflow-hidden rounded-full">
          <span className="bg-chart-series animate-indeterminate absolute inset-y-0 w-1/3 rounded-full" />
        </div>
      </CardBody>
    </Card>
  )
}

/**
 * Resolve a set of `{slot, player_id}` pairs back into the builder.
 *
 * Two things arrive as ids and have to become players: a run loaded from
 * history, and a matchup opened from a link. Both are the same problem, so they
 * share this. The ids are fetched rather than trusted from the source — history
 * stores names for display and a URL could name anyone — which means a link
 * opens on the current dimension instead of on whatever was true when it was
 * written.
 *
 * Rendering nothing, this exists purely to own the hook call: `usePlayers` takes
 * a variable-length list, which cannot be called conditionally from the page.
 */
function LineupResolver({
  entries,
  onResolved,
}: {
  entries: { a: LineupEntry[]; b: LineupEntry[] }
  onResolved: (teamA: LineupRow[], teamB: LineupRow[]) => void
}) {
  const ids = [...entries.a, ...entries.b].map((entry) => entry.player_id)
  const queries = usePlayers(ids)
  const settled = queries.every((query) => query.isSuccess || query.isError)

  // `queries` is a fresh array every render, so it is read through a ref rather
  // than listed as a dependency — listing it would re-run the effect forever.
  const latest = useRef(queries)
  latest.current = queries

  useEffect(() => {
    if (!settled) return
    const byId = new Map<string, Player>()
    for (const query of latest.current) {
      if (query.data) byId.set(query.data.player_id, query.data)
    }

    const rows = (side: LineupEntry[], prefix: string): LineupRow[] =>
      side.map((entry, index) => ({
        key: `${prefix}-${entry.slot}-${index}`,
        slot: entry.slot,
        // A player the dimension no longer knows leaves the slot empty rather
        // than silently dropping it — the shape of the lineup is preserved.
        player: byId.get(entry.player_id) ?? null,
      }))

    onResolved(rows(entries.a, 'a'), rows(entries.b, 'b'))
  }, [settled, entries, onResolved])

  return null
}

function idsOf(rows: LineupRow[]): string[] {
  return rows.map((row) => row.player?.player_id).filter((id): id is string => Boolean(id))
}

/** Filled rows as the API's lineup entries, in the order they were submitted. */
function rowsToEntries(rows: LineupRow[]): LineupEntry[] {
  return rows
    .filter((row) => row.player !== null)
    .map((row) => ({ player_id: (row.player as Player).player_id, slot: row.slot }))
}

function toHistoryPlayers(rows: LineupRow[]): HistoryPlayer[] {
  return rows.map((row) => ({
    player_id: (row.player as Player).player_id,
    slot: row.slot,
    name: (row.player as Player).name,
    position: (row.player as Player).position ?? null,
    team: (row.player as Player).team ?? null,
  }))
}
