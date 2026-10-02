import { useRef, type Ref } from 'react'
import { Link } from 'react-router-dom'
import { TeamLink } from '@/components/domain/TeamLink'
import { ArrowLeft, Check, GitCompareArrows, UserPlus } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { EvidenceChip } from '@/components/domain/EvidenceChip'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { TeamLogo } from '@/components/domain/TeamLogo'
import { Button, ButtonLink } from '@/components/ui/Button'
import { teamStyle, useTeamBrand } from '@/hooks/useTeamBrand'
import { cn } from '@/utils/cn'
import { flyTo } from '@/utils/flyTo'
import { formatPercent, formatPoints, formatScoringProfile, formatThreshold } from '@/utils/format'
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
 *
 * Team colour is a wash, a stripe and nothing more: decoration under ink text,
 * never a colour a reader has to decode (see `useTeamBrand`). The jersey number
 * is outline type behind the name, the way a broadcast lower-third carries it,
 * and is hidden from assistive technology because the meta line says it.
 *
 * With room for it (64rem of its own width, measured as a container) the name
 * and the scoreboard sit side by side, which is what brings the game log onto
 * the first screen of a laptop, and the jersey number is left to the meta
 * line. Narrower, the scoreboard goes under the name.
 */
export function PlayerHero({
  player,
  projection,
  scoringProfile,
  onRoster,
  onAdd,
  ref,
}: {
  player: Player
  projection: Projection | null | undefined
  scoringProfile: string
  /**
   * Whether the player is on the remembered roster. Null for a position My
   * team and Compare do not accept: a kicker page offering "Add to my team"
   * would add a player the lineup can never start.
   */
  onRoster: boolean | null
  onAdd: () => void
  ref?: Ref<HTMLElement>
}) {
  const points = projection?.prediction.points
  const actionable = onRoster !== null
  const team = projection?.team ?? player.team
  const brand = useTeamBrand(team)
  const avatarRef = useRef<HTMLSpanElement>(null)
  // The headshot flies to My team and the player is saved as it lands, so the
  // nav's count bumps on arrival. The write does not depend on the flight: a
  // skipped or failed animation resolves at once and saves immediately.
  const add = () => void flyTo(avatarRef.current, '/my-team').then(onAdd)
  const jersey =
    player.jersey_number !== null && player.jersey_number !== undefined ? String(player.jersey_number) : null

  return (
    <div className="mb-4">
      <Link
        to="/rankings"
        className="text-ink-muted hover:text-ink mb-3 inline-flex items-center gap-1.5 text-detail font-medium transition-colors"
      >
        <ArrowLeft aria-hidden className="size-3.5" />
        All rankings
      </Link>

      <section
        ref={ref}
        aria-label={`${player.name} this week`}
        className="bg-surface border-line shadow-raised animate-rise @container relative overflow-hidden rounded-[var(--radius-card)] border"
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
            // Not drawn side by side: the scoreboard has the right-hand side
            // then, and behind the name it only made the name harder to read.
            className="tnum pointer-events-none absolute -top-5 right-3 text-[8rem] leading-none font-black tracking-tighter select-none sm:right-8 sm:text-[11rem] @5xl:hidden"
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

        <div className="relative p-4 sm:p-5 @5xl:grid @5xl:grid-cols-[minmax(0,24rem)_minmax(0,1fr)] @5xl:items-center @5xl:gap-6">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3 sm:gap-x-5">
            <span ref={avatarRef} className="shrink-0 rounded-full">
              <PlayerAvatar
                player={player}
                size="xl"
                className="ring-surface shadow-raised size-20 ring-4 sm:size-24"
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
              // up under the name (avatar 6rem + gap 1.25rem).
              <div className="flex w-full flex-wrap gap-2 sm:pl-[7.25rem]">
                {onRoster ? (
                  <ButtonLink to="/my-team" size="sm" icon={<Check aria-hidden />}>
                    On your team
                  </ButtonLink>
                ) : (
                  <Button variant="primary" size="sm" icon={<UserPlus aria-hidden />} onClick={add}>
                    Add to my team
                  </Button>
                )}
                <ButtonLink
                  to={`/compare?players=${player.player_id}`}
                  size="sm"
                  icon={<GitCompareArrows aria-hidden />}
                >
                  Compare
                </ButtonLink>
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
            <dl className="border-line bg-surface/85 mt-4 grid grid-cols-2 overflow-hidden rounded-[var(--radius-control)] border backdrop-blur-sm @3xl:grid-cols-[1.4fr_1fr_1fr_1fr] @5xl:mt-0">
              <div className="border-line col-span-2 border-b p-4 @3xl:col-span-1 @3xl:border-r @3xl:border-b-0">
                <dt className="text-accent-text flex items-center justify-between gap-2 text-caption font-medium tracking-wide uppercase">
                  Projected
                  <ProvenanceBadge provenance="model" showLabel={false} />
                </dt>
                <dd className="mt-2">
                  <span className="text-ink flex items-baseline gap-1.5">
                    <ProjectionValue points={points} size="hero" markUncalibrated />
                    <span className="text-ink-muted text-sm font-medium">pts</span>
                  </span>
                  <span className="text-ink-muted mt-2 block text-detail">
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
                  <span className="text-ink-secondary mt-1.5 block text-right text-detail font-semibold">
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
                className="@3xl:border-r"
              />
              <div className="border-line col-span-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-t p-4 @3xl:col-span-1 @3xl:block @3xl:border-t-0">
                <dt className="text-ink-muted text-caption font-medium tracking-wide uppercase">Range based on</dt>
                <dd className="@3xl:mt-2">
                  <EvidenceChip
                    evidence={points.evidence}
                    note={points.evidence_note}
                    samples={points.samples}
                    size="md"
                  />
                </dd>
                {/* The caveat is the API's sentence, which quotes what was
                    measured. With none, the tile says what the range is. */}
                <dd className="text-ink-muted w-full text-detail leading-relaxed @3xl:mt-2">
                  {points.evidence_note ?? evidenceDetail(points.evidence, player.position)}
                </dd>
              </div>
            </dl>
          )}
        </div>
      </section>
    </div>
  )
}

/** What an uncaveated range is, in a sentence. Never a rating of the player. */
function evidenceDetail(evidence: string, position: string | null | undefined): string {
  if (evidence !== 'established') return 'No floor or ceiling is stored for this projection.'
  const who = position ? `${position}s` : 'players'
  return `How past ${who} with a similar projection actually scored. It sizes the range, not the player.`
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
      <dt className="text-ink-muted text-caption font-medium tracking-wide uppercase">{label}</dt>
      <dd className="mt-2 flex items-baseline gap-1">
        <span className="tnum text-ink text-2xl leading-none font-semibold tracking-tight">{value}</span>
        <span className="text-ink-muted text-detail font-medium">pts</span>
      </dd>
      <dd className="text-ink-muted mt-2 text-detail leading-relaxed">{detail}</dd>
    </div>
  )
}
