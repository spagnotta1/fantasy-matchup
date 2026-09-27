import { SlidersHorizontal } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { StatCard } from '@/components/ui/StatCard'
import { InfoTip } from '@/components/ui/Tooltip'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { AssumptionsPanel } from '@/features/simulations/AssumptionsPanel'
import { PositionalEdges } from '@/features/simulations/PositionalEdges'
import { ScoreDistribution } from '@/features/simulations/ScoreDistribution'
import { SwingFactors } from '@/features/simulations/SwingFactors'
import { groupNotices } from '@/features/simulations/notices'
import { ShareMatchup } from '@/features/simulations/ShareMatchup'
import { formatPercent, formatPoints, formatScoringProfile } from '@/utils/format'
import type { MatchupSimulation, ResponseMeta, SimulationAssumptions } from '@/api/schemas'
import type { NoticeGroup } from '@/features/simulations/notices'

/** Below this the two totals disagree enough to be worth explaining. */
const RECONCILIATION_TOLERANCE = 0.02

/**
 * The result.
 *
 * Ordered by what a manager asks, in order: how likely am I to win, what do the
 * two scores look like, how much do the ranges overlap, where does the gap come
 * from, who could move it, and what did this not account for. The assumptions
 * are last but not optional — they are on the same screen as the probability,
 * not behind a link.
 *
 * Nothing here recomputes the outcome. The win probability, both score
 * distributions and every per-player figure come from the response; the only
 * arithmetic in this subtree is subtracting one published number from another
 * to describe a gap, and each place it happens says so.
 */
export function SimulationResults({
  result,
  meta,
  labelA,
  labelB,
  /** Sends the reader back to the run controls. See `AdjustAndRerun`. */
  onAdjust,
}: {
  result: MatchupSimulation
  meta: ResponseMeta
  labelA: string
  labelB: string
  onAdjust?: () => void
}) {
  const { team_a: teamA, team_b: teamB } = result
  const notices = groupNotices(meta.notices, { a: labelA, b: labelB })
  const runNotes = notices.find((group) => group.key === 'run')?.notices ?? []
  const leaderLabel = teamA.win_probability >= teamB.win_probability ? labelA : labelB
  const leaderProbability = Math.max(teamA.win_probability, teamB.win_probability)

  return (
    <div className="animate-rise space-y-6">
      <WinProbability
        labelA={labelA}
        labelB={labelB}
        probabilityA={teamA.win_probability}
        probabilityB={teamB.win_probability}
        tieProbability={teamA.tie_probability}
        iterations={result.simulation.iterations}
        leaderLabel={leaderLabel}
        leaderProbability={leaderProbability}
        assumptions={result.assumptions}
      />

      {/*
        Every notice the engine returns is still shown, each once. The ones
        that name a lineup's own players — a designation, a stack — sit here,
        right under the result they qualify. The run-wide ones (independence,
        no kickers, no injury adjustment) used to be repeated here as a third
        alert box and again in the assumptions panel; they now live only in
        the panel, and the headline carries a one-sentence summary of them.
      */}
      <LineupNotes groups={notices.filter((group) => group.key !== 'run')} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={`${labelA} — simulated`}
          emphasis="primary"
          value={formatPoints(teamA.expected_score)}
          unit="pts"
          detail={`Median ${formatPoints(teamA.median_score)} · ${formatScoringProfile(result.scoring_profile)}`}
        />
        <StatCard
          label={`${labelB} — simulated`}
          value={formatPoints(teamB.expected_score)}
          unit="pts"
          detail={`Median ${formatPoints(teamB.median_score)}`}
        />
        <StatCard
          label="Expected margin"
          value={formatPoints(Math.abs(result.score_differential))}
          unit="pts"
          detail={`${teamA.expected_score >= teamB.expected_score ? labelA : labelB} ahead on average. Typical margin ${formatPoints(Math.abs(result.median_differential))}.`}
        />
        <StatCard
          label="Projections added up"
          value={formatPoints(teamA.projection_sum)}
          unit="pts"
          badge={<ProvenanceBadge provenance="model" showLabel={false} />}
          detail={`${labelB} ${formatPoints(teamB.projection_sum)}. Each lineup's player projections, added together.`}
        />
      </div>

      <Reconciliation
        labelA={labelA}
        simulated={teamA.expected_score}
        projected={teamA.projection_sum}
      />

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader
            as="h2"
            title="Where the scores land"
            description="Both lineups on one chart. The overlap is why the result above is a chance, not a certainty."
            action={<ProvenanceBadge provenance="derived" />}
          />
          <CardBody>
            <ScoreDistribution labelA={labelA} teamA={teamA} labelB={labelB} teamB={teamB} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            as="h2"
            title="Where the gap is"
            description="Average simulated points at each position, one lineup against the other."
            action={<ProvenanceBadge provenance="derived" />}
          />
          <CardBody>
            <PositionalEdges
              labelA={labelA}
              labelB={labelB}
              playersA={teamA.players}
              playersB={teamB.players}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            as="h2"
            title="Most unpredictable players"
            description="The players on either side whose score could swing the most."
            action={<ProvenanceBadge provenance="model" />}
          />
          <CardBody>
            <SwingFactors
              labelA={labelA}
              labelB={labelB}
              playersA={teamA.players}
              playersB={teamB.players}
            />
          </CardBody>
        </Card>

        <AssumptionsPanel
          id="simulation-assumptions"
          assumptions={result.assumptions}
          simulation={result.simulation}
          notes={runNotes}
        />

        {onAdjust && <AdjustAndRerun onAdjust={onAdjust} />}
      </div>
    </div>
  )
}

