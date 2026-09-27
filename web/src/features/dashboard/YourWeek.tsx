import { Link } from 'react-router-dom'
import { ArrowRight, GitCompareArrows, Shuffle, UserRound } from 'lucide-react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/feedback/States'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { ProjectionValue } from '@/components/domain/ProjectionValue'
import { useSlate } from '@/app/slate-context'
import { closestCall, useMyLineup } from '@/hooks/useMyLineup'
import { formatPoints } from '@/utils/format'

const PRIMARY_LINK =
  'bg-accent text-on-accent hover:bg-accent-hover inline-flex h-10 items-center gap-2 rounded-[var(--radius-control)] px-4 text-sm font-medium transition-colors'
const SECONDARY_LINK =
  'border-line-input text-ink hover:bg-surface-hover inline-flex h-10 items-center gap-2 rounded-[var(--radius-control)] border px-4 text-sm font-medium transition-colors'

/**
 * The dashboard's first answer: what this week means for *your* team.
 *
 * Everything else on the dashboard is about the league. A manager opens the
 * app to decide their own lineup, so the first panel is that lineup — its
 * projected total, anyone ruled out or carrying a designation, and the closest
 * start/sit call — with the two next steps one click away: compare the close
 * call, or estimate the matchup.
 *
 * With no roster it is an invitation, not a blank: the roster lives in the
 * browser and in a link, so adding it once makes this panel appear.
 *
 * Nothing here computes a projection. The total adds up published projections
 * for the starters (skill positions only, so it is not a full lineup score);
 * the close call is the smallest gap between two published projections and is
 * offered as a comparison, never as a verdict.
 */
export function YourWeek() {
  const slate = useSlate()
  const my = useMyLineup()

  if (my.ids.length === 0) {
    return (
      <Card>
        <CardBody className="flex flex-wrap items-center gap-4 p-5">
          <span className="bg-accent-soft text-accent-text flex size-10 shrink-0 items-center justify-center rounded-full">
            <UserRound aria-hidden className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-ink text-base font-semibold">Start with your team</h2>
            <p className="text-ink-secondary mt-0.5 text-sm leading-relaxed">
              Add your roster once and this page opens on your week: your best lineup, anyone
              ruled out, your closest start/sit call and your estimated chance of winning. It stays
              in this browser — no account.
            </p>
          </div>
          <Link to="/my-team" className={PRIMARY_LINK}>
            Add your roster
            <ArrowRight aria-hidden className="size-4" />
          </Link>
        </CardBody>
      </Card>
    )
  }

  if (my.board.isPending || my.catalog.isPending) {
    return (
      <Card>
        <CardHeader as="h2" title="Your team" />
        <SkeletonTable rows={4} columns={3} />
      </Card>
    )
  }

  if (my.board.isError) {
    return (
      <Card>
        <CardHeader as="h2" title="Your team" />
        <ErrorState error={my.board.error} onRetry={() => void my.board.refetch()} compact />
      </Card>
    )
  }

  const starters = my.lineup.filter((row) => row.player)
  const flagged = starters
    .map((row) => my.byId.get(row.player?.player_id ?? ''))
    .filter((entry) => entry?.projection.context.injury?.is_questionable_or_worse)
  const call = closestCall(my.lineup, my.bench, my.byId, my.fits)

  return (
    <Card>
      <CardHeader
        as="h2"
        title={`Your lineup for week ${slate.week ?? '—'}`}
        description={
          my.customised
            ? 'The lineup you set on My team.'
            : 'Your highest-projected lineup, filled slot by slot from your roster.'
        }
      />
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="tnum text-ink text-4xl font-bold tracking-tight">{formatPoints(my.total)}</span>
          <span className="text-ink-secondary text-sm">
            projected points from {starters.length} starters. QB, RB, WR and TE only: kickers and
            defences are not projected.
          </span>
        </div>

        {(my.ruledOut.length > 0 || flagged.length > 0 || my.openSlots > 0 || my.unprojected.length > 0) && (
          <ul className="space-y-2" aria-label="Before you lock your lineup">
            {my.ruledOut.map((entry) => (
              <li key={entry.projection.player.player_id} className="flex flex-wrap items-center gap-2 text-sm">
                <InjuryBadge injury={entry.projection.context.injury} />
                <span className="text-ink font-medium">{entry.projection.player.name}</span>
                <span className="text-ink-secondary">is ruled out and kept out of your lineup.</span>
              </li>
            ))}
            {flagged.map((entry) =>
              entry ? (
                <li key={entry.projection.player.player_id} className="flex flex-wrap items-center gap-2 text-sm">
                  <InjuryBadge injury={entry.projection.context.injury} />
                  <span className="text-ink font-medium">{entry.projection.player.name}</span>
                  <span className="text-ink-secondary">
                    starts for you. The projection does not adjust for the designation.
                  </span>
                </li>
              ) : null,
            )}
            {my.openSlots > 0 && (
              <li className="text-caution-text text-sm font-medium">
                {my.openSlots} {my.openSlots === 1 ? 'slot is' : 'slots are'} empty — no eligible,
                available player on your roster.
              </li>
            )}
            {my.unprojected.length > 0 && (
              <li className="text-ink-secondary text-sm">
                {my.unprojected.length} rostered {my.unprojected.length === 1 ? 'player has' : 'players have'} no
                projection this week (a bye, inactive, or not covered).
              </li>
            )}
          </ul>
        )}

        {call && (
          <div className="bg-surface-sunken rounded-[var(--radius-control)] p-3">
            <p className="text-ink-muted text-xs font-medium">Your closest call, at {call.slot}</p>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-2">
              <span className="text-sm">
                <span className="text-ink font-medium">{call.starter.projection.player.name}</span>{' '}
                <ProjectionValue points={call.starter.projection.prediction.points} size="sm" />
                <span className="text-ink-muted"> starting, </span>
                <span className="text-ink font-medium">{call.challenger.projection.player.name}</span>{' '}
                <ProjectionValue points={call.challenger.projection.prediction.points} size="sm" />
                <span className="text-ink-muted"> on your bench</span>
              </span>
              {/* A designation is a caveat on the call itself, so it sits in
                  the call, not in a list further up. */}
              <InjuryBadge injury={call.starter.projection.context.injury} />
              <InjuryBadge injury={call.challenger.projection.context.injury} />
              <Link
                to={`/compare?players=${call.starter.projection.player.player_id},${call.challenger.projection.player.player_id}`}
                className="text-accent-text inline-flex items-center gap-1 text-sm font-medium hover:underline"
              >
                <GitCompareArrows aria-hidden className="size-4" />
                Compare them
              </Link>
            </div>
          </div>
        )}

        <div className="flex flex-wrap gap-2 pt-1">
          <Link to={my.simulateHref} className={PRIMARY_LINK}>
            <Shuffle aria-hidden className="size-4" />
            Estimate my chance of winning
          </Link>
          <Link to="/my-team" className={SECONDARY_LINK}>
            Edit lineup
          </Link>
        </div>
      </CardBody>
    </Card>
  )
}
