import { Construction } from 'lucide-react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import type { PositionSupport } from '@/api/schemas'

/**
 * A position the API recognises but does not project.
 *
 * The endpoint answers these with a 422 carrying exactly this explanation, so
 * requesting one and rendering the error would work. It is not requested,
 * because the catalog already said so before the click — and because a refusal
 * shown as an error state reads as a failure, when it is a documented boundary
 * of what the model covers.
 *
 * The blocking work is listed rather than summarised as "coming soon". A
 * fantasy manager deciding whether to wait for kicker projections is better
 * served by knowing they need a scoring vocabulary the model does not have.
 */
export function UnprojectedPosition({ support }: { support: PositionSupport }) {
  return (
    <Card>
      <CardHeader
        as="h2"
        title={`${support.label} projections are not published yet`}
        description="This position is recognised by the API but is not covered by the current model."
        action={
          <span className="bg-caution-soft text-caution-text flex size-9 items-center justify-center rounded-full">
            <Construction aria-hidden className="size-4" />
          </span>
        }
      />
      <CardBody className="space-y-4">
        {support.reason && (
          <p className="text-ink-secondary max-w-2xl text-sm leading-relaxed">{support.reason}</p>
        )}

        {support.blocked_on.length > 0 && (
          <div>
            <h3 className="text-ink-muted mb-2 text-xs font-semibold tracking-wide uppercase">
              What it is waiting on
            </h3>
            <ul className="text-ink-secondary space-y-1.5 text-sm">
              {support.blocked_on.map((item) => (
                <li key={item} className="flex gap-2 leading-relaxed">
                  <span aria-hidden className="text-ink-muted">
                    •
                  </span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="text-ink-muted text-xs leading-relaxed">
          Nothing on this page estimates {support.label.toLowerCase()} scoring in the meantime. A
          made-up number is worse than a missing one.
        </p>
      </CardBody>
    </Card>
  )
}
