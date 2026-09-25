import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, CloudRain, ShieldQuestion } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { Skeleton, SkeletonTable } from '@/components/ui/Skeleton'
import { StatCard } from '@/components/ui/StatCard'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { ConfidenceChip } from '@/components/domain/ConfidenceChip'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { NotAppliedNotice, ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { TeamLink } from '@/components/domain/TeamLink'
import { ScheduleRow } from '@/features/matchups/ScheduleGrid'
import { useDocumentTitle } from '@/app/page-title'
import { useSlate } from '@/app/slate-context'
import { usePositions, useTeams } from '@/hooks/useCatalog'
import { useAllDefenseForm, useScheduleStrength, useTeamOutlook } from '@/hooks/useInsights'
import { useGames } from '@/hooks/useMatchups'
import { useUrlState } from '@/hooks/useUrlState'
import { boardCeiling } from '@/utils/board'
import { formatGameDay, formatPercent, formatPoints, formatSpread } from '@/utils/format'
import type { Game, Team } from '@/api/schemas'

/** `/teams` lists every team; `/teams/:team` is one team's week. One route, one page. */
export default function TeamsPage() {
  const { team } = useParams<{ team: string }>()
  return team ? <TeamDetail team={team.toUpperCase()} /> : <TeamIndex />
}

// ---------------------------------------------------------------------------
// Index
// ---------------------------------------------------------------------------

/**
 * Every team, by division, with this week's opponent.
 *
 * The index is a way in, not an analysis: it answers "where is my team's page"
 * and, at a glance, who everyone plays. The analysis is one click further.
 */
function TeamIndex() {
  const slate = useSlate()
  const teams = useTeams()
  const games = useGames()

  const gameByTeam = useMemo(() => {
    const map = new Map<string, Game>()
    for (const game of games.data?.data ?? []) {
      map.set(game.home_team, game)
      map.set(game.away_team, game)
    }
    return map
  }, [games.data])

  const divisions = useMemo(() => {
    const grouped = new Map<string, Team[]>()
    for (const team of teams.data ?? []) {
      const key = team.division ?? 'Other'
      grouped.set(key, [...(grouped.get(key) ?? []), team])
    }
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [teams.data])

  return (
    <>
      <PageHeader
        title="Teams"
        question={`Who does each team play in week ${slate.week ?? '—'}, and who is projected?`}
      />
      {teams.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, index) => (
            <Skeleton key={index} className="h-48 rounded-[var(--radius-card)]" />
          ))}
        </div>
      ) : teams.isError ? (
        <Card>
          <ErrorState error={teams.error} onRetry={() => void teams.refetch()} />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {divisions.map(([division, members]) => (
            <Card key={division}>
              <CardHeader as="h2" title={division} />
              <ul className="divide-line divide-y">
                {members.map((team) => (
                  <li key={team.abbr}>
                    <TeamTile team={team} game={gameByTeam.get(team.abbr)} />
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
    </>
  )
}

function TeamLogo({ team, size = 'md' }: { team: Pick<Team, 'abbr' | 'logo_url'>; size?: 'md' | 'lg' }) {
  const box = size === 'lg' ? 'size-14' : 'size-8'
  return team.logo_url ? (
    <img src={team.logo_url} alt="" className={`${box} shrink-0 object-contain`} loading="lazy" />
  ) : (
    <span
      aria-hidden
      className={`${box} bg-surface-sunken text-ink-muted flex shrink-0 items-center justify-center rounded-full text-xs font-semibold`}
    >
      {team.abbr}
    </span>
  )
}

function TeamTile({ team, game }: { team: Team; game: Game | undefined }) {
  const isHome = game?.home_team === team.abbr
  const opponent = game ? (isHome ? game.away_team : game.home_team) : null
  return (
    <Link
      to={`/teams/${team.abbr}`}
      className="hover:bg-surface-hover flex items-center gap-3 px-4 py-2.5 transition-colors"
    >
      <TeamLogo team={team} />
      <span className="min-w-0 flex-1">
        <span className="text-ink block truncate text-sm font-medium">{team.name ?? team.abbr}</span>
        <span className="text-ink-muted block text-xs">
          {opponent ? `${isHome ? 'vs' : '@'} ${opponent}` : 'Bye this week'}
        </span>
      </span>
    </Link>
  )
}

// ---------------------------------------------------------------------------
// One team
// ---------------------------------------------------------------------------

const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE']

/**
 * One team's week.
 *
 * Top to bottom: the game and the market (context, not applied), the offence's
 * projected players (model), how the team's *defence* has played each position
 * (derived), and the offence's remaining schedule at a chosen position
 * (derived). The same provenance order as the player page, for the same
 * reason — nearest the model first, so the layout never implies the projection
 * accounts for the spread.
 */
function TeamDetail({ team }: { team: string }) {
  const slate = useSlate()
  const teams = useTeams()
  const outlook = useTeamOutlook(team)
  const branding = teams.data?.find((t) => t.abbr === team)
  const data = outlook.data?.data
  useDocumentTitle(branding?.name ?? team)

  if (outlook.isPending) {
    return (
      <>
        <BackLink />
        <Skeleton className="mb-6 h-16 w-72" />
        <Card>
          <SkeletonTable rows={8} columns={5} />
        </Card>
      </>
    )
  }

  if (outlook.isError) {
    return (
      <>
        <BackLink />
        <Card>
          <ErrorState error={outlook.error} onRetry={() => void outlook.refetch()} />
        </Card>
      </>
    )
  }

  const game = data?.context.game ?? null
  const weather = data?.context.weather ?? null
  const players = [...(data?.players ?? [])].sort(
    (a, b) =>
      POSITION_ORDER.indexOf(a.projection.player.position ?? '') -
        POSITION_ORDER.indexOf(b.projection.player.position ?? '') || a.rank - b.rank,
  )
  const scaleMax = boardCeiling(players)

  return (
    <>
      <BackLink />
      <div className="mb-6 flex items-center gap-4">
        <TeamLogo team={branding ?? { abbr: team, logo_url: null }} size="lg" />
        <div>
          <h1 className="text-ink text-xl font-semibold tracking-tight sm:text-2xl">
            {branding?.name ?? team}
          </h1>
          <p className="text-ink-secondary mt-0.5 text-sm">
            {[branding?.division, `Week ${data?.week ?? slate.week}, ${data?.season ?? slate.season}`]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
      </div>

      {outlook.data && <NoticeList notices={outlook.data.meta.notices} className="mb-6" />}

      <Refreshing active={outlook.isPlaceholderData}>
        <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Opponent"
            value={
              game?.opponent ? (
                <>
                  {game.is_home ? 'vs ' : '@ '}
                  <TeamLink team={game.opponent} />
                </>
              ) : (
                'Bye'
              )
            }
            detail={game?.gameday ? formatGameDay(game.gameday) : 'No game this week'}
          />
          <StatCard
            label="Spread"
            value={game ? `${team} ${formatSpread(game.team_spread)}` : '—'}
            detail="Observed market line — not in the projection."
            badge={<ProvenanceBadge provenance="context" />}
          />
          <StatCard
            label="Implied points"
            value={formatPoints(game?.implied_team_total)}
            detail={`Total ${formatPoints(game?.total_line)} — the market's estimate, not the model's.`}
            badge={<ProvenanceBadge provenance="context" />}
          />
          <StatCard
            label="Projected fantasy points"
            value={formatPoints(data?.projected_points)}
            detail="Sum over projected skill players. Not a team score: no kickers, no defence."
            badge={<ProvenanceBadge provenance="model" />}
          />
        </div>

        {(game || weather) && (
          <Card className="mb-6">
            <CardBody className="flex flex-wrap items-center gap-2 py-3">
              {game?.divisional && <Badge tone="info">Divisional</Badge>}
              {game?.rest_advantage != null && game.rest_advantage !== 0 && (
                <Badge tone="neutral">
                  Rest {game.rest_advantage > 0 ? '+' : ''}
                  {game.rest_advantage} days
                </Badge>
              )}
              {weather && !weather.is_indoor && (
                <Badge tone={weather.is_adverse ? 'caution' : 'neutral'} icon={<CloudRain className="size-3" />}>
                  {formatPoints(weather.temperature_f, 0)}°F · wind {formatPoints(weather.wind_mph, 0)} mph
                  {weather.precipitation_probability != null
                    ? ` · ${formatPercent(weather.precipitation_probability / 100)} precip`
                    : ''}
                </Badge>
              )}
              {weather?.is_indoor && <Badge tone="neutral">Indoors</Badge>}
              <div className="w-full">
                <NotAppliedNotice reason={game?.unapplied_reason ?? weather?.unapplied_reason} />
              </div>
            </CardBody>
          </Card>
        )}

        <div className="grid gap-6 xl:grid-cols-[1fr_22rem]">
          <Card className="min-w-0 overflow-hidden">
            <CardHeader
              as="h2"
              title="Projected players"
              description="This week's published projections for the offence, by position."
              action={<ProvenanceBadge provenance="model" />}
            />
            {players.length === 0 ? (
              <EmptyState
                title="No projected players"
                description="The published run holds no projections for this team this week — a bye, or a week not yet run."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <caption className="sr-only">{team} projected players for the week</caption>
                  <thead>
                    <tr className="border-line text-ink-muted border-b text-xs font-medium tracking-wide uppercase">
                      <th scope="col" className="px-3 py-2 text-left">Player</th>
                      <th scope="col" className="px-3 py-2 text-left">Matchup</th>
                      <th scope="col" className="hidden w-48 px-3 py-2 text-left lg:table-cell">Range</th>
                      <th scope="col" className="hidden px-3 py-2 text-left md:table-cell">Confidence</th>
                      <th scope="col" className="px-3 py-2 text-right">Projection</th>
                    </tr>
                  </thead>
                  <tbody>
                    {players.map((entry) => {
                      const { projection } = entry
                      const { points } = projection.prediction
                      return (
                        <tr key={projection.player.player_id} className="border-line border-b last:border-b-0">
                          <td className="px-3 py-2">
                            <PlayerIdentity
                              player={projection.player}
                              team={projection.team}
                              size="sm"
                              subtitle={
                                <span className="inline-flex items-center gap-1.5">
                                  {projection.player.position}
                                  <InjuryBadge injury={projection.context.injury} />
                                </span>
                              }
                            />
                          </td>
                          <td className="px-3 py-2">
                            <MatchupGradeChip
                              grade={projection.matchup?.grade}
                              opponent={projection.opponent}
                              fpAllowed={projection.matchup?.fp_allowed_vs_position_l4}
                            />
                          </td>
                          <td className="hidden px-3 py-2 lg:table-cell">
                            <OutcomeRange
                              floor={points.floor}
                              median={points.median}
                              ceiling={points.ceiling}
                              scaleMax={scaleMax}
                            />
                          </td>
                          <td className="hidden px-3 py-2 md:table-cell">
                            <ConfidenceChip label={points.confidence_label} value={points.confidence} />
                          </td>
                          <td className="px-3 py-2 text-right">
                            <ProjectionValue points={points} actualPoints={projection.actual_points} />
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <DefenseCard team={team} />
        </div>

        <TeamSchedule team={team} />
      </Refreshing>
    </>
  )
}

function BackLink() {
  return (
    <Link
      to="/teams"
      className="text-ink-muted hover:text-ink mb-4 inline-flex items-center gap-1.5 rounded-sm text-sm"
    >
      <ArrowLeft aria-hidden className="size-3.5" />
      All teams
    </Link>
  )
}

/** How this team's defence has played each position — what opponents face. */
function DefenseCard({ team }: { team: string }) {
  const defense = useAllDefenseForm()
  const rows = defense.data?.data[team] ?? []

  return (
    <Card className="h-fit">
      <CardHeader
        as="h2"
        title="Defence by position"
        description="What this defence has allowed over its last four completed games. Rank 1 is the toughest."
        action={<ProvenanceBadge provenance="derived" />}
      />
      {defense.isPending ? (
        <CardBody>
          <Skeleton className="h-32" />
        </CardBody>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<ShieldQuestion aria-hidden className="size-5" />}
          title="No defensive history yet"
          description="There are no completed games before this week to rank the defence on."
        />
      ) : (
        <ul className="divide-line divide-y">
          {rows.map((row) => (
            <li key={row.position} className="flex items-center gap-3 px-4 py-2.5">
              <span className="text-ink w-8 text-sm font-semibold">{row.position}</span>
              <span className="text-ink-secondary flex-1 text-xs">
                {formatPoints(row.fp_allowed_l4)} pts/game allowed
                {row.grade.defense_rank ? ` · rank ${row.grade.defense_rank} of 32` : ''}
              </span>
              <MatchupGradeChip grade={row.grade} opponent={team} fpAllowed={row.fp_allowed_l4} align="end" />
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/** The offence's remaining schedule at one position — the Matchups grid, one row of it. */
function TeamSchedule({ team }: { team: string }) {
  const positions = usePositions()
  const projected = (positions.data ?? []).filter((p) => p.projected)
  const [state, setState] = useUrlState({ sospos: 'WR' })
  const strength = useScheduleStrength(state.sospos)
  const row = strength.data?.data.teams.find((t) => t.team === team)

  return (
    <Card className="mt-6 overflow-hidden">
      <CardHeader
        as="h2"
        title="Remaining schedule"
        description="Each remaining opponent's current form against this position. Current form carried forward, not a forecast."
        action={
          projected.length > 0 && (
            <SegmentedControl
              label="Position"
              size="sm"
              value={state.sospos}
              onChange={(value) => setState({ sospos: value })}
              options={projected.map((p) => ({ value: p.position, label: p.position }))}
            />
          )
        }
      />
      {strength.isPending ? (
        <CardBody>
          <Skeleton className="h-16" />
        </CardBody>
      ) : strength.isError ? (
        <ErrorState error={strength.error} onRetry={() => void strength.refetch()} compact />
      ) : !row ? (
        <EmptyState title="No remaining games" description="The regular season has no weeks left from here." />
      ) : (
        <Refreshing active={strength.isPlaceholderData}>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <caption className="sr-only">
                {team} remaining schedule against {state.sospos}
              </caption>
              <thead>
                <tr className="border-line text-ink-muted border-b font-medium tracking-wide uppercase">
                  <th scope="col" className="bg-surface sticky left-0 z-10 px-3 py-2 text-left">Team</th>
                  <th scope="col" className="px-2 py-2 text-center">Rest</th>
                  <th scope="col" className="hidden px-2 py-2 text-center sm:table-cell">Next 4</th>
                  <th scope="col" className="hidden px-2 py-2 text-center sm:table-cell">Wk 15–17</th>
                  {strength.data?.data.weeks.map((week) => (
                    <th key={week} scope="col" className="px-1 py-2 text-center">
                      {week}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <ScheduleRow team={row} />
              </tbody>
            </table>
          </div>
          <CardBody className="border-line text-ink-muted border-t py-3 text-xs">
            <Link to={`/matchups?view=schedule&position=${state.sospos}`} className="text-accent-text hover:underline">
              Compare every team's schedule
            </Link>
          </CardBody>
        </Refreshing>
      )}
    </Card>
  )
}
