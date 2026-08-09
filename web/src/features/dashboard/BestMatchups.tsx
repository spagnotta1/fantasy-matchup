import { useMemo } from 'react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState } from '@/components/feedback/States'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { ProjectionValue } from '@/components/domain/ProjectionValue'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { useBoard } from '@/hooks/useProjections'
import { entryPoints } from '@/utils/board'
import { formatPoints } from '@/utils/format'

/** Only the top grades are worth a "best matchups" panel; below this it is noise. */
const FAVOURABLE_LETTERS = new Set(['A+', 'A', 'A-'])

/**
 * A projection floor for inclusion.
 *
 * Without it the panel fills with third-string players who happen to draw a
 * soft defence — a 2.8-point tight end with an A+ matchup is arithmetically
 * true and useless to someone setting a lineup. The question this panel answers
 * is "who that I might start has the softest draw", so the population is
 * startable players and the ordering within it is the projection.
 */
const STARTABLE_FLOOR = 8

/** Keeps the panel from becoming a quarterback list. See the selection comment. */
const MAX_PER_POSITION = 2

/**
 * Players drawing the softest defences this week.
 *
 * The panel filters and orders by the grade the API computed — it does not
 * grade anything. The provenance badge is on the header rather than each row
 * because every number in the panel shares it: a matchup grade is derived
 * above the model, and the projection beside it does not account for the
 * matchup at all.
 */
export function BestMatchups({ count = 6 }: { count?: number }) {
  const { data, isPending, isError, error, refetch } = useBoard()

  const favourable = useMemo(() => {
    if (!data) return []

    const eligible = data.data.filter((entry) => {
      const grade = entry.projection.matchup?.grade
      if (!grade?.graded || !grade.letter || !FAVOURABLE_LETTERS.has(grade.letter)) return false
      return (entryPoints(entry) ?? 0) >= STARTABLE_FLOOR
    })

    // The board arrives ranked by projection, so walking it in order gives the
    // strongest startable players with a top-graded draw. The per-position cap
    // is what stops that from being six quarterbacks: quarterbacks project
    // highest in every format, and a lineup has one.
    const perPosition = new Map<string, number>()
    const picked: typeof eligible = []
    for (const entry of eligible) {
      const position = entry.projection.player.position ?? 'UNK'
      const used = perPosition.get(position) ?? 0
      if (used >= MAX_PER_POSITION) continue
      perPosition.set(position, used + 1)
      picked.push(entry)
      if (picked.length === count) break
    }
    return picked
  }, [data, count])

  return (
    <Card>
      <CardHeader
        as="h2"
        title="Softest matchups"
        description="Startable players drawing an A-graded defence. A grade is a percentile across this week, not a verdict on the defence in absolute terms."
        action={<ProvenanceBadge provenance="derived" />}
      />

      {isPending ? (
        <SkeletonTable rows={count} columns={3} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} compact />
      ) : favourable.length === 0 ? (
        <EmptyState
          title="No standout matchups"
          description={
            data.data.length === 0
              ? 'There is no published board for this week yet.'
              : 'No startable projected player draws an A-grade matchup this week. Grades are withheld below three completed games of defensive history.'
          }
        />
      ) : (
        <CardBody className="p-0">
          <ul className="divide-line divide-y">
            {favourable.map((entry) => {
              const matchup = entry.projection.matchup
              return (
                <li
                  key={entry.projection.player.player_id}
                  className="hover:bg-surface-hover flex items-center gap-3 px-5 py-2.5 transition-colors"
                >
                  <PlayerIdentity
                    player={entry.projection.player}
                    team={entry.projection.team}
                    size="sm"
                    className="flex-1"
                    subtitle={
                      <>
                        {entry.projection.player.position} {entry.projection.is_home ? 'vs' : '@'}{' '}
                        {entry.projection.opponent}
                        {matchup?.fp_allowed_vs_position_l4 !== null &&
                          matchup?.fp_allowed_vs_position_l4 !== undefined && (
                            <>
                              {' · '}
                              {formatPoints(matchup.fp_allowed_vs_position_l4)} allowed/gm
                            </>
                          )}
                      </>
                    }
                  />
                  <MatchupGradeChip
                    grade={matchup?.grade}
                    opponent={entry.projection.opponent}
                    fpAllowed={matchup?.fp_allowed_vs_position_l4}
                  />
                  <span className="w-14 shrink-0 text-right">
                    <ProjectionValue points={entry.projection.prediction.points} />
                  </span>
                </li>
              )
            })}
          </ul>
        </CardBody>
      )}
    </Card>
  )
}
