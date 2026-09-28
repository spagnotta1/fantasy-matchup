import { useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowLeftRight } from 'lucide-react'

import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { TopValues } from '@/features/trade/TopValues'
import { TradeSide, type SideRow } from '@/features/trade/TradeSide'
import { TradeVerdict } from '@/features/trade/TradeVerdict'
import { SIDE_LIMIT, bestLineup, evenOut, fromRoster, tradeBalance } from '@/features/trade/tradeMath'
import { eligiblePositions, expandSlots } from '@/features/simulations/lineupFormat'
import { useSlate } from '@/app/slate-context'
import { useTradeValues } from '@/hooks/useInsights'
import { useBoard, usePlayers } from '@/hooks/useProjections'
import { useRoster } from '@/hooks/useRoster'
import { useLineupCatalog } from '@/hooks/useSimulation'
import { useSlidingIndicator } from '@/hooks/useSlidingIndicator'
import { cn } from '@/utils/cn'
import { headlinePoints } from '@/utils/format'
import type { Injury, RankedProjection, TradeValue } from '@/api/schemas'

type Side = 'give' | 'get'
type View = 'trade' | 'top'

function parseIds(value: string | null): string[] {
  return value ? [...new Set(value.split(',').filter(Boolean))].slice(0, SIDE_LIMIT) : []
}

/**
 * Trade analyzer: two sides weighed on one number that adds up, and the board
 * that number comes from.
 *
 * The number is rest-of-season value above the waiver wire (`/trade/values`):
 * this week's published projection used as a per-game rate, carried over the
 * games left and scaled by historical availability, measured from the best
 * player nobody rosters. It is `derived` and a rate, not a forecast, and the
 * page says both beside the verdict.
 *
 * What the value cannot know is the manager's roster, so when My team holds one
 * the page also shows the trade's effect on their best starting lineup — the
 * question a two-for-one actually turns on.
 */
