import { AlertTriangle, Sparkles, Trash2, X } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { PlayerSearchField } from '@/components/domain/PlayerSearchField'
import { ProjectionValue } from '@/components/domain/ProjectionValue'
import { eligiblePositions, type LineupRow } from '@/features/simulations/lineupFormat'
import { slotStatus, type BoardIndex, type SlotStatus } from '@/features/simulations/availability'
import { cn } from '@/utils/cn'
import type { LineupSlot, Player } from '@/api/schemas'

/**
 * One side's starting lineup.
 *
 * The shape comes from the API's own format rather than a constant here, so the
 * builder follows the league the backend says it simulates. Each row's search is
 * constrained to that slot's eligible positions, which is what stops the most
 * common mistake — putting a quarterback in a flex — from becoming a 422 the
 * user has to interpret.
 *
 * The second such mistake is a starter with no projection this week, and it is
 * caught the same way: the row says so, in place of the points it would
 * otherwise show, while there is still an obvious thing to do about it. See
 * `availability.ts` for why that check refuses to guess when the board is not
 * fully in hand.
 */
export function LineupBuilder({
  title,
  description,
  rows,
  slots,
  board,
  projectedPositions,
  week,
  otherLineupIds,
  onChange,
  onAutofill,
  disabled = false,
}: {
  title: string
  description: string
  rows: LineupRow[]
  slots: LineupSlot[]
  /** The week's board, indexed — the per-row projection and the gaps in it. */
  board: BoardIndex
  /** Positions the engine projects, from `/meta/positions`. */
  projectedPositions: Set<string> | null
  week: number | null
  /** Players on the opposing lineup — allowed, but worth flagging. */
  otherLineupIds: string[]
  onChange: (rows: LineupRow[]) => void
  /**
   * Fill the empty slots.
   *
   * Owned by the page rather than performed here, because the choice depends on
   * *both* lineups and only the page can read both without a render in between.
   */
  onAutofill: () => void
  disabled?: boolean
}) {
  const filled = rows.filter((row) => row.player !== null).length
  const usedIds = rows.map((row) => row.player?.player_id).filter((id): id is string => Boolean(id))
  const statuses = rows.map((row) => slotStatus(row, board, projectedPositions, week))
  const unavailable = statuses.filter((status) => status.kind === 'unavailable').length

  const setRow = (key: string, player: Player | null) => {
    onChange(rows.map((row) => (row.key === key ? { ...row, player } : row)))
  }

  // Marks a search result the engine could not sample. Only offered once the
  // board is complete, for the same reason the rows go quiet without it.
  const note = board.complete
    ? (player: Player) => (board.byPlayer.has(player.player_id) ? null : 'No board')
    : undefined

  return (
    <Card>
      <CardHeader
        as="h2"
        title={title}
        description={description}
        action={
          <div className="flex items-center gap-2">
            <Badge
              tone={
                unavailable > 0 ? 'caution' : filled === rows.length ? 'positive' : 'neutral'
              }
              icon={unavailable > 0 ? <AlertTriangle className="size-3" /> : undefined}
            >
              {filled}/{rows.length}
              {unavailable > 0 && <span className="sr-only">, {unavailable} cannot be simulated</span>}
            </Badge>
            <Button
              size="sm"
              variant="ghost"
              onClick={onAutofill}
              // Gated on the board *arriving*, not on it being complete. A
              // truncated board is still ranked, so autofill still picks the
              // best available players from it; only the "no projection"
              // claim needs the whole slate.
              disabled={disabled || board.pending || filled === rows.length}
              title="Fill empty slots with the highest-projected available players"
            >
              <Sparkles aria-hidden className="size-3.5" />
              Autofill
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onChange(rows.map((row) => ({ ...row, player: null })))}
              disabled={disabled || filled === 0}
            >
              <Trash2 aria-hidden className="size-3.5" />
              <span className="sr-only">Clear {title}</span>
            </Button>
          </div>
        }
      />

      <CardBody className="space-y-2 p-3 sm:p-4">
        {rows.map((row, index) => (
          <SlotRow
            key={row.key}
            row={row}
            eligible={eligiblePositions(slots, row.slot)}
            status={statuses[index] ?? { kind: 'empty' }}
            excludeIds={usedIds}
            alsoOnOtherSide={row.player ? otherLineupIds.includes(row.player.player_id) : false}
            disabled={disabled}
            note={note}
            onSelect={(player) => setRow(row.key, player)}
            onClear={() => setRow(row.key, null)}
          />
        ))}
      </CardBody>
    </Card>
  )
}

