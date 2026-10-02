import { memo, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { ShowMoreRows } from '@/components/domain/BoardBudget'
import { useReorderAnimation } from '@/hooks/useReorderAnimation'
import { useRenderBudget } from '@/hooks/useRenderBudget'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { RowFlags } from '@/components/domain/RowFlags'
import { boardCeiling, groupByTier, orderSignature } from '@/utils/board'
import { formatPercent, formatPoints, formatThreshold } from '@/utils/format'
import type { RankedProjection } from '@/api/schemas'

/**
 * The card view: one player at a time.
 *
 * Not the table with the columns removed. A card leads with the projection —
 * the number the whole page is about — and puts the range under it, for a
 * reader checking players one by one rather than scanning a ranking. The whole
 * card is the link.
 *
 * A choice on a wide screen, and no longer what a phone is given: at about
 * 235px a card it took 25 screens to reach the hundredth player, and
 * `ProjectionList` draws the same rows in a quarter of the height.
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
  const orderKey = useMemo(() => orderSignature(visible), [visible])
  const ref = useReorderAnimation<HTMLDivElement>(orderKey)

  if (!showTiers) {
    return (
      <div ref={ref}>
        <CardGrid entries={visible} scaleMax={scaleMax} showRank={showRank} rankMode={rankMode} />
        <ShowMoreRows budget={budget} />
      </div>
    )
  }

  return (
    <>
      <div ref={ref} className="space-y-6">
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
                className="text-ink-secondary mb-2 text-caption font-semibold tracking-wide uppercase"
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

  return (
    <li data-flip-key={projection.player.player_id} className="deferred-card">
      <Link
        to={`/players/${encodeURIComponent(projection.player.player_id)}`}
        className="bg-surface border-line hover:border-line-strong focus-visible:outline-focus block rounded-[var(--radius-card)] border p-4 transition-colors"
      >
        <div className="flex items-start gap-3">
          {showRank && (
            <span className="bg-surface-sunken text-ink-secondary tnum mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full text-detail font-semibold">
              {rankMode === 'positional' ? entry.positional_rank : entry.rank}
            </span>
          )}
          <PlayerAvatar player={projection.player} />
          <div className="min-w-0 flex-1">
            <p className="text-ink truncate text-sm font-medium">{projection.player.name}</p>
            <p className="text-ink-muted truncate text-detail">
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
            <p className="text-ink-muted text-chip tracking-wide uppercase">
              Projected
            </p>
          </div>
        </div>

        <div className="mt-3">
          <OutcomeRange
            floor={points.floor}
            p25={points.p25}
            median={points.median}
            p75={points.p75}
            ceiling={points.ceiling}
            threshold={points.boom_threshold}
            scaleMax={scaleMax}
          />
          <p className="text-ink-muted mt-1 flex justify-between text-chip">
            <span>
              Floor {formatPoints(points.floor)} · Ceiling {formatPoints(points.ceiling)}
            </span>
            <span className="text-ink font-semibold">
              {formatPercent(points.boom_probability)} chance of {formatThreshold(points.boom_threshold)}+
            </span>
          </p>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <MatchupGradeChip
            grade={projection.matchup?.grade}
            opponent={projection.opponent}
            fpAllowed={projection.matchup?.fp_allowed_vs_position_l4}
          />
          <RowFlags projection={projection} />
        </div>
      </Link>
    </li>
  )
})
