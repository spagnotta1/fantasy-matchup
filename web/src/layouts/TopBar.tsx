import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { GitCompareArrows, Menu, Monitor, Moon, Search, Settings, SlidersHorizontal, Sun, User } from 'lucide-react'

import { openCommandPalette } from '@/app/command-palette'
import { useTheme } from '@/hooks/useTheme'
import { Button, IconButton, IconButtonLink } from '@/components/ui/Button'
import { cn } from '@/utils/cn'

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
 * persistent rather than repeated on every page. On mobile the selectors move
 * behind a disclosure — three dropdowns across a phone header leaves no room
 * for the page title, and the selection changes far less often than it is read.
 */
export function TopBar() {
  // The draft pages carry their own season, scoring and league settings and
  // never read the header's. Showing both put two scoring formats on one
  // screen that could disagree (Half PPR above, PPR below), with no way to
  // tell which one the numbers used.
  const { pathname } = useLocation()
  const ownsSettings = pathname.startsWith('/mock-draft') || pathname.startsWith('/draft-board')

  const [filtersOpen, setFiltersOpen] = useState(false)

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

        {/*
          Inline from `md` rather than `lg`. The sidebar needs 1024px to earn
          its width, but three compact selectors fit comfortably on a tablet,
          and hiding the slate selection behind a tap on a screen with room for
          it is a worse trade than a slightly busier header.
        */}
        <div className="hidden flex-1 md:block">
          {ownsSettings ? (
            <p className="text-ink-muted text-detail">This page uses its own season and scoring settings, below.</p>
          ) : (
            <SlateControls />
          )}
        </div>

        <div className="flex flex-1 items-center justify-end gap-1 md:flex-none">
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

          <IconButton
            label="Season, week and scoring"
            className={cn('md:hidden', ownsSettings && 'hidden')}
            aria-expanded={filtersOpen}
            aria-controls="slate-controls-mobile"
            onClick={() => setFiltersOpen((open) => !open)}
          >
            <SlidersHorizontal />
          </IconButton>

          <IconButtonLink to="/compare" label="Compare players" className="hidden sm:inline-flex">
            <GitCompareArrows />
          </IconButtonLink>

          <ThemeToggle />

          <IconButtonLink to="/settings" label="Settings">
            <Settings />
          </IconButtonLink>

          {/*
            Account placeholder. The API is anonymous today — `current_principal`
            returns an anonymous principal and no endpoint requires auth — so
            this is a signed-out affordance rather than a fake profile menu.
          */}
          <span
            className="border-line text-ink-muted ml-1 inline-flex size-8 items-center justify-center rounded-full border"
            title="You are not signed in. Accounts are not available yet."
          >
            <User aria-hidden className="size-4" />
            <span className="sr-only">Not signed in</span>
          </span>
        </div>
      </div>

      <div
        id="slate-controls-mobile"
        hidden={!filtersOpen}
        className={cn('border-line border-t px-4 py-3 md:hidden')}
      >
        <SlateControls compact />
      </div>
    </header>
  )
}
