import { memo, useCallback, useDeferredValue, useEffect, useMemo, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Radio, Search, X } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardHeader } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { PageHeader } from '@/components/ui/PageHeader'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { Skeleton, SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { ShowMoreRows } from '@/components/domain/BoardBudget'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { OutcomeRange } from '@/components/domain/ProjectionValue'
import { MatchupColorBar, ScoreBugTeam } from '@/components/domain/ScoreBug'
import { useSlate } from '@/app/slate-context'
import { LIVE_REFRESH_MS, useLive } from '@/hooks/useInsights'
import { useRenderBudget } from '@/hooks/useRenderBudget'
import { replayAnimation, useCountUp } from '@/hooks/useCountUp'
import { useRememberedRoster } from '@/hooks/useRoster'
import { useUrlDraft } from '@/hooks/useUrlDraft'
import { useUrlState } from '@/hooks/useUrlState'
import { cn } from '@/utils/cn'
import { formatPoints, formatSigned } from '@/utils/format'
import type { LiveGame, LivePlayer } from '@/api/schemas'

const DEFAULT_STATE = { position: '', who: 'all', query: '', game: '' }

/** Case-insensitive substring match on name or team, as on the boards. */
function matchesSearch(player: LivePlayer, query: string): boolean {
  const term = query.trim().toLocaleLowerCase()
  if (!term) return true
  return (
    player.name.toLocaleLowerCase().includes(term) || player.team.toLocaleLowerCase().includes(term)
  )
}

/** A signed count, with a real minus sign for negative yardage. */
const n = (value: number | undefined) => {
  const v = value ?? 0
  return v < 0 ? `−${Math.abs(v)}` : String(v)
}

/** A compact, labelled stat line: "16 car, 52 yds · 6/8 rec, 61 yds, 1 TD". */
function statLine(c: Record<string, number>): string {
  const parts: string[] = []
  const td = (count: number | undefined) => (count ? `, ${count} TD` : '')
  if (c.passing_yards || c.passing_tds || c.passing_interceptions) {
    parts.push(`${n(c.passing_yards)} pass yds${td(c.passing_tds)}${c.passing_interceptions ? `, ${c.passing_interceptions} INT` : ''}`)
  }
  if (c.carries) parts.push(`${c.carries} car, ${n(c.rushing_yards)} yds${td(c.rushing_tds)}`)
  if (c.targets || c.receptions) {
    parts.push(`${c.receptions ?? 0}/${c.targets ?? 0} rec, ${n(c.receiving_yards)} yds${td(c.receiving_tds)}`)
  }
  if (c.special_teams_tds) parts.push(`${c.special_teams_tds} return TD`)
  if (c.fumbles_lost_total) parts.push(`${c.fumbles_lost_total} fum lost`)
  return parts.join(' · ') || 'No offensive stats yet'
}

/**
 * The week as it happens.
 *
 * Every started player's points so far, from ESPN's in-game box score scored
 * with this product's rules, beside the projection published before kickoff.
 * The two are kept apart on purpose: the projection is never updated by the
 * live number, and the difference between them is shown only once a game is
 * final — mid-game, "behind his projection" mostly measures how much of the
 * game is left.
 *
 * Unofficial, and labelled so: two-point conversions and stat corrections are
 * missing until the official line is loaded. Refreshes once a minute while a
 * game is in progress, and not at all otherwise.
 */
export default function LivePage() {
  const slate = useSlate()
  const live = useLive()
  const roster = useRememberedRoster()
  const [state, setState] = useUrlState(DEFAULT_STATE)
  const data = live.data?.data

  // The field owns its text and the URL catches up when typing pauses — see
  // `useUrlDraft` for why binding the input to the URL dropped keystrokes.
  const setQuery = useCallback((value: string) => setState({ query: value }), [setState])
  const [search, setSearch] = useUrlDraft(state.query, setQuery)
  const deferredSearch = useDeferredValue(search)

  const games = useMemo(() => new Map((data?.games ?? []).map((g) => [g.event_id, g])), [data])
  // A game from another week's link matches nothing here, so it is ignored
  // rather than leaving an empty table behind a filter nobody can see.
  const selectedGame = state.game ? games.get(state.game) : undefined
  const players = useMemo(
    () =>
      (data?.players ?? []).filter(
        (p) =>
          (!state.position || p.position === state.position) &&
          (state.who !== 'mine' || roster.has(p.player_id)) &&
          (!selectedGame || p.event_id === selectedGame.event_id) &&
          matchesSearch(p, deferredSearch),
      ),
    [data, state.position, state.who, roster, selectedGame, deferredSearch],
  )
  const filtered = Boolean(state.position || state.who !== 'all' || selectedGame || search.trim())
  const clearFilters = () => {
    setSearch('', { immediate: true })
    setState({ position: '', who: 'all', query: '', game: '' })
  }
  const inProgress = (data?.games ?? []).some((g) => g.state === 'in')
  // A full Sunday is ~300 players; draw the top of it and reveal the rest on
  // request, like the boards (see `useRenderBudget`).
  const budget = useRenderBudget(players.length)
  const visible = players.slice(0, budget.shown)
  // One scale for every strip on the page, as on the boards, so a ball
  // further right is more points — and wide enough that a 34-point day is
  // drawn where it happened rather than pinned to the end of a 40.
  const fieldMax = useMemo(
    () => Math.max(40, ...(data?.players ?? []).flatMap((p) => [p.live_points, p.ceiling ?? 0])),
    [data],
  )

  return (
    <>
      <PageHeader
        title="Live"
        question={`How is week ${slate.week ?? '—'} going, against what was projected?`}
        action={
          inProgress ? (
            <Badge tone="negative" icon={<Radio className="size-3" />}>
              Live · updates every {LIVE_REFRESH_MS / 1000}s
            </Badge>
          ) : undefined
        }
      />

      {live.data && <NoticeList notices={live.data.meta.notices} className="mb-4" />}

      {live.isPending ? (
        <div className="space-y-6">
          <Skeleton className="h-24 rounded-[var(--radius-card)]" />
          <Card>
            <SkeletonTable rows={10} columns={4} />
          </Card>
        </div>
      ) : live.isError ? (
        <Card>
          <ErrorState error={live.error} onRetry={() => void live.refetch()} />
        </Card>
      ) : (
        <Refreshing active={live.isPlaceholderData}>
          {/*
            A scoreboard ticker, the way a broadcast runs one: games in
            progress first, then the ones still to kick off, then the finals.
            One row that scrolls sideways rather than a grid four rows deep,
            so the points table — the reason for the page — starts on the
            first screen.
          */}
          <ul
            aria-label="Games this week"
            // `pt-1` and the ring-width side padding keep a selected tile's ring
            // inside the scroller, which clips on both axes; `scroll-px-4`
            // snaps a tile to the gutter rather than to the screen edge.
            className="-mx-4 mb-6 flex snap-x scroll-px-4 gap-2 overflow-x-auto px-4 pt-1 pb-2 sm:mx-0 sm:scroll-px-1 sm:px-1"
          >
            {tickerOrder(data?.games ?? []).map((game) => (
              <li key={game.event_id} className="w-40 shrink-0 snap-start">
                <GameTile
                  game={game}
                  selected={selectedGame?.event_id === game.event_id}
                  onSelect={() =>
                    setState({ game: selectedGame?.event_id === game.event_id ? '' : game.event_id })
                  }
                />
              </li>
            ))}
          </ul>

          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Input
              label="Search players"
              hideLabel
              placeholder="Search by name or team…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              icon={<Search className="size-4" />}
              className="min-w-0 flex-1 basis-56 sm:max-w-72"
              type="search"
              trailing={
                search ? (
                  <button
                    type="button"
                    onClick={() => setSearch('', { immediate: true })}
                    aria-label="Clear search"
                    className="text-ink-muted hover:text-ink flex size-6 items-center justify-center rounded-md"
                  >
                    <X aria-hidden className="size-3.5" />
                  </button>
                ) : undefined
              }
            />
            <SegmentedControl
              label="Position"
              value={state.position}
              onChange={(value) => setState({ position: value })}
              options={[{ value: '', label: 'All' }, ...['QB', 'RB', 'WR', 'TE'].map((p) => ({ value: p, label: p }))]}
            />
            <SegmentedControl
              label="Players"
              value={state.who}
              onChange={(value) => setState({ who: value })}
              options={[
                { value: 'all', label: 'Everyone' },
                { value: 'mine', label: `My team${roster.size ? ` (${roster.size})` : ''}` },
              ]}
            />
            {state.who === 'mine' && roster.size === 0 && (
              <Link to="/my-team" className="text-accent-text text-xs hover:underline">
                Add your roster first
              </Link>
            )}
            {selectedGame && (
              <Badge tone="accent" className="gap-1 py-0.5 pr-0.5">
                {selectedGame.away} @ {selectedGame.home}
                <button
                  type="button"
                  onClick={() => setState({ game: '' })}
                  aria-label={`Show every game, not just ${selectedGame.away} at ${selectedGame.home}`}
                  className="hover:bg-surface-hover flex size-5 items-center justify-center rounded-full"
                >
                  <X aria-hidden className="size-3" />
                </button>
              </Badge>
            )}
          </div>

          <Card className="overflow-hidden">
            <CardHeader
              as="h2"
              title="Points so far"
              description="Unofficial points scored so far, highest first, next to each player's projection."
              action={
                <span className="flex items-center gap-1.5">
                  <ProvenanceBadge provenance="actual" />
                  <ProvenanceBadge provenance="model" />
                </span>
              }
            />
            {players.length === 0 ? (
              <EmptyState
                icon={<Radio aria-hidden className="size-5" />}
                eyebrow={data?.games.length && !filtered ? 'Pre-game warmups' : undefined}
                title={
                  !data?.games.length
                    ? 'No games found for this week'
                    : selectedGame?.state === 'pre'
                      ? `${selectedGame.away} @ ${selectedGame.home} has not kicked off`
                      : filtered
                        ? 'No players match'
                        : 'No points yet'
                }
                description={
                  !data?.games.length
                    ? 'We could not find any games for the selected week.'
                    : selectedGame?.state === 'pre'
                      ? 'Points appear here once the game starts.'
                      : filtered
                        ? 'Nobody who has played this week matches these filters.'
                        : 'Points appear once games kick off.'
                }
                action={
                  filtered ? (
                    <Button size="sm" variant="secondary" onClick={clearFilters}>
                      Clear filters
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <caption className="sr-only">Unofficial live fantasy points with published projections</caption>
                  <thead>
                    <tr className="border-line text-ink-muted border-b text-xs font-medium tracking-wide uppercase">
                      <th scope="col" className="px-3 py-2 text-left">Player</th>
                      <th scope="col" className="hidden px-3 py-2 text-left lg:table-cell">Stat line</th>
                      <th scope="col" className="hidden w-[30%] px-3 py-2 text-left md:table-cell">
                        On the field
                      </th>
                      <th scope="col" className="px-3 py-2 text-right">Live</th>
                      <th scope="col" className="px-3 py-2 text-right">Projected</th>
                      <th scope="col" className="hidden px-3 py-2 text-right sm:table-cell">Final vs proj.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((player) => (
                      <LiveRow
                        key={player.player_id}
                        player={player}
                        game={games.get(player.event_id)}
                        mine={roster.has(player.player_id)}
                        fieldMax={fieldMax}
                      />
                    ))}
                  </tbody>
                </table>
                <ShowMoreRows budget={budget} />
              </div>
            )}
          </Card>
        </Refreshing>
      )}
    </>
  )
}

/**
 * The yellow line: `BOOM_THRESHOLD` in `nflfp/predict/distribution.py`, the
 * same 20 points every board draws and every "chance of 20+" is measured
 * against. The live payload does not carry it, so it is named here once.
 */
const LINE_TO_GAIN = 20

const STATE_ORDER: Record<string, number> = { in: 0, pre: 1, post: 2 }

function tickerOrder(games: LiveGame[]): LiveGame[] {
  return [...games].sort(
    (a, b) =>
      (STATE_ORDER[a.state] ?? 1) - (STATE_ORDER[b.state] ?? 1) ||
      (a.kickoff ?? '').localeCompare(b.kickoff ?? ''),
  )
}

/**
 * One game on the ticker, and the way to narrow the table to it.
 *
 * The whole tile is the button — a pressed toggle, so a second click shows
 * every game again. The team names are plain text rather than links for that
 * reason: a link inside a button is two controls in one place.
 */
function GameTile({
  game,
  selected,
  onSelect,
}: {
  game: LiveGame
  selected: boolean
  onSelect: () => void
}) {
  const live = game.state === 'in'
  const final = game.state === 'post'
  const awayScore = game.away_score ?? 0
  const homeScore = game.home_score ?? 0
  const scored = game.state !== 'pre'

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`${game.away} at ${game.home}, ${final ? 'final' : (game.detail ?? game.state)}. ${selected ? 'Showing only this game; press to show every game.' : 'Show only players in this game.'}`}
      className={cn(
        'bg-surface shadow-card hover:bg-surface-hover relative block h-full w-full overflow-hidden rounded-[var(--radius-control)] border px-3 pt-3 pb-2 text-left transition-colors',
        selected ? 'border-accent ring-accent ring-2' : live ? 'border-negative/50' : 'border-line',
      )}
    >
      <MatchupColorBar away={game.away} home={game.home} />
      <div className="space-y-1.5">
        <ScoreBugTeam
          team={game.away}
          score={scored ? game.away_score : undefined}
          trailing={final && awayScore < homeScore}
        >
          <span>{game.away}</span>
        </ScoreBugTeam>
        <ScoreBugTeam
          team={game.home}
          score={scored ? game.home_score : undefined}
          trailing={final && homeScore < awayScore}
        >
          <span>{game.home}</span>
        </ScoreBugTeam>
      </div>
      <p
        className={cn(
          'mt-2 flex items-center gap-1.5 truncate text-[0.6875rem]',
          live ? 'text-negative-text font-semibold' : final ? 'text-ink font-semibold' : 'text-ink-muted',
        )}
      >
        {live && <span aria-hidden className="bg-negative animate-live-dot size-1.5 shrink-0 rounded-full" />}
        {final ? 'Final' : (game.detail ?? game.state)}
      </p>
    </button>
  )
}

