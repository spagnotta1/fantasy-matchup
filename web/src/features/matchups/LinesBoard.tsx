import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { InfoTip } from '@/components/ui/Tooltip'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { TeamLink } from '@/components/domain/TeamLink'
import { useGames } from '@/hooks/useMatchups'
import { useBoard } from '@/hooks/useProjections'
import { formatGameDay, formatPoints, formatSigned, formatSpread } from '@/utils/format'
import type { Game, GameContext } from '@/api/schemas'

interface Side {
  team: string
  spread: number | null
  implied: number | null
  movement: number | null
}

interface LineRow {
  game: Game
  total: number | null
  home: Side
  away: Side
  book: string | null
  capturedAt: string | null
}

function side(team: string, own: GameContext | undefined, other: GameContext | undefined): Side {
  return {
    team,
    // Read from the team's own context, else mirrored from its opponent's —
    // the market is one number per game seen from two sides.
    spread: own?.team_spread ?? (other?.team_spread != null ? -other.team_spread : null),
    implied: own?.implied_team_total ?? other?.implied_opponent_total ?? null,
    movement: own?.spread_movement ?? (other?.spread_movement != null ? -other.spread_movement : null),
  }
}

/**
 * The slate as the betting market sees it.
 *
 * A game's total and each side's implied points are the market's estimate of
 * scoring environment — the thing a fantasy manager reads to decide which games
 * to be in. This view exists because the projection does **not** use it: the
 * frozen model excludes market features (the reason travels with every
 * context block and is shown here), so a manager who wants it has to read it
 * separately, and should be able to without opening sixteen game pages.
 *
 * Everything is `context`, observed and not applied, and says so above the
 * table rather than in a footnote.
 */
export function LinesBoard() {
  const games = useGames()
  const board = useBoard()

  const { rows, reason } = useMemo(() => {
    const contexts = new Map<string, GameContext>()
    let unapplied: string | null = null
    for (const entry of board.data?.data ?? []) {
      const game = entry.projection.context.game
      if (!game?.game_id || !game.team) continue
      unapplied ??= game.unapplied_reason ?? null
      contexts.set(`${game.game_id}:${game.team}`, game)
    }

    const built: LineRow[] = (games.data?.data ?? []).map((game) => {
      const home = contexts.get(`${game.game_id}:${game.home_team}`)
      const away = contexts.get(`${game.game_id}:${game.away_team}`)
      const anchor = home ?? away
      return {
        game,
        total: anchor?.total_line ?? game.total_line ?? null,
        home: side(game.home_team, home, away),
        away: side(game.away_team, away, home),
        book: anchor?.odds_book ?? null,
        capturedAt: anchor?.odds_captured_at ?? null,
      }
    })
    // Highest-scoring environments first; games with no line at the bottom.
    built.sort((a, b) => (b.total ?? -1) - (a.total ?? -1))
    return { rows: built, reason: unapplied }
  }, [games.data, board.data])

  const topTotals = useMemo(
    () =>
      rows
        .flatMap((row) => [row.home, row.away].map((s) => ({ ...s, game: row.game })))
        .filter((s) => s.implied !== null)
        .sort((a, b) => (b.implied ?? 0) - (a.implied ?? 0))
        .slice(0, 8),
    [rows],
  )

  if (games.isPending) {
    return (
      <Card>
        <SkeletonTable rows={10} columns={6} />
      </Card>
    )
  }
  if (games.isError) {
    return (
      <Card>
        <ErrorState error={games.error} onRetry={() => void games.refetch()} />
      </Card>
    )
  }
  if (rows.length === 0) {
    return (
      <Card>
        <EmptyState title="No games this week" description="The schedule holds no games for the selected week." />
      </Card>
    )
  }

  const maxImplied = Math.max(...topTotals.map((s) => s.implied ?? 0), 1)

  return (
    <div className="space-y-6">
      <NoticeList
        title="Not included in the projection"
        showTitle
        notices={[
          reason ??
            'The frozen model excludes market features, so none of these lines is reflected in any projection.',
        ]}
      />

      <Refreshing active={games.isPlaceholderData || board.isPlaceholderData}>
        <div className="grid gap-6 xl:grid-cols-[1fr_20rem]">
          <Card className="min-w-0 overflow-hidden">
            <CardHeader
              as="h2"
              title="Betting lines"
              description="Spread, total and each side's implied points, highest total first."
              action={<ProvenanceBadge provenance="context" />}
            />
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <caption className="sr-only">
                  Betting lines for the week's games, highest total first.
                </caption>
                <thead>
                  <tr className="border-line text-ink-muted border-b text-xs font-medium tracking-wide uppercase">
                    <th scope="col" className="px-3 py-2 text-left">Game</th>
                    <th scope="col" className="hidden px-3 py-2 text-left sm:table-cell">Kickoff</th>
                    <th scope="col" className="px-3 py-2 text-right">Spread</th>
                    <th scope="col" className="px-3 py-2 text-right">Total</th>
                    <th scope="col" className="px-3 py-2 text-right">Implied</th>
                    <th scope="col" className="hidden px-3 py-2 text-right md:table-cell">
                      <span className="inline-flex items-center gap-1">
                        Move
                        <InfoTip
                          label="About line movement"
                          content="How far the favourite's spread has moved since the line opened. An arrow up means the market moved toward that team."
                        />
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <LineTableRow key={row.game.game_id} row={row} />
                  ))}
                </tbody>
              </table>
            </div>
            <CardBody className="border-line text-ink-muted border-t py-3 text-xs">
              {rows[0]?.book
                ? `Lines from ${rows[0].book}${rows[0].capturedAt ? `, captured ${formatGameDay(rows[0].capturedAt)}` : ''}. `
                : ''}
              Where no market line was captured the schedule's closing line stands in, and a game with
              neither shows a dash.
            </CardBody>
          </Card>

          <Card className="h-fit">
            <CardHeader
              as="h2"
              title="Highest implied totals"
              description="Points the market expects each offence to score."
            />
            <CardBody>
              <ol className="space-y-2.5">
                {topTotals.map((s) => (
                  <li key={`${s.game.game_id}:${s.team}`} className="flex items-center gap-3">
                    <TeamLink team={s.team} className="text-ink w-10 text-sm font-semibold" />
                    <div className="bg-surface-sunken relative h-2 flex-1 overflow-hidden rounded-full">
                      <div
                        className="bg-accent/60 absolute inset-y-0 left-0 rounded-full"
                        style={{ width: `${((s.implied ?? 0) / maxImplied) * 100}%` }}
                      />
                    </div>
                    <span className="tnum text-ink w-10 text-right text-sm font-medium">
                      {formatPoints(s.implied)}
                    </span>
                  </li>
                ))}
              </ol>
            </CardBody>
          </Card>
        </div>
      </Refreshing>
    </div>
  )
}

