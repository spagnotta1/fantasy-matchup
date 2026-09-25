import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { CornerDownLeft, Search, Shield, User } from 'lucide-react'

import { closeCommandPalette, openCommandPalette, useCommandPaletteOpen } from '@/app/command-palette'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { useTeams } from '@/hooks/useCatalog'
import { MIN_SEARCH_LENGTH, usePlayerSearch } from '@/hooks/useProjections'
import { cn } from '@/utils/cn'

import { HIDDEN_DESTINATIONS, NAV_GROUP_LABELS, NAV_ITEMS } from './navigation'

/** Long enough to stop firing per keystroke, short enough to feel immediate. */
const DEBOUNCE_MS = 150

const FANTASY_POSITIONS = ['QB', 'RB', 'WR', 'TE']

interface Option {
  id: string
  section: string
  label: string
  detail: string
  to: string
  icon: React.ReactNode
}

/**
 * Jump anywhere: a player, a team, or any page — including the pages that are
 * deliberately not in the navigation.
 *
 * Opened with ⌘K / Ctrl+K from anywhere, with "/" when focus is not in a text
 * field, or from the header. On a phone it is also the menu: with nothing
 * typed it lists every destination, which is how the pages beyond the five in
 * the bottom bar are reached without a second navigation system.
 *
 * A native `<dialog>` opened with `showModal()`, so focus is trapped, Escape
 * closes it and the page behind is inert — by the platform rather than by
 * hand-rolled listeners that each miss a case. The input is a combobox whose
 * active option is tracked with `aria-activedescendant`, so the arrow keys move
 * through results without moving focus out of the field being typed in.
 */
export function CommandPalette() {
  const open = useCommandPaletteOpen()
  const dialogRef = useRef<HTMLDialogElement>(null)

  // Global shortcut. One listener for the app's lifetime.
  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        openCommandPalette()
        return
      }
      if (event.key === '/' && !event.metaKey && !event.ctrlKey && !event.altKey) {
        const target = event.target as HTMLElement | null
        const typing =
          target?.isContentEditable ||
          ['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName ?? '')
        if (!typing) {
          event.preventDefault()
          openCommandPalette()
        }
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      aria-label="Search players, teams and pages"
      onClose={closeCommandPalette}
      // A click on the backdrop lands on the dialog element itself.
      onClick={(event) => {
        if (event.target === event.currentTarget) closeCommandPalette()
      }}
      className="bg-surface-raised border-line text-ink m-auto mt-[10vh] w-[min(36rem,calc(100vw-2rem))] rounded-[var(--radius-card)] border p-0 shadow-overlay backdrop:bg-black/40"
    >
      {/* Mounted only while open, so every opening starts from an empty query. */}
      {open && <PaletteBody />}
    </dialog>
  )
}

