import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Tooltip } from '@/components/ui/Tooltip'
import { formatLabel, formatPercent } from '@/utils/format'

const TONES: Record<string, BadgeTone> = {
  high: 'positive',
  moderate: 'info',
  low: 'caution',
  very_low: 'negative',
  unknown: 'neutral',
}

/**
 * How much information the model had.
 *
 * The tooltip says the thing people get wrong about this number, every time:
 * confidence is not quality. A confidently projected bad player is still a bad
 * player, and a low-confidence projection is not a bad projection — it is a
 * wide one.
 */
export function ConfidenceChip({
  label,
  value,
  size = 'sm',
}: {
  label: string
  value?: number | null
  size?: 'sm' | 'md'
}) {
  const tone = TONES[label] ?? 'neutral'

  return (
    <Tooltip
      content={
        <>
          <strong className="font-semibold">How much the model knows</strong>
          {value !== null && value !== undefined ? ` (${formatPercent(value)})` : ''} — not how
          good the player is. Low confidence means a wider range of outcomes, not a worse
          projection.
        </>
      }
    >
      <Badge tone={tone} size={size}>
        {formatLabel(label)}
      </Badge>
    </Tooltip>
  )
}
