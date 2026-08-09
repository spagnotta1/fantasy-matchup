import { Badge } from '@/components/ui/Badge'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { formatPoints } from '@/utils/format'
import type { PositionMatchup } from '@/api/schemas'

/**
 * One defence against one position, drawn on the scale the grade actually uses.
 *
 * The letter alone hides the thing that decides whether a matchup is worth
 * acting on: how far along the slate it sits. A B- and a C+ are adjacent
 * letters and can be four percentile points apart. The bar puts both on the
 * 0-100 scale the API graded them on, so a row of positions reads as "this is
 * the one to attack" at a glance instead of as four letters to compare.
 *
 * The scale is a percentile across the week, so the bar is directly comparable
 * between teams and positions. It is not a share of anything, and the fill
 * length carries no absolute meaning — which is why the points allowed are
 * printed beside it rather than encoded in the bar.
 */
export function MatchupMeter({
  matchup,
  /** Rendered at the left. Usually the position, sometimes the team. */
  label,
  /** The defence being graded, for the accessible description. */
  defense,
}: {
  matchup: PositionMatchup
  label: string
  defense?: string | null
}) {
  const { grade } = matchup
  const score = grade.graded ? Math.max(0, Math.min(100, grade.score ?? 0)) : null

  return (
    <div className="grid grid-cols-[2.5rem_1fr_auto] items-center gap-3">
      <span className="text-ink-secondary text-xs font-semibold">{label}</span>

      <div className="flex items-center gap-2">
        {score === null ? (
          <span className="text-ink-muted text-xs">Not enough history to grade</span>
        ) : (
          <>
            <div
              className="bg-surface-sunken relative h-2 min-w-16 flex-1 overflow-hidden rounded-full"
              role="img"
              aria-label={`${label} against ${defense ?? 'this defence'}: ${grade.letter ?? 'ungraded'}, ${Math.round(score)}th percentile of matchup softness this week, defensive rank ${grade.defense_rank ?? 'unknown'} of 32 where 1 is toughest.`}
            >
              <div
                className="bg-chart-series absolute inset-y-0 left-0 rounded-full transition-[width] duration-300"
                style={{ width: `${score}%` }}
              />
            </div>
            <span className="text-ink-muted tnum hidden w-24 shrink-0 text-right text-[0.6875rem] sm:block">
              {formatPoints(matchup.fp_allowed_l4)} allowed
            </span>
          </>
        )}
      </div>

      <span className="flex shrink-0 items-center gap-1.5">
        {grade.graded && grade.defense_rank !== null && grade.defense_rank !== undefined && (
          <Badge tone="neutral" className="tnum hidden md:inline-flex">
            #{grade.defense_rank}
          </Badge>
        )}
        <MatchupGradeChip grade={grade} opponent={defense} fpAllowed={matchup.fp_allowed_l4} align="end" />
      </span>
    </div>
  )
}
