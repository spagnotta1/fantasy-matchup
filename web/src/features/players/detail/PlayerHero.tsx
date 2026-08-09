import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { StatCard } from '@/components/ui/StatCard'
import { ConfidenceChip } from '@/components/domain/ConfidenceChip'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { ProjectionValue } from '@/components/domain/ProjectionValue'
import { formatPercent, formatPoints, formatScoringProfile } from '@/utils/format'
import type { Player, Projection } from '@/api/schemas'

/**
 * The top of the player page.
 *
 * The projection is the hero number and is the one place in the product that
 * marks itself as uncalibrated inline — here a single number is the subject, so
 * the caveat attaches to it rather than becoming per-row wallpaper.
 *
 * Floor and ceiling are given as percentiles with their meaning spelled out.
 * "Ceiling 31.1" invites reading as a target; "P90 — a 1-in-10 week" does not.
 */
export function PlayerHero({
  player,
  projection,
  scoringProfile,
}: {
  player: Player
  projection: Projection | null | undefined
  scoringProfile: string
}) {
  const points = projection?.prediction.points

  return (
    <div className="mb-6">
      <Link
        to="/players"
        className="text-ink-muted hover:text-ink mb-4 inline-flex items-center gap-1.5 text-xs font-medium transition-colors"
      >
        <ArrowLeft aria-hidden className="size-3.5" />
        All players
      </Link>

      <div className="flex flex-wrap items-start gap-4">
        <PlayerAvatar player={player} size="lg" />

        <div className="min-w-0 flex-1">
          <h1 className="text-ink text-2xl font-semibold tracking-tight">{player.name}</h1>
          <p className="text-ink-secondary mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span>
              {player.position} — {projection?.team ?? player.team ?? 'Free agent'}
            </span>
            {projection?.opponent && (
              <>
                <span aria-hidden className="text-ink-muted">
                  ·
                </span>
                <span>
                  Week {projection.week} {projection.is_home ? 'vs' : 'at'} {projection.opponent}
                </span>
              </>
            )}
            {player.jersey_number !== null && player.jersey_number !== undefined && (
              <>
                <span aria-hidden className="text-ink-muted">
                  ·
                </span>
                <span className="text-ink-muted">#{player.jersey_number}</span>
              </>
            )}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge tone="neutral">{formatScoringProfile(scoringProfile)}</Badge>
            {projection?.matchup && (
              <MatchupGradeChip
                grade={projection.matchup.grade}
                opponent={projection.opponent}
                fpAllowed={projection.matchup.fp_allowed_vs_position_l4}
              />
            )}
            {projection?.context.injury?.is_questionable_or_worse && (
              <Badge tone="caution">
                {projection.context.injury.report_status ?? 'Questionable'}
              </Badge>
            )}
          </div>
        </div>
      </div>

      {points && (
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Projected"
            emphasis="primary"
            badge={<ProvenanceBadge provenance="model" showLabel={false} />}
            value={<ProjectionValue points={points} size="xl" markUncalibrated />}
            unit="pts"
            detail={`Median ${formatPoints(points.median)} · ${formatScoringProfile(scoringProfile)}`}
          />
          <StatCard
            label="Floor"
            value={formatPoints(points.floor)}
            unit="pts"
            detail="P10 — a bad week goes below this one time in ten."
          />
          <StatCard
            label="Ceiling"
            value={formatPoints(points.ceiling)}
            unit="pts"
            detail="P90 — a big week clears this one time in ten."
          />
          <StatCard
            label="Confidence"
            value={<ConfidenceChip label={points.confidence_label} value={points.confidence} size="md" />}
            detail={
              points.confidence !== null && points.confidence !== undefined
                ? `${formatPercent(points.confidence)} — how much the model knew, not how good the player is.`
                : 'How much the model knew, not how good the player is.'
            }
          />
        </div>
      )}
    </div>
  )
}
