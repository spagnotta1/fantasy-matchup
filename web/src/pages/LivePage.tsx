import { memo, useCallback, useDeferredValue, useEffect, useMemo, useRef, type RefObject } from 'react'
import { Link } from 'react-router-dom'
import { Radio } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardHeader } from '@/components/ui/Card'
import {
  ColumnHeader,
  RowHeaderCell,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from '@/components/ui/DataTable'
import { FilterChip, FilterChoice, FilterSearch, FilterToolbar } from '@/components/ui/FilterToolbar'
import { PageHeader } from '@/components/ui/PageHeader'
import { RowList, RowListItem, RowListLine, RowListRows, RowListTitle } from '@/components/ui/RowList'
import { Skeleton, SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { PlayerCell } from '@/components/domain/PlayerCell'
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
import { useRowList } from '@/hooks/useRowList'
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
  const total = data?.players.length ?? 0
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

          <FilterToolbar
            label="Filter players"
            summary={
              total > 0
                ? players.length === total
                  ? `${total} players`
                  : `${players.length} of ${total} players`
                : undefined
            }
          >
            <FilterSearch
              label="Search players"
              placeholder="Search by name or team…"
              value={search}
              onChange={setSearch}
              onClear={() => setSearch('', { immediate: true })}
            />
            <FilterChoice
              label="Position"
              value={state.position}
              onChange={(value) => setState({ position: value })}
              options={[{ value: '', label: 'All' }, ...['QB', 'RB', 'WR', 'TE'].map((p) => ({ value: p, label: p }))]}
            />
            <FilterChoice
              label="Players"
              value={state.who}
              onChange={(value) => setState({ who: value })}
              options={[
                { value: 'all', label: 'Everyone' },
                { value: 'mine', label: `My team${roster.size ? ` (${roster.size})` : ''}` },
              ]}
            />
            {state.who === 'mine' && roster.size === 0 && (
              <Link to="/my-team" className="text-accent-text text-detail hover:underline">
                Add your roster first
              </Link>
            )}
            {selectedGame && (
              <FilterChip
                removeLabel={`Show every game, not just ${selectedGame.away} at ${selectedGame.home}`}
                onRemove={() => setState({ game: '' })}
              >
                {selectedGame.away} @ {selectedGame.home}
              </FilterChip>
            )}
          </FilterToolbar>

          {/* `clip`, not `hidden`: a hidden overflow would make the card a
              scroll container and the column header would stick to it. */}
          <Card className="overflow-clip">
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
              <>
                <LiveRows players={visible} games={games} roster={roster} fieldMax={fieldMax} />
                <ShowMoreRows budget={budget} />
              </>
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
        'bg-surface hover:bg-surface-hover relative block h-full w-full overflow-hidden rounded-[var(--radius-control)] border px-3 pt-3 pb-2 text-left transition-colors',
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
          'mt-2 flex items-center gap-1.5 truncate text-chip',
          live ? 'text-negative-text font-semibold' : final ? 'text-ink font-semibold' : 'text-ink-muted',
        )}
      >
        {live && <span aria-hidden className="bg-negative animate-live-dot size-1.5 shrink-0 rounded-full" />}
        {final ? 'Final' : (game.detail ?? game.state)}
      </p>
    </button>
  )
}

/**
 * The narrowest the table is drawn at before it scrolls inside its own frame:
 * its four fixed columns (36.5rem), the smallest field strip (13rem) and a
 * 10rem player column — a headshot, a name and a line under it. The numbers
 * come first after the player so that on a phone, where the rest scrolls, the
 * first thing beside a name is his points.
 */
const TABLE_MIN_WIDTH = '59.5rem'

/**
 * What the table has to spare after the fixed columns and a 19.5rem player
 * cell: a name, a team, where the game stands and "My team" on one line.
 */
const FIELD_WIDTH = 'w-[clamp(13rem,calc(100cqw-56rem),26cqw)]'

const CAPTION = 'Unofficial live fantasy points with published projections'
const ORDER = 'highest live points first'

/**
 * The rows: a table where there is room for its columns, a list where there is
 * not.
 *
 * On a phone the table kept the name in view and showed one column beside it,
 * so live points and the projection they are measured against were never on
 * screen together, and a full Sunday scrolled inside a frame the height of the
 * screen. The list is the page scrolling, with every column of a row in it.
 */
