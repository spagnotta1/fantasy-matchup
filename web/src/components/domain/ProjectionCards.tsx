import { memo, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { CloudRain } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { ShowMoreRows } from '@/components/domain/BoardBudget'
import { useRenderBudget } from '@/hooks/useRenderBudget'
import { ConfidenceChip } from '@/components/domain/ConfidenceChip'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { boardCeiling, groupByTier } from '@/utils/board'
import { formatPoints } from '@/utils/format'
import type { RankedProjection } from '@/api/schemas'

/**
 * The touch view.
 *
 * Not the table with the columns removed. A card leads with the projection —
 * the number the whole page is about — and puts the range under it, because on
 * a phone a manager is checking one player at a time rather than scanning a
 * ranking. The whole card is the tap target.
 */
export const ProjectionCards = memo(function ProjectionCards({
  entries,
  /** Prints the rank in a leading badge. Off in the explorer, on in rankings. */
  showRank = false,
  rankMode = 'overall',
  /** Breaks the grid into tier sections. Rank order only — see `groupByTier`. */
  showTiers = false,
}: {
  entries: RankedProjection[]
  showRank?: boolean
  rankMode?: 'overall' | 'positional'
  showTiers?: boolean
}) {
  // One scale for every card on the page, including across tier sections and
  // rows not yet revealed, so a range bar in tier 4 is comparable to one in
  // tier 1 and nothing rescales when more cards are shown.
  const scaleMax = useMemo(() => boardCeiling(entries), [entries])
  const tierSizes = useMemo(() => {
    const sizes = new Map<number, number>()
    for (const entry of entries) sizes.set(entry.tier, (sizes.get(entry.tier) ?? 0) + 1)
    return sizes
  }, [entries])

  const budget = useRenderBudget(entries.length)
  const visible = useMemo(() => entries.slice(0, budget.shown), [entries, budget.shown])

  if (!showTiers) {
    return (
      <>
        <CardGrid entries={visible} scaleMax={scaleMax} showRank={showRank} rankMode={rankMode} />
        <ShowMoreRows budget={budget} />
      </>
    )
  }

  return (
    <>
      <div className="space-y-6">
        {groupByTier(visible).map((group) => {
          const size = tierSizes.get(group.tier) ?? group.entries.length
          return (
            <section key={group.tier} aria-labelledby={`tier-${group.tier}`}>
              {/*
                h2, not h3. A tier is a top-level division of the board, and the
                page's h1 is the only heading above it — the table view expresses
                the same grouping with rows rather than headings, so this is the
                one place the level is visible, and at h3 it skipped a level for
                anyone navigating the card view by heading.
              */}
              <h2
                id={`tier-${group.tier}`}
                className="text-ink-secondary mb-2 text-xs font-semibold tracking-wide uppercase"
              >
                Tier {group.tier}
                <span className="text-ink-muted ml-2 font-normal normal-case">
                  {size} {size === 1 ? 'player' : 'players'}
                </span>
              </h2>
              <CardGrid
                entries={group.entries}
                scaleMax={scaleMax}
                showRank={showRank}
                rankMode={rankMode}
              />
            </section>
          )
        })}
      </div>
      <ShowMoreRows budget={budget} />
    </>
  )
})

function CardGrid({
  entries,
  scaleMax,
  showRank,
  rankMode,
}: {
  entries: RankedProjection[]
  scaleMax: number
  showRank: boolean
  rankMode: 'overall' | 'positional'
}) {
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {entries.map((entry) => (
        <ProjectionCard
          key={entry.projection.player.player_id}
          entry={entry}
          scaleMax={scaleMax}
          showRank={showRank}
          rankMode={rankMode}
        />
      ))}
    </ul>
  )
}

/** One card, memoised so a re-sort moves it instead of re-rendering it. */
const ProjectionCard = memo(function ProjectionCard({
  entry,
  scaleMax,
  showRank,
  rankMode,
}: {
  entry: RankedProjection
  scaleMax: number
  showRank: boolean
  rankMode: 'overall' | 'positional'
}) {
  const { projection } = entry
  const { points } = projection.prediction
  const injury = projection.context.injury
  const weather = projection.context.weather

  return (
    <li className="deferred-card">
      <Link
        to={`/players/${encodeURIComponent(projection.player.player_id)}`}
        className="bg-surface border-line hover:border-line-strong focus-visible:outline-focus block rounded-[var(--radius-card)] border p-4 shadow-card transition-colors"
      >
        <div className="flex items-start gap-3">
          {showRank && (
            <span className="bg-surface-sunken text-ink-secondary tnum mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold">
              {rankMode === 'positional' ? entry.positional_rank : entry.rank}
            </span>
          )}
          <PlayerAvatar player={projection.player} />
          <div className="min-w-0 flex-1">
            <p className="text-ink truncate text-sm font-medium">{projection.player.name}</p>
            <p className="text-ink-muted truncate text-xs">
              {projection.player.position} · {projection.team}{' '}
              {projection.is_home ? 'vs' : '@'} {projection.opponent}
            </p>
          </div>
          <div className="text-right">
            <ProjectionValue
              points={points}
              size="lg"
              actualPoints={projection.actual_points}
            />
            <p className="text-ink-muted text-[0.625rem] tracking-wide uppercase">
              Projected
            </p>
          </div>
        </div>

        <div className="mt-3">
          <OutcomeRange
            floor={points.floor}
            median={points.median}
            ceiling={points.ceiling}
            scaleMax={scaleMax}
          />
          <p className="text-ink-muted mt-1 text-[0.6875rem]">
            Floor {formatPoints(points.floor)} · Ceiling {formatPoints(points.ceiling)}
          </p>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <MatchupGradeChip
            grade={projection.matchup?.grade}
            opponent={projection.opponent}
            fpAllowed={projection.matchup?.fp_allowed_vs_position_l4}
          />
          <ConfidenceChip label={points.confidence_label} value={points.confidence} />
          <InjuryBadge injury={injury} />
          {weather?.is_adverse && (
            <Badge tone="info" icon={<CloudRain className="size-3" />}>
              Weather
            </Badge>
          )}
        </div>
      </Link>
    </li>
  )
})
