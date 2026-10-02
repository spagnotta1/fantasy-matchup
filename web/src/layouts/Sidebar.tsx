import { useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'

import { useHealth } from '@/hooks/useCatalog'
import { replayAnimation } from '@/hooks/useCountUp'
import { useRosterCount } from '@/hooks/useRoster'
import { cn } from '@/utils/cn'

import { NAV_ITEMS, navGroups } from './navigation'

/** The wordmark. Distinct from any league product, and the same in both themes. */
function Wordmark() {
  return (
    <div className="flex items-center gap-2.5 px-3">
      <span
        aria-hidden
        className="bg-accent text-on-accent flex size-8 shrink-0 items-center justify-center rounded-lg text-sm font-bold tracking-tight"
      >
        FP
      </span>
      <span className="min-w-0">
        <span className="text-ink block text-sm leading-tight font-semibold tracking-tight">
          Fourth &amp; Probable
        </span>
        <span className="text-ink-muted block text-chip leading-tight">
          Fantasy projections
        </span>
      </span>
    </div>
  )
}

/**
 * Reports the API's own health, quietly.
 *
 * Shown only when something is wrong. A permanent green dot is decoration that
 * trains people to ignore the spot where a real warning will appear.
 */
function ServiceStatus() {
  const { data, isError } = useHealth()
  const degraded = isError || (data && data.status !== 'ok')
  if (!degraded) return null

  return (
    <div className="bg-caution-soft text-caution-text mx-3 rounded-[var(--radius-control)] px-3 py-2 text-detail leading-relaxed">
      <span className="font-medium">Service degraded.</span> Some data may be stale or
      unavailable.
    </div>
  )
}

/**
 * The desktop sidebar.
 *
 * Hidden below `lg`, where the same destinations are served by a bottom bar.
 * That is a different layout rather than a narrower one — a sidebar squeezed
 * onto a phone is either unreachable by thumb or eats a third of the screen.
 */
export function Sidebar() {
  return (
    <nav
      aria-label="Main"
      // Sticky at the height of the screen: on a long page — a finished
      // simulation is several screens — the navigation used to scroll away
      // and leave an empty white column beside the content.
      className="border-line bg-surface sticky top-0 hidden h-dvh w-60 shrink-0 flex-col gap-6 border-r py-5 lg:flex"
    >
      <Wordmark />

      <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-3">
        {navGroups().map(({ group, label, items }) => (
          <div key={group}>
            <p className="text-ink-muted mb-1 px-3 text-chip font-medium tracking-wide uppercase">
              {label}
            </p>
            <ul className="flex flex-col gap-0.5">
              {items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === '/'}
                    title={item.description}
                    data-nav={item.to}
                    className={({ isActive }) =>
                      cn(
                        'group flex items-center gap-3 rounded-[var(--radius-control)] px-3 py-2 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-accent-soft text-accent-text'
                          : 'text-ink-secondary hover:bg-surface-hover hover:text-ink',
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <item.icon
                          aria-hidden
                          className={cn(
                            'size-4 shrink-0',
                            isActive ? 'text-accent-text' : 'text-ink-muted',
                          )}
                        />
                        {item.label}
                        {item.to === '/my-team' && <RosterBadge className="ml-auto" />}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <ServiceStatus />
    </nav>
  )
}

/**
 * The mobile bar.
 *
 * Fixed to the bottom, five destinations, generous targets, and padded for the
 * home indicator. Everything else is in the header's menu rather than crammed
 * in here.
 */
export function MobileNav() {
  const items = NAV_ITEMS.filter((item) => item.primary)

  return (
    <nav
      aria-label="Main"
      className="border-line bg-surface/95 fixed inset-x-0 bottom-0 z-40 border-t backdrop-blur-md lg:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <ul className="grid grid-cols-5">
        {items.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.to === '/'}
              data-nav={item.to}
              className={({ isActive }) =>
                cn(
                  'relative flex min-h-14 flex-col items-center justify-center gap-1 px-1 py-2 text-chip font-medium transition-colors',
                  isActive ? 'text-accent-text' : 'text-ink-muted',
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span className="relative">
                    <item.icon aria-hidden className={cn('size-5', isActive && 'text-accent')} />
                    {item.to === '/my-team' && (
                      <RosterBadge className="absolute -top-1.5 left-3.5" />
                    )}
                  </span>
                  <span className="truncate">{item.label}</span>
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}

/**
 * How many players are on My team, beside its nav item.
 *
 * Absent at zero rather than showing a "0". It bumps when the count goes up,
 * which is the landing half of the add-to-team flight (`flyTo`); nothing else
 * moves it.
 */
function RosterBadge({ className }: { className?: string }) {
  const count = useRosterCount()
  const ref = useRef<HTMLSpanElement>(null)
  const last = useRef(count)
  useEffect(() => {
    if (count > last.current) replayAnimation(ref.current, 'animate-score-bump')
    last.current = count
  }, [count])

  if (count === 0) return null
  return (
    <span
      ref={ref}
      className={cn(
        'bg-accent text-on-accent tnum inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-chip leading-none font-bold',
        className,
      )}
    >
      {count}
      <span className="sr-only"> players on your team</span>
    </span>
  )
}
