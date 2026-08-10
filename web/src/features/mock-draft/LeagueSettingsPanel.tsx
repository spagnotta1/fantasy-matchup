import { useId } from 'react'
import { Dices, Play, Settings2 } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Select } from '@/components/ui/Select'
import { Tooltip } from '@/components/ui/Tooltip'
import { ROSTER_SLOT_ORDER, SLOT_LABELS, starterCount } from '@/hooks/useMockDraft'
import { formatScoringProfile } from '@/utils/format'
import type { DraftConfig } from '@/api/schemas'

export interface DraftForm {
  season: number
  teams: number
  rounds: number
  scoringProfile: string
  draftFormat: string
  draftPosition: number
  simulations: number
  seed: number
  roster: Record<string, number>
}

/**
 * The configuration panel.
 *
 * Every bound in here is served by `GET /mock-draft/config` rather than
 * hard-coded, so the form cannot offer a league the server will refuse — a
 * season with no published board, a simulation count above the cap, a roster
 * slot that has no projection model. The one exception is the arithmetic that
 * has to happen as you type: rounds must cover the starters, and the server
 * says so too, but finding that out after a minute of simulation is a bad way
 * to learn it.
 *
 * Kickers and defences are not in the slot list, and their absence is stated
 * rather than left to be noticed. A fantasy manager who starts a kicker will
 * otherwise assume the form forgot one.
 */
export function LeagueSettingsPanel({
  form,
  config,
  onChange,
  onAnalyze,
  onCompare,
  isBusy,
  error,
}: {
  form: DraftForm
  config: DraftConfig
  onChange: (next: Partial<DraftForm>) => void
  onAnalyze: () => void
  onCompare: () => void
  isBusy: boolean
  error: string | null
}) {
  const headingId = useId()
  const starters = starterCount(form.roster)
  const { limits } = config
  const totalDrafts = form.simulations * form.teams
  const comparisonTooLarge = totalDrafts > limits.max_total_drafts

  const simulationChoices = [100, 250, 500, 1000, 2500, 5000, 10000].filter(
    (value) => value >= limits.min_simulations && value <= limits.max_simulations,
  )

  return (
    <Card aria-labelledby={headingId}>
      <CardHeader
        title={<span id={headingId}>League settings</span>}
        description="Everything the draft depends on. Nothing is saved — the settings and the seed are the whole reproducible input."
        as="h2"
      />
      <CardBody className="space-y-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Select
            label="Season"
            value={String(form.season)}
            onChange={(event) => onChange({ season: Number(event.target.value) })}
            options={config.draftable_seasons.map((season) => ({
              value: String(season),
              label: String(season),
            }))}
            hint="Seasons with a published week 1 board"
          />
          <Select
            label="Teams"
            value={String(form.teams)}
            onChange={(event) => {
              const teams = Number(event.target.value)
              onChange({
                teams,
                draftPosition: Math.min(form.draftPosition, teams),
              })
            }}
            options={rangeOptions(limits.min_teams, limits.max_teams)}
          />
          <Select
            label="Scoring"
            value={form.scoringProfile}
            onChange={(event) => onChange({ scoringProfile: event.target.value })}
            options={limits.scoring_profiles.map((profile) => ({
              value: profile,
              label: formatScoringProfile(profile),
            }))}
          />
          <Select
            label="Draft format"
            value={form.draftFormat}
            onChange={(event) => onChange({ draftFormat: event.target.value })}
            options={limits.draft_formats.map((value) => ({
              value,
              label: value === 'snake' ? 'Snake' : 'Linear',
            }))}
          />
          <Select
            label="Rounds"
            value={String(form.rounds)}
            onChange={(event) => onChange({ rounds: Number(event.target.value) })}
            options={rangeOptions(
              Math.max(limits.min_rounds, starters),
              limits.max_rounds,
            )}
            hint={`${starters} starters, ${Math.max(0, form.rounds - starters)} bench`}
          />
          <Select
            label="Your draft position"
            value={String(form.draftPosition)}
            onChange={(event) => onChange({ draftPosition: Number(event.target.value) })}
            options={rangeOptions(1, form.teams)}
          />
        </div>

        <fieldset className="space-y-2">
          <legend className="text-ink text-sm font-semibold">Starting roster</legend>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {ROSTER_SLOT_ORDER.map((slot) => (
              <Select
                key={slot}
                // The visible label and the accessible name are the same
                // string. Naming this "Quarterback" over a control that reads
                // "QB" breaks WCAG 2.5.3: a speech-input user says what they
                // see and nothing happens. The expansion is a hint instead,
                // which is announced without replacing the name.
                label={slot}
                hint={SLOT_LABELS[slot]}
                value={String(form.roster[slot] ?? 0)}
                onChange={(event) =>
                  onChange({
                    roster: { ...form.roster, [slot]: Number(event.target.value) },
                  })
                }
                options={rangeOptions(0, slot === 'QB' ? 2 : 4)}
                size="sm"
              />
            ))}
          </div>
          <p className="text-ink-muted text-xs leading-relaxed">
            Kicker and team-defence slots are not offered:{' '}
            {config.unavailable_positions.map((entry) => entry.position).join(' and ')}{' '}
            have no validated projection, and drafting a position with no projected value
            would put an invented number into every roster total.
          </p>
        </fieldset>

        <details className="group">
          <summary className="text-ink-secondary hover:text-ink flex cursor-pointer items-center gap-1.5 text-sm font-medium">
            <Settings2 aria-hidden className="size-3.5" />
            Simulation options
          </summary>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Select
              label="Simulated drafts"
              value={String(form.simulations)}
              onChange={(event) => onChange({ simulations: Number(event.target.value) })}
              options={simulationChoices.map((value) => ({
                value: String(value),
                label: value.toLocaleString(),
              }))}
              hint="More drafts narrow the error, and cost time"
            />
            <div className="flex items-end gap-2">
              <Select
                label="Seed"
                value={String(form.seed)}
                onChange={(event) => onChange({ seed: Number(event.target.value) })}
                options={[{ value: String(form.seed), label: String(form.seed) }]}
                hint="Same seed, same draft"
                className="flex-1"
              />
              <Button
                variant="secondary"
                size="md"
                onClick={() => onChange({ seed: Math.floor(Math.random() * 2_000_000_000) })}
                aria-label="Use a new random seed"
              >
                <Dices aria-hidden className="size-4" />
                New
              </Button>
            </div>
          </div>
        </details>

        {error && (
          <p role="alert" className="text-negative-text text-sm">
            {error}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={onAnalyze} loading={isBusy} size="md">
            <Play aria-hidden className="size-4" />
            Analyze draft position
          </Button>
          <Tooltip
            content={
              comparisonTooLarge
                ? `${totalDrafts.toLocaleString()} simulated drafts is above the ${limits.max_total_drafts.toLocaleString()} one request may run. Lower the simulation count.`
                : `Simulates all ${form.teams} seats — ${totalDrafts.toLocaleString()} drafts in total.`
            }
          >
            <span>
              <Button
                variant="secondary"
                size="md"
                onClick={onCompare}
                loading={isBusy}
                disabled={comparisonTooLarge}
              >
                Compare all draft positions
              </Button>
            </span>
          </Tooltip>
          {comparisonTooLarge && (
            <Badge tone="caution">Too many drafts to compare every seat</Badge>
          )}
        </div>
      </CardBody>
    </Card>
  )
}

function rangeOptions(from: number, to: number) {
  const options = []
  for (let value = from; value <= to; value += 1) {
    options.push({ value: String(value), label: String(value) })
  }
  return options
}
