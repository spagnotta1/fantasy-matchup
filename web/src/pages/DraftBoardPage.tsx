import { memo, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { ListOrdered } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { Select } from '@/components/ui/Select'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { InfoTip } from '@/components/ui/Tooltip'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { useValueBoard } from '@/hooks/useInsights'
import { useDraftConfig } from '@/hooks/useMockDraft'
import { useUrlState } from '@/hooks/useUrlState'
import { cn } from '@/utils/cn'
import { formatPoints, formatScoringProfile } from '@/utils/format'
import type { ValueEntry } from '@/api/schemas'

type Lens = 'all' | 'value' | 'reach'

const DEFAULT_STATE = { season: '', position: '', lens: 'all' }

/** Rank gaps this small are inside the ordinary spread of any two boards. */
const NOTABLE_GAP = 3

/**
 * The draft pool beside the market: where the model's value and ADP disagree.
 *
 * Two numbers with different origins, kept labelled. Season value is the pool
 * the mock draft drafts on — the published week 1 projection read as a
 * per-game rate, times expected games (`derived`). ADP is the market's observed
 * draft slot (`context`), which no projection and none of the mock draft's
 * opponents read.
 *
 * Ranks are compared within position and only among players both lists hold,
 * which is the one comparison that is fair: overall ranks would make every
 * quarterback a bargain, and counting the market's rookies — whom the model
 * cannot value — would make every veteran one. The rookies are listed below,
 * with the reason, rather than dropped.
 */
export default function DraftBoardPage() {
  const config = useDraftConfig()
  const [state, setState] = useUrlState(DEFAULT_STATE)
  const seasons = config.data?.data.draftable_seasons ?? []
  const season = state.season ? Number(state.season) : (seasons[0] ?? null)
  const lens = state.lens as Lens

  const { data, isPending, isError, error, refetch, isPlaceholderData } = useValueBoard(season)
  const board = data?.data

  const entries = useMemo(() => {
    return (board?.entries ?? []).filter((entry) => {
      if (state.position && entry.player.position !== state.position) return false
      if (lens === 'value') return entry.rank_gap >= NOTABLE_GAP
      if (lens === 'reach') return entry.rank_gap <= -NOTABLE_GAP
      return true
    })
  }, [board, state.position, lens])

  return (
    <>
      <PageHeader
        title="Draft board"
        question="Where does the model's season value disagree with the market's ADP?"
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Select
          label="Season"
          size="sm"
          value={season === null ? '' : String(season)}
          onChange={(event) => setState({ season: event.target.value })}
          className="w-32"
          options={
            seasons.length
              ? seasons.map((s) => ({ value: String(s), label: String(s) }))
              : [{ value: '', label: config.isPending ? 'Loading…' : 'None' }]
          }
          disabled={seasons.length === 0}
        />
        <SegmentedControl
          label="Position"
          value={state.position}
          onChange={(value) => setState({ position: value })}
          options={[{ value: '', label: 'All' }, ...['QB', 'RB', 'WR', 'TE'].map((p) => ({ value: p, label: p }))]}
        />
        <SegmentedControl<Lens>
          label="Show"
          value={lens}
          onChange={(value) => setState({ lens: value })}
          options={[
            { value: 'all', label: 'Everyone' },
            { value: 'value', label: 'Model higher' },
            { value: 'reach', label: 'Market higher' },
          ]}
        />
        <Link to="/mock-draft" className="text-accent-text ml-auto pb-1.5 text-xs hover:underline">
          Run a mock draft on this pool
        </Link>
      </div>

      {data && <NoticeList notices={data.meta.notices} className="mb-6" />}

      {isPending || config.isPending ? (
        <Card>
          <SkeletonTable rows={12} columns={6} />
        </Card>
      ) : isError ? (
        <Card>
          <ErrorState error={error} onRetry={() => void refetch()} />
        </Card>
      ) : !board || season === null ? (
        <Card>
          <EmptyState
            icon={<ListOrdered aria-hidden className="size-5" />}
            title="No draftable season"
            description="A season needs a published week 1 board before its players can be valued."
          />
        </Card>
      ) : (
        <Refreshing active={isPlaceholderData}>
          <Card className="overflow-hidden">
            <CardHeader
              as="h2"
              title={`${board.season} value against ADP`}
              description={`${formatScoringProfile(board.scoring_profile)} scoring. Ordered by ADP; ranks are within position among players with both.`}
              action={
                <span className="flex items-center gap-1.5">
                  <ProvenanceBadge provenance="derived" />
                  <ProvenanceBadge provenance="context" />
                </span>
              }
            />
            {board.market && (
              <CardBody className="border-line text-ink-muted border-b py-2.5 text-xs">
                ADP from {board.market.total_drafts?.toLocaleString() ?? 'an unknown number of'} drafts in{' '}
                {board.market.teams ?? '—'}-team leagues, {board.market.window_start} to {board.market.window_end}
                {board.market.is_preseason === false && ' (an in-season window, not draft day)'}.
              </CardBody>
            )}
            {entries.length === 0 ? (
              <EmptyState
                title="No players match"
                description="Nothing on the board fits this position and lens."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <caption className="sr-only">Season value against ADP, ordered by ADP</caption>
                  <thead>
                    <tr className="border-line text-ink-muted border-b text-xs font-medium tracking-wide uppercase">
                      <th scope="col" className="px-3 py-2 text-left">ADP</th>
                      <th scope="col" className="px-3 py-2 text-left">Player</th>
                      <th scope="col" className="px-3 py-2 text-right">
                        <span className="inline-flex items-center gap-1">
                          Market → model
                          <InfoTip
                            label="About the ranks"
                            content="Positional rank by ADP, then by season value, counted only among players who have both. The gap is the first minus the second: positive means the model values him above where the market takes him."
                          />
                        </span>
                      </th>
                      <th scope="col" className="px-3 py-2 text-right">Season value</th>
                      <th scope="col" className="hidden px-3 py-2 text-right md:table-cell">Per game × games</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry) => (
                      <ValueRow key={entry.player.player_id} entry={entry} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <Card className="overflow-hidden">
              <CardHeader
                as="h2"
                title={`In the market, not on the board (${board.market_only.length})`}
                description="Drafted players the model cannot value, and why. Before a season these are mostly rookies, who have no usage window and so no projection."
              />
              {/* Focusable, because it scrolls and holds nothing else a keyboard
                  can land on — without a tab stop it could not be scrolled at all. */}
              <ul
                tabIndex={0}
                aria-label="Drafted players with no projection"
                className="divide-line focus-visible:outline-focus max-h-96 divide-y overflow-y-auto"
              >
                {board.market_only.map((m) => (
                  <li key={`${m.name}-${m.adp}`} className="flex items-start gap-3 px-4 py-2">
                    <span className="tnum text-ink-muted w-10 text-xs">{formatPoints(m.adp)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="text-ink block text-sm font-medium">
                        {m.name} <span className="text-ink-muted text-xs font-normal">{m.position} · {m.team ?? '—'}</span>
                      </span>
                      <span className="text-ink-muted block text-xs">{m.reason}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
            <Card className="overflow-hidden">
              <CardHeader
                as="h2"
                title="On the board, not in the market"
                description="The pool's highest season values that the ADP window did not draft at all."
              />
              <ul className="divide-line max-h-96 divide-y overflow-y-auto">
                {board.unpriced.map((p) => (
                  <li key={p.player_id} className="flex items-center gap-3 px-4 py-2">
                    <span className="min-w-0 flex-1">
                      <Link to={`/players/${encodeURIComponent(p.player_id)}`} className="text-ink hover:text-accent-text block truncate text-sm font-medium">
                        {p.name}
                      </Link>
                      <span className="text-ink-muted block text-xs">{p.position} · {p.team ?? '—'}</span>
                    </span>
                    <span className="tnum text-ink text-sm font-medium">{formatPoints(p.season_value, 0)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </Refreshing>
      )}
    </>
  )
}

const ValueRow = memo(function ValueRow({ entry }: { entry: ValueEntry }) {
  const { player } = entry
  const gap = entry.rank_gap
  const notable = Math.abs(gap) >= NOTABLE_GAP
  return (
    <tr className="border-line border-b last:border-b-0">
      <td className="tnum text-ink-secondary px-3 py-2 text-xs">
        {entry.adp_formatted ?? formatPoints(entry.adp)}
      </td>
      <td className="px-3 py-2">
        <Link to={`/players/${encodeURIComponent(player.player_id)}`} className="text-ink hover:text-accent-text font-medium">
          {player.name}
        </Link>
        <span className="text-ink-muted block text-xs">
          {player.position} · {player.team ?? '—'}
        </span>
      </td>
      <td className="px-3 py-2 text-right">
        <span className="tnum text-ink-secondary text-xs">
          {player.position}
          {entry.market_rank} → {player.position}
          {entry.value_rank}
        </span>
        {notable && (
          <Badge tone={gap > 0 ? 'positive' : 'caution'} className="ml-2">
            {gap > 0 ? `+${gap}` : `−${Math.abs(gap)}`}
          </Badge>
        )}
      </td>
      <td className={cn('tnum text-ink px-3 py-2 text-right font-medium')}>{formatPoints(player.season_value, 0)}</td>
      <td className="tnum text-ink-muted hidden px-3 py-2 text-right text-xs md:table-cell">
        {formatPoints(player.projected_points_per_game)} × {formatPoints(player.expected_games)}
      </td>
    </tr>
  )
})
