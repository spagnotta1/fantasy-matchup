import { Link } from 'react-router-dom'
import { ArrowLeft, Swords } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Skeleton, SkeletonText } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { useDocumentTitle } from '@/app/page-title'
import { MatchupMeter } from '@/components/domain/MatchupMeter'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { ProjectionValue } from '@/components/domain/ProjectionValue'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { NotAppliedNotice, ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { useMatchupAnalysis } from '@/hooks/useMatchups'
import {
  formatGameDay,
  formatPercent,
  formatPoints,
  formatSpread,
} from '@/utils/format'
import type { MatchupAnalysis, PlayerContext, PositionMatchup, RankedProjection } from '@/api/schemas'

/** The order positions are shown in, which is the order a lineup is filled. */
const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE']

/**
 * One game, read as a fantasy question.
 *
 * The structure follows the only question that matters here — *which side of
 * this game do I want my players on, and at which position*. So the two
 * offences are the sections, each headed by the defence it faces, rather than
 * the API's own shape (a dictionary keyed by defending team) which is correct
 * for a wire format and unreadable as a screen.
 *
 * Nothing in this view is folded into the projections beside it. The grades are
 * derived above the model and the weather and market are not consumed at all,
 * both of which are stated where they appear rather than in a footnote.
 */
export function GameAnalysis({ gameId }: { gameId: string }) {
  const { data, isPending, isError, error, refetch, isPlaceholderData } =
    useMatchupAnalysis(gameId)

  // This view draws its own `<h1>` — the fixture — rather than going through
  // `PageHeader`, so it has to name the document itself.
  const teams = data && `${data.data.away.abbr} at ${data.data.home.abbr}`
  useDocumentTitle(teams)

  if (isPending) return <AnalysisSkeleton />

  if (isError) {
    return (
      <>
        <BackLink />
        <Card>
          <ErrorState error={error} onRetry={() => void refetch()} />
        </Card>
      </>
    )
  }

  const analysis = data.data

  return (
    <>
      <BackLink />
      <GameHeader analysis={analysis} />
      <NoticeList notices={data.meta.notices} className="mb-6" />

      {/* The header stays put — it names the fixture, which a scoring change
          does not alter. Only the graded panels below it go stale. */}
      <Refreshing active={isPlaceholderData}>
        <div className="grid gap-6 xl:grid-cols-2">
          <OffenseCard
            analysis={analysis}
            offense={analysis.away.abbr}
            defense={analysis.home.abbr}
          />
          <OffenseCard
            analysis={analysis}
            offense={analysis.home.abbr}
            defense={analysis.away.abbr}
          />
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-2">
          <TopProjectionsCard analysis={analysis} />
          <GameContextCard context={analysis.context} />
        </div>
      </Refreshing>
    </>
  )
}

function BackLink() {
  return (
    <Link
      to="/matchups"
      className="text-ink-muted hover:text-ink mb-4 inline-flex items-center gap-1.5 text-xs font-medium transition-colors"
    >
      <ArrowLeft aria-hidden className="size-3.5" />
      All games
    </Link>
  )
}

function GameHeader({ analysis }: { analysis: MatchupAnalysis }) {
  const game = analysis.context.game

  return (
    <div className="mb-6">
      <h1 className="text-ink text-xl font-semibold tracking-tight sm:text-2xl">
        {analysis.away.abbr} <span className="text-ink-muted font-normal">at</span>{' '}
        {analysis.home.abbr}
      </h1>
      <p className="text-ink-secondary mt-1 text-sm">
        Week {analysis.week}, {analysis.season}
        {game?.gameday ? ` · ${formatGameDay(game.gameday)}` : ''}
      </p>
      {game && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {/* `team_spread` here is the home team's, because the API resolves the
              game context from the home row. Labelled with the team so the sign
              cannot be read against the wrong side. */}
          <Badge tone="neutral">
            {analysis.home.abbr} {formatSpread(game.team_spread)}
          </Badge>
          <Badge tone="neutral">Total {formatPoints(game.total_line)}</Badge>
          {game.divisional && <Badge tone="info">Divisional</Badge>}
        </div>
      )}
    </div>
  )
}

