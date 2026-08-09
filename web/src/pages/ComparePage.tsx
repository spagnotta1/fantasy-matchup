import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { GitCompareArrows } from 'lucide-react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Select } from '@/components/ui/Select'
import { Skeleton, SkeletonText } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { CalibrationNotice } from '@/components/domain/CalibrationNotice'
import { ComparisonGrid } from '@/features/comparison/ComparisonGrid'
import { HeadToHeadCard } from '@/features/comparison/HeadToHead'
import { PlayerPicker } from '@/features/comparison/PlayerPicker'
import {
  MAX_COMPARISON_PLAYERS,
  MIN_COMPARISON_PLAYERS,
  useComparison,
  useStartSit,
} from '@/hooks/useCompare'
import { usePlayers } from '@/hooks/useProjections'
import type { Player } from '@/api/schemas'

const PLAYERS_PARAM = 'players'

/**
 * Side-by-side start/sit.
 *
 * The selection lives in the query string, which is what makes a comparison
 * shareable — "who do I start" is a question people ask each other, and a link
 * that reopens the same six players in the same format is most of the answer.
 *
 * Two things this screen refuses to do. It does not compute a winner from the
 * two projections: the win probability comes from `/compare`, which integrates
 * both stored distributions, and half a point of projection is not half a point
 * of certainty. And it never converts a toss-up into a pick.
 */
