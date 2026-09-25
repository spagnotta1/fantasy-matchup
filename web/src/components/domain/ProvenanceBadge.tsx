import { Cpu, Eye, FunctionSquare, History } from 'lucide-react'

import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Tooltip } from '@/components/ui/Tooltip'
import type { Provenance } from '@/api/schemas'

/**
 * Where a number came from.
 *
 * This is the API's central contract and therefore the product's. A projection
 * screen mixes three kinds of number that look identical and mean entirely
 * different things: the model's output, analysis computed above the model, and
 * context the model never consumed. Rendering them without the distinction is
 * the specific dishonesty this component exists to prevent.
 *
 * The copy is a short form of `GET /meta/provenance`; the full legend is
 * fetched and shown on Settings.
 */
const PRESENTATION: Record<
  Provenance,
  { label: string; tone: BadgeTone; icon: typeof Cpu; explanation: string }
> = {
  model: {
    label: 'Model',
    tone: 'accent',
    icon: Cpu,
    explanation:
      'Comes straight from the projection model. How accurate these numbers have been is tracked on the Track record page.',
  },
  derived: {
    label: 'Calculated',
    tone: 'info',
    icon: FunctionSquare,
    explanation:
      'Worked out separately from the projection — for example, a matchup grade based on points a defence has allowed recently. It does not change the projection, and its accuracy has not been tested.',
  },
  context: {
    label: 'Info only',
    tone: 'neutral',
    icon: Eye,
    explanation:
      'Shown for your information. It is not factored into the projection — injuries, weather and betting lines do not change the number shown.',
  },
  actual: {
    label: 'Actual',
    tone: 'positive',
    icon: History,
    explanation: 'What actually happened in a finished game. Not a prediction.',
  },
}

export function ProvenanceBadge({
  provenance,
  showLabel = true,
}: {
  provenance: Provenance
  showLabel?: boolean
}) {
  const { label, tone, icon: Icon, explanation } = PRESENTATION[provenance]

  return (
    <Tooltip content={explanation}>
      <Badge tone={tone} icon={<Icon className="size-3" />}>
        {showLabel ? label : <span className="sr-only">{label}</span>}
      </Badge>
    </Tooltip>
  )
}

/**
 * One row of the Settings legend: the badge and its plain-English meaning.
 *
 * Uses the badge's own wording so the legend matches the labels everywhere
 * else. The API's text is the fallback for a value this build does not know.
 */
export function ProvenanceLegendRow({ provenance, fallback }: { provenance: string; fallback: string }) {
  const known = provenance in PRESENTATION ? PRESENTATION[provenance as Provenance] : null
  return (
    <div className="grid gap-1 sm:grid-cols-[7rem_1fr] sm:gap-4">
      <dt>
        {known ? (
          <ProvenanceBadge provenance={provenance as Provenance} />
        ) : (
          <Badge tone="neutral">{provenance}</Badge>
        )}
      </dt>
      <dd className="text-ink-secondary text-sm leading-relaxed">{known?.explanation ?? fallback}</dd>
    </div>
  )
}

/**
 * The "this is not baked into the projection" notice.
 *
 * Rendered next to any context block whose `applied_to_projection` is false.
 * The API flips that flag on its own the day a model consumes the input, and
 * this component follows it — so the UI can never drift into implying the
 * projection accounts for the wind when it does not.
 */
export function NotAppliedNotice({ reason }: { reason?: string | null }) {
  return (
    <p className="text-ink-muted border-line mt-3 border-t pt-3 text-xs leading-relaxed">
      <span className="text-ink-secondary font-medium">Not included in the projection.</span>{' '}
      {reason ?? 'It is here to help you make your own call.'}
    </p>
  )
}
