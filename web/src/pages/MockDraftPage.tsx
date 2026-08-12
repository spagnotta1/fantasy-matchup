import { useEffect, useMemo, useState } from 'react'

import { Card, CardBody } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatCard } from '@/components/ui/StatCard'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { AvailabilityPanel } from '@/features/mock-draft/AvailabilityPanel'
import { DraftBoard } from '@/features/mock-draft/DraftBoard'
import { DraftPositionChart } from '@/features/mock-draft/DraftPositionChart'
import {
  LeagueSettingsPanel,
  type DraftForm,
} from '@/features/mock-draft/LeagueSettingsPanel'
import {
  PickRecommendation,
  PositionStrength,
} from '@/features/mock-draft/PickRecommendation'
import { SimulatedRoster } from '@/features/mock-draft/SimulatedRoster'
import { StrategyInsights } from '@/features/mock-draft/StrategyInsights'
import {
  fromRosterList,
  starterCount,
  toRosterList,
  useDraftAnalysis,
  useDraftComparison,
  useDraftConfig,
} from '@/hooks/useMockDraft'
import { formatNumber, formatScoringProfile, ordinal } from '@/utils/format'
import type {
  DraftAnalysisRequest,
  DraftMethodology,
  DraftPoolSummary,
  DraftRequest,
  SeatAnalysis,
} from '@/api/schemas'

/**
 * `/mock-draft`.
 *
 * The page is built around one distinction that the brief is emphatic about and
 * that is easy to lose in a layout: **the configuration is what the user edits,
 * and the result is what the simulation produced from a configuration they
 * committed.** Editing a field does not fire a request — a thousand simulated
 * drafts on every keystroke would be absurd — so the form holds draft state and
 * a button promotes it to a committed request.
 *
 * That split is also what makes the retained-result behaviour work. A committed
 * request is the query key, so re-requesting the same league is a cache hit and
 * changing the seat holds the previous answer on screen under a busy state
 * instead of blanking a page of numbers. Only a change of *season* blanks,
 * because that is a change of board and the old rosters would be captioned with
 * the wrong year.
 *
 * Two things are deliberately not built. There is no live drafting — you cannot
 * make a pick and have the board respond, because nothing is persisted and a
 * draft that forgets itself on refresh is worse than one that never claimed to
 * remember. And there is no sticky mobile action bar; the brief warns against
 * introducing one unvalidated, and the configuration panel is short enough that
 * scrolling back to it is not a hardship.
 */
