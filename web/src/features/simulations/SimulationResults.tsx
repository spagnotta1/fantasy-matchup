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
import { ShareImage, ShareMatchup } from '@/features/simulations/ShareMatchup'
import { useCountUp } from '@/hooks/useCountUp'
import { CORRELATION_MODES } from '@/hooks/useSimulation'
import { formatPercent, formatPoints, formatScoringProfile } from '@/utils/format'
import type {
  MatchupSimulation,
  ResponseMeta,
  SimulatedPlayer,
  SimulationAssumptions,
} from '@/api/schemas'
import type { NoticeGroup } from '@/features/simulations/notices'

/** Below this the two totals disagree enough to be worth explaining. */
const RECONCILIATION_TOLERANCE = 0.02

/**
 * The result, in two parts.
 *
 * A finished run used to be read in the order it was built: both lineups,
 * fourteen rows, then the settings, and only then the answer, a screen and a
 * half down a desktop and three down a phone. The answer now comes first.
 *
 * `SimulationSummary` is the first screen: the estimated win probability, the
 * two score ranges that explain it, and where the gap is by position. One
 * surface, not three cards and four tiles — it is read as one thing, the way a
 * box score is. The page puts it above the lineups, which fold to a line each
 * under it.
 *
 * `SimulationDetails` is everything else, below the lineups and the run
 * controls, in the order it always had: what the engine flagged about each
 * lineup, the totals and how they reconcile, who could swing it, and what the
 * run assumed. Nothing the old result showed is gone, and every notice is
 * still shown once.
 *
 * Nothing here recomputes the outcome. The win probability, both score
 * distributions and every per-player figure come from the response; the only
 * arithmetic in this subtree is subtracting one published number from another
 * to describe a gap, and each place it happens says so.
 */
export function SimulationSummary({
  result,
  labelA,
  labelB,
}: {
  result: MatchupSimulation
  labelA: string
  labelB: string
}) {
  const { team_a: teamA, team_b: teamB } = result
  const leaderLabel = teamA.win_probability >= teamB.win_probability ? labelA : labelB
  const leaderProbability = Math.max(teamA.win_probability, teamB.win_probability)
  const mode = CORRELATION_MODES.find((entry) => entry.value === result.simulation.correlation_mode)

  return (
    // A query container: the three parts sit side by side or one under the
    // other by the room the card has, not the window. A laptop with the
    // sidebar open has less than a tablet.
    <Card data-simulation-summary="" className="animate-rise @container">
      <div className="border-line flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b px-5 py-3">
        <h2 className="text-ink text-section">Result</h2>
        {/* What was asked, from the response: the week and format it scored,
            how many weeks it played out, and how. */}
        <p className="text-ink-muted text-detail">
          Week {result.week} · {formatScoringProfile(result.scoring_profile)} ·{' '}
          {result.simulation.iterations.toLocaleString()} simulated weeks ·{' '}
          {mode?.label ?? result.simulation.correlation_mode}
        </p>
      </div>

      <div className="grid @[44rem]:grid-cols-2">
        <section aria-label="Estimated win probability" className="border-line p-5 @[44rem]:border-r">
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
            result={result}
          />
        </section>

        <section
          aria-labelledby="simulation-scores"
          className="border-line border-t p-5 @[44rem]:border-t-0"
        >
          <SummaryHeading
            id="simulation-scores"
            title="Where the scores land"
            // "Above" where the parts are stacked, beside where they are not:
            // the sentence no longer says which.
            description="Both lineups on one chart. The overlap is why the result is a chance, not a certainty."
          />
          <ScoreDistribution labelA={labelA} teamA={teamA} labelB={labelB} teamB={teamB} />
        </section>

        <section
          aria-labelledby="simulation-gaps"
          className="border-line border-t p-5 @[44rem]:col-span-2"
        >
          {/* No line under this heading: the sentence that belongs here is the
              one under the bars, which also says what the gaps are not. */}
          <SummaryHeading id="simulation-gaps" title="Where the gap is" />
          <PositionalEdges
            labelA={labelA}
            labelB={labelB}
            playersA={teamA.players}
            playersB={teamB.players}
          />
        </section>
      </div>

      <div className="border-line flex flex-wrap items-start justify-end gap-2 border-t px-5 py-3">
        <ShareImage result={result} labelA={labelA} labelB={labelB} />
        <ShareMatchup />
      </div>
    </Card>
  )
}

/** A part of the summary: its name, that it is calculated, and a line on reading it. */
function SummaryHeading({ id, title, description }: { id: string; title: string; description?: string }) {
  return (
    <div className="mb-3">
      <div className="flex items-center justify-between gap-3">
        <h3 id={id} className="text-ink text-body font-semibold">
          {title}
        </h3>
        <ProvenanceBadge provenance="derived" />
      </div>
      {description && <p className="text-ink-muted text-detail mt-0.5">{description}</p>}
    </div>
  )
}

