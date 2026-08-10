import { SlidersHorizontal } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { StatCard } from '@/components/ui/StatCard'
import { InfoTip } from '@/components/ui/Tooltip'
import { NoticeList } from '@/components/feedback/States'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { AssumptionsPanel } from '@/features/simulations/AssumptionsPanel'
import { PositionalEdges } from '@/features/simulations/PositionalEdges'
import { ScoreDistribution } from '@/features/simulations/ScoreDistribution'
import { SwingFactors } from '@/features/simulations/SwingFactors'
import { groupNotices } from '@/features/simulations/notices'
import { ShareMatchup } from '@/features/simulations/ShareMatchup'
import { formatPercent, formatPoints, formatScoringProfile } from '@/utils/format'
import type { MatchupSimulation, ResponseMeta } from '@/api/schemas'

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
      />

      {/*
        Grouped rather than listed. The engine labels the caveats that belong to
        one lineup — an injury designation, a stack sharing an offence — and a
        real matchup produces a dozen notices in total. Flat, the two that name
        your own starters are indistinguishable from the boilerplate.
      */}
      <div className="space-y-3">
        {groupNotices(meta.notices, { a: labelA, b: labelB }).map((group) => (
          <NoticeList key={group.key} notices={group.notices} title={group.title} showTitle />
        ))}
      </div>

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
          detail={`${teamA.expected_score >= teamB.expected_score ? labelA : labelB} ahead on average. Median margin ${formatPoints(Math.abs(result.median_differential))}.`}
        />
        <StatCard
          label="Sum of projections"
          value={formatPoints(teamA.projection_sum)}
          unit="pts"
          badge={<ProvenanceBadge provenance="model" showLabel={false} />}
          detail={`${labelB} ${formatPoints(teamB.projection_sum)}. The projections themselves, added up — see below.`}
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
            description="Both lineups on one scale. The overlap is the reason the probability above is not a verdict."
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
            description="Simulated mean points by position, one lineup against the other."
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
            title="Widest ranges"
            description="The players whose weeks are least settled, on either side."
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

        <AssumptionsPanel assumptions={result.assumptions} simulation={result.simulation} />

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
            Change the lineups, the correlation mode or the number of draws. This same run repeated
            would return this same result.
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
}: {
  labelA: string
  labelB: string
  probabilityA: number
  probabilityB: number
  tieProbability: number
  iterations: number
  leaderLabel: string
  leaderProbability: number
}) {
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
              This is an estimate from the published outcome distributions, not a forecast of the
              result.
            </span>
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
        <span className="font-semibold">
          The simulated total and the sum of the projections disagree.
        </span>{' '}
        For {labelA} the simulation averages {formatPoints(simulated)} while the projections add up
        to {formatPoints(projected)}. The API treats those agreeing as the check that the sampler
        drew from the stored distributions, so the gap is worth stating: this published run did not
        store calibrated means, so the projections shown are the model&apos;s raw output while the
        simulation draws from the stored outcome curve, whose average is higher. Read the win
        probability and the margins — which come from one consistent set of draws — rather than the
        absolute totals.
        <InfoTip
          label="About the two totals"
          content="expected_score is the mean of the simulated team totals. projection_sum adds up each player's stored headline projection. They coincide when a run stores calibrated means."
        />
      </p>
    </aside>
  )
}