/**
 * One offence against the defence it faces.
 *
 * The heading names the *defence* being attacked, because that is what the
 * grades describe. Saying "DAL offence" over a set of grades computed from what
 * the New York defence allows is the kind of small mislabel that makes a
 * reader draw exactly the wrong conclusion.
 */
function OffenseCard({
  analysis,
  offense,
  defense,
}: {
  analysis: MatchupAnalysis
  offense: string
  defense: string
}) {
  const rows = orderPositions(analysis.defense[defense] ?? [])

  return (
    <Card>
      <CardHeader
        as="h2"
        title={
          <span className="flex items-center gap-2">
            <Swords aria-hidden className="text-ink-muted size-4" />
            {offense} attacking the {defense} defence
          </span>
        }
        description="How much this defence has given up to each position over its last four completed games, as a percentile across the week."
        action={<ProvenanceBadge provenance="derived" />}
      />
      <CardBody>
        {rows.length === 0 ? (
          <p className="text-ink-muted text-sm">
            No defensive form is available for {defense} this week.
          </p>
        ) : (
          <div className="space-y-3">
            {rows.map((row) => (
              <MatchupMeter
                key={row.position}
                matchup={row}
                label={row.position}
                defense={defense}
              />
            ))}
          </div>
        )}

        <p className="text-ink-muted mt-4 text-xs leading-relaxed">
          A longer bar is a softer draw. The scale is a percentile across every defence this week,
          so an A means one of the softest matchups on the slate rather than a weak defence in
          absolute terms.
        </p>
      </CardBody>
    </Card>
  )
}

/** QB, RB, WR, TE first; anything else the API adds keeps its own order after. */
function orderPositions(rows: PositionMatchup[]): PositionMatchup[] {
  return [...rows].sort((a, b) => {
    const left = POSITION_ORDER.indexOf(a.position)
    const right = POSITION_ORDER.indexOf(b.position)
    return (left === -1 ? POSITION_ORDER.length : left) - (right === -1 ? POSITION_ORDER.length : right)
  })
}

/**
 * The projected players in this game, both sides together.
 *
 * Deliberately one list rather than two columns: the useful comparison is
 * across the whole game — who in this game is worth starting — and splitting by
 * team turns that into two short lists nobody compares.
 */
function TopProjectionsCard({ analysis }: { analysis: MatchupAnalysis }) {
  const entries = analysis.top_projections

  return (
    <Card>
      <CardHeader
        as="h2"
        title="Projected players in this game"
        description="Ranked by projection across both teams."
        action={<ProvenanceBadge provenance="model" />}
      />
      {entries.length === 0 ? (
        <EmptyState
          title="No projections for this game"
          description="No model run covering this week has published players for either team."
        />
      ) : (
        <ul className="divide-line max-h-[28rem] divide-y overflow-y-auto">
          {entries.map((entry) => (
            <ProjectionRow key={entry.projection.player.player_id} entry={entry} />
          ))}
        </ul>
      )}
    </Card>
  )
}

function ProjectionRow({ entry }: { entry: RankedProjection }) {
  const { projection } = entry
  const usage = projection.usage

  return (
    <li className="hover:bg-surface-hover flex items-center gap-3 px-5 py-2.5 transition-colors">
      <PlayerIdentity
        player={projection.player}
        team={projection.team}
        size="sm"
        className="min-w-0 flex-1"
        subtitle={
          <>
            {projection.player.position} · {projection.team}
            {usage.snap_pct_l4 !== null && usage.snap_pct_l4 !== undefined && (
              <> · {formatPercent(usage.snap_pct_l4)} snaps</>
            )}
            {usage.target_share_l4 !== null && usage.target_share_l4 !== undefined && (
              <> · {formatPercent(usage.target_share_l4)} targets</>
            )}
          </>
        }
      />
      <MatchupGradeChip
        grade={projection.matchup?.grade}
        opponent={projection.opponent}
        fpAllowed={projection.matchup?.fp_allowed_vs_position_l4}
        align="end"
      />
      <span className="w-12 shrink-0 text-right">
        <ProjectionValue points={projection.prediction.points} />
      </span>
    </li>
  )
}

