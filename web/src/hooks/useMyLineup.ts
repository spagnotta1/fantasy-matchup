import { useMemo } from 'react'

import { autofillLineup, eligiblePositions, emptyLineup, type LineupRow } from '@/features/simulations/lineupFormat'
import { encodeLineup, TEAM_A_PARAM } from '@/features/simulations/shareLink'
import { useBoard, usePlayers } from '@/hooks/useProjections'
import { useLineupChoice, useRoster } from '@/hooks/useRoster'
import { useLineupCatalog } from '@/hooks/useSimulation'
import { headlinePoints } from '@/utils/format'
import type { LineupSlot, Player, RankedProjection } from '@/api/schemas'

/**
 * The manager's roster, resolved against this week's board, and the lineup it
 * fields.
 *
 * One definition shared by My team, which edits it, and the dashboard, which
 * summarises it. Two copies of "which players start" would eventually disagree
 * about who is ruled out or which slot a player fits, and the dashboard would
 * then summarise a lineup My team does not show.
 *
 * The lineup is the simulation builder's autofill over the available players in
 * board order — a starting point filled slot by slot, not an optimiser — unless
 * the manager chose one (`useLineupChoice`). Anyone ruled out is kept out of it
 * and named, never silently dropped or zeroed.
 */
export function useMyLineup() {
  const [ids, setIds] = useRoster()
  const [choice, setChoice] = useLineupChoice()
  const board = useBoard()
  const catalog = useLineupCatalog()
  const identities = usePlayers(ids)

  const byId = useMemo(() => {
    const map = new Map<string, RankedProjection>()
    for (const entry of board.data?.data ?? []) map.set(entry.projection.player.player_id, entry)
    return map
  }, [board.data])

  const roster = useMemo(
    () =>
      ids.map((id, index) => {
        const entry = byId.get(id)
        const player: Player | undefined = entry?.projection.player ?? identities[index]?.data
        return { id, entry, player }
      }),
    [ids, byId, identities],
  )

  const { projected, ruledOut, available, unprojected } = useMemo(() => {
    const projected = roster
      .filter((r) => r.entry)
      .map((r) => r.entry as RankedProjection)
      .sort((a, b) => a.rank - b.rank)
    return {
      projected,
      ruledOut: projected.filter((e) => e.projection.context.injury?.will_not_play),
      available: projected.filter((e) => !e.projection.context.injury?.will_not_play),
      unprojected: roster.filter((r) => !r.entry),
    }
  }, [roster])

  const best = useMemo(
    () =>
      catalog.isPending ? [] : autofillLineup(emptyLineup(catalog.format), available, catalog.slots, []),
    [catalog.isPending, catalog.format, catalog.slots, available],
  )
  const lineup = useMemo(
    () =>
      catalog.isPending
        ? []
        : (chosenLineup(emptyLineup(catalog.format), choice, available, catalog.slots) ?? best),
    [catalog.isPending, catalog.format, catalog.slots, choice, available, best],
  )

  const starters = new Set(lineup.map((row) => row.player?.player_id).filter(Boolean))
  const bench = available.filter((e) => !starters.has(e.projection.player.player_id))

  const fits = (entry: RankedProjection, slot: string) => {
    const position = entry.projection.player.position
    return position ? eligiblePositions(catalog.slots, slot).includes(position) : false
  }

  const simulateHref = `/simulation?${TEAM_A_PARAM}=${encodeURIComponent(
    encodeLineup(
      lineup
        .filter((r) => r.player)
        .map((r) => ({ slot: r.slot, player_id: r.player?.player_id as string })),
    ),
  )}`

  // Every change writes the whole lineup, slot by slot, so the link always
  // describes exactly what is on screen. Landing back on the default clears it.
  const writeLineup = (players: (Player | null)[]) => {
    const next = players.map((player) => player?.player_id ?? '')
    setChoice(sameIds(next, lineupIds(best)) ? null : next)
  }

  return {
    ids,
    setIds,
    choice,
    setChoice,
    board,
    catalog,
    byId,
    roster,
    projected,
    ruledOut,
    available,
    unprojected,
    best,
    lineup,
    bench,
    customised: !sameLineup(lineup, best),
    total: lineupPoints(lineup, byId),
    bestTotal: lineupPoints(best, byId),
    openSlots: lineup.filter((row) => !row.player).length,
    fits,
    simulateHref,
    writeLineup,
  }
}

/**
 * The closest start/sit decision on a lineup: the bench player projected
 * nearest to (or above) a starter whose slot they fit.
 *
 * "Closest" is the smallest gap between two *published* projections, and the
 * caller presents it as a pair to compare, not as a verdict — the gap between
 * two projections is usually far smaller than either player's weekly swing.
 */
export function closestCall(
  lineup: LineupRow[],
  bench: RankedProjection[],
  byId: Map<string, RankedProjection>,
  fits: (entry: RankedProjection, slot: string) => boolean,
): { starter: RankedProjection; challenger: RankedProjection; slot: string; gap: number } | null {
  let closest: ReturnType<typeof closestCall> = null
  for (const challenger of bench) {
    const challengerPoints = headlinePoints(challenger.projection.prediction.points).value
    if (challengerPoints === null) continue
    for (const row of lineup) {
      if (!row.player || !fits(challenger, row.slot)) continue
      const starter = byId.get(row.player.player_id)
      const starterPoints = starter ? headlinePoints(starter.projection.prediction.points).value : null
      if (!starter || starterPoints === null) continue
      const gap = starterPoints - challengerPoints
      if (closest === null || gap < closest.gap) closest = { starter, challenger, slot: row.slot, gap }
    }
  }
  return closest
}

/**
 * The lineup the manager chose, or null when there is no usable choice.
 *
 * A stored choice is re-checked against this week every time: a player who
 * left the roster, has no projection, is ruled out or no longer fits the slot
 * leaves that slot empty rather than being silently replaced. A choice written
 * for a different lineup format (a different slot count) is ignored outright.
 */
function chosenLineup(
  rows: LineupRow[],
  choice: string[] | null,
  available: RankedProjection[],
  slots: LineupSlot[],
): LineupRow[] | null {
  if (!choice || choice.length !== rows.length) return null
  const players = new Map(available.map((entry) => [entry.projection.player.player_id, entry.projection.player]))
  const used = new Set<string>()
  return rows.map((row, index) => {
    const player = players.get(choice[index] ?? '')
    if (!player || used.has(player.player_id)) return row
    if (!player.position || !eligiblePositions(slots, row.slot).includes(player.position)) return row
    used.add(player.player_id)
    return { ...row, player }
  })
}

function lineupPoints(rows: LineupRow[], byId: Map<string, RankedProjection>): number {
  return rows.reduce((sum, row) => {
    const entry = row.player ? byId.get(row.player.player_id) : undefined
    return sum + (headlinePoints(entry?.projection.prediction.points).value ?? 0)
  }, 0)
}

function lineupIds(rows: LineupRow[]): string[] {
  return rows.map((row) => row.player?.player_id ?? '')
}

function sameIds(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((id, index) => id === b[index])
}

function sameLineup(a: LineupRow[], b: LineupRow[]): boolean {
  return sameIds(lineupIds(a), lineupIds(b))
}
