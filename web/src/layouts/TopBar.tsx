import { useState } from 'react'
import { Link } from 'react-router-dom'
import { GitCompareArrows, Monitor, Moon, Settings, SlidersHorizontal, Sun, User } from 'lucide-react'

import { useTheme } from '@/hooks/useTheme'
import { Button } from '@/components/ui/Button'
import { cn } from '@/utils/cn'

import { SlateControls } from './SlateControls'

function ThemeToggle() {
  const { preference, cycle } = useTheme()
  const Icon = preference === 'light' ? Sun : preference === 'dark' ? Moon : Monitor
  const next = preference === 'light' ? 'dark' : preference === 'dark' ? 'system' : 'light'

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={cycle}
      aria-label={`Theme: ${preference}. Switch to ${next}.`}
      title={`Theme: ${preference}`}
      className="px-2"
    >
      <Icon aria-hidden className="size-4" />
    </Button>
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
  const [filtersOpen, setFiltersOpen] = useState(false)

  return (
    <header className="border-line bg-bg/85 sticky top-0 z-30 border-b backdrop-blur-md">
      <div className="flex h-14 items-center gap-3 px-4 sm:px-6">
        {/* The wordmark lives in the sidebar on desktop; on mobile it belongs here. */}
        <Link
          to="/"
          className="flex items-center gap-2 rounded-md lg:hidden"
          aria-label="Fourth and Probable, home"
        >
          <span
            aria-hidden
            className="bg-accent text-on-accent flex size-7 items-center justify-center rounded-md text-xs font-bold"
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
          <SlateControls />
        </div>

        <div className="flex flex-1 items-center justify-end gap-1 md:flex-none">
          <Button
            variant="ghost"
            size="sm"
            className="px-2 md:hidden"
            aria-expanded={filtersOpen}
            aria-controls="slate-controls-mobile"
            onClick={() => setFiltersOpen((open) => !open)}
          >
            <SlidersHorizontal aria-hidden className="size-4" />
            <span className="sr-only">Season, week and scoring</span>
          </Button>

          <Link
            to="/compare"
            aria-label="Compare players"
            className="text-ink-secondary hover:bg-surface-hover hover:text-ink hidden size-8 items-center justify-center rounded-[var(--radius-control)] transition-colors sm:inline-flex"
          >
            <GitCompareArrows aria-hidden className="size-4" />
          </Link>

          <ThemeToggle />

          <Link
            to="/settings"
            aria-label="Settings"
            className="text-ink-secondary hover:bg-surface-hover hover:text-ink inline-flex size-8 items-center justify-center rounded-[var(--radius-control)] transition-colors"
          >
            <Settings aria-hidden className="size-4" />
          </Link>

          {/*
            Account placeholder. The API is anonymous today — `current_principal`
            returns an anonymous principal and no endpoint requires auth — so
            this is a signed-out affordance rather than a fake profile menu.
          */}
          <span
            className="border-line text-ink-muted ml-1 inline-flex size-8 items-center justify-center rounded-full border"
            title="Not signed in. Accounts are a later phase."
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