/**
 * The way back to the controls.
 *
 * Measured on a Pixel 7: a finished run makes this page 8.8 screens tall, and
 * the run controls sit seven screens above the end of the results. Reading a
 * result and wanting a different one — a different correlation mode, more
 * draws, a swapped flex — meant scrolling all the way back with nothing on
 * screen to suggest that was even the next step.
 *
 * Deliberately not a "run again" button. A run is fully determined by its
 * lineups, seed, iteration count, correlation mode and model run, all of which
 * are unchanged at this point, so re-running from here would spend ten thousand
 * draws to redraw the identical screen. What the reader wants is not this
 * result again; it is a different question, and the controls are where a
 * question gets changed.
 */
function AdjustAndRerun({ onAdjust }: { onAdjust: () => void }) {
  return (
    <Card>
      <CardBody className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-ink text-sm font-medium">Ask a different question</p>
          <p className="text-ink-secondary mt-0.5 text-sm leading-relaxed">
            Change the lineups, the simulation mode or the number of simulations. Running this
            exact setup again would give the same result.
          </p>
        </div>
        <Button variant="secondary" onClick={onAdjust}>
          <SlidersHorizontal aria-hidden className="size-4" />
          Adjust and run again
        </Button>
      </CardBody>
    </Card>
  )
}

/**
 * The headline.
 *
 * "Estimated win probability", never "you win". The iteration count sits under
 * it because it is what the percentage *is* — the share of ten thousand
 * simulated weeks — which is a more honest reading than a bare percentage and
 * costs one line.
 */
function WinProbability({
  labelA,
  labelB,
  probabilityA,
  probabilityB,
  tieProbability,
  iterations,
  leaderLabel,
  leaderProbability,
  assumptions,
}: {
  labelA: string
  labelB: string
  probabilityA: number
  probabilityB: number
  tieProbability: number
  iterations: number
  leaderLabel: string
  leaderProbability: number
  assumptions: SimulationAssumptions
}) {
  const limits = headlineLimits(assumptions)
  return (
    <Card className="overflow-hidden">
      <CardBody className="p-5 sm:p-6">
        <div className="flex items-end justify-between gap-6">
          <div className="min-w-0">
            <p className="text-ink-muted text-xs font-medium tracking-wide uppercase">
              {labelA} — estimated win probability
            </p>
            <p className="text-accent-text tnum mt-1 text-5xl leading-none font-semibold tracking-tight">
              {formatPercent(probabilityA)}
            </p>
          </div>
          <div className="min-w-0 text-right">
            <p className="text-ink-muted text-xs font-medium tracking-wide uppercase">{labelB}</p>
            <p className="text-ink-secondary tnum mt-1 text-3xl leading-none font-semibold tracking-tight">
              {formatPercent(probabilityB)}
            </p>
          </div>
        </div>

        <div
          className="bg-surface-sunken mt-4 flex h-4 overflow-hidden rounded-full"
          role="img"
          aria-label={`${labelA} wins ${formatPercent(probabilityA)} of simulated weeks, ${labelB} wins ${formatPercent(probabilityB)}.`}
        >
          <div
            className="bg-chart-series transition-[width] duration-500 ease-out"
            style={{ width: `${probabilityA * 100}%` }}
          />
          <div
            className="bg-chart-series/30 transition-[width] duration-500 ease-out"
            style={{ width: `${probabilityB * 100}%` }}
          />
        </div>

        <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
          <p className="text-ink-secondary min-w-0 flex-1 text-sm leading-relaxed">
            Across {iterations.toLocaleString()} simulated weeks, {leaderLabel} finished ahead in{' '}
            {formatPercent(leaderProbability)} of them.
            {tieProbability > 0 && (
              <> Both lineups tied in {formatPercent(tieProbability, 2)}.</>
            )}{' '}
            <span className="text-ink-muted">
              This is an estimate based on each player&apos;s projected range, not a prediction of
              the result.
            </span>
            {limits.length > 0 && (
              <span className="text-ink-muted mt-1.5 block">
                It {joinClauses(limits)}.{' '}
                <a href="#simulation-assumptions" className="text-accent-text font-medium hover:underline">
                  What it assumes
                </a>
              </span>
            )}
          </p>
          <ShareMatchup />
        </div>
      </CardBody>
    </Card>
  )
}