export default function MockDraftPage() {
  const config = useDraftConfig()
  const draftConfig = config.data?.data ?? null

  const [form, setForm] = useState<DraftForm | null>(null)
  const [analysisRequest, setAnalysisRequest] = useState<DraftAnalysisRequest | null>(null)
  const [comparisonRequest, setComparisonRequest] = useState<DraftRequest | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  // Seed the form from the server's own defaults the moment they arrive, so no
  // constant in this file can disagree with what the API will accept.
  useEffect(() => {
    if (form || !draftConfig) return
    const { limits, draftable_seasons: seasons } = draftConfig
    if (seasons.length === 0) return
    setForm({
      season: seasons[0] ?? new Date().getFullYear(),
      teams: 12,
      rounds: 15,
      scoringProfile: limits.scoring_profiles.includes('ppr')
        ? 'ppr'
        : (limits.scoring_profiles[0] ?? 'half_ppr'),
      draftFormat: limits.draft_formats[0] ?? 'snake',
      draftPosition: 4,
      simulations: Math.min(limits.default_simulations, 500),
      seed: limits.default_seed,
      roster: fromRosterList(limits.default_roster),
    })
  }, [draftConfig, form])

  const analysis = useDraftAnalysis(analysisRequest)
  const comparison = useDraftComparison(comparisonRequest)

  const onChange = (next: Partial<DraftForm>) => {
    setFormError(null)
    setForm((current) => (current ? { ...current, ...next } : current))
  }

  const buildRequest = (): DraftRequest | null => {
    if (!form) return null
    const starters = starterCount(form.roster)
    if (starters === 0) {
      setFormError('A roster needs at least one starting slot.')
      return null
    }
    if (form.rounds < starters) {
      setFormError(
        `A ${form.rounds}-round draft cannot fill a ${starters}-player starting lineup.`,
      )
      return null
    }
    return {
      season: form.season,
      teams: form.teams,
      rounds: form.rounds,
      scoring_profile: form.scoringProfile,
      draft_format: form.draftFormat,
      roster: toRosterList(form.roster),
      simulations: form.simulations,
      seed: form.seed,
    }
  }

  const onAnalyze = () => {
    const request = buildRequest()
    if (!request || !form) return
    setComparisonRequest(null)
    setAnalysisRequest({ ...request, draft_position: form.draftPosition })
  }

  const onCompare = () => {
    const request = buildRequest()
    if (!request) return
    setAnalysisRequest(null)
    setComparisonRequest(request)
  }

  /** Clicking a bar in the comparison inspects that seat without a new request. */
  const onSelectSeat = (position: number) => {
    onChange({ draftPosition: position })
  }

  // Both queries hold the whole `{data, meta}` envelope, which is the
  // application's convention: `meta.notices` is the backend telling the UI what
  // it must not quietly omit, and unwrapping it away at the hook would lose it.
  const analysed = analysis.data?.data ?? null
  const compared = comparison.data?.data ?? null

  const selectedSeat: SeatAnalysis | null = useMemo(() => {
    if (compared && form) {
      return (
        compared.detail.find((entry) => entry.draft_position === form.draftPosition) ??
        compared.detail[0] ??
        null
      )
    }
    return analysed?.seat ?? null
  }, [analysed, compared, form])

  const settings = compared?.settings ?? analysed?.settings ?? null
  const pool = compared?.pool ?? analysed?.pool ?? null
  const methodology = compared?.methodology ?? analysed?.methodology ?? null
  const notices = comparison.data?.meta.notices ?? analysis.data?.meta.notices ?? []

  const isBusy = analysis.isFetching || comparison.isFetching
  const isRefreshing =
    (analysis.isFetching && analysis.data != null) ||
    (comparison.isFetching && comparison.data != null)
  const requestError = analysis.error ?? comparison.error

  return (
    <>
      <PageHeader
        title="Mock draft"
        question="Which draft position builds the strongest roster, and what does it take there?"
      />

      <div className="space-y-6">
        {config.isPending && <Skeleton className="h-72 w-full" />}

        {config.isError && (
          <Card>
            <ErrorState error={config.error} onRetry={() => config.refetch()} />
          </Card>
        )}

        {draftConfig && draftConfig.draftable_seasons.length === 0 && (
          <Card>
            <EmptyState
              title="No season can be drafted yet"
              description="A mock draft reads the published week 1 board of the season being drafted, and no season has one. Once a projection run publishes for week 1, that season appears here."
            />
          </Card>
        )}

        {draftConfig && form && (
          <LeagueSettingsPanel
            form={form}
            config={draftConfig}
            onChange={onChange}
            onAnalyze={onAnalyze}
            onCompare={onCompare}
            isBusy={isBusy}
            error={formError}
          />
        )}

        {requestError && (
          <Card>
            <ErrorState
              error={requestError}
              onRetry={() => (comparisonRequest ? comparison.refetch() : analysis.refetch())}
            />
          </Card>
        )}

        {isBusy && !analysis.data && !comparison.data && (
          <Card>
            <CardBody>
              <p className="text-ink-secondary text-sm" aria-live="polite">
                Simulating drafts. A few hundred complete drafts take a moment; a
                comparison of every seat takes longer.
              </p>
              <div className="mt-4 space-y-3">
                <Skeleton className="h-6 w-full" />
                <Skeleton className="h-6 w-11/12" />
                <Skeleton className="h-6 w-10/12" />
              </div>
            </CardBody>
          </Card>
        )}

        {!isBusy && !analysis.data && !comparison.data && !requestError && form && (
          <Card>
            <EmptyState
              title="Nothing simulated yet"
              description="Set your league up above, then analyse a single draft position or compare all of them. Nothing is saved: the settings and the seed are the entire input, so the same configuration always returns the same draft."
            />
          </Card>
        )}

        <Refreshing active={isRefreshing} label="Simulating">
          {settings && selectedSeat && (
            <div className="space-y-6">
              <SeatSummary seat={selectedSeat} isComparison={compared != null} />

              {compared && form && (
                <DraftPositionChart
                  comparison={compared}
                  selected={form.draftPosition}
                  onSelect={onSelectSeat}
                />
              )}

              <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
                <PickRecommendation seat={selectedSeat} />
                <StrategyInsights seat={selectedSeat} />
              </div>

              <SimulatedRoster seat={selectedSeat} />

              <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
                <AvailabilityPanel seat={selectedSeat} />
                <div className="space-y-6">
                  <PositionStrength seat={selectedSeat} />
                  <DraftBoard
                    seat={selectedSeat}
                    teams={settings.teams}
                    snake={settings.draft_format === 'snake'}
                  />
                </div>
              </div>

              {pool && methodology && (
                <Methodology
                  pool={pool}
                  methodology={methodology}
                  scoringProfile={settings.scoring_profile}
                />
              )}

              {notices.length > 0 && (
                <Card>
                  <CardBody>
                    <NoticeList notices={notices} showTitle title="What this does and does not claim" />
                  </CardBody>
                </Card>
              )}
            </div>
          )}
        </Refreshing>
      </div>
    </>
  )
}

