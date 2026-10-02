import { useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Skeleton, SkeletonText } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { ContextPanel, MatchupPanel, UsagePanel } from '@/features/players/detail/ContextPanels'
import { GameLog } from '@/features/players/detail/GameLog'
import {
  DEFAULT_HISTORY,
  FULL_HISTORY,
  describeWindow,
  gamesIn,
  scoredGames,
  selectableSeasons,
  type GameWindow,
} from '@/features/players/detail/gameWindow'
import {
  BAR_LINKS_FROM,
  BAR_ROOMY_FROM,
  PlayerBar,
  SectionLinks,
  type PageSection,
} from '@/features/players/detail/PlayerBar'
import { PlayerHero } from '@/features/players/detail/PlayerHero'
import { ProjectionPanel } from '@/features/players/detail/ProjectionPanel'
import { UsageTrends } from '@/features/players/detail/UsageTrends'
import { useDocumentTitle } from '@/app/page-title'
import { useElementSize } from '@/hooks/useElementSize'
import { usePlayerProfile } from '@/hooks/useProjections'
import { useRosterMembership } from '@/hooks/useRoster'
import { cn } from '@/utils/cn'
import type { PlayerProfile } from '@/api/schemas'

/**
 * Everything known about one player for one week.
 *
 * A single `/players/{id}/profile` call backs the whole page, which is why it
 * loads as one unit rather than six panels racing each other.
 *
 * The page reads top to bottom as one story, provenance nearest the model
 * first: the projection itself, then the game log that shows how this
 * player's projections have actually tracked (the same boom/bust thresholds
 * as the panel above it, so the chart sits next to the number it explains
 * instead of at the bottom of the page); then usage, the model's own inputs
 * restated for a reader; then matchup and context, both derived *above* the
 * model or merely observed, and correspondingly last. A layout that
 * interleaved those would quietly imply the projection accounts for the wind.
 *
 * ## Moving around it
 *
 * A bar stays under the application bar for the whole scroll (`PlayerBar`):
 * the week stepper, the links to each section, and, once the header has
 * scrolled away, who this is and what they are projected for. Stepping a week
 * keeps the page where it is and dims it until the new week arrives, so a
 * reader looking at the matchup sees last week's matchup, not the top of a
 * new page.
 */
export default function PlayerDetailPage() {
  const { playerId } = useParams<{ playerId: string }>()
  // Earlier seasons are loaded on request (see `usePlayerProfile`), and for
  // the player they were asked for: the next player opens with the default.
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  const historyWeeks = loadedFor !== null && loadedFor === playerId ? FULL_HISTORY : DEFAULT_HISTORY
  // The default is the API's own, so it is not sent: the page's first request
  // is the one it has always made.
  const { data, isPending, isError, error, refetch, isPlaceholderData } = usePlayerProfile(
    playerId,
    historyWeeks === DEFAULT_HISTORY ? undefined : historyWeeks,
  )

  // This page's heading is the player's own name — `PlayerHero` draws it, so
  // the title is set here instead. Before the profile resolves there is no name
  // to use, and the hook leaves the previous title alone rather than flashing
  // the bare product name between two real ones.
  useDocumentTitle(data?.data.player.name)

  if (isPending) return <ProfileSkeleton />

  if (isError) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refetch()} />
      </Card>
    )
  }

  return (
    <Profile
      // A different player starts again: their own game window, their own roster state.
      key={data.data.player.player_id}
      profile={data.data}
      notices={data.meta.notices}
      refreshing={isPlaceholderData}
      historyWeeks={historyWeeks}
      onLoadEarlier={() => setLoadedFor(playerId ?? null)}
    />
  )
}

/**
 * What every anchor on the page stops under: the application bar, the player
 * bar (its measured height, which is two lines where it wraps) and a little air.
 */
const UNDER_BARS = 'scroll-mt-[calc(var(--spacing-shell-bar)+var(--player-bar,3rem)+0.75rem)]'

/**
 * A part of the page a section link jumps to. Focusable from script only, so
 * the link can hand focus to it and the next Tab carries on from here.
 */
function Section({ id, className, children }: { id: string; className?: string; children: ReactNode }) {
  return (
    <div id={id} tabIndex={-1} className={cn(UNDER_BARS, 'rounded-card outline-none', className)}>
      {children}
    </div>
  )
}