function LineTableRow({ row }: { row: LineRow }) {
  const favourite =
    row.home.spread === null ? null : row.home.spread >= 0 ? row.home : row.away
  const move = favourite?.movement ?? null
  const MoveIcon = move === null || move === 0 ? Minus : move > 0 ? ArrowUpRight : ArrowDownRight

  return (
    <tr className="border-line hover:bg-surface-hover border-b last:border-b-0">
      <th scope="row" className="px-3 py-2 text-left font-medium">
        <span className="inline-flex items-center gap-1.5">
          <TeamLink team={row.away.team} className="text-ink" />
          <span className="text-ink-muted font-normal">at</span>
          <TeamLink team={row.home.team} className="text-ink" />
        </span>
        <Link
          to={`/matchups/${encodeURIComponent(row.game.game_id)}`}
          className="text-ink-muted hover:text-accent-text block text-xs font-normal"
        >
          Open game
        </Link>
      </th>
      <td className="text-ink-secondary hidden px-3 py-2 text-xs sm:table-cell">
        {formatGameDay(row.game.gameday)}
      </td>
      <td className="tnum text-ink px-3 py-2 text-right">
        {favourite && favourite.spread !== null
          ? `${favourite.team} ${formatSpread(Math.abs(favourite.spread))}`
          : '—'}
      </td>
      <td className="tnum text-ink px-3 py-2 text-right font-medium">{formatPoints(row.total)}</td>
      <td className="tnum text-ink-secondary px-3 py-2 text-right text-xs">
        {row.away.team} {formatPoints(row.away.implied)}
        <br />
        {row.home.team} {formatPoints(row.home.implied)}
      </td>
      <td className="tnum text-ink-secondary hidden px-3 py-2 text-right text-xs md:table-cell">
        {move === null ? (
          '—'
        ) : (
          <span className="inline-flex items-center gap-1">
            <MoveIcon aria-hidden className="size-3.5" />
            {formatSigned(move)}
            <span className="sr-only">
              {move > 0 ? `toward ${favourite?.team}` : move < 0 ? `away from ${favourite?.team}` : 'unchanged'}
            </span>
          </span>
        )}
      </td>
    </tr>
  )
}
