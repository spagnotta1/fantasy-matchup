import { HelpCircle } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Tooltip } from '@/components/ui/Tooltip'
import type { MatchupGrade } from '@/api/schemas'
import { formatPoints } from '@/utils/format'
import { toneForLetter } from '@/utils/grades'

interface MatchupGradeChipProps {
  /** Null when the projection carries no matchup block at all — same story to tell. */
  grade: MatchupGrade | null | undefined
  opponent?: string | null
  /** Points allowed to this position over the trailing four games. */
  fpAllowed?: number | null
  size?: 'sm' | 'md'
  /** Pass `end` when the chip sits in a right-hand column. */
  align?: 'center' | 'end'
}

/**
 * A defensive matchup as the API states it: a letter, a rank, and a caveat.
 *
 * Two behaviours are contractual. An ungraded matchup renders as "not graded"
 * with the reason, never as a neutral C — Week 1 is legitimately ungraded and
 * inventing a middle grade would be a fabrication. And the tooltip always
 * carries the magnitude in points, because the letter is a *rank percentile*:
 * about 2.5 defences hold each letter every week, so an A means "one of the
 * best matchups on this slate", not "good in absolute terms".
 */
export function MatchupGradeChip({
  grade,
  opponent,
  fpAllowed,
  size = 'sm',
  align = 'center',
}: MatchupGradeChipProps) {
  if (!grade || !grade.graded || !grade.letter) {
    return (
      <Tooltip
        align={align}
        content={grade?.reason ?? 'Not enough completed defensive history to grade this matchup.'}
      >
        <Badge tone="neutral" size={size} icon={<HelpCircle className="size-3" />}>
          Not graded
        </Badge>
      </Tooltip>
    )
  }

  const parts = [
    opponent ? `Against ${opponent}.` : null,
    grade.defense_rank
      ? `Ranked ${grade.defense_rank} of 32 against this position, where 1 is the toughest.`
      : null,
    fpAllowed !== null && fpAllowed !== undefined
      ? `Allowed ${formatPoints(fpAllowed)} fantasy points per game to the position over the last ${grade.sample_games ?? 4} games.`
      : null,
    'Grades are percentiles across this week — an A means one of the softest matchups on the slate, not a soft defence in absolute terms.',
  ].filter(Boolean)

  return (
    <Tooltip content={parts.join(' ')} align={align}>
      <Badge tone={toneForLetter(grade.letter)} size={size}>
        <span className="tnum font-semibold">{grade.letter}</span>
        <span className="sr-only">matchup grade</span>
      </Badge>
    </Tooltip>
  )
}
