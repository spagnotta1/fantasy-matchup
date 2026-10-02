import { useEffect, useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen, TriangleAlert } from 'lucide-react'

import { useHealth } from '@/hooks/useCatalog'
import { replayAnimation } from '@/hooks/useCountUp'
import { useRosterCount } from '@/hooks/useRoster'
import { useSidebarRail } from '@/hooks/useSidebarRail'
import { cn } from '@/utils/cn'

import { FOOT_ITEMS, NAV_ITEMS, isAt, navGroups, type Destination, type NavItem } from './navigation'

/** The wordmark. Distinct from any league product, and the same in both themes. */
function Wordmark({ rail }: { rail: boolean }) {
  return (
    <div className={cn('flex items-center gap-2.5', rail ? 'justify-center' : 'px-3')}>
      <span
        aria-hidden
        className="bg-accent text-on-accent flex size-8 shrink-0 items-center justify-center rounded-lg text-sm font-bold tracking-tight"
      >
        FP
      </span>
      <span className={cn('min-w-0', rail && 'sr-only')}>
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
function ServiceStatus({ rail }: { rail: boolean }) {
  const { data, isError } = useHealth()
  const degraded = isError || (data && data.status !== 'ok')
  if (!degraded) return null

  if (rail) {
    return (
      <div
        className="bg-caution-soft text-caution-text mx-2 flex h-10 items-center justify-center rounded-[var(--radius-control)]"
        title="Service degraded. Some data may be stale or unavailable."
      >
        <TriangleAlert aria-hidden className="size-4" />
        <span className="sr-only">Service degraded. Some data may be stale or unavailable.</span>
      </div>
    )
  }

  return (
    <div className="bg-caution-soft text-caution-text mx-3 rounded-[var(--radius-control)] px-3 py-2 text-detail leading-relaxed">
      <span className="font-medium">Service degraded.</span> Some data may be stale or
      unavailable.
    </div>
  )
}

/**
 * One line of the sidebar.
 *
 * A link marked as the current page for every path that belongs to it, which
 * is more than the paths under it: a team's page is Matchups (see `alsoAt`).
 * On the rail it is the icon alone, and the label becomes its name and its
 * hover title, so nothing is an unlabelled glyph.
 */
function SidebarLink({ item, rail }: { item: Destination & Pick<NavItem, 'alsoAt'>; rail: boolean }) {
  const { pathname } = useLocation()
  const active = isAt(item, pathname)

  return (
    <Link
      to={item.to}
      title={rail ? item.label : item.description}
      aria-label={rail ? item.label : undefined}
      aria-current={active ? 'page' : undefined}
      data-nav={item.to}
      className={cn(
        'group relative flex items-center rounded-[var(--radius-control)] text-sm font-medium transition-colors',
        rail ? 'size-10 justify-center' : 'gap-3 px-3 py-2',
        active ? 'bg-accent-soft text-accent-text' : 'text-ink-secondary hover:bg-surface-hover hover:text-ink',
      )}
    >
      <item.icon aria-hidden className={cn('size-4 shrink-0', active ? 'text-accent-text' : 'text-ink-muted')} />
      {!rail && item.label}
      {item.to === '/my-team' && <RosterBadge className={rail ? 'absolute top-0.5 right-0.5' : 'ml-auto'} />}
    </Link>
  )
}

/**
 * The desktop sidebar.
 *
 * Hidden below `lg`, where the same destinations are served by a bottom bar.
 * That is a different layout rather than a narrower one — a sidebar squeezed
 * onto a phone is either unreachable by thumb or eats a third of the screen.
 *
 * Two groups, then a foot: the week and the tools a manager runs on it, and
 * under a rule the two pages that are about the product itself. It folds to a
 * rail of icons (`useSidebarRail`), which hands its width to the page: every
 * table here chooses its drawing by the room it has, and 184px is a column.
 */
export function Sidebar() {
  const [rail, setRail] = useSidebarRail()

  return (
    <nav
      aria-label="Main"
      data-rail={rail || undefined}
      // Sticky at the height of the screen: on a long page — a finished
      // simulation is several screens — the navigation used to scroll away
      // and leave an empty white column beside the content.
      className={cn(
        'border-line bg-surface sticky top-0 hidden h-dvh shrink-0 flex-col gap-6 border-r py-5 lg:flex',
        rail ? 'w-14' : 'w-60',
      )}
    >
      <Wordmark rail={rail} />

      <div className={cn('flex flex-1 flex-col overflow-y-auto', rail ? 'items-center gap-3 px-1.5' : 'gap-5 px-3')}>
        {navGroups().map(({ group, label, items }, index) => (
          <div key={group} className={cn(rail && index > 0 && 'border-line border-t pt-3')}>
            {/* On the rail the group is still named, for a screen reader; a rule
                says the same thing to the eye. */}
            <p
              id={`nav-group-${group}`}
              className={cn('text-ink-muted mb-1 px-3 text-chip font-medium tracking-wide uppercase', rail && 'sr-only')}
            >
              {label}
            </p>
            <ul aria-labelledby={`nav-group-${group}`} className="flex flex-col gap-0.5">
              {items.map((item) => (
                <li key={item.to}>
                  <SidebarLink item={item} rail={rail} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className={cn('border-line flex flex-col gap-0.5 border-t pt-3', rail ? 'items-center px-1.5' : 'px-3')}>
        <ul aria-label="About and settings" className="flex flex-col gap-0.5">
          {FOOT_ITEMS.map((item) => (
            <li key={item.to}>
              <SidebarLink item={item} rail={rail} />
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() => setRail(!rail)}
          aria-expanded={!rail}
          aria-label={rail ? 'Expand the sidebar' : 'Collapse the sidebar'}
          title={rail ? 'Expand the sidebar' : 'Collapse the sidebar to icons'}
          className={cn(
            'text-ink-muted hover:bg-surface-hover hover:text-ink flex items-center rounded-[var(--radius-control)] text-sm font-medium transition-colors',
            rail ? 'size-10 justify-center' : 'gap-3 px-3 py-2',
          )}
        >
          {rail ? <PanelLeftOpen aria-hidden className="size-4" /> : <PanelLeftClose aria-hidden className="size-4" />}
          {!rail && 'Collapse'}
        </button>
      </div>

      <ServiceStatus rail={rail} />
    </nav>
  )
}

/**
 * The phone bar's five, in the order a thumb has learned: the roster at the
 * right-hand end, where it has been since it joined the bar.
 */
const MOBILE_ORDER = ['/', '/rankings', '/matchups', '/simulation', '/my-team']

/**
 * The mobile bar.
 *
 * Fixed to the bottom, five destinations, generous targets, and padded for the
 * home indicator. Everything else is in the header's menu rather than crammed
 * in here.
 */
export function MobileNav() {
  const { pathname } = useLocation()
  const items = MOBILE_ORDER.map((to) => NAV_ITEMS.find((item) => item.to === to && item.primary)).filter(
    (item): item is NavItem => item !== undefined,
  )

  return (
    <nav
      aria-label="Main"
      className="border-line bg-surface/95 fixed inset-x-0 bottom-0 z-40 border-t backdrop-blur-md lg:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <ul className="grid grid-cols-5">
        {items.map((item) => {
          const active = isAt(item, pathname)
          return (
            <li key={item.to}>
              <Link
                to={item.to}
                aria-current={active ? 'page' : undefined}
                data-nav={item.to}
                className={cn(
                  'relative flex min-h-14 flex-col items-center justify-center gap-1 px-1 py-2 text-chip font-medium transition-colors',
                  active ? 'text-accent-text' : 'text-ink-muted',
                )}
              >
                <span className="relative">
                  <item.icon aria-hidden className={cn('size-5', active && 'text-accent')} />
                  {item.to === '/my-team' && <RosterBadge className="absolute -top-1.5 left-3.5" />}
                </span>
                <span className="truncate">{item.label}</span>
              </Link>
            </li>
          )
        })}
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