const LiveRow = memo(function LiveRow({
  player,
  game,
  mine,
  fieldMax,
}: {
  player: LivePlayer
  game: LiveGame | undefined
  mine: boolean
  fieldMax: number
}) {
  const final = game?.state === 'post'
  const difference = final && player.projected != null ? player.live_points - player.projected : null
  const shown = useCountUp(player.live_points)
  const pastTheLine = player.live_points >= LINE_TO_GAIN

  // Plays only when a refetch brings a different number: a score, not a page
  // load. Crossing the line to gain gets the yellow sweep; any other score
  // gets the bump on the number.
  const rowRef = useRef<HTMLTableRowElement>(null)
  const numberRef = useRef<HTMLSpanElement>(null)
  const last = useRef(player.live_points)
  useEffect(() => {
    const before = last.current
    last.current = player.live_points
    if (before === player.live_points) return
    replayAnimation(numberRef.current, 'animate-score-bump')
    if (before < LINE_TO_GAIN && player.live_points >= LINE_TO_GAIN) {
      replayAnimation(rowRef.current, 'animate-chains')
    }
  }, [player.live_points])

  const strip = (compact: boolean) => (
    <OutcomeRange
      hideEndpoints={compact}
      floor={player.floor}
      median={null}
      ceiling={player.ceiling}
      threshold={LINE_TO_GAIN}
      scaleMax={fieldMax}
      actual={player.live_points}
    />
  )

  return (
    <tr ref={rowRef} className={cn('border-line border-b last:border-b-0', mine && 'bg-accent-soft/40')}>
      <td className="px-3 py-2">
        <span className="flex items-center gap-3">
          <PlayerAvatar player={{ name: player.name, headshot_url: player.headshot_url }} size="sm" />
          <span className="min-w-0 flex-1">
            <Link to={`/players/${encodeURIComponent(player.player_id)}`} className="text-ink hover:text-accent-text block truncate font-medium">
              {player.name}
            </Link>
            <span className="text-ink-muted block text-xs">
              {player.position} · {player.team}
              {game ? ` · ${game.state === 'in' ? game.detail : final ? 'Final' : 'Not started'}` : ''}
              {mine && ' · My team'}
            </span>
            {/* The field under the name on a phone, where there is no column for it. */}
            <span className="mt-1.5 block md:hidden">{strip(true)}</span>
          </span>
        </span>
      </td>
      <td className="text-ink-secondary hidden px-3 py-2 text-xs lg:table-cell">{statLine(player.components)}</td>
      <td className="hidden px-3 py-2 md:table-cell">{strip(false)}</td>
      <td className="px-3 py-2 text-right">
        <span ref={numberRef} className="tnum text-ink inline-block text-base font-semibold">
          <span aria-hidden>{formatPoints(shown)}</span>
          <span className="sr-only">{formatPoints(player.live_points)}</span>
        </span>
        {pastTheLine && (
          <span className="bg-line-to-gain text-on-line-to-gain mt-1 block w-fit rounded-sm px-1.5 py-px text-[0.625rem] font-bold tracking-wide whitespace-nowrap uppercase sm:ml-auto">
            Past the {LINE_TO_GAIN}
          </span>
        )}
      </td>
      <td className="tnum text-ink-secondary px-3 py-2 text-right">
        {formatPoints(player.projected)}
        {player.floor != null && player.ceiling != null && (
          <span className="text-ink-muted block text-[0.6875rem]">
            {formatPoints(player.floor)}–{formatPoints(player.ceiling)}
          </span>
        )}
      </td>
      <td
        className={cn(
          'tnum hidden px-3 py-2 text-right sm:table-cell',
          difference == null ? 'text-ink-muted' : difference >= 0 ? 'text-positive-text' : 'text-negative-text',
        )}
      >
        {difference == null ? '—' : formatSigned(difference)}
      </td>
    </tr>
  )
})
