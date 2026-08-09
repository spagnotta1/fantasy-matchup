import { useEffect, useRef, useState } from 'react'
import { Search } from 'lucide-react'

import { Input } from '@/components/ui/Input'
import { Skeleton } from '@/components/ui/Skeleton'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { MIN_SEARCH_LENGTH, usePlayerSearch } from '@/hooks/useProjections'
import { cn } from '@/utils/cn'
import type { Player } from '@/api/schemas'

/** Long enough to stop firing per keystroke, short enough to feel immediate. */
const DEBOUNCE_MS = 200

/**
 * Search for a player and pick one.
 *
 * A combobox rather than a `<select>` of four hundred names, and shared by
 * everything that needs to name a player — the comparison picker and every slot
 * in the lineup builder. Keeping it in one place is what makes the keyboard
 * path (type, arrow, enter) work identically in both, which matters on the two
 * screens someone opens at 12:55 on a Sunday.
 *
 * `positions` is pushed to the API rather than filtering results in the
 * browser: a flex slot searching "Ja" should spend its ten results on eligible
 * players instead of showing eight quarterbacks it will not accept.
 *
 * `note` exists because `/players/search` searches the player *dimension*, which
 * holds everyone who has ever played — so "Aaron" offers receivers who retired
 * in the nineties beside this week's starters. Hiding them would be wrong: the
 * dimension is what the endpoint searches and a caller may legitimately want a
 * player with no board. Marking them is not, and a caller that knows which
 * players are projected this week passes a note so the difference is visible
 * before the click rather than after it.
 */
export function PlayerSearchField({
  label,
  placeholder,
  positions,
  excludeIds,
  disabled = false,
  hint,
  size = 'md',
  note,
  onSelect,
}: {
  label: string
  placeholder?: string
  /** Eligible positions. Omitted means every position. */
  positions?: string[]
  /** Players already chosen elsewhere, hidden from the results. */
  excludeIds?: string[]
  disabled?: boolean
  hint?: string
  size?: 'sm' | 'md'
  /** A short caution to show against a result, or null. Never hides a result. */
  note?: (player: Player) => string | null
  onSelect: (player: Player) => void
}) {
  const [term, setTerm] = useState('')
  const [debounced, setDebounced] = useState('')
  const [highlight, setHighlight] = useState(0)
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term), DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [term])

  useEffect(() => {
    setHighlight(0)
  }, [debounced])

  // Close when focus leaves the whole control rather than on input blur:
  // clicking a result blurs the input before the click lands.
  useEffect(() => {
    const onOutside = (event: Event) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('focusin', onOutside)
    document.addEventListener('mousedown', onOutside)
    return () => {
      document.removeEventListener('focusin', onOutside)
      document.removeEventListener('mousedown', onOutside)
    }
  }, [])

  const { data, isPending, isFetching } = usePlayerSearch(debounced, { limit: 8, positions })
  const excluded = new Set(excludeIds ?? [])
  const results = (data ?? []).filter((player) => !excluded.has(player.player_id))
  const searching = debounced.trim().length >= MIN_SEARCH_LENGTH

  const choose = (player: Player) => {
    onSelect(player)
    setTerm('')
    setDebounced('')
    setOpen(false)
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!open || results.length === 0) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlight((current) => (current + 1) % results.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlight((current) => (current - 1 + results.length) % results.length)
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const player = results[highlight]
      if (player) choose(player)
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <Input
        label={label}
        hideLabel={size === 'sm'}
        placeholder={placeholder ?? 'Search by name…'}
        value={term}
        disabled={disabled}
        onChange={(event) => {
          setTerm(event.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        icon={<Search className="size-4" />}
        type="search"
        role="combobox"
        aria-expanded={open && searching}
        aria-autocomplete="list"
        hint={hint}
        className={size === 'sm' ? '[&_input]:h-9' : undefined}
      />

      {open && searching && !disabled && (
        <ul
          role="listbox"
          aria-label={label}
          className={cn(
            'bg-surface-raised border-line absolute z-40 max-h-72 w-full min-w-56 overflow-y-auto rounded-[var(--radius-card)] border shadow-overlay',
            size === 'sm' ? 'top-11' : 'top-[4.25rem]',
          )}
        >
          {isPending || (isFetching && results.length === 0) ? (
            <li className="space-y-2 p-3">
              {Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-9 w-full" />
              ))}
            </li>
          ) : results.length === 0 ? (
            <li className="text-ink-muted px-3 py-4 text-sm">
              No {positions?.length ? `${positions.join('/')} ` : ''}players match “
              {debounced.trim()}”.
            </li>
          ) : (
            results.map((player, index) => (
              <li key={player.player_id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={index === highlight}
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => choose(player)}
                  className={cn(
                    'flex w-full items-center gap-3 px-3 py-2 text-left transition-colors',
                    index === highlight && 'bg-surface-hover',
                  )}
                >
                  <PlayerAvatar player={player} size="sm" />
                  <span className="min-w-0 flex-1">
                    <span className="text-ink block truncate text-sm font-medium">
                      {player.name}
                    </span>
                    <span className="text-ink-muted block truncate text-xs">
                      {[player.position, player.team].filter(Boolean).join(' · ')}
                    </span>
                  </span>
                  {note?.(player) && (
                    <span className="bg-caution-soft text-caution-text shrink-0 rounded-full px-2 py-0.5 text-[0.6875rem] font-medium">
                      {note(player)}
                    </span>
                  )}
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}
