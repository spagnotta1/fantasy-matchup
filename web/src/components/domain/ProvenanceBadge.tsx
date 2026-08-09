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
      'Produced by the published model run. Interval coverage and calibration for these numbers are measured and published.',
  },
  derived: {
    label: 'Derived',
    tone: 'info',
    icon: FunctionSquare,
    explanation:
      'Computed above the model from data the model never saw — for example a matchup grade from trailing defensive points allowed. Reproducible, but not validated as a prediction.',
  },
  context: {
    label: 'Context',
    tone: 'neutral',
    icon: Eye,
    explanation:
      'Observed and reported, but not an input to the projection. Weather, the betting market and injury designations do not move the number shown.',
  },
  actual: {
    label: 'Actual',
    tone: 'positive',
    icon: History,
    explanation: 'A recorded outcome from a completed game. Not a prediction.',
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
      {reason ?? 'This is shown as context for your own judgement.'}
    </p>
  )
}