export function SimulationDetails({
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

  return (
    <div className="space-y-6">
      {/*
        Every notice the engine returns is still shown, each once. The ones
        that name a lineup's own players — a designation, a stack — sit here,
        first under the lineups they are about. The run-wide ones
        (independence, no kickers, no injury adjustment) live only in the
        assumptions panel, and the headline carries a one-sentence summary of
        them.
      */}
      <LineupNotes groups={notices.filter((group) => group.key !== 'run')} />

      {/*
        Two tiles, where there were four. Each lineup's simulated average and
        median are in the summary now, beside its range ("116.4 pts on
        average", "Middle 115.3"), with the scoring format in its heading;
        printing them again here was the same four numbers twice.
      */}
      <div className="grid gap-3 sm:grid-cols-2">
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

      <Reconciliation labelA={labelA} players={teamA.players} />

      {/* `min-w-0` on each card: a grid item is otherwise as wide as its
          widest unbroken line, which on a 360px phone was wider than the
          phone. */}
      <div className="grid gap-6 xl:grid-cols-2 [&>*]:min-w-0">
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
 * costs one line. The limits that qualify the number stay directly under it,
 * in the same part of the summary: a limit belongs beside the number it limits.
 *
 * The figure is 36px, not the 60px it was. It is the first thing in a readout,
 * and it does not need to be a poster to be first.
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
  result,
}: {
  result: MatchupSimulation
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
  // Revealed from even odds — the honest reading before anything was
  // simulated — to the estimate. A new run counts from the last estimate to
  // the next. Assistive tech reads the real figures from the label and the
  // sentence below, never the numbers in flight.
  const shownA = useCountUp(probabilityA, 900, 0.5)
  const shownB = useCountUp(probabilityB, 900, 0.5)
  return (
    <>
        <div className="flex items-end justify-between gap-6">
          <div className="min-w-0">
            <p className="text-ink-muted text-caption font-medium tracking-wide uppercase">
              {labelA} — estimated win probability
            </p>
            <p className="text-you tnum mt-1 text-4xl leading-none font-bold tracking-tight">
              <span aria-hidden>{formatPercent(shownA)}</span>
              <span className="sr-only">{formatPercent(probabilityA)}</span>
            </p>
          </div>
          {/* Not shrunk: squeezed, the label ran out past the bar's end. The
              longer label on the left wraps instead. */}
          <div className="shrink-0 text-right">
            <p className="text-ink-muted text-caption font-medium tracking-wide uppercase">{labelB}</p>
            <p className="text-ink-secondary tnum mt-1 text-2xl leading-none font-semibold tracking-tight">
              <span aria-hidden>{formatPercent(shownB)}</span>
              <span className="sr-only">{formatPercent(probabilityB)}</span>
            </p>
          </div>
        </div>

        <div
          className="bg-surface-sunken mt-3 flex h-3 overflow-hidden rounded-full"
          role="img"
          aria-label={`${labelA} wins ${formatPercent(probabilityA)} of simulated weeks, ${labelB} wins ${formatPercent(probabilityB)}.`}
        >
          <div className="bg-you" style={{ width: `${shownA * 100}%` }} />
          <div className="bg-chart-series/30" style={{ width: `${shownB * 100}%` }} />
        </div>

          <p className="text-ink-secondary text-detail mt-3 leading-relaxed">
            Across {iterations.toLocaleString()} simulated weeks, {leaderLabel} finished ahead in{' '}
            {formatPercent(leaderProbability)} of them.
            {tieProbability > 0 && (
              <> Both lineups tied in {formatPercent(tieProbability, 2)}.</>
            )}{' '}
            <SettledSentence result={result} />
            {limits.length > 0 && (
              <span className="text-ink-muted mt-1.5 block">
                It {joinClauses(limits)}.{' '}
                <a href="#simulation-assumptions" className="text-accent-text font-medium hover:underline">
                  What it assumes
                </a>
              </span>
            )}
          </p>
    </>
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
function Reconciliation({ labelA, players }: { labelA: string; players: SimulatedPlayer[] }) {
  // Only the players still being sampled. A finished game's score replaces the
  // projection by design, and that gap is a result, not a reconciliation issue.
  const sampled = players.filter((player) => !player.final)
  const simulated = sampled.reduce((total, player) => total + player.simulated_mean, 0)
  const projected = sampled.reduce((total, player) => total + (player.expected_points ?? 0), 0)
  if (projected <= 0) return null
  const gap = Math.abs(simulated - projected) / projected
  if (gap <= RECONCILIATION_TOLERANCE) return null

  return (
    <aside
      className="bg-caution-soft rounded-[var(--radius-card)] px-4 py-3"
      aria-label="Totals do not reconcile"
    >
      <p className="text-caution-text text-detail leading-relaxed">
        <span className="font-semibold">Why the two totals above differ.</span> For {labelA}
        {sampled.length < players.length ? "'s players still to play" : ''}, the simulation averages {formatPoints(simulated)} points; the players&apos; projections add up
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
 * What the headline percentage is made of, once some games are over.
 *
 * Counted from `players[].final`, never from notice prose. Before any game has
 * finished it is the sentence the page always carried. After, it says how many
 * starters entered as a result, and when every one of them did, that there is
 * nothing left to estimate — without calling an unofficial box score official.
 */
function SettledSentence({ result }: { result: MatchupSimulation }) {
  const players = [...result.team_a.players, ...result.team_b.players]
  const settled = players.filter((player) => player.final)
  const unofficial = settled.some((player) => player.final && !player.final.official)

  if (settled.length === 0) {
    return (
      <span className="text-ink-muted">
        This is an estimate based on each player&apos;s projected range, not a prediction of the
        result.
      </span>
    )
  }
  if (settled.length === players.length) {
    return (
      <span className="text-ink-muted">
        Every game in both lineups is over, so nothing was estimated: these are the final scores
        {unofficial ? ', unofficial until the official stat lines are loaded' : ''}.
      </span>
    )
  }
  return (
    <span className="text-ink-muted">
      {settled.length} of {players.length} players{' '}
      {settled.length === 1 ? 'has finished their game' : 'have finished their games'}, so{' '}
      {settled.length === 1 ? 'their actual score' : 'their actual scores'}
      {unofficial ? ' (unofficial until the official stat lines are loaded)' : ''}{' '}
      {settled.length === 1 ? 'is' : 'are'} used in every simulated week. The rest is an estimate based on each remaining player&apos;s
      projected range, not a prediction of the result.
    </span>
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
        description="What the engine flagged about the players on each side. A finished game's score replaces that player's projection; nothing else here changes the numbers above."
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