function Profile({
  profile,
  notices,
  refreshing,
  historyWeeks,
  onLoadEarlier,
}: {
  profile: PlayerProfile
  notices: string[]
  /** A new week, scoring format or history is on its way; what is drawn is the previous one. */
  refreshing: boolean
  historyWeeks: number
  onLoadEarlier: () => void
}) {
  const current = profile.current
  const { player } = profile

  const [onRosterNow, addToRoster] = useRosterMembership(player.player_id)
  // Only the positions My team and Compare accept. A kicker page offering
  // "Add to my team" would add a player the lineup can never start.
  const actionable = ['QB', 'RB', 'WR', 'TE'].includes(player.position ?? '')
  const onRoster = actionable ? onRosterNow : null

  const heroRef = useRef<HTMLElement>(null)
  const [barRef, bar] = useElementSize<HTMLDivElement>()
  const withLinks = bar.width >= BAR_LINKS_FROM

  // Which games the log and the usage trend draw. Theirs jointly, so the two
  // read column for column.
  const [gameWindow, setGameWindow] = useState<GameWindow>('recent')
  const allGames = useMemo(() => scoredGames(profile.history), [profile.history])
  // What is drawn while earlier seasons load is still the short history.
  const loadingEarlier = refreshing && historyWeeks > DEFAULT_HISTORY
  // As many rows as were asked for means there may be older ones.
  const truncated = loadingEarlier || profile.history.length >= historyWeeks
  const seasons = useMemo(() => selectableSeasons(allGames, truncated), [allGames, truncated])
  // A season that is no longer on offer falls back to the recent games.
  const activeWindow: GameWindow = gameWindow === 'recent' || seasons.includes(gameWindow) ? gameWindow : 'recent'
  const games = useMemo(() => gamesIn(allGames, activeWindow), [allGames, activeWindow])
  const windowInWords = describeWindow(games, activeWindow)
  const endsAtLatest = games.length > 0 && games.at(-1) === allGames.at(-1)

  const gameLog = (
    <GameLog
      games={games}
      window={activeWindow}
      seasons={seasons}
      onWindowChange={setGameWindow}
      trend={profile.trend}
      boomThreshold={current?.prediction.points.boom_threshold ?? null}
      bustThreshold={current?.prediction.points.bust_threshold ?? null}
      current={current ? { season: current.season, week: current.week } : null}
      loaded={allGames.length}
      canLoadEarlier={loadingEarlier || (truncated && historyWeeks < FULL_HISTORY)}
      onLoadEarlier={onLoadEarlier}
      loadingEarlier={loadingEarlier}
    />
  )
  const usageTrend = <UsageTrends games={games} window={windowInWords} endsAtLatest={endsAtLatest} />

  const sections: PageSection[] = current
    ? [
        { id: 'this-week', label: 'This week' },
        { id: 'game-log', label: 'Game log' },
        { id: 'usage', label: 'Usage' },
        { id: 'matchup', label: 'Matchup' },
        { id: 'context', label: 'Context' },
      ]
    : [
        { id: 'game-log', label: 'Game log' },
        { id: 'usage', label: 'Usage' },
      ]

  return (
    <div style={{ '--player-bar': `${bar.height}px` } as CSSProperties}>
      {/* Dimmed with the rest of the page while a new week loads; the one
          "Updating" notice is the page's, below. */}
      <div className={cn('transition-opacity duration-200', refreshing && 'opacity-45')} inert={refreshing || undefined}>
        <PlayerHero
          ref={heroRef}
          player={player}
          projection={current}
          scoringProfile={profile.scoring_profile}
          onRoster={onRoster}
          onAdd={addToRoster}
        />
      </div>

      {/* Outside the dimmed page: the stepper is what caused the refresh, and
          has to keep the keyboard's focus through it. */}
      <PlayerBar
        ref={barRef}
        player={player}
        projection={current}
        sections={sections}
        heroRef={heroRef}
        withLinks={withLinks}
        roomy={bar.width >= BAR_ROOMY_FROM}
        onRoster={onRoster}
        onAdd={addToRoster}
      />
      {/* One line on a phone: the links go under the bar and scroll away. */}
      {!withLinks && bar.width > 0 && <SectionLinks sections={sections} className="mb-4" />}

      <Refreshing active={refreshing}>
        <NoticeList notices={notices} className="mb-6" />

        {current ? (
          <div className="space-y-6">
            <Section id="this-week">
              <ProjectionPanel points={current.prediction.points} components={current.prediction.components} />
            </Section>

            <Section id="game-log">{gameLog}</Section>

            <Section id="usage">{usageTrend}</Section>

            <div className="grid gap-6 xl:grid-cols-2">
              <UsagePanel usage={current.usage} />
              <Section id="matchup">
                <MatchupPanel matchup={current.matchup} opponent={current.opponent} isHome={current.is_home} />
              </Section>
            </div>

            <Section id="context">
              <ContextPanel context={current.context} />
            </Section>
          </div>
        ) : (
          <div className="space-y-6">
            <Card>
              <EmptyState
                title="No projection for this week"
                description="This player has no projection for the selected week — usually a bye week or an inactive listing. Their past games are below."
              />
            </Card>
            <Section id="game-log">{gameLog}</Section>
            <Section id="usage">{usageTrend}</Section>
          </div>
        )}
      </Refreshing>
    </div>
  )
}

/** Mirrors the real layout, so nothing jumps when the data lands. */
function ProfileSkeleton() {
  return (
    <div className="animate-fade-in">
      <div className="mb-6 flex items-start gap-4">
        <Skeleton className="size-16 rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-4 w-40" />
        </div>
      </div>
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-28 rounded-[var(--radius-card)]" />
        ))}
      </div>
      <div className="space-y-6">
        <Card>
          <CardHeader as="h2" title={<Skeleton className="h-4 w-28" />} />
          <CardBody>
            <SkeletonText lines={6} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader as="h2" title={<Skeleton className="h-4 w-28" />} />
          <CardBody>
            <Skeleton className="h-40 rounded-[var(--radius-card)]" />
          </CardBody>
        </Card>
        <div className="grid gap-6 xl:grid-cols-2">
          {Array.from({ length: 2 }, (_, index) => (
            <Card key={index}>
              <CardHeader as="h2" title={<Skeleton className="h-4 w-28" />} />
              <CardBody>
                <SkeletonText lines={6} />
              </CardBody>
            </Card>
          ))}
        </div>
        <Card>
          <CardHeader as="h2" title={<Skeleton className="h-4 w-28" />} />
          <CardBody>
            <SkeletonText lines={6} />
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
