import { Hammer } from 'lucide-react'

import { Card } from '@/components/ui/Card'

/**
 * An honest placeholder for a route that exists but is not built yet.
 *
 * Deliberately not a fake screen. Mock rows and lorem numbers on an analytics
 * product are worse than nothing: they are indistinguishable from real output
 * and every reviewer has to ask which parts are real. This says what the view
 * will do, what it will call, and when it lands.
 */
export function PhasePlaceholder({
  phase,
  summary,
  planned,
  endpoints,
}: {
  phase: string
  summary: string
  planned: string[]
  endpoints: string[]
}) {
  return (
    <Card className="animate-rise overflow-hidden">
      <div className="border-line flex items-center gap-3 border-b px-5 py-4">
        <span className="bg-accent-soft text-accent-text flex size-9 items-center justify-center rounded-full">
          <Hammer aria-hidden className="size-4" />
        </span>
        <div>
          <p className="text-ink text-sm font-semibold">Not built yet — {phase}</p>
          <p className="text-ink-muted mt-0.5 text-xs">
            The route, shell and data layer are in place; the view itself lands in this phase.
          </p>
        </div>
      </div>

      <div className="grid gap-6 p-5 sm:grid-cols-2">
        <div>
          <p className="text-ink-secondary text-sm leading-relaxed">{summary}</p>
          <h2 className="text-ink-muted mt-5 text-xs font-semibold tracking-wide uppercase">
            What this view will do
          </h2>
          <ul className="text-ink-secondary mt-2 space-y-1.5 text-sm">
            {planned.map((item) => (
              <li key={item} className="flex gap-2">
                <span aria-hidden className="text-ink-muted">
                  •
                </span>
                {item}
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h2 className="text-ink-muted text-xs font-semibold tracking-wide uppercase">
            Backed by
          </h2>
          <ul className="mt-2 space-y-1.5">
            {endpoints.map((endpoint) => (
              <li
                key={endpoint}
                className="bg-surface-sunken text-ink-secondary rounded-md px-2.5 py-1.5 font-mono text-xs"
              >
                {endpoint}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  )
}
