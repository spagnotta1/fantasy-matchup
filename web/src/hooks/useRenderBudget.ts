import { useState, useTransition } from 'react'

/**
 * Rows drawn before the reader asks for more.
 *
 * A full slate is ~640 players and each row is ~37 DOM nodes — an avatar, a
 * range bar, three chips with tooltips. Drawing all of them on arrival was
 * measured at 18,400 nodes and 1.3 s of main-thread blocking under a 4x CPU
 * throttle, and every re-sort paid most of that again. A hundred rows is five
 * tiers deep at every position, which is further down the board than a weekly
 * start/sit decision ever reaches.
 *
 * This limits what is *drawn*, never what is *considered*: search, sort and
 * the result count all run over the whole slate, so a player ranked 400th is
 * one keystroke away and a sort by ceiling still ranks everyone. That is the
 * line `utils/board.ts` draws against sorting a paginated board, and it holds
 * here because the pagination is presentation-only.
 */
export const BOARD_PAGE_ROWS = 100

export interface RenderBudget {
  shown: number
  total: number
  step: number
  hasMore: boolean
  isPending: boolean
  showMore: () => void
  showAll: () => void
}

export function useRenderBudget(total: number, step = BOARD_PAGE_ROWS): RenderBudget {
  const [budget, setBudget] = useState(step)
  // A transition, so the button acknowledges the press immediately and the
  // several hundred new rows render without freezing the page.
  const [isPending, startTransition] = useTransition()
  const shown = Math.min(total, budget)

  return {
    shown,
    total,
    step,
    hasMore: shown < total,
    isPending,
    showMore: () => startTransition(() => setBudget((current) => current + step)),
    showAll: () => startTransition(() => setBudget(Number.POSITIVE_INFINITY)),
  }
}
