import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Tooltip } from '@/components/ui/Tooltip'
import { formatInteger } from '@/utils/format'

/**
 * What stands behind a player's floor-to-ceiling range.
 *
 * This replaced a "confidence" chip that read "Very low" on four boards in five
 * and "High" on none. The number behind it was the width of the range relative
 * to the projection, and weekly football is wide — so the chip told readers to
 * distrust ranges that hold the share of results they claim to. The width is
 * already on screen as the range itself; it is not graded here.
 *
 * What is said instead is what was measured. A normal range states how many
 * past player-weeks it was built from, in a neutral tone, because that is a
 * fact and not a warning. The two cases where the range is on weaker ground —
 * a short history, or a projection higher than any the range was built from —
 * carry the API's own sentence, which quotes the measurement.
 */
export function EvidenceChip({
  evidence,
  note,
  samples,
  size = 'sm',
}: {
  evidence: string
  note?: string | null
  samples?: number | null
  size?: 'sm' | 'md'
}) {
  const { label, tone } = describeEvidence(evidence, samples)

  return (
    <Tooltip
      content={
        <>
          <strong className="font-semibold">What the range is based on.</strong>{' '}
          {note ?? ESTABLISHED_DETAIL} This describes the range, not how good the player is.
        </>
      }
    >
      <Badge tone={tone} size={size}>
        {label}
      </Badge>
    </Tooltip>
  )
}

const ESTABLISHED_DETAIL =
  'The floor and ceiling come from how past players at this position with a similar projection actually scored.'

/** The chip's words and tone. */
function describeEvidence(
  evidence: string,
  samples?: number | null,
): { label: string; tone: BadgeTone } {
  switch (evidence) {
    case 'extrapolated':
      return { label: 'Beyond tested range', tone: 'caution' }
    case 'thin_history':
      return { label: 'Short history', tone: 'info' }
    case 'established':
      return {
        label:
          samples === null || samples === undefined
            ? 'Past results'
            : `${formatInteger(samples)} similar weeks`,
        tone: 'neutral',
      }
    default:
      return { label: 'No range', tone: 'neutral' }
  }
}