/**
 * Why the simulated total does not match the sum of the projections.
 *
 * The API keeps `projection_sum` beside `expected_score` and documents the two
 * agreeing as the check that the sampler drew from the stored distributions.
 * Under the currently published run they do *not* agree — the run stored no
 * calibrated mean, so `projection_sum` adds up the raw model output while the
 * sampler draws from the stored quantile curve, whose mean is higher.
 *
 * Two numbers differing by eighteen percent on the same screen with no
 * explanation is worse than either number alone. This says which is which. It
 * renders nothing when the two agree, which is the state it is built to
 * disappear in.
 */
function Reconciliation({
  labelA,
  simulated,
  projected,
}: {
  labelA: string
  simulated: number
  projected: number
}) {
  if (projected <= 0) return null
  const gap = Math.abs(simulated - projected) / projected
  if (gap <= RECONCILIATION_TOLERANCE) return null

  return (
    <aside
      className="bg-caution-soft rounded-[var(--radius-card)] px-4 py-3"
      aria-label="Totals do not reconcile"
    >
      <p className="text-caution-text text-xs leading-relaxed">
        <span className="font-semibold">Why the two totals above differ.</span> For {labelA}, the
        simulation averages {formatPoints(simulated)} points; the players&apos; projections add up
        to {formatPoints(projected)}. This week&apos;s projections were published without the
        model&apos;s final adjustment, and the simulation draws from each player&apos;s full range,
        which averages a little higher. The win chance and the margins come from the simulation,
        so read those rather than the added-up total.
        <InfoTip
          label="About the two totals"
          content="The simulated total is the average team score across every simulated week. The projection total adds up each player's projection. The two match when projections have had their final adjustment."
        />
      </p>
    </aside>
  )
}

/**
 * The limits that qualify the headline number, from the structured flags.
 *
 * Read from `assumptions`, never from notice prose, so the sentence changes by
 * itself the day a kicker model or an injury adjustment ships. Only the limits
 * that change what the percentage means are here; the rest are in the panel.
 */
function headlineLimits(assumptions: SimulationAssumptions): string[] {
  const limits: string[] = []
  if (!assumptions.kicker_projection_available || !assumptions.defense_projection_available) {
    limits.push('covers QB, RB, WR and TE only (no kickers or defences)')
  }
  if (assumptions.player_independence) {
    limits.push("simulates each player's score on its own")
  }
  if (!assumptions.injury_adjustment_applied) {
    limits.push('does not adjust for injury designations')
  }
  return limits
}

function joinClauses(clauses: string[]): string {
  if (clauses.length <= 1) return clauses.join('')
  return `${clauses.slice(0, -1).join(', ')} and ${clauses[clauses.length - 1]}`
}

/**
 * The notes the engine attached to one lineup: designations, stacks, players
 * sharing a game. One card with a section per side, rather than an alert box
 * each — they are things to know about your players, not warnings about the
 * run. The text is the engine's, untouched.
 */
function LineupNotes({ groups }: { groups: NoticeGroup[] }) {
  if (groups.length === 0) return null
  return (
    <Card>
      <CardHeader
        as="h2"
        title="About these lineups"
        description="What the engine flagged about the players on each side. None of it changes the numbers above."
      />
      <CardBody className="grid gap-5 sm:grid-cols-2">
        {groups.map((group) => (
          <section key={group.key} className="min-w-0">
            <h3 className="text-ink text-sm font-semibold">{group.title.replace(/ — what to know$/, '')}</h3>
            <ul className="text-ink-secondary mt-1.5 list-disc space-y-1.5 pl-5 text-sm leading-relaxed">
              {group.notices.map((notice) => (
                <li key={notice}>{notice}</li>
              ))}
            </ul>
          </section>
        ))}
      </CardBody>
    </Card>
  )
}