export default function ComparePage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const playerIds = useMemo(() => {
    const raw = searchParams.get(PLAYERS_PARAM)
    if (!raw) return []
    // De-duplicated and capped here rather than at the request: an over-long
    // URL should open a working screen, not a 422.
    return [...new Set(raw.split(',').map((id) => id.trim()).filter(Boolean))].slice(
      0,
      MAX_COMPARISON_PLAYERS,
    )
  }, [searchParams])

  const setPlayerIds = useCallback(
    (next: string[]) => {
      setSearchParams(
        (current) => {
          const params = new URLSearchParams(current)
          if (next.length === 0) params.delete(PLAYERS_PARAM)
          else params.set(PLAYERS_PARAM, next.join(','))
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const identityQueries = usePlayers(playerIds)
  const selected = identityQueries
    .map((query) => query.data)
    .filter((player): player is Player => player !== undefined)

  const comparison = useComparison(playerIds)
  const entries = comparison.data?.data.entries ?? []

  const onAdd = (player: Player) => {
    if (playerIds.includes(player.player_id)) return
    setPlayerIds([...playerIds, player.player_id])
  }

  const onRemove = (playerId: string) => {
    setPlayerIds(playerIds.filter((id) => id !== playerId))
  }

  return (
    <>
      <PageHeader
        title="Compare"
        question="Which of these players should I start this week?"
      />

      <PlayerPicker selected={selected} onAdd={onAdd} onRemove={onRemove} />

      {playerIds.length < MIN_COMPARISON_PLAYERS ? (
        <Card>
          <EmptyState
            icon={<GitCompareArrows aria-hidden className="size-5" />}
            title="Pick two players to compare"
            description={`Search above to add players — two at a minimum, ${MAX_COMPARISON_PLAYERS} at most. Each pair gets a win probability computed from both players' published outcome distributions.`}
          />
        </Card>
      ) : comparison.isPending ? (
        <ComparisonSkeleton />
      ) : comparison.isError ? (
        <Card>
          <ErrorState error={comparison.error} onRetry={() => void comparison.refetch()} />
        </Card>
      ) : entries.length === 0 ? (
        <Card>
          <EmptyState
            title="No projections for these players"
            description="None of the selected players has a published projection for this week — a bye, an inactive listing, or a run that does not cover them."
          />
        </Card>
      ) : (
        <Refreshing active={comparison.isPlaceholderData}>
          <div className="space-y-6">
          <CalibrationNotice projections={entries.map((entry) => entry.projection)} />
          <NoticeList notices={comparison.data.meta.notices} />

          <ComparisonGrid entries={entries} />

          <section aria-labelledby="head-to-head">
            <h2 id="head-to-head" className="text-ink mb-1 text-base font-semibold tracking-tight">
              Head to head
            </h2>
            <p className="text-ink-secondary mb-4 max-w-2xl text-sm leading-relaxed">
              Each player against the next one down the list. A probability here is the share of
              simulated outcomes in which one player outscores the other, not a confidence in the
              projection.
            </p>

            <div className="grid gap-4 xl:grid-cols-2">
              {comparison.data.data.head_to_head.map((result) => (
                <HeadToHeadCard
                  key={`${result.a.projection.player.player_id}-${result.b.projection.player.player_id}`}
                  result={result}
                />
              ))}
            </div>

            {comparison.data.data.head_to_head.length === 0 && (
              <Card>
                <EmptyState
                  title="No head-to-head available"
                  description="A pairing needs a stored outcome distribution on both sides. One of these players does not have one for this week."
                />
              </Card>
            )}
          </section>

          {playerIds.length > 2 && <ArbitraryPair players={entries.map((e) => e.projection.player)} />}
          </div>
        </Refreshing>
      )}
    </>
  )
}

/**
 * Any two of the selected players, not just consecutive ones.
 *
 * `/compare` grades the ordering one step at a time, which answers "is the list
 * right" but not "should I start the first or the fourth". `/start-sit` exists
 * for exactly that pair, so the control is offered rather than the user being
 * asked to remove four players and add them back.
 */
function ArbitraryPair({ players }: { players: Player[] }) {
  const [chosenA, setA] = useState(players[0]?.player_id ?? '')
  const [chosenB, setB] = useState(players.at(-1)?.player_id ?? '')

  // The stored choice is validated during render rather than corrected by an
  // effect. Removing a player from the comparison would otherwise leave this
  // control pointing at someone who is no longer on screen for one frame, and
  // fire a request for them.
  const ids = players.map((player) => player.player_id)
  const a = ids.includes(chosenA) ? chosenA : (ids[0] ?? '')
  const b = ids.includes(chosenB) ? chosenB : (ids.at(-1) ?? '')

  const { data, isPending, isError, error, refetch } = useStartSit(a || null, b || null)
  const options = players.map((player) => ({
    value: player.player_id,
    label: `${player.name} (${player.position ?? '—'})`,
  }))

  return (
    <section aria-labelledby="any-pair">
      <h2 id="any-pair" className="text-ink mb-1 text-base font-semibold tracking-tight">
        Compare any two
      </h2>
      <p className="text-ink-secondary mb-4 max-w-2xl text-sm leading-relaxed">
        The pairs above are consecutive. Pick any two of your selected players for a direct
        head-to-head.
      </p>

      <Card className="mb-4">
        <CardBody className="flex flex-wrap items-end gap-3">
          <Select
            label="Player"
            value={a}
            onChange={(event) => setA(event.target.value)}
            options={options}
            className="min-w-48 flex-1"
          />
          <span className="text-ink-muted pb-2.5 text-sm">vs</span>
          <Select
            label="Player"
            value={b}
            onChange={(event) => setB(event.target.value)}
            options={options}
            className="min-w-48 flex-1"
          />
        </CardBody>
      </Card>

      {a === b ? (
        <Card>
          <EmptyState
            title="Pick two different players"
            description="A player cannot be compared with themselves."
          />
        </Card>
      ) : isPending ? (
        <Card>
          <CardBody>
            <SkeletonText lines={5} />
          </CardBody>
        </Card>
      ) : isError ? (
        <Card>
          <ErrorState error={error} onRetry={() => void refetch()} compact />
        </Card>
      ) : (
        <HeadToHeadCard result={data.data} />
      )}
    </section>
  )
}

function ComparisonSkeleton() {
  return (
    <div className="animate-fade-in space-y-6">
      <Card>
        <CardHeader as="h2" title={<Skeleton className="h-4 w-28" />} />
        <CardBody>
          <SkeletonText lines={8} />
        </CardBody>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        {Array.from({ length: 2 }, (_, index) => (
          <Card key={index}>
            <CardHeader as="h3" title={<Skeleton className="h-4 w-40" />} />
            <CardBody>
              <SkeletonText lines={5} />
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  )
}
