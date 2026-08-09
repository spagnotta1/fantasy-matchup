import { History, RotateCcw, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { EmptyState } from '@/components/feedback/States'
import { formatPercent, formatPoints, formatScoringProfile } from '@/utils/format'
import type { HistoryEntry } from '@/features/simulations/history'

const TIME_FORMAT = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
})

/**
 * Previous runs, from this browser.
 *
 * The API stores nothing, and the panel says so rather than implying an
 * account. Each entry keeps the exact request, so "Load" puts the lineups back
 * in the builder and a re-run reproduces the numbers rather than restoring a
 * screenshot of them.
 *
 * An entry taken against an older published model run is marked. Week 18's
 * board is republished when the projection job runs again, and a win
 * probability from the previous run is not wrong so much as answering a
 * question about data that no longer exists.
 */
export function SimulationHistory({
  entries,
  currentModelRunId,
  onLoad,
  onRemove,
  onClear,
}: {
  entries: HistoryEntry[]
  currentModelRunId: number | null
  onLoad: (entry: HistoryEntry) => void
  onRemove: (id: string) => void
  onClear: () => void
}) {
  return (
    <Card>
      <CardHeader
        as="h2"
        title="Previous runs"
        description="Kept in this browser only — the API stores no simulations, so these do not follow you to another device and clearing site data clears them."
        action={
          entries.length > 0 ? (
            <Button size="sm" variant="ghost" onClick={onClear}>
              <Trash2 aria-hidden className="size-3.5" />
              Clear all
            </Button>
          ) : undefined
        }
      />

      {entries.length === 0 ? (
        <EmptyState
          icon={<History aria-hidden className="size-5" />}
          title="No simulations yet"
          description="Run one and it is kept here, with the lineups and the seed, so you can load it back and reproduce it exactly."
        />
      ) : (
        <ul className="divide-line divide-y">
          {entries.map((entry) => {
            const stale =
              currentModelRunId !== null &&
              entry.modelRunId !== null &&
              entry.modelRunId !== currentModelRunId

            return (
              <li key={entry.id} className="px-5 py-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-ink text-sm font-medium">
                      <span className="tnum">{formatPercent(entry.winProbabilityA)}</span> win
                      probability
                      <span className="text-ink-muted font-normal">
                        {' '}
                        · {formatPoints(entry.expectedScoreA)} to{' '}
                        {formatPoints(entry.expectedScoreB)}
                      </span>
                    </p>
                    <p className="text-ink-muted mt-0.5 text-xs">
                      {TIME_FORMAT.format(new Date(entry.ranAt))} · {entry.season} week{' '}
                      {entry.week} · {formatScoringProfile(entry.scoringProfile)} ·{' '}
                      {entry.iterations.toLocaleString()} draws · seed {entry.seed}
                    </p>
                    <p className="text-ink-muted mt-1 truncate text-xs">
                      {entry.teamA.map((player) => player.name).join(', ')}
                    </p>
                  </div>

                  <div className="flex shrink-0 items-center gap-1.5">
                    {entry.correlationMode !== 'independent' && (
                      <Badge tone="info">{entry.correlationMode.replace(/_/g, ' ')}</Badge>
                    )}
                    {stale && (
                      <Badge tone="caution" title={`Run against model run #${entry.modelRunId}`}>
                        Older model run
                      </Badge>
                    )}
                    <Button size="sm" variant="secondary" onClick={() => onLoad(entry)}>
                      <RotateCcw aria-hidden className="size-3.5" />
                      Load
                    </Button>
                    <button
                      type="button"
                      onClick={() => onRemove(entry.id)}
                      aria-label="Remove this run from history"
                      className="text-ink-muted hover:bg-surface-hover hover:text-ink flex size-8 items-center justify-center rounded-full transition-colors"
                    >
                      <Trash2 aria-hidden className="size-3.5" />
                    </button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <CardBody className="border-line border-t py-3">
        <p className="text-ink-muted text-xs leading-relaxed">
          A run is reproducible from its lineups, its seed and the published model run it was made
          against. All three are stored, which is why loading one back and running it again gives
          the same numbers rather than similar ones.
        </p>
      </CardBody>
    </Card>
  )
}