function PaletteBody() {
  const navigate = useNavigate()
  const listboxId = useId()
  const [term, setTerm] = useState('')
  const [debounced, setDebounced] = useState('')
  const [active, setActive] = useState(0)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term), DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [term])

  const teams = useTeams()
  // Fantasy positions only: the search endpoint covers every player the
  // warehouse has ever seen, and "hen" should find Derrick Henry before a safety.
  const players = usePlayerSearch(debounced, { limit: 6, positions: FANTASY_POSITIONS })
  const query = term.trim().toLowerCase()

  const options = useMemo<Option[]>(() => {
    const pages = [
      ...NAV_ITEMS.map((item) => ({ ...item, section: NAV_GROUP_LABELS[item.group] })),
      ...HIDDEN_DESTINATIONS.map((item) => ({ ...item, section: 'More' })),
    ]
      .filter(
        (item) =>
          !query ||
          item.label.toLowerCase().includes(query) ||
          item.description.toLowerCase().includes(query),
      )
      .map<Option>((item) => ({
        id: `page:${item.to}`,
        section: query ? 'Pages' : item.section,
        label: item.label,
        detail: item.description,
        to: item.to,
        icon: <item.icon aria-hidden className="size-4" />,
      }))

    if (!query) return pages

    const teamOptions = (teams.data ?? [])
      .filter(
        (team) =>
          team.abbr.toLowerCase() === query ||
          (query.length >= 2 &&
            [team.abbr, team.name, team.nickname].some((v) => v?.toLowerCase().includes(query))),
      )
      .slice(0, 4)
      .map<Option>((team) => ({
        id: `team:${team.abbr}`,
        section: 'Teams',
        label: team.name ?? team.abbr,
        detail: [team.abbr, team.division].filter(Boolean).join(' · '),
        to: `/teams/${team.abbr}`,
        icon: team.logo_url ? (
          <img src={team.logo_url} alt="" className="size-5 object-contain" loading="lazy" />
        ) : (
          <Shield aria-hidden className="size-4" />
        ),
      }))

    const playerOptions = (debounced.trim().length >= MIN_SEARCH_LENGTH ? (players.data ?? []) : []).map<Option>(
      (player) => ({
        id: `player:${player.player_id}`,
        section: 'Players',
        label: player.name,
        detail: [player.position, player.team].filter(Boolean).join(' · '),
        to: `/players/${encodeURIComponent(player.player_id)}`,
        icon: <PlayerAvatar player={player} size="sm" />,
      }),
    )

    return [...playerOptions, ...teamOptions, ...pages]
  }, [query, debounced, teams.data, players.data])

  // Keep the highlight on a real row as results arrive.
  const current = Math.min(active, Math.max(options.length - 1, 0))

  const choose = (option: Option | undefined) => {
    if (!option) return
    closeCommandPalette()
    navigate(option.to)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((index) => (options.length ? (Math.min(index, options.length - 1) + 1) % options.length : 0))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) =>
        options.length ? (Math.min(index, options.length - 1) - 1 + options.length) % options.length : 0,
      )
    } else if (event.key === 'Enter') {
      event.preventDefault()
      choose(options[current])
    }
  }

  const searchingPlayers = query.length >= MIN_SEARCH_LENGTH && players.isFetching
  let lastSection = ''

  return (
    <div className="flex max-h-[70vh] flex-col">
      <div className="border-line flex items-center gap-2 border-b px-4">
        <Search aria-hidden className="text-ink-muted size-4 shrink-0" />
        <input
          autoFocus
          value={term}
          onChange={(event) => {
            setTerm(event.target.value)
            setActive(0)
          }}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-expanded="true"
          aria-controls={listboxId}
          aria-activedescendant={options[current] ? `${listboxId}-${current}` : undefined}
          aria-autocomplete="list"
          aria-label="Search players, teams and pages"
          placeholder="Search players, teams and pages…"
          className="text-ink placeholder:text-ink-muted h-12 min-w-0 flex-1 bg-transparent text-sm outline-none"
        />
        <kbd className="border-line text-ink-muted hidden rounded border px-1.5 py-0.5 text-[0.625rem] sm:inline">
          Esc
        </kbd>
      </div>

      <ul id={listboxId} role="listbox" aria-label="Results" className="overflow-y-auto p-2">
        {options.length === 0 && (
          <li role="presentation" className="text-ink-muted px-3 py-6 text-center text-sm">
            {searchingPlayers ? 'Searching…' : 'Nothing matches that.'}
          </li>
        )}
        {options.map((option, index) => {
          const heading = option.section !== lastSection ? option.section : null
          lastSection = option.section
          return (
            <li key={option.id} role="presentation">
              {heading && (
                <p
                  role="presentation"
                  className="text-ink-muted px-3 pt-2 pb-1 text-[0.6875rem] font-medium tracking-wide uppercase"
                >
                  {heading}
                </p>
              )}
              <div
                id={`${listboxId}-${index}`}
                role="option"
                aria-selected={index === current}
                onPointerMove={() => setActive(index)}
                onClick={() => choose(option)}
                className={cn(
                  'flex cursor-pointer items-center gap-3 rounded-[var(--radius-control)] px-3 py-2',
                  index === current ? 'bg-accent-soft text-accent-text' : 'text-ink',
                )}
              >
                <span className="text-ink-muted flex size-8 shrink-0 items-center justify-center">
                  {option.icon ?? <User aria-hidden className="size-4" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{option.label}</span>
                  <span className="text-ink-muted block truncate text-xs">{option.detail}</span>
                </span>
                {index === current && <CornerDownLeft aria-hidden className="size-3.5 shrink-0" />}
              </div>
            </li>
          )
        })}
      </ul>

      <p className="border-line text-ink-muted border-t px-4 py-2 text-[0.6875rem]">
        ↑ ↓ to move · Enter to open · Esc to close
        {query.length > 0 && query.length < MIN_SEARCH_LENGTH && ' · type two letters to search players'}
      </p>
    </div>
  )
}
