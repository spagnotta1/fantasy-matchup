import { Plus, X } from 'lucide-react'

import { Card } from '@/components/ui/Card'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { PlayerSearchField } from '@/components/domain/PlayerSearchField'
import { cn } from '@/utils/cn'
import { formatNumber } from '@/utils/format'
import type { Injury, Player, TradeValue } from '@/api/schemas'

import { SIDE_LIMIT, TRADE_POSITIONS } from './tradeMath'

export interface SideRow {
  id: string
  player: Player | undefined
  value: TradeValue | undefined
  injury: Injury | null | undefined
}

/** "WR23": the position and where the player ranks in it. */
export function PositionRank({ value, className }: { value: TradeValue; className?: string }) {
  return (
    <span
      className={cn(
        'bg-accent text-on-accent tnum inline-flex h-5 min-w-10 shrink-0 items-center justify-center rounded-[5px] px-1.5 text-[0.6875rem] font-bold tracking-tight',
        className,
      )}
    >
      {value.position}
      {value.position_rank}
    </span>
  )
}

/** The rate-times-games line, so the value's construction is on screen, not in a footnote. */
export function ValueWorking({ value }: { value: TradeValue }) {
  return (
    <span className="tnum">
      {formatNumber(value.rate)} pts/g × {formatNumber(value.expected_games)} games
      {value.on_bye && <span className="text-caution-text"> · bye, week {value.rate_week} rate</span>}
    </span>
  )
}

/**
 * One side of the trade: a search field, the players, and the side's total.
 *
 * A player with no trade value is kept on the side and says why, rather than
 * being counted as zero in silence: "projected zero" and "not projected" are
 * different statements.
 */
export function TradeSide({
  title,
  side,
  rows,
  total,
  allIds,
  suggestions,
  suggestionsLabel,
  onAdd,
  onRemove,
}: {
  title: string
  side: 'give' | 'get'
  rows: SideRow[]
  total: number
  allIds: string[]
  /** Quick adds, e.g. the manager's own roster on the give side. */
  suggestions?: TradeValue[]
  suggestionsLabel?: string
  onAdd: (id: string) => void
  onRemove: (id: string) => void
}) {
  const full = rows.length >= SIDE_LIMIT
  return (
    <Card className="flex flex-col">
      <div className="flex items-baseline justify-between gap-3 px-4 pt-4 pb-3 sm:px-5">
        <h2 className="text-ink text-lg font-extrabold tracking-tight">{title}</h2>
        <p className="text-ink-secondary text-sm">
          <span className="sr-only">Total value </span>
          <span className="tnum text-ink font-bold">{formatNumber(total, 0)}</span>
        </p>
      </div>
      <div className="px-4 sm:px-5">
        <PlayerSearchField
          label={`Add a player you ${side}`}
          placeholder="Add a player"
          size="sm"
          positions={[...TRADE_POSITIONS]}
          excludeIds={allIds}
          disabled={full}
          hint={full ? `Up to ${SIDE_LIMIT} players a side.` : undefined}
          onSelect={(player) => onAdd(player.player_id)}
        />
      </div>

      <ul className="space-y-2 px-4 pt-3 pb-4 sm:px-5">
        {rows.map((row) => (
          <li
            key={row.id}
            className="border-line bg-surface animate-rise flex items-center gap-3 rounded-[var(--radius-control)] border px-3 py-2.5"
          >
            {row.value && <PositionRank value={row.value} />}
            <div className="min-w-0 flex-1">
              {row.player ? (
                <PlayerIdentity
                  player={row.player}
                  team={row.value?.team}
                  size="sm"
                  subtitle={
                    <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                      {row.value ? (
                        <>
                          <span className="tnum">#{row.value.overall_rank} overall</span>
                          <span aria-hidden>·</span>
                          <span>{row.value.team ?? row.player.team ?? '—'}</span>
                        </>
                      ) : (
                        <span>{[row.player.position, row.player.team].filter(Boolean).join(' · ')}</span>
                      )}
                      <InjuryBadge injury={row.injury} />
                    </span>
                  }
                />
              ) : (
                <span className="text-ink-muted text-sm">Loading…</span>
              )}
              {row.value && (
                <p className="text-ink-muted mt-1 text-[0.6875rem]">
                  <ValueWorking value={row.value} />
                </p>
              )}
            </div>
            <div className="shrink-0 text-right">
              {row.value ? (
                <span className="tnum text-ink text-base font-bold">{formatNumber(row.value.trade_value, 0)}</span>
              ) : (
                row.player && (
                  <span className="text-caution-text block max-w-28 text-[0.6875rem] leading-tight">
                    No value: not projected this week
                  </span>
                )
              )}
            </div>
            <button
              type="button"
              onClick={() => onRemove(row.id)}
              aria-label={`Remove ${row.player?.name ?? 'player'}`}
              className="text-ink-muted hover:text-ink hover:bg-surface-hover -mr-1 rounded-sm p-1"
            >
              <X aria-hidden className="size-4" />
            </button>
          </li>
        ))}
      </ul>

      {suggestions && suggestions.length > 0 && !full && (
        <div className="border-line mt-auto border-t px-4 py-3 sm:px-5">
          <p className="text-ink-muted mb-2 text-xs font-medium">{suggestionsLabel}</p>
          <div className="flex flex-wrap gap-1.5">
            {suggestions.map((value) => (
              <button
                key={value.player.player_id}
                type="button"
                onClick={() => onAdd(value.player.player_id)}
                className="border-line bg-surface hover:bg-surface-hover hover:border-line-strong text-ink inline-flex items-center gap-1.5 rounded-full border py-1 pr-2.5 pl-1.5 text-xs transition-colors"
              >
                <Plus aria-hidden className="text-ink-muted size-3.5" />
                <span className="font-medium">{value.player.name}</span>
                <span className="tnum text-ink-muted">{formatNumber(value.trade_value, 0)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </Card>
  )
}
