import { Link } from 'react-router-dom'
import { ArrowRight, Shuffle } from 'lucide-react'

import { Card, CardBody } from '@/components/ui/Card'
import { useSlate } from '@/app/slate-context'

/**
 * The dashboard's way into the simulation.
 *
 * The product's most complete workflow had no front door: it was one item in
 * the navigation, indistinguishable from the settings page, on a screen whose
 * job is to answer "what should I care about this week?". A manager who has just
 * read the board is one question away from "so does my lineup beat theirs" — and
 * that question had no link.
 *
 * It renders only when there is a board to simulate against. Offering a
 * simulation for a week with no published run sends the user to a screen that
 * can only tell them no, which is the opposite of an entry point.
 */
export function SimulationCallout() {
  const slate = useSlate()
  if (!slate.resolved || !slate.hasPublishedBoard) return null

  return (
    <Card>
      <CardBody className="flex flex-wrap items-center gap-4 p-4 sm:p-5">
        <span className="bg-accent-soft text-accent-text flex size-10 shrink-0 items-center justify-center rounded-full">
          <Shuffle aria-hidden className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-ink text-sm font-semibold">Does your lineup beat theirs?</h2>
          <p className="text-ink-muted mt-0.5 text-xs leading-relaxed">
            Build both starting lineups for week {slate.week} and run a Monte Carlo over the
            published outcome distributions for an estimated win probability — with what it does
            not account for stated beside it.
          </p>
        </div>
        <Link
          to="/simulation"
          className="bg-accent text-on-accent hover:bg-accent-hover inline-flex h-10 shrink-0 items-center gap-2 rounded-[var(--radius-control)] px-4 text-sm font-medium transition-colors"
        >
          Simulate a matchup
          <ArrowRight aria-hidden className="size-4" />
        </Link>
      </CardBody>
    </Card>
  )
}
