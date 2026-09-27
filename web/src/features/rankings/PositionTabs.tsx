import { NavLink } from 'react-router-dom'

import { Tooltip } from '@/components/ui/Tooltip'
import { Skeleton } from '@/components/ui/Skeleton'
import { usePositions } from '@/hooks/useCatalog'
import { useSlidingIndicator } from '@/hooks/useSlidingIndicator'
import { cn } from '@/utils/cn'

/**
 * The position selector.
 *
 * Links rather than buttons, because the position lives in the path — a board
 * for running backs is a thing people send each other, and the browser's back
 * button should walk between positions.
 *
 * The list comes from `/meta/positions`, never from a constant. Positions the
 * API reports as unprojected are still rendered, disabled, with the reason the
 * API gave: a manager looking for kickers learns they do not exist yet instead
 * of assuming the filter is broken. The day a kicker model ships, this grows a
 * tab with no change here.
 */
export function PositionTabs({ active }: { active: string | null }) {
  const { data, isPending } = usePositions()
  // One underline that slides between tabs. Changing position is a param
  // change on a mounted page (see `routes.tsx`), which is what lets it slide
  // rather than reappear.
  const [ref, underline] = useSlidingIndicator<HTMLUListElement>(`${active}:${data?.length ?? 0}`)

  if (isPending) {
    return (
      <div className="mb-4 flex gap-2" aria-hidden>
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-9 w-16 rounded-[var(--radius-control)]" />
        ))}
      </div>
    )
  }

  return (
    <nav aria-label="Position" className="border-line mb-5 -mx-1 overflow-x-auto border-b px-1">
      <ul ref={ref} className="relative flex min-w-max items-center gap-1 pb-px">
        {underline && (
          <li
            aria-hidden
            className="bg-accent pointer-events-none absolute h-0.5 rounded-full"
            style={{ ...underline, top: undefined, height: undefined, bottom: 1 }}
          />
        )}
        <li>
          <TabLink to="/rankings" active={active === null} slid={underline !== null}>
            All
          </TabLink>
        </li>
        {(data ?? []).map((position) => (
          <li key={position.position}>
            {position.projected ? (
              <TabLink
                to={`/rankings/${position.position}`}
                active={active === position.position}
                slid={underline !== null}
                title={position.label}
              >
                {position.position}
              </TabLink>
            ) : (
              <Tooltip content={`${position.label} is not projected yet. ${position.reason ?? ''}`}>
                <span
                  aria-disabled="true"
                  className="text-ink-muted/70 inline-flex h-9 cursor-not-allowed items-center rounded-t-[var(--radius-control)] px-3 text-sm font-medium line-through"
                >
                  {position.position}
                </span>
              </Tooltip>
            )}
          </li>
        ))}
      </ul>
    </nav>
  )
}

function TabLink({
  to,
  active,
  title,
  slid,
  children,
}: {
  to: string
  active: boolean
  /** The sliding underline is drawn, so the tab should not draw its own. */
  slid: boolean
  title?: string
  children: React.ReactNode
}) {
  return (
    <NavLink
      to={to}
      end
      title={title}
      aria-current={active ? 'page' : undefined}
      data-active={active}
      className={cn(
        'inline-flex h-9 items-center rounded-t-[var(--radius-control)] px-3 text-sm font-medium transition-colors',
        // The underline is drawn as a bottom border on the tab itself so it
        // sits on the nav's border rather than floating above it.
        'border-b-2',
        active
          ? cn('text-ink', slid ? 'border-transparent' : 'border-accent')
          : 'text-ink-muted hover:text-ink border-transparent hover:border-line-strong',
      )}
    >
      {children}
    </NavLink>
  )
}
