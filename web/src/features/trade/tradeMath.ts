/**
 * The trade analyzer's arithmetic, kept apart from the page so it can be read
 * (and tested) as arithmetic.
 *
 * Every input is a `derived` trade value: rest-of-season points above the
 * waiver wire, from this week's projection carried forward. Nothing here makes
 * those numbers any more certain than they are. The verdict is a statement
 * about the sum of two columns, and the page words it that way.
 */

import type { TradeValue } from '@/api/schemas'

/** Players a side can hold. */
export const SIDE_LIMIT = 5

/** Positions with a trade value; kickers and defences are not projected. */
export const TRADE_POSITIONS = ['QB', 'RB', 'WR', 'TE'] as const

/**
 * Below this share of the larger side, a trade is called close to even.
 *
 * A display threshold, not a measured one: nothing in this system has measured
 * how far apart two sides' rest-of-season values must be before the difference
 * survives the error in them. Ten percent is a round number that stops a
 * one-point gap on a two-hundred-point trade from being announced as a lean.
 */
export const EVEN_SHARE = 0.1

export type Lean = 'you' | 'them' | 'even'

export interface TradeBalance {
  give: number
  get: number
  /** What you get minus what you give. */
  gap: number
  /** `|gap|` as a share of the larger side, 0–1. */
  share: number
  lean: Lean
}

const total = (values: TradeValue[]) => values.reduce((sum, value) => sum + value.trade_value, 0)

function leanOf(give: number, get: number): { share: number; lean: Lean } {
  const larger = Math.max(give, get)
  const share = larger > 0 ? Math.abs(get - give) / larger : 0
  return { share, lean: share < EVEN_SHARE ? 'even' : get > give ? 'you' : 'them' }
}

export function tradeBalance(give: TradeValue[], get: TradeValue[]): TradeBalance {
  const giveTotal = total(give)
  const getTotal = total(get)
  return { give: giveTotal, get: getTotal, gap: getTotal - giveTotal, ...leanOf(giveTotal, getTotal) }
}

export interface EvenOut {
  /** Which side the added player goes on. */
  side: 'give' | 'get'
  /** Value range that would bring the trade inside the even band. */
  low: number
  high: number
  /** Overall ranks spanned by the players in that range. */
  rankLow: number | null
  rankHigh: number | null
  /** Players to suggest, closest to the gap first. */
  candidates: TradeValue[]
}

/**
 * The player value that would bring a lopsided trade inside the even band.
 *
 * Solved exactly rather than approximated as "about the gap", so the suggestion
 * and the verdict can never disagree: adding any player in `[low, high]` to the
 * lighter side produces a trade {@link tradeBalance} calls even. With `S` the
 * lighter side, `L` the heavier and `e` the band, the added value `x` must keep
 * `|L − (S + x)| < e · max(L, S + x)`, which is `L − S − eL < x < L/(1 − e) − S`.
 *
 * `preferred` — the manager's own roster, when giving — is searched first,
 * because "add one of your players ranked around #110" is only useful if you
 * have one.
 */
export function evenOut(
  balance: TradeBalance,
  pool: TradeValue[],
  exclude: Set<string>,
  preferred: Set<string> = new Set(),
  limit = 3,
): EvenOut | null {
  if (balance.lean === 'even') return null
  const side = balance.lean === 'you' ? 'give' : 'get'
  const heavier = Math.max(balance.give, balance.get)
  const lighter = Math.min(balance.give, balance.get)
  const low = Math.max(heavier - lighter - EVEN_SHARE * heavier, 0)
  const high = heavier / (1 - EVEN_SHARE) - lighter

  const fits = pool.filter(
    (value) => !exclude.has(value.player.player_id) && value.trade_value > low && value.trade_value < high,
  )
  const ranks = fits.map((value) => value.overall_rank)
  const target = Math.abs(balance.gap)
  const byCloseness = (a: TradeValue, b: TradeValue) =>
    Math.abs(a.trade_value - target) - Math.abs(b.trade_value - target)
  const own = side === 'give' ? fits.filter((value) => preferred.has(value.player.player_id)) : []
  const candidates = (own.length ? own : fits).slice().sort(byCloseness).slice(0, limit)

  return {
    side,
    low,
    high,
    rankLow: ranks.length ? Math.min(...ranks) : null,
    rankHigh: ranks.length ? Math.max(...ranks) : null,
    candidates,
  }
}

/** Whether a suggestion came from the manager's own roster. */
export function fromRoster(result: EvenOut, roster: Set<string>): boolean {
  return result.side === 'give' && result.candidates.some((value) => roster.has(value.player.player_id))
}

export interface LineupResult {
  /** Summed per-game rate of the starters. */
  total: number
  starters: TradeValue[]
}

/**
 * The best lineup a set of players fields, by per-game rate.
 *
 * Filled slot by slot, in format order, each with the best eligible player not
 * yet used. With the flexible slots last — which is how every format in the
 * catalog lists them — that greedy fill is the optimum: a dedicated slot never
 * gives up a player a later, wider slot could have used instead.
 */
export function bestLineup(
  players: TradeValue[],
  slots: string[],
  eligible: (slot: string) => string[],
): LineupResult {
  const ranked = players.slice().sort((a, b) => b.rate - a.rate)
  const used = new Set<string>()
  const starters: TradeValue[] = []
  for (const slot of slots) {
    const accepts = eligible(slot)
    const pick = ranked.find((value) => !used.has(value.player.player_id) && accepts.includes(value.position))
    if (!pick) continue
    used.add(pick.player.player_id)
    starters.push(pick)
  }
  return { total: starters.reduce((sum, value) => sum + value.rate, 0), starters }
}
