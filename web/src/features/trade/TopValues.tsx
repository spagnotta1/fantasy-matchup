import { useMemo, useState } from 'react'

import { Card } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { cn } from '@/utils/cn'
import { formatNumber } from '@/utils/format'
import type { Injury, TradeValue } from '@/api/schemas'

import { PositionRank, ValueWorking } from './TradeSide'
import { TRADE_POSITIONS } from './tradeMath'

const TOP_N = 150

type Filter = 'ALL' | (typeof TRADE_POSITIONS)[number]

/**
 * The trade value board: the top 150 by rest-of-season value above the waiver
 * wire, with a one-tap add to either side of the trade.
 *
 * The bar behind each value is drawn on one scale for the whole board, so a
 * reader sees where the values fall off — the gap between #5 and #25 is the
 * information, and a bare column of numbers hides it.
 */
export function TopValues({
  values,
  injuries,
  inTrade,
  onAdd,
}: {
  values: TradeValue[]
  injuries: Map<string, Injury | null | undefined>
  inTrade: Map<string, 'give' | 'get'>
  onAdd: (side: 'give' | 'get', id: string) => void
}) {
  const [filter, setFilter] = useState<Filter>('ALL')
  const top = useMemo(() => values.slice(0, TOP_N), [values])
  const shown = filter === 'ALL' ? top : top.filter((value) => value.position === filter)
  const scale = top[0]?.trade_value || 1

  return (
    <Card className="overflow-hidden">
      <div className="border-line flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-5">
        <div className="min-w-0">
          <h2 className="text-ink text-lg font-extrabold tracking-tight">Top {TOP_N}</h2>
          <p className="text-ink-muted text-xs">Rest-of-season value above the waiver wire.</p>
        </div>
        <div className="flex items-center gap-2">
          <ProvenanceBadge provenance="derived" />
          <SegmentedControl
            label="Position"
            size="sm"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'ALL', label: 'All' },
              ...TRADE_POSITIONS.map((position) => ({ value: position as Filter, label: position })),
            ]}
          />
        </div>
      </div>
      <ol>
        {shown.map((value) => {
          const id = value.player.player_id
          const side = inTrade.get(id)
          return (
            <li
              key={id}
              className="border-line flex items-center gap-3 border-b px-4 py-2.5 last:border-b-0 sm:px-5"
            >
              <span className="tnum text-ink-muted w-8 shrink-0 text-right text-sm font-semibold">
                {value.overall_rank}
              </span>
              <PositionRank value={value} className="hidden sm:inline-flex" />
              <div className="min-w-0 flex-1">
                <PlayerIdentity
                  player={value.player}
                  team={value.team}
                  size="sm"
                  subtitle={
                    <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                      <span className="sm:hidden">
                        {value.position}
                        {value.position_rank} ·{' '}
                      </span>
                      <span>{value.team ?? '—'}</span>
                      <span aria-hidden className="hidden md:inline">
                        ·
                      </span>
                      <span className="hidden md:inline">
                        <ValueWorking value={value} />
                      </span>
                      <InjuryBadge injury={injuries.get(id)} />
                    </span>
                  }
                />
              </div>
              <div className="hidden w-32 shrink-0 sm:block" aria-hidden>
                <div className="bg-surface-sunken h-1.5 overflow-hidden rounded-full">
                  <div
                    className="bg-accent h-full rounded-full"
                    style={{ width: `${Math.max((value.trade_value / scale) * 100, 1)}%` }}
                  />
                </div>
              </div>
              <span className="tnum text-ink w-10 shrink-0 text-right text-base font-bold">
                {formatNumber(value.trade_value, 0)}
              </span>
              <div className="flex shrink-0 gap-1">
                {(['give', 'get'] as const).map((target) => (
                  <button
                    key={target}
                    type="button"
                    disabled={side !== undefined}
                    onClick={() => onAdd(target, id)}
                    aria-label={`Add ${value.player.name} to ${target === 'give' ? 'You give' : 'You get'}`}
                    className={cn(
                      'border-line rounded-[var(--radius-control)] border px-2 py-1 text-xs font-medium transition-colors',
                      side === target
                        ? 'bg-accent text-on-accent border-transparent'
                        : 'text-ink-secondary hover:bg-surface-hover hover:text-ink disabled:opacity-40',
                    )}
                  >
                    {target === 'give' ? 'Give' : 'Get'}
                  </button>
                ))}
              </div>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}
