import { Dices, Percent, Scale, ShieldQuestion } from 'lucide-react'

import { Card, CardBody } from '@/components/ui/Card'

/**
 * What the empty results area says before the first run.
 *
 * The screen's whole bottom half was blank until a simulation had been run,
 * which is the moment a new user is deciding whether filling fourteen slots is
 * worth it. This is the answer to "what do I get for that", and it is written
 * from what the response actually contains — the four panels below are exactly
 * the four this lists.
 *
 * It states the independence assumption here rather than only on the result,
 * because a user who is about to spend two minutes building a matchup is
 * entitled to know what the answer assumes before they start, not after.
 */
export function PreRunExplainer() {
  const items = [
    {
      icon: Percent,
      title: 'An estimated win probability',
      detail:
        'The share of simulated weeks each lineup finished ahead in — not a prediction of the result.',
    },
    {
      icon: Dices,
      title: 'Both score distributions',
      detail:
        'Where each total lands across every draw, on one scale, so the overlap is visible rather than implied.',
    },
    {
      icon: Scale,
      title: 'Where the gap comes from',
      detail:
        'Mean simulated points by position, and the players whose weeks are least settled on either side.',
    },
    {
      icon: ShieldQuestion,
      title: 'What it did not account for',
      detail:
        'Players are drawn independently by default, kickers and defences are not projected, and no injury or weather adjustment is applied. Every one of those is read from the response.',
    },
  ]

  return (
    <Card>
      <CardBody className="p-5 sm:p-6">
        <h2 className="text-ink text-sm font-semibold">What a run will tell you</h2>
        <p className="text-ink-secondary mt-1 text-sm leading-relaxed">
          Fill both lineups and run the simulation. Every draw is taken from a published outcome
          distribution — nothing on the result is computed in the browser.
        </p>

        <dl className="mt-4 grid gap-x-6 gap-y-4 sm:grid-cols-2">
          {items.map((item) => (
            // A <dl> may only hold <dt>/<dd>, or a <div> that groups them —
            // and that div may hold nothing else. The icon therefore lives
            // inside the <dt> rather than beside it, and the <dd> is indented
            // by the icon's width plus the gap so the two lines still align.
            <div key={item.title} className="min-w-0">
              <dt className="text-ink flex items-start gap-2.5 text-xs font-semibold">
                <span className="bg-surface-sunken text-ink-secondary flex size-7 shrink-0 items-center justify-center rounded-full">
                  <item.icon aria-hidden className="size-3.5" />
                </span>
                <span className="mt-1.5">{item.title}</span>
              </dt>
              <dd className="text-ink-muted ps-[2.375rem] text-xs leading-relaxed">
                {item.detail}
              </dd>
            </div>
          ))}
        </dl>
      </CardBody>
    </Card>
  )
}