/** The three headline numbers, with the words that keep them honest. */
function SeatSummary({
  seat,
  isComparison,
}: {
  seat: SeatAnalysis
  isComparison: boolean
}) {
  return (
    <section aria-label={`Summary for draft position ${seat.draft_position}`}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard
          label="Draft position"
          value={ordinal(seat.draft_position)}
          detail={
            isComparison
              ? 'Selected from the comparison below'
              : `${seat.simulations.toLocaleString()} simulated drafts`
          }
          emphasis="primary"
        />
        <StatCard
          label="Draft value"
          value={formatNumber(seat.roster_value.mean)}
          detail={`Mean roster points above replacement, ±${formatNumber(seat.roster_value.standard_error, 2)}`}
        />
        <StatCard
          label="Projected team"
          value={formatNumber(seat.starter_points.mean)}
          unit="pts"
          detail={`Median ${formatNumber(seat.starter_points.median)}, middle 80% ${formatNumber(seat.starter_points.p10)}–${formatNumber(seat.starter_points.p90)}`}
        />
      </div>
    </section>
  )
}

/**
 * How the answer was produced.
 *
 * Not an appendix. The season-value construction is the single most
 * misinterpretable thing on the page — a per-game rate multiplied by an
 * availability estimate is not a season projection, and this is where that is
 * said in the response's own numbers rather than in prose alone.
 */
function Methodology({
  pool,
  methodology,
  scoringProfile,
}: {
  pool: DraftPoolSummary
  methodology: DraftMethodology
  scoringProfile: string
}) {
  return (
    <Card>
      <CardBody>
        <details>
          <summary className="text-ink cursor-pointer text-sm font-semibold">
            How this was calculated
          </summary>
          <div className="text-ink-secondary mt-3 space-y-3 text-sm leading-relaxed">
            <p>
              Season value is the published <strong>week {pool.board_week}</strong>{' '}
              projection for {pool.season} in {formatScoringProfile(scoringProfile)}, read
              as a points-per-game rate and multiplied by an estimate of games played out
              of {pool.season_games}. There is no season-long projection in this system;
              the model projects one week from a trailing four-game usage window, so
              nothing beyond week 1 of an unplayed season is projectable and none is
              invented here.
            </p>
            <p>
              Expected games is estimated from historical availability over{' '}
              {pool.history_seasons.length > 0
                ? `${pool.history_seasons[0]}–${pool.history_seasons[pool.history_seasons.length - 1]}`
                : 'no completed seasons'}
              , shrunk toward a position prior.{' '}
              {pool.players_without_history} of {pool.players} players have no completed
              season in that window and carry the prior alone.
            </p>
            <p>
              Availability was calibrated over {methodology.calibration_drafts.toLocaleString()}{' '}
              drafts in which every seat used the opponent model, then read during{' '}
              {methodology.simulations.toLocaleString()} drafts per seat in which yours did
              not. The opponent model weights value over replacement at{' '}
              {Math.round((1 - methodology.history_weight) * 100)}% and last completed
              season&rsquo;s actual points at {Math.round(methodology.history_weight * 100)}%,
              with randomness added — an assumption, not a measurement, because this
              system holds no average-draft-position data to fit it against.
            </p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 pt-1 text-xs sm:grid-cols-4">
              <Detail label="Seed" value={String(methodology.seed)} />
              <Detail label="Pool" value={`${pool.players} players`} />
              <Detail
                label="Replacement"
                value={pool.replacement
                  .map((entry) => `${entry.position} ${formatNumber(entry.value, 0)}`)
                  .join(' · ')}
              />
              <Detail label="Ran in" value={`${formatNumber(methodology.elapsed_seconds, 1)}s`} />
            </dl>
          </div>
        </details>
      </CardBody>
    </Card>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="text-ink-secondary font-medium">{value}</dd>
    </div>
  )
}