export default function TradePage() {
  const slate = useSlate()
  const [params, setParams] = useSearchParams()
  const give = parseIds(params.get('give'))
  const get = parseIds(params.get('get'))
  const view: View = params.get('view') === 'top' ? 'top' : 'trade'

  const values = useTradeValues()
  const board = useBoard()
  const [rosterIds] = useRoster()
  const catalog = useLineupCatalog()
  const identities = usePlayers([...give, ...get])

  const byId = useMemo(() => {
    const map = new Map<string, TradeValue>()
    for (const value of values.data?.data.values ?? []) map.set(value.player.player_id, value)
    return map
  }, [values.data])

  const boardById = useMemo(() => {
    const map = new Map<string, RankedProjection>()
    for (const entry of board.data?.data ?? []) map.set(entry.projection.player.player_id, entry)
    return map
  }, [board.data])

  const injuries = useMemo(() => {
    const map = new Map<string, Injury | null | undefined>()
    for (const [id, entry] of boardById) map.set(id, entry.projection.context.injury)
    return map
  }, [boardById])


  // Two quick taps land before a re-render, and the second must see the
  // first. The router's functional update still hands back the params of the
  // last render, so the latest write is tracked here instead.
  const latest = useRef(params)
  latest.current = params
  const update = (next: Partial<Record<Side | 'view', string | null>>) => {
    const out = new URLSearchParams(latest.current)
    for (const [key, value] of Object.entries(next)) {
      if (value) out.set(key, value)
      else out.delete(key)
    }
    latest.current = out
    setParams(out, { replace: true })
  }
  const editSides = (edit: (sides: Record<Side, string[]>) => Record<Side, string[]>) => {
    const current = latest.current
    const out = new URLSearchParams(current)
    const next = edit({ give: parseIds(current.get('give')), get: parseIds(current.get('get')) })
    for (const key of ['give', 'get'] as const) {
      if (next[key].length) out.set(key, next[key].join(','))
      else out.delete(key)
    }
    latest.current = out
    setParams(out, { replace: true })
  }
  const add = (side: Side, id: string) =>
    editSides((sides) => {
      if (sides[side].includes(id) || sides[side].length >= SIDE_LIMIT) return sides
      const other: Side = side === 'give' ? 'get' : 'give'
      return { [side]: [...sides[side], id], [other]: sides[other].filter((x) => x !== id) } as Record<Side, string[]>
    })
  const remove = (side: Side, id: string) =>
    editSides((sides) => ({ ...sides, [side]: sides[side].filter((x) => x !== id) }))

  const rowsFor = (ids: string[], offset: number): SideRow[] =>
    ids.map((id, index) => {
      const value = byId.get(id)
      return {
        id,
        value,
        player: value?.player ?? boardById.get(id)?.projection.player ?? identities[offset + index]?.data,
        injury: injuries.get(id),
      }
    })
  const giveRows = rowsFor(give, 0)
  const getRows = rowsFor(get, give.length)
  const valued = (rows: SideRow[]) => rows.flatMap((row) => (row.value ? [row.value] : []))
  const giveValues = valued(giveRows)
  const getValues = valued(getRows)
  const balance = tradeBalance(giveValues, getValues)

  const roster = useMemo(() => new Set(rosterIds), [rosterIds])
  const inTrade = new Map<string, Side>([
    ...give.map((id) => [id, 'give'] as [string, Side]),
    ...get.map((id) => [id, 'get'] as [string, Side]),
  ])
  const pool = values.data?.data.values ?? []
  const even = evenOut(balance, pool, new Set(inTrade.keys()), roster)

  // This week, on the board's own headline number — a bye or an inactive
  // listing is no projection, and is named rather than silently zeroed.
  const weekPoints = (ids: string[]) =>
    ids.reduce((sum, id) => sum + (headlinePoints(boardById.get(id)?.projection.prediction.points).value ?? 0), 0)
  const weekGap = weekPoints(get) - weekPoints(give)
  const weekMissing = [...giveRows, ...getRows]
    .filter((row) => row.player && headlinePoints(boardById.get(row.id)?.projection.prediction.points).value === null)
    .map((row) => row.player?.name ?? row.id)

  const lineup = useMemo(() => {
    if (rosterIds.length === 0 || catalog.isPending) return null
    const slots = expandSlots(catalog.format)
    const eligible = (slot: string) => eligiblePositions(catalog.slots, slot)
    const mine = rosterIds.flatMap((id) => {
      const value = byId.get(id)
      return value && !injuries.get(id)?.will_not_play ? [value] : []
    })
    const after = [
      ...mine.filter((value) => !give.includes(value.player.player_id)),
      ...getValues.filter((value) => !injuries.get(value.player.player_id)?.will_not_play),
    ]
    return {
      before: bestLineup(mine, slots, eligible),
      after: bestLineup(after, slots, eligible),
      notOnRoster: giveRows.filter((row) => !roster.has(row.id)).map((row) => row.player?.name ?? row.id),
    }
  }, [rosterIds, catalog, byId, injuries, give, getValues, giveRows, roster])

  const rosterSuggestions = rosterIds
    .flatMap((id) => {
      const value = byId.get(id)
      return value && !inTrade.has(id) ? [value] : []
    })
    .sort((a, b) => b.trade_value - a.trade_value)
    .slice(0, 6)

  const ready = give.length > 0 && get.length > 0
  const data = values.data?.data

  return (
    <>
      <PageHeader
        title="Trade analyzer"
        question="Who gets more rest-of-season value in this trade, and what does it do to your lineup?"
      />

      <ViewTabs view={view} onChange={(next) => update({ view: next === 'top' ? 'top' : null })} />

      {values.isError ? (
        <ErrorState error={values.error} onRetry={() => void values.refetch()} />
      ) : values.isPending ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-48 rounded-[var(--radius-card)]" />
          <Skeleton className="h-48 rounded-[var(--radius-card)]" />
        </div>
      ) : data && data.values.length === 0 ? (
        <>
          <NoticeList className="mb-4" notices={values.data?.meta.notices ?? []} />
          <Card>
            <EmptyState
              icon={<ArrowLeftRight aria-hidden className="size-5" />}
              title="No trade values for this week"
              description="Values are built from the week's published projections. Pick a published week to compare players."
            />
          </Card>
        </>
      ) : (
        <Refreshing active={values.isPlaceholderData}>
          {view === 'top' ? (
            <TopValues values={pool} injuries={injuries} inTrade={inTrade} onAdd={add} />
          ) : (
            <>
              <div className="grid gap-4 sm:gap-6 lg:grid-cols-2">
                <TradeSide
                  title="You give"
                  side="give"
                  rows={giveRows}
                  total={balance.give}
                  allIds={[...give, ...get]}
                  suggestions={rosterSuggestions}
                  suggestionsLabel="From your team"
                  onAdd={(id) => add('give', id)}
                  onRemove={(id) => remove('give', id)}
                />
                <TradeSide
                  title="You get"
                  side="get"
                  rows={getRows}
                  total={balance.get}
                  allIds={[...give, ...get]}
                  onAdd={(id) => add('get', id)}
                  onRemove={(id) => remove('get', id)}
                />
              </div>

              {ready ? (
                <TradeVerdict
                  balance={balance}
                  even={even}
                  ownRoster={even !== null && fromRoster(even, roster)}
                  weekGap={weekGap}
                  weekMissing={weekMissing}
                  lineup={lineup}
                  notices={values.data?.meta.notices ?? []}
                  replacement={data?.replacement ?? []}
                  week={slate.week}
                  onAdd={add}
                  onClear={() => update({ give: null, get: null })}
                />
              ) : (
                <Card className="mt-4 sm:mt-6">
                  <EmptyState
                    icon={<ArrowLeftRight aria-hidden className="size-5" />}
                    title="Add a player to each side"
                    description="Search above, tap one of your players, or add from the Top 150."
                  />
                </Card>
              )}
            </>
          )}
        </Refreshing>
      )}
    </>
  )
}

function ViewTabs({ view, onChange }: { view: View; onChange: (view: View) => void }) {
  const [ref, underline] = useSlidingIndicator<HTMLDivElement>(view)
  const tabs: { id: View; label: string }[] = [
    { id: 'trade', label: 'Trade analyzer' },
    { id: 'top', label: 'Top 150' },
  ]
  return (
    <div ref={ref} role="tablist" aria-label="Trade view" className="border-line relative mb-4 flex gap-1 border-b sm:mb-5">
      {underline && (
        <span
          aria-hidden
          className="bg-accent pointer-events-none absolute h-0.5 rounded-full"
          style={{ ...underline, top: undefined, height: undefined, bottom: -1 }}
        />
      )}
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={view === tab.id}
          data-active={view === tab.id || undefined}
          onClick={() => onChange(tab.id)}
          className={cn(
            'relative h-10 px-3 text-sm font-bold tracking-tight transition-colors',
            view === tab.id ? 'text-ink' : 'text-ink-muted hover:text-ink',
            !underline && view === tab.id && 'border-accent border-b-2',
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
