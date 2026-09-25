import { AlertTriangle, Check, X } from 'lucide-react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { cn } from '@/utils/cn'
import type { SimulationAssumptions, SimulationRun } from '@/api/schemas'

/**
 * What this simulation did not account for.
 *
 * The API returns `assumptions` as a set of booleans rather than a paragraph
 * specifically so a client can render this without string-matching prose, and
 * so the day a kicker model ships `kicker_projection_available` flips on its own
 * with no frontend release. Each flag is read, never inferred.
 *
 * `player_independence` is given its own banner because it is an assumption a
 * user is entitled to know about before acting on a win probability, not
 * because it is a large error. Phase 6D measured its cost at the shipped tail
 * factors and found it small: 80% interval coverage 0.7943 against a nominal
 * 0.800 over 2,878 held-out lineups, with the correlated mode moving that past
 * nominal rather than onto it. The banner therefore discloses the assumption
 * and states what it was measured to cost — overstating it would teach a user
 * to discount a number the evidence supports, which is the same failure as
 * overstating the number itself.
 */
export function AssumptionsPanel({
  assumptions,
  simulation,
}: {
  assumptions: SimulationAssumptions
  simulation: SimulationRun
}) {
  const flags = [
    {
      label: 'Kickers',
      ok: assumptions.kicker_projection_available,
      detail: assumptions.kicker_projection_available
        ? 'Included.'
        : 'Not included. Totals cover QB, RB, WR and TE only, so they will be lower than a full lineup score.',
    },
    {
      label: 'Team defence',
      ok: assumptions.defense_projection_available,
      detail: assumptions.defense_projection_available
        ? 'Included.'
        : 'Not included. Totals cover QB, RB, WR and TE only.',
    },
    {
      label: 'Injury designations',
      ok: assumptions.injury_adjustment_applied,
      detail: assumptions.injury_adjustment_applied
        ? 'Applied.'
        : 'Not factored in. A player ruled Out is still simulated as if they play.',
    },
    {
      label: 'Matchup',
      ok: assumptions.matchup_adjustment_applied,
      detail: assumptions.matchup_adjustment_applied
        ? 'Applied.'
        : 'Not factored in. The matchup grade is calculated separately and does not feed the projection.',
    },
    {
      label: 'Weather',
      ok: assumptions.weather_adjustment_applied,
      detail: assumptions.weather_adjustment_applied
        ? 'Applied.'
        : 'Not factored in. Weather is shown for information and does not change the projection.',
    },
  ]

  return (
    <Card>
      <CardHeader
        as="h2"
        title="What this simulation assumes"
        description="What this run did and did not include."
        action={<ProvenanceBadge provenance="derived" />}
      />
      <CardBody className="space-y-5">
        {assumptions.player_independence && (
          <div className="bg-caution-soft flex gap-2.5 rounded-[var(--radius-control)] px-3 py-2.5">
            <AlertTriangle aria-hidden className="text-caution-text mt-0.5 size-4 shrink-0" />
            <p className="text-caution-text text-xs leading-relaxed">
              <span className="font-semibold">Each player was simulated on their own.</span> In
              real games, teammates share one offence&apos;s plays and a game&apos;s pace affects both
              sides, so scores are linked — most of all a quarterback and their own receivers. Tested
              on 2,878 past lineups, the effect is small: the 80% range held the real score 79.4% of
              the time, against a target of 80%. The linked mode above overshoots that target rather
              than hitting it, which is why it is not the default.
            </p>
          </div>
        )}

        <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          {flags.map((flag) => (
            // The status glyph belongs inside the <dt>: a <dl>'s grouping
            // <div> may contain only <dt> and <dd>, so an icon sitting beside
            // them breaks the list semantics for a screen reader. The <dd> is
            // indented by the glyph's width plus the gap to keep the alignment.
            <div key={flag.label} className="min-w-0">
              <dt className="text-ink flex items-start gap-2.5 text-xs font-semibold">
                <span
                  className={cn(
                    'mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full',
                    flag.ok
                      ? 'bg-positive-soft text-positive-text'
                      : 'bg-surface-sunken text-ink-muted',
                  )}
                >
                  {flag.ok ? (
                    <Check aria-hidden className="size-3" />
                  ) : (
                    <X aria-hidden className="size-3" />
                  )}
                </span>
                <span>
                  {flag.label}
                  <span className="sr-only">: {flag.ok ? 'included' : 'not included'}</span>
                </span>
              </dt>
              <dd className="text-ink-muted ps-[1.625rem] text-xs leading-relaxed">
                {flag.detail}
              </dd>
            </div>
          ))}
        </dl>

        <div className="border-line border-t pt-3">
          <h3 className="text-ink-muted mb-2 text-xs font-semibold tracking-wide uppercase">
            How it was run
          </h3>
          <dl className="text-ink-muted grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
            <Detail label="Simulations" value={simulation.iterations.toLocaleString()} />
            <Detail label="Seed" value={String(simulation.seed)} />
            <Detail label="Method" value={simulation.sampling_method.replace(/_/g, ' ')} />
            <Detail
              label="Mode"
              value={
                simulation.correlation_model_version
                  ? `${simulation.correlation_mode} v${simulation.correlation_model_version}`
                  : simulation.correlation_mode
              }
            />
            <Detail label="Lineup format" value={simulation.lineup_format.replace(/_/g, ' ')} />
            <Detail
              label="Projections used"
              value={
                simulation.model
                  ? `#${simulation.model.run_id} · ${simulation.model.model_name} ${simulation.model.model_version}`
                  : 'none'
              }
            />
          </dl>
          <p className="text-ink-muted mt-2 text-xs leading-relaxed">
            Running the same lineups with the same seed against the same projections gives exactly
            the same numbers. Every simulated score comes from a player&apos;s projected range.
          </p>
        </div>
      </CardBody>
    </Card>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt>{label}</dt>
      <dd className="text-ink-secondary tnum truncate font-medium">{value}</dd>
    </div>
  )
}