function LiveRows({
  players,
  games,
  roster,
  fieldMax,
}: {
  players: LivePlayer[]
  games: Map<string, LiveGame>
  roster: Set<string>
  fieldMax: number
}) {
  const [frameRef, asList] = useRowList<HTMLDivElement>()

  return (
    <div ref={frameRef}>
      {asList ? (
        <RowList
          value="Live points"
          note="The ball is the points scored so far, on the range the projection gave before kickoff. The yellow line is 20 points."
        >
          <RowListRows aria-label={`${CAPTION}, ${ORDER}`}>
            {players.map((player) => (
              <LiveListRow
                key={player.player_id}
                player={player}
                game={games.get(player.event_id)}
                mine={roster.has(player.player_id)}
                fieldMax={fieldMax}
              />
            ))}
          </RowListRows>
        </RowList>
      ) : (
        <Table
          // A query container, so the field column can size to the table.
          className="@container"
          caption={CAPTION}
          captionNote={ORDER}
          layout="fixed"
          minWidth={TABLE_MIN_WIDTH}
          freezeFirstColumn
        >
          <TableHead>
            <ColumnHeader>Player</ColumnHeader>
            {/* As wide as the "Past the 20" mark under the number. */}
            <ColumnHeader numeric className="w-28">
              Live
            </ColumnHeader>
            <ColumnHeader numeric className="w-26">
              Projected
            </ColumnHeader>
            <ColumnHeader
              numeric
              className="w-28"
              tip="Live points minus the projection, shown once the game is final. Before then the gap mostly measures how much of the game is left."
            >
              Final vs proj.
            </ColumnHeader>
            <ColumnHeader
              className={FIELD_WIDTH}
              tip="The ball is the points scored so far, on the range the projection gave before kickoff: the floor and the ceiling are printed either side. The yellow line is 20 points."
            >
              On the field
            </ColumnHeader>
            <ColumnHeader className="w-64">Stat line</ColumnHeader>
          </TableHead>
          <TableBody>
            {players.map((player) => (
              <LiveRow
                key={player.player_id}
                player={player}
                game={games.get(player.event_id)}
                mine={roster.has(player.player_id)}
                fieldMax={fieldMax}
              />
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

/**
 * Where a player's game stands. A game in progress is the one thing here that
 * is still moving, so it is marked the way the ticker marks it: the live dot
 * and the clock in the alert colour, and in words either way.
 */
function GameState({ game }: { game: LiveGame }) {
  if (game.state === 'in') {
    return (
      <span className="text-negative-text inline-flex items-center gap-1 font-semibold">
        <span aria-hidden className="bg-negative animate-live-dot size-1.5 shrink-0 rounded-full" />
        <span className="sr-only">In progress, </span>
        {game.detail ?? 'In progress'}
      </span>
    )
  }
  return <>{game.state === 'post' ? 'Final' : 'Not started'}</>
}

/**
 * One player, memoised: a refresh hands every row whose numbers did not change
 * the same props it had, so the row is not redrawn and whatever in it had
 * focus keeps it.
 */
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
  const { difference, shown, pastTheLine, rowRef, numberRef } = useLiveScore<HTMLTableRowElement>(player, game)

  return (
    <TableRow ref={rowRef} highlighted={mine}>
      <RowHeaderCell>
        <PlayerCell
          player={player}
          meta={
            <>
              {player.position} · {player.team}
              {game && (
                <>
                  {' · '}
                  <GameState game={game} />
                </>
              )}
            </>
          }
        >
          {/* The tint on the row says the same thing; this says it in words. */}
          {mine && <span className="text-accent-text text-detail font-medium whitespace-nowrap">My team</span>}
        </PlayerCell>
      </RowHeaderCell>
      <TableCell numeric>
        <span ref={numberRef} className="text-ink inline-block text-base font-semibold">
          <span aria-hidden>{formatPoints(shown)}</span>
          <span className="sr-only">{formatPoints(player.live_points)}</span>
        </span>
        {pastTheLine && (
          <span className="bg-line-to-gain text-on-line-to-gain text-chip ml-auto block w-fit rounded-sm px-1.5 py-px font-bold tracking-wide whitespace-nowrap uppercase">
            Past the {LINE_TO_GAIN}
          </span>
        )}
      </TableCell>
      <TableCell numeric className="text-ink-secondary">
        {formatPoints(player.projected)}
      </TableCell>
      <TableCell
        numeric
        className={
          difference == null ? 'text-ink-muted' : difference >= 0 ? 'text-positive-text' : 'text-negative-text'
        }
      >
        {difference == null ? '—' : formatSigned(difference)}
      </TableCell>
      <TableCell>
        <OutcomeRange
          floor={player.floor}
          median={null}
          ceiling={player.ceiling}
          threshold={LINE_TO_GAIN}
          scaleMax={fieldMax}
          actual={player.live_points}
        />
      </TableCell>
      <TableCell className="text-ink-secondary text-detail">{statLine(player.components)}</TableCell>
    </TableRow>
  )
})

/**
 * What both drawings of a row need from its score: the number as it counts up,
 * the difference once the game is final, and the two animations.
 */
function useLiveScore<Row extends HTMLElement>(
  player: LivePlayer,
  game: LiveGame | undefined,
): {
  difference: number | null
  shown: number
  pastTheLine: boolean
  rowRef: RefObject<Row | null>
  numberRef: RefObject<HTMLSpanElement | null>
} {
  const final = game?.state === 'post'
  const difference = final && player.projected != null ? player.live_points - player.projected : null
  const shown = useCountUp(player.live_points)
  const pastTheLine = player.live_points >= LINE_TO_GAIN

  // Plays only when a refetch brings a different number: a score, not a page
  // load. Crossing the line to gain gets the yellow sweep; any other score
  // gets the bump on the number.
  const rowRef = useRef<Row>(null)
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

  return { difference, shown, pastTheLine, rowRef, numberRef }
}

/**
 * One player on the list, memoised like the table's row.
 *
 * Line one is who and how many: the name, where the game stands, the live
 * points. Line two is the field strip with the projection beside it, and line
 * three the stat line with, once the game is final, how the score finished
 * against that projection. A list has no header to name a number, so each of
 * the two smaller ones is named where it is printed.
 */
const LiveListRow = memo(function LiveListRow({
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
  const { difference, shown, pastTheLine, rowRef, numberRef } = useLiveScore<HTMLLIElement>(player, game)

  return (
    <RowListItem ref={rowRef} to={`/players/${encodeURIComponent(player.player_id)}`} highlighted={mine}>
      <PlayerAvatar player={player} size="xs" />
      <RowListTitle
        name={player.name}
        meta={
          <>
            {player.position} · {player.team}
            {game && (
              <>
                {' · '}
                <GameState game={game} />
              </>
            )}
          </>
        }
      >
        {/* The tint on the row says the same thing; this says it in words. */}
        {mine && <span className="text-accent-text text-chip font-medium whitespace-nowrap">My team</span>}
        {pastTheLine && (
          <span className="bg-line-to-gain text-on-line-to-gain text-chip rounded-sm px-1.5 py-px font-bold tracking-wide whitespace-nowrap uppercase">
            Past the {LINE_TO_GAIN}
          </span>
        )}
      </RowListTitle>
      <span ref={numberRef} className="text-ink tnum inline-block justify-self-end text-base font-semibold">
        <span aria-hidden>{formatPoints(shown)}</span>
        <span className="sr-only">{formatPoints(player.live_points)} live points</span>
      </span>
      <RowListLine>
        <OutcomeRange
          floor={player.floor}
          median={null}
          ceiling={player.ceiling}
          threshold={LINE_TO_GAIN}
          scaleMax={fieldMax}
          actual={player.live_points}
          className="min-w-0 flex-1"
        />
        <span className={SIDE_NOTE}>
          <span className="text-ink-muted">Proj. </span>
          {formatPoints(player.projected)}
        </span>
      </RowListLine>
      <RowListLine className="items-start">
        <span className="text-ink-secondary text-chip min-w-0 flex-1">{statLine(player.components)}</span>
        {difference != null && (
          <span className={cn(SIDE_NOTE, difference >= 0 ? 'text-positive-text' : 'text-negative-text')}>
            <span className="text-ink-muted">Final </span>
            {formatSigned(difference)}
          </span>
        )}
      </RowListLine>
    </RowListItem>
  )
})

/**
 * The projection and the final difference, one above the other at the row's
 * right edge. A fixed width, so every strip beside them ends at the same place
 * and one row's yard lines sit over the next's.
 */
const SIDE_NOTE = 'text-ink-secondary tnum text-chip w-[4.75rem] shrink-0 text-right font-medium whitespace-nowrap'