/**
 * Weather and the betting market for the game.
 *
 * Both are observed, neither is an input, and each carries the API's own reason
 * for why. The player page says the same thing per player; this says it once
 * for the game, which is the level the facts actually live at.
 */
function GameContextCard({ context }: { context: PlayerContext }) {
  const { game, weather } = context

  return (
    <Card>
      <CardHeader
        as="h2"
        title="Conditions and market"
        description="Observed facts about the game. Useful for your judgement; not folded into any number on this page."
        action={<ProvenanceBadge provenance="context" />}
      />
      <CardBody className="space-y-6">
        <section>
          <h3 className="text-ink-muted mb-2 text-xs font-semibold tracking-wide uppercase">
            Weather
          </h3>
          {!weather ? (
            <p className="text-ink-muted text-sm">No forecast is available for this game.</p>
          ) : weather.is_indoor ? (
            <p className="text-ink-secondary text-sm">
              Indoor venue — conditions are not a factor.
            </p>
          ) : (
            <>
              <dl>
                <Row
                  label="Temperature"
                  value={
                    weather.temperature_f === null || weather.temperature_f === undefined
                      ? '—'
                      : `${Math.round(weather.temperature_f)}°F`
                  }
                />
                <Row
                  label="Wind"
                  value={
                    weather.wind_mph === null || weather.wind_mph === undefined
                      ? '—'
                      : `${Math.round(weather.wind_mph)} mph`
                  }
                />
                <Row label="Precipitation" value={formatPercent(weather.precipitation_probability)} />
                <Row label="Source" value={weather.source ?? '—'} />
              </dl>
              {weather.is_adverse && (
                <p className="bg-caution-soft text-caution-text mt-3 rounded-[var(--radius-control)] px-3 py-2 text-xs leading-relaxed">
                  Flagged as adverse: 20+ mph wind or 60%+ chance of precipitation, outdoors.
                </p>
              )}
              {!weather.applied_to_projection && (
                <NotAppliedNotice reason={weather.unapplied_reason} />
              )}
            </>
          )}
        </section>

        <section>
          <h3 className="text-ink-muted mb-2 text-xs font-semibold tracking-wide uppercase">
            Betting market
          </h3>
          {!game ? (
            <p className="text-ink-muted text-sm">No market data is available for this game.</p>
          ) : (
            <>
              <dl>
                <Row label="Kickoff" value={formatGameDay(game.gameday)} />
                <Row label={`Spread (${game.team ?? 'home'})`} value={formatSpread(game.team_spread)} />
                <Row label="Game total" value={formatPoints(game.total_line)} />
                <Row
                  label={`Implied total (${game.team ?? 'home'})`}
                  value={formatPoints(game.implied_team_total)}
                />
                <Row
                  label={`Implied total (${game.opponent ?? 'away'})`}
                  value={formatPoints(game.implied_opponent_total)}
                />
                {game.spread_source && <Row label="Line source" value={game.spread_source} />}
              </dl>
              {!game.applied_to_projection && <NotAppliedNotice reason={game.unapplied_reason} />}
            </>
          )}
        </section>
      </CardBody>
    </Card>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="border-line flex items-baseline justify-between gap-4 border-b py-1.5 last:border-b-0">
      <dt className="text-ink-secondary text-sm">{label}</dt>
      <dd className="tnum text-ink shrink-0 text-sm font-medium">{value}</dd>
    </div>
  )
}

function AnalysisSkeleton() {
  return (
    <div className="animate-fade-in">
      <Skeleton className="mb-4 h-4 w-24" />
      <Skeleton className="mb-2 h-8 w-56" />
      <Skeleton className="mb-6 h-4 w-40" />
      <div className="grid gap-6 xl:grid-cols-2">
        {Array.from({ length: 4 }, (_, index) => (
          <Card key={index}>
            <CardHeader as="h2" title={<Skeleton className="h-4 w-40" />} />
            <CardBody>
              <SkeletonText lines={6} />
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  )
}
