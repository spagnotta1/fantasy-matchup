import { CloudRain } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import type { Projection } from '@/api/schemas'

/**
 * The caveats that sit above a projection, beside the name they qualify.
 *
 * A designation of "Out" is not a detail of the row, it is a reason to doubt
 * the number in it, so it is on the board at every width and in every view.
 * It used to be on the cards only: a desktop table showed a ruled-out player's
 * projection with nothing beside it. Weather is observed context and never an
 * input, and its chip says only that there is something to read.
 */
export function RowFlags({ projection }: { projection: Projection }) {
  return (
    <>
      <InjuryBadge injury={projection.context.injury} />
      {projection.context.weather?.is_adverse && (
        <Badge tone="info" icon={<CloudRain className="size-3" />}>
          Weather
        </Badge>
      )}
    </>
  )
}
