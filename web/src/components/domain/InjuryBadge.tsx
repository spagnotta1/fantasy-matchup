import { HeartPulse } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import type { Injury } from '@/api/schemas'

/**
 * The one injury caveat every screen showing a projection should carry.
 *
 * A designation of "Out" or "Questionable" is a hard caveat above the
 * statistical verdict — it must sit beside the number it qualifies, not be
 * omitted because the screen is a comparison or a lineup slot rather than a
 * ranked list. Renders nothing below "Questionable" — day-to-day report noise
 * (Probable, no designation) is not decision-relevant.
 */
export function InjuryBadge({ injury }: { injury: Injury | null | undefined }) {
  if (!injury?.is_questionable_or_worse) return null
  return (
    <Badge tone="caution" icon={<HeartPulse className="size-3" />}>
      {injury.report_status ?? 'Questionable'}
    </Badge>
  )
}
