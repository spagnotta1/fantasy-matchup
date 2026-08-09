import { useMemo, useState } from 'react'
import { CloudRain, HeartPulse, TrendingDown, MoveUp } from 'lucide-react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState } from '@/components/feedback/States'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { ProjectionValue } from '@/components/domain/ProjectionValue'
import { useBoard } from '@/hooks/useProjections'
import { formatPercent, formatPoints } from '@/utils/format'
import type { RankedProjection } from '@/api/schemas'

type Lens = 'ceiling' | 'bust' | 'injury' | 'weather'

/**
 * The four things that make a week unusual.
 *
 * Every lens is a **filter or an ordering over numbers the API published** —
 * `ceiling`, `bust_probability`, `is_questionable_or_worse`, `is_adverse`.
 * Nothing here subtracts, averages or rescales anything.
 *
 * That constraint removed a panel. An obvious "biggest upside" lens would rank
 * by ceiling minus projection — but the stored intervals are bucketed, so that
 * difference ties across whole groups of players (eight running backs share the
 * widest bucket exactly). The "ranking" would be a tie broken by array order.
 * The ceiling itself is shown instead: a published number, and one that really
 * does separate players across positions.
 *
 * Split by a control instead of shown as four lists, because a manager asks one
 * of these questions at a time and four stacked panels of six rows is a wall.
 */
export function RiskOpportunity() {
  const [lens, setLens] = useState<Lens>('ceiling')
  const { data, isPending, isError, error, refetch } = useBoard()

  const entries = useMemo(() => {
    if (!data) return []
    return selectByLens(data.data, lens)
  }, [data, lens])

  return (
    <Card>
      <CardHeader
        as="h2"
        title="Risk and opportunity"
        description="Players whose week carries more uncertainty than their projection alone suggests."
        action={
          <SegmentedControl<Lens>
            label="Which risk to show"
            size="sm"
            value={lens}
            onChange={setLens}
            options={[
              { value: 'ceiling', label: 'Ceiling', icon: <MoveUp className="size-3.5" /> },
              { value: 'bust', label: 'Bust risk', icon: <TrendingDown className="size-3.5" /> },
              { value: 'injury', label: 'Injury', icon: <HeartPulse className="size-3.5" /> },
              { value: 'weather', label: 'Weather', icon: <CloudRain className="size-3.5" /> },
            ]}
          />
        }
      />

      {isPending ? (
        <SkeletonTable rows={5} columns={3} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} compact />
      ) : entries.length === 0 ? (
        <EmptyState title={EMPTY[lens].title} description={EMPTY[lens].description} />
      ) : (
        <CardBody className="p-0">
          <ul className="divide-line divide-y">
            {entries.map((entry) => (
              <li
                key={entry.projection.player.player_id}
                className="hover:bg-surface-hover flex items-center gap-3 px-5 py-2.5 transition-colors"
              >
                <PlayerIdentity
                  player={entry.projection.player}
                  team={entry.projection.team}
                  size="sm"
                  className="flex-1"
                  subtitle={detailFor(entry, lens)}
                />
                <span className="w-14 shrink-0 text-right">
                  <ProjectionValue points={entry.projection.prediction.points} />
                </span>
              </li>
            ))}
          </ul>
          <p className="text-ink-muted border-line border-t px-5 py-3 text-xs leading-relaxed">
            {FOOTNOTE[lens]}
          </p>
        </CardBody>
      )}
    </Card>
  )
}

const LIMIT = 6

/** A minimum projection, so the lists are not dominated by deep-bench noise. */
const RELEVANCE_FLOOR = 6

function selectByLens(entries: RankedProjection[], lens: Lens): RankedProjection[] {
  const relevant = entries.filter((entry) => {
    const expected = entry.projection.prediction.points.median ?? entry.projection.prediction.points.predicted
    return expected >= RELEVANCE_FLOOR
  })

  switch (lens) {
    case 'ceiling':
      return relevant
        .filter((entry) => entry.projection.prediction.points.ceiling !== null)
        .sort(
          (a, b) =>
            (b.projection.prediction.points.ceiling ?? 0) -
            (a.projection.prediction.points.ceiling ?? 0),
        )
        .slice(0, LIMIT)

    case 'bust':
      return relevant
        .filter((entry) => (entry.projection.prediction.points.bust_probability ?? 0) > 0)
        .sort(
          (a, b) =>
            (b.projection.prediction.points.bust_probability ?? 0) -
            (a.projection.prediction.points.bust_probability ?? 0),
        )
        .slice(0, LIMIT)

    case 'injury':
      // Not scored or ranked — a designation is a fact, so these are ordered by
      // projection, which is the order they matter to a lineup decision.
      return relevant
        .filter((entry) => entry.projection.context.injury?.is_questionable_or_worse)
        .slice(0, LIMIT)

    case 'weather':
      return relevant.filter((entry) => entry.projection.context.weather?.is_adverse).slice(0, LIMIT)
  }
}

function detailFor(entry: RankedProjection, lens: Lens): React.ReactNode {
  const { points } = entry.projection.prediction
  const position = entry.projection.player.position
  const opponent = `${entry.projection.is_home ? 'vs' : '@'} ${entry.projection.opponent}`

  switch (lens) {
    case 'ceiling':
      return `${position} ${opponent} · ceiling ${formatPoints(points.ceiling)} · ${formatPercent(points.boom_probability)} chance of clearing ${formatPoints(points.boom_threshold)}`
    case 'bust':
      return `${position} ${opponent} · ${formatPercent(points.bust_probability)} chance of under ${formatPoints(points.bust_threshold)}`
    case 'injury': {
      const injury = entry.projection.context.injury
      return `${position} ${opponent} · listed ${injury?.report_status ?? 'questionable'}${injury?.will_not_play ? ' — not expected to play' : ''}`
    }
    case 'weather': {
      const weather = entry.projection.context.weather
      const bits = [
        weather?.wind_mph ? `${Math.round(weather.wind_mph)} mph wind` : null,
        weather?.precipitation_probability
          ? `${formatPercent(weather.precipitation_probability)} precipitation`
          : null,
        weather?.temperature_f !== null && weather?.temperature_f !== undefined
          ? `${Math.round(weather.temperature_f)}°F`
          : null,
      ].filter(Boolean)
      return `${position} ${opponent} · ${bits.join(', ') || 'adverse conditions'}`
    }
  }
}

const EMPTY: Record<Lens, { title: string; description: string }> = {
  ceiling: {
    title: 'No ceiling estimates',
    description: 'The published run stored no P90 for this week, so ceilings cannot be shown.',
  },
  bust: {
    title: 'No bust probabilities',
    description: 'The published run did not store bust probabilities for this week.',
  },
  injury: {
    title: 'No injury designations',
    description:
      'No projected player carries a questionable-or-worse designation on this slate. Injury reports move all week, so check again closer to kickoff.',
  },
  weather: {
    title: 'No weather concerns',
    description:
      'No game on this slate is flagged for adverse conditions — that means under 20 mph wind and under 60% precipitation at every outdoor venue.',
  },
}

const FOOTNOTE: Record<Lens, string> = {
  ceiling:
    'Ceiling is the published P90 — a 1-in-10 outcome, not a target. Under this run the stored spreads are bucketed, so players in the same band rise and fall together in this list.',
  bust: 'Bust probability comes from the calibrated outcome distribution and is a model output.',
  injury:
    'Injury designations are reported, not applied. The projection beside each player does not adjust for the designation — a player listed Out still shows their full projected distribution.',
  weather:
    'Weather is observed context. The frozen model excludes it, so these projections do not account for wind or precipitation.',
}
