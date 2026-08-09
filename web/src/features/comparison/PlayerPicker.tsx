import { X } from 'lucide-react'

import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { PlayerSearchField } from '@/components/domain/PlayerSearchField'
import { MAX_COMPARISON_PLAYERS } from '@/hooks/useCompare'
import type { Player } from '@/api/schemas'

/**
 * Choose the players to compare.
 *
 * The search itself is the shared `PlayerSearchField`; what this adds is the
 * set — removable chips and the API's own ceiling of six, enforced here so an
 * over-long selection is impossible rather than refused.
 */
export function PlayerPicker({
  selected,
  onAdd,
  onRemove,
}: {
  selected: Player[]
  onAdd: (player: Player) => void
  onRemove: (playerId: string) => void
}) {
  const full = selected.length >= MAX_COMPARISON_PLAYERS

  return (
    <div className="mb-5 space-y-3">
      <div className="max-w-lg">
        <PlayerSearchField
          label="Add a player to compare"
          placeholder={full ? 'Six players is the maximum' : 'Search by name…'}
          disabled={full}
          excludeIds={selected.map((player) => player.player_id)}
          onSelect={onAdd}
          hint={
            full
              ? 'Remove a player to add another.'
              : `Add ${selected.length < 2 ? 'at least two' : 'up to six'} players.`
          }
        />
      </div>

      {selected.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="Players being compared">
          {selected.map((player) => (
            <li key={player.player_id}>
              <span className="bg-surface border-line inline-flex items-center gap-2 rounded-full border py-1 pr-1 pl-2 text-sm">
                <PlayerAvatar player={player} size="sm" />
                <span className="text-ink font-medium">{player.name}</span>
                <span className="text-ink-muted text-xs">
                  {[player.position, player.team].filter(Boolean).join(' · ')}
                </span>
                <button
                  type="button"
                  onClick={() => onRemove(player.player_id)}
                  aria-label={`Remove ${player.name} from the comparison`}
                  className="text-ink-muted hover:bg-surface-hover hover:text-ink flex size-6 items-center justify-center rounded-full transition-colors"
                >
                  <X aria-hidden className="size-3.5" />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
