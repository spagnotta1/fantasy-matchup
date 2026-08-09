import { NavLink } from 'react-router-dom'

import { useHealth } from '@/hooks/useCatalog'
import { cn } from '@/utils/cn'

import { NAV_ITEMS } from './navigation'

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
        <span className="text-ink-muted block text-[0.6875rem] leading-tight">
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
    <div className="bg-caution-soft text-caution-text mx-3 rounded-[var(--radius-control)] px-3 py-2 text-xs leading-relaxed">
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
      className="border-line bg-surface hidden w-60 shrink-0 flex-col gap-6 border-r py-5 lg:flex"
    >
      <Wordmark />

      <ul className="flex flex-1 flex-col gap-0.5 px-3">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.to === '/'}
              title={item.description}
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
                    className={cn('size-4 shrink-0', isActive ? 'text-accent-text' : 'text-ink-muted')}
                  />
                  {item.label}
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>

      <ServiceStatus />
    </nav>
  )
}

/**
 * The mobile bar.
 *
 * Fixed to the bottom, five destinations, generous targets, and padded for the
 * home indicator. Compare and Settings are reachable from the header rather
 * than crammed in here.
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
              className={({ isActive }) =>
                cn(
                  'flex min-h-14 flex-col items-center justify-center gap-1 px-1 py-2 text-[0.625rem] font-medium transition-colors',
                  isActive ? 'text-accent-text' : 'text-ink-muted',
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon aria-hidden className={cn('size-5', isActive && 'text-accent')} />
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
