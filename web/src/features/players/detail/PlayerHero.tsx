import { useRef } from 'react'
import { Link } from 'react-router-dom'
import { TeamLink } from '@/components/domain/TeamLink'
import { ArrowLeft, Check, GitCompareArrows, UserPlus } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { ConfidenceChip } from '@/components/domain/ConfidenceChip'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { TeamLogo } from '@/components/domain/TeamLogo'
import { Button } from '@/components/ui/Button'
import { useRosterMembership } from '@/hooks/useRoster'
import { teamStyle, useTeamBrand } from '@/hooks/useTeamBrand'
import { cn } from '@/utils/cn'
import { flyTo } from '@/utils/flyTo'
import { formatPercent, formatPoints, formatScoringProfile, formatThreshold } from '@/utils/format'
import type { Player, Projection } from '@/api/schemas'

const OUTLINE_LINK =
  'border-line-input text-ink bg-surface hover:bg-surface-hover inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-control)] border px-3 text-sm font-medium transition-colors'

/**
 * The top of the player page.
 *
 * The projection is the hero number and is the one place in the product that
 * marks itself as uncalibrated inline — here a single number is the subject, so
 * the caveat attaches to it rather than becoming per-row wallpaper.
 *
 * Floor and ceiling are given as percentiles with their meaning spelled out.
 * "Ceiling 31.1" invites reading as a target; "P90 — a 1-in-10 week" does not.
 *
 * Team colour is a wash, a stripe and nothing more: decoration under ink text,
 * never a colour a reader has to decode (see `useTeamBrand`). The jersey number
 * is outline type behind the name, the way a broadcast lower-third carries it,
 * and is hidden from assistive technology because the meta line says it.
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
  const [onRoster, addToRoster] = useRosterMembership(player.player_id)
  // Only the positions My team and Compare accept. A kicker page offering
  // "Add to my team" would add a player the lineup can never start.
  const actionable = ['QB', 'RB', 'WR', 'TE'].includes(player.position ?? '')
  const team = projection?.team ?? player.team
  const brand = useTeamBrand(team)
  const avatarRef = useRef<HTMLSpanElement>(null)
  // The headshot flies to My team and the player is saved as it lands, so the
  // nav's count bumps on arrival. The write does not depend on the flight: a
  // skipped or failed animation resolves at once and saves immediately.
  const add = () => void flyTo(avatarRef.current, '/my-team').then(addToRoster)
  const jersey =
    player.jersey_number !== null && player.jersey_number !== undefined ? String(player.jersey_number) : null

  return (
    <div className="mb-6">
      <Link
        to="/rankings"
        className="text-ink-muted hover:text-ink mb-4 inline-flex items-center gap-1.5 text-xs font-medium transition-colors"
      >
        <ArrowLeft aria-hidden className="size-3.5" />
        All rankings
      </Link>

      <section
        aria-label={`${player.name} this week`}
        className="bg-surface border-line shadow-card animate-rise relative overflow-hidden rounded-[var(--radius-card)] border"
        style={teamStyle(brand)}
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'linear-gradient(115deg, color-mix(in oklch, var(--team, var(--color-accent)) 22%, var(--color-surface)) 0%, var(--color-surface) 60%)',
          }}
        />
        <div aria-hidden className="absolute inset-y-0 left-0 w-1.5 bg-[var(--team,var(--color-accent))]" />
        {jersey && (
          <span
            aria-hidden
            className="tnum pointer-events-none absolute -top-5 right-3 text-[8rem] leading-none font-black tracking-tighter select-none sm:right-8 sm:text-[11rem]"
            style={{
              color: 'transparent',
              // The team colour pulled toward the ink: navy on paper, chalk on
              // turf. A dark brand colour alone vanished on the dark theme.
              WebkitTextStroke:
                '2px color-mix(in oklch, color-mix(in oklch, var(--team, var(--color-ink)) 55%, var(--color-ink)) 35%, transparent)',
            }}
          >
            {jersey}
          </span>
        )}

        <div className="relative p-5 sm:p-6">
          <div className="flex flex-wrap items-center gap-4 sm:gap-5">
            <span ref={avatarRef} className="shrink-0 rounded-full">
              <PlayerAvatar
                player={player}
                size="xl"
                className="ring-surface shadow-raised size-20 ring-4 sm:size-28"
              />
            </span>

            <div className="min-w-0 flex-1">
              <p className="text-ink-secondary flex items-center gap-2 text-sm font-medium">
                <TeamLogo team={team} size="sm" />
                <span>
                  {player.position} · {team ? <TeamLink team={team} /> : 'Free agent'}
                  {jersey && <span className="text-ink-muted"> · #{jersey}</span>}
                </span>
              </p>
              <h1 className="text-ink mt-1 text-3xl leading-tight font-bold tracking-tight sm:text-4xl">
                {player.name}
              </h1>
              {projection?.opponent && (
                <p className="text-ink-secondary mt-1 flex items-center gap-1.5 text-sm">
                  Week {projection.week} {projection.is_home ? 'vs' : 'at'}
                  <TeamLogo team={projection.opponent} size="xs" />
                  <TeamLink team={projection.opponent} />
                </p>
              )}
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

            {actionable && (
              // Always their own row: beside the name on a phone they squeezed it
              // into a one-word column, and at the top right on a desktop they
              // sat on the jersey number. From `sm` the row is indented to line
              // up under the name (avatar 7rem + gap 1.25rem).
              <div className="flex w-full flex-wrap gap-2 sm:pl-[8.25rem]">
                {onRoster ? (
                  <Link to="/my-team" className={OUTLINE_LINK}>
                    <Check aria-hidden className="size-4" />
                    On your team
                  </Link>
                ) : (
                  <Button variant="primary" size="md" onClick={add}>
                    <UserPlus aria-hidden className="size-4" />
                    Add to my team
                  </Button>
                )}
                <Link to={`/compare?players=${player.player_id}`} className={OUTLINE_LINK}>
                  <GitCompareArrows aria-hidden className="size-4" />
                  Compare
                </Link>
              </div>
            )}
          </div>

          {/*
            One scoreboard instead of four stacked cards. On a phone the four
            cards filled the whole first screen and pushed the range — the
            thing this product exists to show — below the fold. The copy in
            each cell is unchanged: it is what makes the number readable.
          */}
          {points && (
            <dl className="border-line bg-surface/85 mt-5 grid grid-cols-2 overflow-hidden rounded-[var(--radius-control)] border backdrop-blur-sm lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
              <div className="border-line col-span-2 border-b p-4 lg:col-span-1 lg:border-r lg:border-b-0">
                <dt className="text-accent-text flex items-center justify-between gap-2 text-xs font-medium tracking-wide uppercase">
                  Projected
                  <ProvenanceBadge provenance="model" showLabel={false} />
                </dt>
                <dd className="mt-2">
                  <span className="text-ink flex items-baseline gap-1.5">
                    <ProjectionValue points={points} size="hero" markUncalibrated />
                    <span className="text-ink-muted text-sm font-medium">pts</span>
                  </span>
                  <span className="text-ink-muted mt-2 block text-xs">
                    Middle outcome {formatPoints(points.median)} · {formatScoringProfile(scoringProfile)}
                  </span>
                  {/* The range, on the same 40-point field as every board, in
                      the first screen on a phone rather than two cards down. */}
                  <OutcomeRange
                    floor={points.floor}
                    p25={points.p25}
                    median={points.median}
                    p75={points.p75}
                    ceiling={points.ceiling}
                    threshold={points.boom_threshold}
                    scaleMax={Math.max(40, points.ceiling ?? 0)}
                    className="mt-3"
                  />
                  <span className="text-ink-secondary mt-1.5 block text-right text-xs font-semibold">
                    {formatPercent(points.boom_probability)} chance of {formatThreshold(points.boom_threshold)}+
                  </span>
                </dd>
              </div>
              <HeroCell
                label="Floor"
                value={formatPoints(points.floor)}
                detail="A bad week. Scores less than this about 1 week in 10."
                className="border-r"
              />
              <HeroCell
                label="Ceiling"
                value={formatPoints(points.ceiling)}
                detail="A strong week. Scores more than this about 1 week in 10."
                className="lg:border-r"
              />
              <div className="border-line col-span-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-t p-4 lg:col-span-1 lg:block lg:border-t-0">
                <dt className="text-ink-muted text-xs font-medium tracking-wide uppercase">Confidence</dt>
                <dd className="lg:mt-2">
                  <ConfidenceChip label={points.confidence_label} value={points.confidence} size="md" />
                </dd>
                <dd className="text-ink-muted w-full text-xs leading-relaxed lg:mt-2">
                  {points.confidence !== null && points.confidence !== undefined
                    ? `${formatPercent(points.confidence)} — how much data backs this, not how good the player is.`
                    : 'How much data backs this, not how good the player is.'}
                </dd>
              </div>
            </dl>
          )}
        </div>
      </section>
    </div>
  )
}

function HeroCell({
  label,
  value,
  detail,
  className,
}: {
  label: string
  value: string
  detail: string
  className?: string
}) {
  return (
    <div className={cn('border-line p-4', className)}>
      <dt className="text-ink-muted text-xs font-medium tracking-wide uppercase">{label}</dt>
      <dd className="mt-2 flex items-baseline gap-1">
        <span className="tnum text-ink text-2xl leading-none font-semibold tracking-tight">{value}</span>
        <span className="text-ink-muted text-xs font-medium">pts</span>
      </dd>
      <dd className="text-ink-muted mt-2 text-xs leading-relaxed">{detail}</dd>
    </div>
  )
}
