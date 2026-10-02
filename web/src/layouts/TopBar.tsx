import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ChevronDown, Menu, Monitor, Moon, Search, Sun } from 'lucide-react'

import { openCommandPalette } from '@/app/command-palette'
import { useSlate } from '@/app/slate-context'
import { useTheme } from '@/hooks/useTheme'
import { Button, IconButton } from '@/components/ui/Button'
import { buttonClasses } from '@/components/ui/buttonStyles'
import { cn } from '@/utils/cn'
import { formatScoringProfile } from '@/utils/format'

import { SlateControls } from './SlateControls'

function ThemeToggle() {
  const { preference, cycle } = useTheme()
  const Icon = preference === 'light' ? Sun : preference === 'dark' ? Moon : Monitor
  const next = preference === 'light' ? 'dark' : preference === 'dark' ? 'system' : 'light'

  return (
    <IconButton label={`Theme: ${preference}. Switch to ${next}.`} title={`Theme: ${preference}`} onClick={cycle}>
      <Icon />
    </IconButton>
  )
}

/**
 * The application header.
 *
 * Holds the slate selection, because it is global state and belongs somewhere
 * persistent rather than repeated on every page. It is one button that says
 * what the slate is — "2026 · Wk 4 · Half PPR" — and opens the three selectors
 * (`SlateSwitch`), at every width.
 *
 * It used to be three dropdowns across a desktop header and an unlabelled icon
 * on a phone. The three change at very different rates: the week weekly, the
 * season almost never, the scoring format once per league. Three permanent
 * controls gave them equal weight and the first 400px of every page, and the
 * phone showed nowhere which week its numbers were for. What a reader needs
 * all the time is to *read* the slate; changing it is the occasional act, and
 * is one press further away.
 *
 * Three things that were here are gone. Compare and Settings each had a second
 * home in the sidebar (and, on a phone, in the menu beside this), and two
 * doors to one room is one more thing to read. The account badge said "not
 * signed in" about a product that has no accounts.
 */
export function TopBar() {
  // The draft pages carry their own season, scoring and league settings and
  // never read the header's. Showing both put two scoring formats on one
  // screen that could disagree (Half PPR above, PPR below), with no way to
  // tell which one the numbers used.
  const { pathname } = useLocation()
  const ownsSettings = pathname.startsWith('/mock-draft') || pathname.startsWith('/draft-board')

  return (
    <header className="border-line bg-bg/85 sticky top-0 z-30 border-b backdrop-blur-md">
      <div className="h-shell-bar flex items-center gap-3 px-4 sm:px-6">
        {/* The wordmark lives in the sidebar on desktop; on mobile it belongs here. */}
        <Link
          to="/"
          className="flex items-center gap-2 rounded-md lg:hidden"
          aria-label="Fourth and Probable, home"
        >
          <span
            aria-hidden
            className="bg-accent text-on-accent flex size-7 items-center justify-center rounded-md text-detail font-bold"
          >
            FP
          </span>
        </Link>

        {ownsSettings ? (
          <p className="text-ink-muted text-detail hidden md:block">
            This page uses its own season and scoring settings, below.
          </p>
        ) : (
          <SlateSwitch />
        )}

        <div className="ml-auto flex items-center justify-end gap-1">
          {/*
            The palette is search and, on a phone, the menu: with nothing typed
            it lists every page, including the ones beyond the five in the
            bottom bar. Two faces for one control, labelled for what each does.
          */}
          <Button
            size="sm"
            icon={<Search aria-hidden />}
            onClick={openCommandPalette}
            className="text-ink-muted not-disabled:hover:text-ink mr-1 hidden font-normal lg:inline-flex"
          >
            Search
            <kbd className="border-line rounded-chip text-chip border px-1">Ctrl K</kbd>
          </Button>
          <IconButton label="Search and all pages" className="lg:hidden" onClick={openCommandPalette}>
            <Menu />
          </IconButton>

          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}

/**
 * The slate, as the header states it, and the way to change it.
 *
 * A disclosure, not a menu and not a dialog: the button says whether the
 * selectors are showing, and the selectors are ordinary labelled selects that
 * come next in the tab order. They stay open while a reader changes more than
 * one of them, and close on Escape (which hands focus back to the button), on
 * a press anywhere else, and when the page changes.
 *
 * On a phone the panel is a row the width of the header, under it. From `md`
 * it hangs under the button. Either way it lies over the page instead of
 * pushing it down: the bars that stick under the header are placed against the
 * header's fixed height.
 */
function SlateSwitch() {
  const slate = useSlate()
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const wrapper = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)

  useEffect(() => setOpen(false), [pathname])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      button.current?.focus()
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  // The season is always said. A reader two seasons back should not have to
  // open anything to find that out, and one in the current season loses six
  // characters to it.
  const parts = [
    slate.season === null ? null : String(slate.season),
    slate.week === null ? null : `Wk ${slate.week}`,
    slate.scoringProfile ? formatScoringProfile(slate.scoringProfile) : null,
  ].filter(Boolean)

  return (
    <div ref={wrapper} className="min-w-0 md:relative">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls="slate-controls"
        onClick={() => setOpen((current) => !current)}
        className={buttonClasses({ variant: 'secondary', size: 'sm', className: 'tnum max-w-full min-w-0 gap-1 px-2.5' })}
      >
        {/* The visible words are part of the name, so saying what is on the
            button presses it. */}
        <span className="sr-only">Season, week and scoring: </span>
        <span className="truncate">{parts.length > 0 ? parts.join(' · ') : slate.catalogFailed ? 'Unavailable' : 'Loading…'}</span>
        <ChevronDown aria-hidden className={cn('text-ink-muted transition-transform', open && 'rotate-180')} />
      </button>

      <div
        id="slate-controls"
        hidden={!open}
        className="border-line bg-bg absolute inset-x-0 top-full z-10 border-b px-4 py-3 md:bg-surface-raised md:shadow-overlay md:inset-x-auto md:left-0 md:mt-2 md:w-[26rem] md:rounded-[var(--radius-card)] md:border md:p-4"
      >
        <SlateControls compact />
      </div>
    </div>
  )
}