function SlotRow({
  row,
  eligible,
  status,
  excludeIds,
  alsoOnOtherSide,
  disabled,
  note,
  onSelect,
  onClear,
}: {
  row: LineupRow
  eligible: string[]
  status: SlotStatus
  excludeIds: string[]
  alsoOnOtherSide: boolean
  disabled: boolean
  note?: (player: Player) => string | null
  onSelect: (player: Player) => void
  onClear: () => void
}) {
  const projection = status.kind === 'ready' ? status.projection : undefined
  const blocked = status.kind === 'unavailable'

  return (
    <div className="flex items-center gap-3">
      <span
        className={cn(
          'flex h-9 w-14 shrink-0 items-center justify-center rounded-[var(--radius-control)] text-xs font-semibold',
          blocked
            ? 'bg-caution-soft text-caution-text'
            : 'bg-surface-sunken text-ink-secondary',
        )}
      >
        {row.slot}
      </span>

      {row.player ? (
        <div
          className={cn(
            'flex min-w-0 flex-1 items-center gap-2 rounded-[var(--radius-control)] px-2 py-1.5',
            blocked ? 'bg-caution-soft/50' : 'bg-surface-sunken/60',
          )}
        >
          <PlayerAvatar player={row.player} size="sm" />
          <span className="min-w-0 flex-1">
            <span className="text-ink block truncate text-sm font-medium">{row.player.name}</span>
            <span
              className={cn(
                'block truncate text-xs',
                blocked ? 'text-caution-text' : 'text-ink-muted',
              )}
            >
              {blocked
                ? status.detail
                : [row.player.position, projection?.team ?? row.player.team]
                    .filter(Boolean)
                    .join(' · ') +
                  (projection?.opponent
                    ? ` ${projection.is_home ? 'vs' : '@'} ${projection.opponent}`
                    : '')}
            </span>
          </span>

          {alsoOnOtherSide && !blocked && (
            <Badge tone="caution" className="hidden sm:inline-flex">
              Both sides
            </Badge>
          )}

          <span className="shrink-0 text-right">
            {projection ? (
              <ProjectionValue points={projection.prediction.points} />
            ) : blocked ? (
              <Badge tone="caution" icon={<AlertTriangle className="size-3" />}>
                {status.reason === 'unprojected_position' ? 'Not projected' : 'No board'}
              </Badge>
            ) : (
              // The board is not fully in hand, so absence from it means
              // nothing yet. Saying "no projection" here would be a guess.
              <span className="text-ink-muted text-xs">—</span>
            )}
          </span>

          <button
            type="button"
            onClick={onClear}
            disabled={disabled}
            aria-label={`Remove ${row.player.name} from ${row.slot}`}
            className="text-ink-muted hover:bg-surface-hover hover:text-ink flex size-7 shrink-0 items-center justify-center rounded-full transition-colors"
          >
            <X aria-hidden className="size-3.5" />
          </button>
        </div>
      ) : (
        <div className="min-w-0 flex-1">
          <PlayerSearchField
            label={`${row.slot} — search for a player`}
            placeholder={`Add ${eligible.join('/') || row.slot}…`}
            positions={eligible.length > 0 ? eligible : undefined}
            excludeIds={excludeIds}
            disabled={disabled}
            size="sm"
            note={note}
            onSelect={onSelect}
          />
        </div>
      )}
    </div>
  )
}

/** Matches the builder's height so the page does not jump when slots arrive. */
export function LineupSkeleton({ rows = 7 }: { rows?: number }) {
  return (
    <Card>
      <CardHeader as="h2" title={<Skeleton className="h-4 w-24" />} />
      <CardBody className="space-y-2 p-3 sm:p-4">
        {Array.from({ length: rows }, (_, index) => (
          <div key={index} className="flex items-center gap-3">
            <Skeleton className="h-9 w-14 rounded-[var(--radius-control)]" />
            <Skeleton className="h-9 flex-1" />
          </div>
        ))}
      </CardBody>
    </Card>
  )
}
